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

function lookupOne(snap: StatusMap, key: string): NodeStatus {
  if (key && snap[key]) return snap[key]
  const last = key?.split('.').pop()
  if (last && snap[last]) return snap[last]
  return EMPTY
}

// 健康度"坏 → 好"优先级。聚合时取最坏的成员状态。
const BADNESS: Health[] = ['down', 'degraded', 'pending', 'up', 'unknown']

// 聚合一组成员状态: 状态取最坏 (任一 down → 整块 down), 异常数求和。
// 用于"系统全景"粗粒度节点 (一个块红 = 块内任一服务挂)。
export function rollup(members: NodeStatus[]): NodeStatus {
  if (members.length === 0) return EMPTY
  let worst: Health = 'unknown'
  let anomaly = 0
  for (const m of members) {
    anomaly += m.anomaly_count
    if (BADNESS.indexOf(m.status) < BADNESS.indexOf(worst)) worst = m.status
  }
  return { status: worst, anomaly_count: anomaly }
}

// 按多个候选 key 查 (fqn / 短名 / 末段)，命中第一个。
// 传 members (成员 key 数组) 时改为聚合: 状态取最坏 + 异常数求和 (粗粒度系统节点用)。
export function useStatusFor(keys: string[], members?: string[]): NodeStatus {
  const snap = useSyncExternalStore(subscribe, snapshot, snapshot)
  if (members && members.length > 0) {
    return rollup(members.map((m) => lookupOne(snap, m)))
  }
  for (const k of keys) {
    const s = lookupOne(snap, k)
    if (s !== EMPTY) return s
  }
  return EMPTY
}
