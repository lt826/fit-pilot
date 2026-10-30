# 前端镜像：Node 构建 + Nginx 托管（静态文件 + /api 反代）
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json ./
RUN npm config set registry https://registry.npmmirror.com && npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /web/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
