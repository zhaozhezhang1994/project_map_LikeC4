import { useSyncExternalStore } from 'react'

// 节点健康状态。Phase 1-1A: 轮询 sidecar 的 /api/status (真实 Docker 状态)。
// 后端不可达时 fetch 静默失败 → 保留上次状态 (无后端也不崩, 地图/点击照常)。
// 演示/离线种子保留在 public/status.json, 切 STATUS_URL 即可回退。
export type Health = 'up' | 'down' | 'degraded' | 'pending' | 'unknown'

export type NodeStatus = {
  status: Health
  anomaly_count: number
}

type StatusMap = Record<string, NodeStatus>

const EMPTY: NodeStatus = { status: 'unknown', anomaly_count: 0 }

// 切回演示种子: 'status.json'。线上走 sidecar: 'api/status'。
const STATUS_URL = 'api/status'

let state: StatusMap = {}
const listeners = new Set<() => void>()

function emit() {
  for (const l of listeners) l()
}

async function poll() {
  try {
    const r = await fetch(STATUS_URL, { cache: 'no-store' })
    if (r.ok) {
      state = (await r.json()) as StatusMap
      emit()
    }
  } catch {
    /* 网络抖动忽略, 保留上次状态 */
  }
}

let started = false
export function startStatusPolling(intervalMs = 5000): void {
  if (started) return
  started = true
  void poll()
  setInterval(() => void poll(), intervalMs)
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

function snapshot(): StatusMap {
  return state
}

// 按多个候选 key 查 (fqn / 短名 / 末段)，命中第一个。
export function useStatusFor(...keys: string[]): NodeStatus {
  const snap = useSyncExternalStore(subscribe, snapshot, snapshot)
  for (const k of keys) {
    if (k && snap[k]) return snap[k]
  }
  for (const k of keys) {
    const last = k?.split('.').pop()
    if (last && snap[last]) return snap[last]
  }
  return EMPTY
}
