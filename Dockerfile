# ── build: 自定义 Vite + React 入口 (LikeC4 vite-plugin 编译 model/) ──
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
# 国内/弱网可: docker build --build-arg NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_REGISTRY=https://registry.npmjs.org
RUN npm install --registry=$NPM_REGISTRY
# index.html / src / public / vite.config.ts / tsconfig.json / model 都要 (.dockerignore 排除 node_modules/dist)
COPY . .
RUN npm run build

# ── serve: nginx 托管静态产物 ──
FROM nginx:alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# 控制页放 html 根之外 → 只有 7099 控制块 (root /usr/share/nginx) 能服务它, :80 (root html) 看不到
COPY deploy/control.html /usr/share/nginx/control.html
EXPOSE 80
