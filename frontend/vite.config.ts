import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 前端 dev 跑在 5173，把 /api 开头的请求转发给后端 8000
      "/api": "http://localhost:8000",
    },
  },
})
