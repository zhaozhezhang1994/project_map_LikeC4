import { elementNode, ElementNode } from 'likec4/react'
import { useStatusFor, type Health } from './status'
import { nodeKeys, nodeMembers } from './config'

// 自定义 element 节点渲染器: 复用 LikeC4 默认节点外观 (视觉一致),
// 外面按健康度套一圈染色环 + 异常数红点。这是 Phase 1 "状态覆盖层"的注入点。
//
// ⚠️ 关键: ReactLikeC4 把图渲染进 Shadow DOM, 全局 styles.css 穿不进去,
// 所以这里必须用 inline style (行内样式无视 shadow 边界), 不能靠 className。

const RING: Record<Health, string | null> = {
  up: 'rgba(34,197,94,0.55)',
  down: '#ef4444',
  degraded: '#f59e0b',
  pending: '#38bdf8',
  unknown: null,
}

export const StatusElementNode = elementNode(({ nodeProps, nodeModel }) => {
  // 普通节点: 按自身 key 查状态。粗粒度系统节点 (config 里带 members): 聚合成员状态。
  const node = { id: String(nodeModel.id) }
  const st = useStatusFor(nodeKeys(node), nodeMembers(node))
  const ring = RING[st.status]
  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        borderRadius: ring ? 12 : undefined,
        outline: ring ? `3px ${st.status === 'pending' ? 'dashed' : 'solid'} ${ring}` : undefined,
        outlineOffset: '3px',
      }}
    >
      <ElementNode {...nodeProps} />
      {st.anomaly_count > 0 && (
        <span
          title={`${st.anomaly_count} 个异常`}
          style={{
            position: 'absolute',
            top: -10,
            right: -10,
            minWidth: 20,
            height: 20,
            padding: '0 5px',
            background: '#ef4444',
            color: '#fff',
            borderRadius: 999,
            fontSize: 12,
            fontWeight: 700,
            lineHeight: '20px',
            textAlign: 'center',
            boxShadow: '0 0 0 2px #fff',
            zIndex: 10,
            pointerEvents: 'none',
          }}
        >
          {st.anomaly_count > 99 ? '99+' : st.anomaly_count}
        </span>
      )}
    </div>
  )
})
