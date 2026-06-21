# likec4-project-map

[![CI](https://github.com/zhaozhezhang1994/project_map_LikeC4/actions/workflows/ci.yml/badge.svg)](https://github.com/zhaozhezhang1994/project_map_LikeC4/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

开箱即用的**项目导航地图** —— 基于 [LikeC4](https://likec4.dev) 的分块多视图架构图,叠加 **live 状态 + 异常红点 + 一键重启**。

> 状态: 只读(状态/异常)+ 控制(docker 重启 MVP)均已落地、隔离实测。
> 一句话: 把"一堆服务"做成一张能看健康、能点进去、(本机)能重启的地图。

## 它解决什么

把"一堆服务/系统"做成一张**可导航、分块分级**的地图:
- **多张聚焦视图**(总览 + 每层钻取),不是一张挤成一团的全局大图;
- **节点按健康度染色 + 异常红点**(绿/琥珀/红 + 角标数字);
- **点节点直接打开**对应系统首页;
- **(本机)一键重启**节点对应的容器,带完整安全笼子。

## 架构

```
浏览器 ──(LAN, 只读)──▶ nginx :80 ──▶ /api/  ─┐
浏览器 ──(本机, 控制)─▶ nginx 127.0.0.1:7099 ─▶ /control/ ─┤
                                                          ▼
                                            sidecar (FastAPI, project-map-api)
                                              ├─ docker 适配器 ─▶ socket-proxy ─▶ dockerd
                                              ├─ process_compose 适配器 ─▶ host:18790
                                              └─ 异常计数 ─▶ ClickHouse alerts_log
```

- **前端**: 自定义 Vite + React(`ReactLikeC4`),把 `model/` 编译成可交互地图;轮询 `/api/status` 染色 + 红点;`onNodeClick` 读 `config.json` 的 url 打开系统。
- **sidecar (`api/`)**: 只读出 `/api/status`(各节点 `{status, anomaly_count, actions}`);控制出 `/control/restart`。不发布宿主端口,只经 nginx 反代。
- **socket-proxy**: Docker API 白名单反代(借 `wollomatic/socket-proxy`),只放行容器查询 + restart/stop/start,**禁 exec/create/镜像**。sidecar 不直挂 `docker.sock`。

## 跑起来

```bash
# 开发(热重载,改 .likec4 即刷新)—— 纯前端,无后端
npm install
npm run dev            # → http://localhost:3002

# 生产(前端 + sidecar + socket-proxy)
cp .env.example .env   # 按需填 (不填也能跑, 只是没异常数/不能控制)
docker compose up -d   # → http://localhost:3002
```

无后端也能用:地图渲染 + 点击进入只靠前端读 `config.json`,**sidecar 挂了不影响看图和跳转**(状态显示 unknown 而已)。

## 配置:`public/config.json`(唯一部署绑定源)

`model/model.likec4` = **结构真相**(有哪些节点/关系/视图);`config.json` = **部署绑定**(节点 → 真实 URL/容器/告警源)。换环境改 `config.json`,**不动模型**。key = 模型节点短名。

| 字段 | 作用 | 谁用 |
|---|---|---|
| `title` | 显示名 | 前端 |
| `url` | 点击打开的系统首页(仅有 web UI 的节点配) | 前端 |
| `adapter` | `docker` / `process_compose` —— 查存活/重启走哪条 | 后端 |
| `target` | 真实容器名 / 进程名 | 后端 |
| `alert_sources` | `alerts_log.source` 前缀列表 → 异常红点(可选) | 后端 |

> 凭据(CH 密码 / 控制 token)**绝不进 config.json**,走 env(见 `.env.example`)。

## 状态从哪来

- **存活**: docker 节点查容器 `status`;process_compose 节点查 `/processes` 的 `is_running`。
- **异常红点**: 查 ClickHouse `alerts_log` —— 每个 `source` 取窗口内最新一条,仅 warn/error/critical 计(恢复=info 不计),按节点 `alert_sources` 前缀累加。配了 `CLICKHOUSE_*` 才有,不配则恒 0。

## 开启控制(一键重启)—— 高危,默认关

控制能远程重启容器(≈ 受限的远程执行),**默认关闭**。开启:

```bash
# .env
MAP_CONTROL_ENABLED=true
MAP_OPERATOR_TOKEN=<≥32 随机>   # python -c "import secrets;print(secrets.token_urlsafe(32))"
```

三层安全笼子:
1. **网络**: 控制端点只走 `nginx` 的 **`127.0.0.1:7099`**(compose 映射 loopback)——LAN 访问公开口(`:3002/control/`)直接 **404**。**反向代理(Caddy 等)绝不要把 7099 带进 LAN**。
2. **Docker 权限**: 走 socket-proxy 路径白名单,sidecar 即使被攻破也只能 restart/stop/start,**不能 exec / 造容器 / 删容器**。
3. **应用**: token 鉴权(`compare_digest`)+ 只认 `config.json` 白名单节点 + 审计(`api/audit/audit.log` NDJSON,失败必打 stderr)。

用法(仅宿主本机):
```bash
# op ∈ restart | stop | start; node = config.json 里的节点短名
curl -X POST http://127.0.0.1:7099/control/restart \
  -H "Authorization: Bearer $MAP_OPERATOR_TOKEN" \
  -H "Content-Type: application/json" -d '{"node":"kafka"}'
```
或开**控制页**(按钮式,仅本机):浏览器访问 **`http://127.0.0.1:7099/`** → 节点表 + restart/stop/start/**logs** 按钮,顶部填 token(只存该页内存)。支持 **docker + process_compose** 的 restart/stop/start + 看最近日志(`logs`,一次性取最近 N 行,N≤500)。

## 先决条件 / 假设

- **必需**: Docker + Docker Compose。`docker compose up -d` 后开 `http://localhost:3002` —— **不需要** Caddy / 自定义域名 / 改 hosts / HTTPS。
- **可选(进阶)**: 反向代理 + `*.local` 短域名是额外接入,非必需。
- **节点 url**: `config.json` 里的 `http://*.local` 是**参考部署示例**;换你的 URL 即可。点了打不开 = 那地址在你环境不存在,正常,改掉。
- **跨平台**: 已用 `.gitattributes` 锁 LF;compose 带 `host.docker.internal` 映射。⚠️ process_compose/CH 等**宿主 127.0.0.1 服务**,容器经 `host.docker.internal` 回连仅 **Docker Desktop(Win/Mac)** 可达;**Linux** 的 host-gateway 够不到 loopback,需让那些服务听 `0.0.0.0`。
- **弱网/国内**: `docker build --build-arg NPM_REGISTRY=https://registry.npmmirror.com`(前端)/ `PIP_INDEX=...`(sidecar)。

## 二次开发须知(踩过的坑)

- **入口是自定义 Vite + React,不是 `likec4 build`**:要运行时注入状态/染色/点击,必须自己掌控 React 树。LikeC4 `vite-plugin` 把 `model/` 编译成虚拟模块(`likec4:react`)且带 HMR。
- **用 `ReactLikeC4`(自包含),别用 `LikeC4Diagram`(低层)**:后者不注入 Mantine 样式 → 渲染空白。
- **节点渲染进 Shadow DOM**:全局 CSS 穿不进,染色环 + 红点必须用 **inline style**(见 `StatusElementNode.tsx`)。
- **节点 key 用短名**:`config.json` key = 模型节点短名;运行时 `node.modelFqn` 可能是 `backbone.kafka`,代码已做"fqn → 末段"回退。
- **socket-proxy 选 `wollomatic` 不选 `tecnativa`**:要"放行 restart 但拦 exec"必须**按路径细粒度**;tecnativa 只能按资源类别(`POST+CONTAINERS` 会连 exec 一起放行,实测未拦)。借工具前务必 spike 验:`POST .../containers/<id>/exec` 必须返 403。
- **nginx 双 server block**:`:80` 公开(只读 + 404 掉 `/control/`)、`127.0.0.1:7099` 控制。改的时候别把 `/control/` 漏进公开块。

## 结构

```
likec4-project-map/
├── model/model.likec4     # SSOT: 元素 + 关系 + 多视图 (结构真相)
├── public/
│   ├── config.json        # 部署绑定: 节点 → url/adapter/target/alert_sources
│   └── status.json        # 演示种子 (后端就绪后由 /api/status 取代)
├── src/                   # 前端: App / StatusElementNode / status / config
├── api/                   # sidecar: main.py (状态+控制) + Dockerfile + requirements
│   └── audit/             # 控制审计 NDJSON (gitignored)
├── deploy/nginx.conf      # 双 block: :80 只读 + 127.0.0.1:7099 控制
├── Dockerfile             # 前端多阶段: vite build → nginx
├── docker-compose.yml     # project-map(nginx) + project-map-api + socket-proxy
└── .env.example           # CH 凭据 / 控制 token / 各后端地址
```

## Roadmap

- **Phase 0** ✅ 静态多视图地图 + 点击进入
- **Phase 1 地基** ✅ 自定义 Vite+React 入口 + 状态染色/红点 + 点击跳转
- **1A/1.5A** ✅ docker + process_compose 适配器(真实存活状态)
- **2A** ✅ 异常红点接真实 `alerts_log`
- **1B-MVP** ✅ docker 一键重启 + 三层安全笼子(socket-proxy + 127.0.0.1 + token + 审计)
- **1.5B** ✅ 控制扩到 restart/stop/start × docker + process_compose
- **控制页** ✅ 独立 loopback 控制台(`127.0.0.1:7099`,按钮 + token + logs)
- **下一步**: 上线 live(`docker compose up -d --build`)· CI(待上 GitHub)
