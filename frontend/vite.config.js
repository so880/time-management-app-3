import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite公式ドキュメント準拠の設定
// https://vite.dev/config/
// - 本体（FastAPI）へは Vite の proxy で中継する（https://vite.dev/config/server-options#server-proxy）。
//   画面からは同じオリジンの /api /bg /webcam を呼ぶだけなので、本体の番号を画面のコードに書かない
// - 本体の番号は起動役（launcher.py）が環境変数 LIFEAPP_API_PORT で渡す（8000 が使用中なら別の番号）
// - 画面の番号は launcher.py が --port と --strictPort で渡す（空いている番号を選んで固定）
const apiPort = Number(process.env.LIFEAPP_API_PORT) || 8000
const apiTarget = `http://127.0.0.1:${apiPort}`

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': apiTarget,
      '/bg': apiTarget,
      '/webcam': apiTarget,
    },
  },
})
