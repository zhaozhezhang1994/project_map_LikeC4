"""项目导航地图 sidecar API —— Phase 1-1A/1.5A (只读状态)。

读 config.json 的 adapter/target, 查真实后端状态, 暴露 GET /api/status。
前端把轮询目标从 public/status.json 换成 /api/status。

适配器 (只读):
  - **docker** (1A): 官方 docker SDK, containers.get(target).status → 归一化
  - **process_compose** (1.5A): GET {PROCESS_COMPOSE_URL}/processes, 按进程名查 is_running
  - **anomaly_count** (2A): 查 ClickHouse alerts_log, 按节点 `alert_sources` 前缀匹配,
    数"当前仍在告警"的来源数 (每个 source 取窗口内最新一条, 仅 warn/error/critical 计;
    _ok 恢复=info 不计)。alert-platform.* 的告警是"关于别的服务"的 → 映射到被监控节点。
  - dagu / http-probe → 后续 (当前 model 无对应节点)
  - **控制 (1B/1.5B)**: POST /control/{restart|stop|start} — docker + process_compose, 全套安全笼子。
    (logs 留后续: 形态不同, 要 tail 上限。process-compose 动作路径:
     restart/start=POST /process/{op}/{name}, stop=PATCH /process/stop/{name} —— stop 是 PATCH, 实测确认。)

安全:
  - 状态读取全只读 (docker 经 socket-proxy 只查询; process-compose 只 GET)。
  - **1B 起 docker 不再直挂 socket, 改走 docker-socket-proxy** (DOCKER_HOST=tcp://proxy:2375),
    proxy 白名单只放行 containers 查询 + restart/stop/start, 禁 exec/create/delete/镜像。
  - **控制端点 /control/* 只经 nginx 的 127.0.0.1:7099 块可达; 0.0.0.0:80 块显式 404 它**
    (LAN 只能看状态, 控制仅宿主本机)。token 鉴权 (compare_digest) + node 白名单 + 默认关 + 审计。
  - 凭据/token 不进 config, 走 env (CLAUDE.md §17 B 类)。

⚠️ 可移植性: process-compose/Dagu 绑宿主 127.0.0.1, 容器经 host.docker.internal 回连
—— Docker Desktop (Win/Mac) 可达 (本机实测 vip/dagu 同法); **Linux host-gateway 是真网桥 IP,
够不到 loopback-only 服务**, 迁 Linux 需让这些服务听 0.0.0.0 或换 host 网络。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from secrets import compare_digest

import docker
from fastapi import FastAPI, HTTPException, Request

CONFIG_PATH = Path(os.getenv("MAP_CONFIG", "/app/config.json"))
PROCESS_COMPOSE_URL = os.getenv("PROCESS_COMPOSE_URL", "http://host.docker.internal:18790")

# 异常计数 (2A): 查 ClickHouse alerts_log。凭据走 env (B 类), 绝不进 config。
CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "http://host.docker.internal:8123")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "discord_pipeline")
ALERT_WINDOW_MIN = int(os.getenv("ALERT_WINDOW_MIN", "60"))


def parse_bool(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "on")


# 控制 (1B/1.5B): 默认关。token 走 env, 绝不进 config / 不下发前端。
MAP_CONTROL_ENABLED = parse_bool(os.getenv("MAP_CONTROL_ENABLED", "false"))
MAP_OPERATOR_TOKEN = os.getenv("MAP_OPERATOR_TOKEN", "")
AUDIT_PATH = Path(os.getenv("AUDIT_PATH", "/app/audit/audit.log"))

# 白名单动作 (无通用命令通道)。process-compose 各动作的 HTTP 方法不对称:
# restart/start=POST, stop=PATCH (实测确认, v1.x)。
ALLOWED_OPS = ("restart", "stop", "start")
_PC_METHOD = {"restart": "POST", "start": "POST", "stop": "PATCH"}
LOG_TAIL_MAX = 500  # logs 一次最多取多少行 (防响应体过大 / OOM)

app = FastAPI(title="project-map-api", version="0.4.0")

UNKNOWN = {"status": "unknown", "anomaly_count": 0, "actions": []}


def _result(status: str) -> dict:
    return {"status": status, "anomaly_count": 0, "actions": []}


# ── Docker 适配器 (只读) ───────────────────────────────────
_DOCKER_STATUS = {
    "running": "up",
    "restarting": "degraded",
    "paused": "degraded",
    "created": "pending",
    "exited": "down",
    "dead": "down",
    "removing": "down",
}

_client = None


def _docker_client():
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def _docker_status(client, target: str) -> dict:
    try:
        c = client.containers.get(target)  # 新鲜 inspect
        return _result(_DOCKER_STATUS.get(c.status, "unknown"))
    except docker.errors.NotFound:
        return _result("down")  # 容器不存在 = 没在跑
    except Exception:
        return _result("unknown")


# ── http 探活适配器 (只读): 宿主独立进程/有 HTTP 口但非 docker/pc 的 ──
def _http_status(target: str) -> dict:
    """GET target: 任何响应(2xx/3xx/401/403/5xx)= up(活着); 连不上/超时 = down。
    用于 Dagu / Syncthing 等宿主独立进程 (经 host.docker.internal 回连)。"""
    try:
        req = urllib.request.Request(target, method="GET")
        with urllib.request.urlopen(req, timeout=4):
            return _result("up")
    except urllib.error.HTTPError:
        return _result("up")  # 有响应(401/403/5xx)= 进程活着
    except Exception:
        return _result("down")  # 连接拒绝/超时/DNS = 没在跑


# ── process-compose 适配器 (只读, 一次拉全部) ──────────────
def _fetch_process_compose() -> dict | None:
    """返回 {进程名: 归一化状态}; 拉不到返回 None (→ 节点 unknown)。"""
    try:
        with urllib.request.urlopen(f"{PROCESS_COMPOSE_URL}/processes", timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
        out = {}
        for p in data.get("data", []):
            out[p.get("name")] = _pc_status(p)
        return out
    except Exception:
        return None


def _pc_status(p: dict) -> str:
    if p.get("is_running"):
        return "up"
    st = (p.get("status") or "").lower()
    if st == "restarting":
        return "degraded"
    if st in ("launching", "pending"):
        return "pending"
    return "down"


# ── 异常计数适配器 (2A, 查 ClickHouse alerts_log) ──────────
def _ch_query(sql: str) -> list | None:
    """POST SQL 到 CH HTTP, 凭据走 header (不进 URL/日志)。失败返 None。"""
    try:
        req = urllib.request.Request(
            f"{CLICKHOUSE_URL}/?database={CLICKHOUSE_DB}",
            data=sql.encode("utf-8"),
            headers={"X-ClickHouse-User": CLICKHOUSE_USER, "X-ClickHouse-Key": CLICKHOUSE_PASSWORD},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            text = r.read().decode("utf-8")
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    except Exception:
        return None


def _fetch_anomaly_counts(nodes: dict) -> dict:
    """返回 {节点短名: 当前在告警的来源数}。

    每个 source 取窗口内最新一条 (argMax level by occurred_at), 仅 warn/error/critical 计
    (_ok 恢复=info 不计)。再按各节点 config 的 alert_sources 前缀匹配累加。
    未被任何节点认领的 source (ollama/flink/doc-generator 等不在 model) 自然不计。
    """
    prefixes = {k: (n.get("alert_sources") or []) for k, n in nodes.items()}
    if not any(prefixes.values()):
        return {}
    sql = (
        "SELECT source, argMax(level, occurred_at) AS latest_level "
        f"FROM {CLICKHOUSE_DB}.alerts_log "
        f"WHERE occurred_at > now() - INTERVAL {ALERT_WINDOW_MIN} MINUTE "
        "GROUP BY source HAVING latest_level IN ('warn','error','critical') "
        "FORMAT JSONEachRow"
    )
    rows = _ch_query(sql)
    if rows is None:
        return {}
    counts: dict = {}
    for row in rows:
        src = row.get("source", "")
        for node_key, plist in prefixes.items():
            if any(src.startswith(p) for p in plist):
                counts[node_key] = counts.get(node_key, 0) + 1
    return counts


# ── config ────────────────────────────────────────────────
def _load_nodes() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("nodes", {})
    except Exception:
        return {}


@app.get("/api/status")
def status():
    """返回 { 节点短名: {status, anomaly_count, actions} }。前端按此染色/红点。"""
    nodes = _load_nodes()
    out: dict = {}

    # 各适配器按需各拉一次
    client = None
    if any(n.get("adapter") == "docker" for n in nodes.values()):
        try:
            client = _docker_client()
        except Exception:
            client = None
    pc_map = (
        _fetch_process_compose()
        if any(n.get("adapter") == "process_compose" for n in nodes.values())
        else None
    )

    for key, n in nodes.items():
        adapter = n.get("adapter")
        target = n.get("target")
        if adapter == "docker" and target:
            out[key] = _docker_status(client, target) if client is not None else dict(UNKNOWN)
        elif adapter == "process_compose" and target:
            if pc_map is None:
                out[key] = dict(UNKNOWN)  # 拉不到 process-compose
            else:
                out[key] = _result(pc_map.get(target, "down"))  # 不在列表 = 没在跑
        elif adapter == "http" and target:
            out[key] = _http_status(target)  # 宿主独立进程, 探 HTTP 口
        # 其它/无 adapter → 不输出, 前端按 unknown 处理

    # 2A: 叠加异常计数 (红点)。status=存活, anomaly_count=告警, 两者独立。
    if any(n.get("alert_sources") for n in nodes.values()):
        for k, c in _fetch_anomaly_counts(nodes).items():
            if k in out:
                out[k]["anomaly_count"] = c

    # 1B/1.5B: 声明可用动作 (前端按此渲染按钮)。控制关 → 空, 不诱导。
    if MAP_CONTROL_ENABLED:
        for key, n in nodes.items():
            if key in out and n.get("adapter") in ("docker", "process_compose") and n.get("target"):
                out[key]["actions"] = list(ALLOWED_OPS)
    return out


@app.get("/api/health")
def health():
    return {"ok": True}


# ── 控制 (1B/1.5B: restart/stop/start × docker/process_compose) ─────
# 安全笼子: 默认关(405) + token(compare_digest) + op 白名单 + node 白名单 + 审计(失败必 stderr)。
# 网络层笼子在 nginx: /control/ 只走 127.0.0.1:7099, 0.0.0.0:80 块 404 它。
# docker 动作经 socket-proxy (允许 restart/stop/start); process_compose 直连宿主 18790。

def _audit(op: str, node: str, adapter: str, target: str, ok: bool,
           detail: str, duration_ms: int, notify_fn=None) -> None:
    """NDJSON append + 失败必喊 stderr(§12 deliver-or-alert, 不耦合主项目告警)。
    notify_fn: OSS 用户可注入自己的告警渠道; 默认 None = 只写文件 + stderr。"""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(), "op": op, "node": node,
        "adapter": adapter, "target": target, "ok": ok,
        "detail": detail, "duration_ms": duration_ms,
    }
    line = json.dumps(rec, ensure_ascii=False)
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[AUDIT-WRITE-FAIL] {e}", file=sys.stderr, flush=True)
    if not ok:
        print(f"[AUDIT-FAIL] {line}", file=sys.stderr, flush=True)
    if notify_fn:
        try:
            notify_fn(rec)
        except Exception:
            pass


def _require_control(request: Request) -> None:
    """默认关 → 405; token 缺/错 → 401。token 比较用 compare_digest 防时序。"""
    if not MAP_CONTROL_ENABLED:
        raise HTTPException(status_code=405, detail="control disabled (set MAP_CONTROL_ENABLED=true)")
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth[:7].lower() == "bearer " else ""
    if not MAP_OPERATOR_TOKEN or not compare_digest(token, MAP_OPERATOR_TOKEN):
        raise HTTPException(status_code=401, detail="unauthorized")


def _pc_action(op: str, name: str) -> None:
    """process-compose 动作: POST /process/{op}/{name} (stop 是 PATCH)。
    非 2xx → urlopen 抛 HTTPError (上层捕获记审计)。"""
    url = f"{PROCESS_COMPOSE_URL}/process/{op}/{urllib.parse.quote(name)}"
    req = urllib.request.Request(url, data=b"", method=_PC_METHOD[op])
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


def _pc_logs(name: str, tail: int) -> list:
    """process-compose 最近日志: GET /process/logs/{name}/0/{limit} → {logs:[...]}。"""
    url = f"{PROCESS_COMPOSE_URL}/process/logs/{urllib.parse.quote(name)}/0/{tail}"
    with urllib.request.urlopen(url, timeout=8) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [ln.rstrip("\r\n") for ln in data.get("logs", [])]


@app.get("/control/logs")
def control_logs(request: Request, node: str = "", tail: int = 200):
    """看节点最近 N 行日志 (只读, 但属控制面 → token + loopback + node 白名单)。
    一次性取, 不流式; tail 上限 LOG_TAIL_MAX。"""
    _require_control(request)
    n = _load_nodes().get(node)
    if not n:
        raise HTTPException(status_code=404, detail="unknown node")
    adapter, target = n.get("adapter"), n.get("target")
    tail = max(1, min(int(tail), LOG_TAIL_MAX))
    try:
        if adapter == "docker":
            raw = _docker_client().containers.get(target).logs(tail=tail, stdout=True, stderr=True)
            lines = raw.decode("utf-8", "replace").splitlines()
        elif adapter == "process_compose":
            lines = _pc_logs(target, tail)
        else:
            raise HTTPException(status_code=400, detail="该 node 不支持 logs")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"logs failed: {str(e)[:200]}")
    return {"node": node, "lines": lines[-tail:]}


@app.post("/control/{op}")
async def control_action(op: str, request: Request):
    _require_control(request)
    if op not in ALLOWED_OPS:
        raise HTTPException(status_code=404, detail=f"unknown op (allowed: {', '.join(ALLOWED_OPS)})")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="bad json body")
    node = (body or {}).get("node", "")

    # node 白名单: 必须在 config + adapter 已知 + 用 config 的 target (绝不信前端传的名字)
    n = _load_nodes().get(node)
    if not n:
        raise HTTPException(status_code=404, detail="unknown node")
    adapter, target = n.get("adapter"), n.get("target")
    if adapter not in ("docker", "process_compose") or not target:
        raise HTTPException(status_code=400, detail="该 node 不支持控制 (需 docker/process_compose adapter)")

    t0 = time.time()
    ok, detail = False, ""
    try:
        if adapter == "docker":
            getattr(_docker_client().containers.get(target), op)()  # restart/stop/start
        else:
            _pc_action(op, target)
        ok = True
    except Exception as e:
        detail = str(e)[:200]
    dur = int((time.time() - t0) * 1000)
    _audit(op, node, adapter, target, ok, detail, dur)
    if not ok:
        raise HTTPException(status_code=500, detail=f"{op} failed: {detail}")
    return {"ok": True, "op": op, "node": node, "target": target, "duration_ms": dur}
