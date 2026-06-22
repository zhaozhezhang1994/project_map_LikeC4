import { useEffect, useState } from 'react'
// ReactLikeC4 = 自包含的可嵌入组件 (自带 Mantine + 样式 + provider),
// 取代低层 LikeC4Diagram (后者不注入样式会渲染空白)。从虚拟模块 likec4:react
// 导入的版本已绑定本项目 model, 直接给 viewId 即可。
import { ReactLikeC4, useLikeC4Views } from 'likec4:react'
import { StatusElementNode } from './StatusElementNode'
import { loadConfig, openNode, nodeKeys } from './config'
import { startStatusPolling } from './status'

export function App() {
  const views = useLikeC4Views()
  // 默认落在"系统全景"(landscape, 日常一眼看健康) → 退回总览 (index) → views[0]。
  // useLikeC4Views() 顺序不保证, 不能直接用 views[0]。
  const [viewId, setViewId] = useState<string>(
    () =>
      views.find((v) => v.id === 'landscape')?.id ??
      views.find((v) => v.id === 'index')?.id ??
      views[0]?.id ??
      '',
  )

  useEffect(() => {
    void loadConfig()
    startStatusPolling(5000)
  }, [])

  return (
    <div className="app">
      <header className="tabs">
        <span className="brand">🗺️ 项目导航地图</span>
        {views.map((v) => (
          <button
            key={v.id}
            className={v.id === viewId ? 'tab active' : 'tab'}
            onClick={() => setViewId(v.id)}
          >
            {v.title ?? v.id}
          </button>
        ))}
      </header>
      <main className="diagram">
        {viewId && (
          <ReactLikeC4
            viewId={viewId as never}
            controls
            fitView
            style={{ height: '100%' }}
            onNodeClick={(node) => {
              // 系统全景里点粗粒度块 (id 形如 'quantSys') → 钻进该块详细视图
              // (view id 去掉 'Sys' = 'quant'), 出问题一眼看哪个成员红。
              const last = String((node as { id?: string }).id ?? '').split('.').pop() ?? ''
              if (last.endsWith('Sys')) {
                const blockView = views.find((v) => v.id === last.replace(/Sys$/, ''))
                if (blockView) {
                  setViewId(blockView.id)
                  return
                }
              }
              // 总览里点分组 → 钻进对应子视图 (view of <group>);
              // 没有对应钻取视图的 (叶子服务) 才按 URL 打开。
              const keys = nodeKeys(node)
              const drill = views.find(
                (v) => v.viewOf != null && keys.includes(String(v.viewOf)),
              )
              if (drill) {
                setViewId(drill.id)
                return
              }
              openNode(node)
            }}
            renderNodes={{ element: StatusElementNode }}
          />
        )}
      </main>
    </div>
  )
}
