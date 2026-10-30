import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期代理：前端 5173 的 /api 请求转给 FastAPI 8000，免 CORS 配置
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
