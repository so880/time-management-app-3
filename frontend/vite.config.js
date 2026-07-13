import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite公式ドキュメント準拠の設定
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
})
