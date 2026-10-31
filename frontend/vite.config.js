import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
const devHost = process.env.VITE_DEV_HOST || '127.0.0.1'

function proxyConfig() {
  return { target: apiTarget, changeOrigin: true }
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: devHost,
    port: 5173,
    proxy: { '/api': proxyConfig(), '/health': proxyConfig() },
  },
})
