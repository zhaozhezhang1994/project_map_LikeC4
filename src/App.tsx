import { useEffect, useState } from 'react'
// ReactLikeC4 = 自包含的可嵌入组件 (自带 Mantine + 样式 + provider),
// 取代低层 LikeC4Diagram (后者不注入样式会渲染空白)。从虚拟模块 likec4:react
// 导入的版本已绑定本项目 model, 直接给 viewId 即可。
import { ReactLikeC4, useLikeC4Views } from 'likec4:react'
import { StatusElementNode } from './StatusElementNode'
import { loadConfig, openNode } from './config'
import { startStatusPolling } from './status'

export function App() {
  const views = useLikeC4Views()
  const [viewId, setViewId] = useState<string>(() => views[0]?.id ?? '')

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
            onNodeClick={(node) => openNode(node)}
            renderNodes={{ element: StatusElementNode }}
          />
        )}
      </main>
    </div>
  )
}
