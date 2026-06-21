import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { LikeC4VitePlugin } from 'likec4/vite-plugin'

// 自定义 Vite + React 入口(取代 `likec4 build` 纯静态产物)。
// 原因: 要在运行时注入状态(轮询 status)+ 自定义节点染色/红点 + onNodeClick,
// 这些只能在自己掌控的 React 树里做。LikeC4 官方 vite-plugin 把 model/ 下的
// .likec4 编译成虚拟模块 (likec4:single-project / likec4:react) 并带 HMR。
export default defineConfig({
  plugins: [
    react(),
    LikeC4VitePlugin({ workspace: 'model' }),
  ],
  server: { host: '0.0.0.0', port: 3002 },
  preview: { host: '0.0.0.0', port: 3002 },
})
