// 部署绑定 (deployment binding) —— Phase 1 config 的浏览器侧入口。
// 真相分层: model.likec4 = 结构真相 (有哪些节点/关系/视图);
//          config = 部署真相 (节点 → 真实 URL / 容器 / 适配器目标)。
// 现在用 public/config.json (浏览器直接 fetch); 后续后端落 config.yaml,
// 由 sidecar API 渲染同一份结构给前端。改部署不动模型。

export type NodeConfig = {
  url?: string // 点击节点打开的系统首页 (*.local 等); 无 = 后端服务无 web UI, 点了不跳
  title?: string
  container?: string // 真实容器/进程名 (Phase 1 适配器用)
  members?: string[] // 粗粒度"系统全景"节点的成员 key; 有则状态在前端聚合 (取最坏 + 异常求和)
}

export type MapConfig = { nodes: Record<string, NodeConfig> }

let cfg: MapConfig = { nodes: {} }

export async function loadConfig(): Promise<MapConfig> {
  try {
    const r = await fetch('config.json', { cache: 'no-store' })
    if (r.ok) cfg = await r.json()
  } catch {
    cfg = { nodes: {} }
  }
  return cfg
}

// 节点 id 可能是 fqn (backbone.kafka) 或短名 (kafka)，运行时不确定，
// 这里统一回退到末段，配置/状态文件一律用短名作 key。
export function nodeKeys(node: { id?: string; modelFqn?: string }): string[] {
  const fqn = node?.modelFqn ?? node?.id ?? ''
  const id = node?.id ?? ''
  const last = String(fqn).split('.').pop() ?? ''
  return [...new Set([fqn, id, last].filter(Boolean))]
}

export function nodeUrl(node: { id?: string; modelFqn?: string }): string | undefined {
  for (const k of nodeKeys(node)) {
    const u = cfg.nodes[k]?.url
    if (u) return u
  }
  return undefined
}

// 粗粒度系统节点的成员 key 列表 (有则前端聚合状态)。普通节点返回 []。
export function nodeMembers(node: { id?: string; modelFqn?: string }): string[] {
  for (const k of nodeKeys(node)) {
    const m = cfg.nodes[k]?.members
    if (m && m.length) return m
  }
  return []
}

// onNodeClick: 有 URL 就新标签打开对应系统首页; 无 URL (后端服务) 静默忽略。
export function openNode(node: { id?: string; modelFqn?: string }): void {
  const u = nodeUrl(node)
  if (u) window.open(u, '_blank', 'noopener,noreferrer')
}
