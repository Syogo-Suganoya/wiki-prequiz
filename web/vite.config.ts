import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  // LP が `/`、ゲームが `/quiz`。本番（Vercel）も開発（nginx 経由）も同じ形に
  // しておく。ここを開発だけ `/` にすると、パスの食い違いが本番でしか
  // 顔を出さない（実際、LP の「遊んでみる」のリンク先で一度やらかした）
  base: "/quiz/",
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // 撮影用コンテナからは http://web:5173 で来るため、そのホスト名を許可する
    allowedHosts: ["web", "localhost", "127.0.0.1"],
    // Docker のバインドマウント上ではファイル変更イベントが届かないことが
    // あるためポーリングで監視する
    watch: { usePolling: true },
    proxy: {
      // ブラウザからは同一オリジンに見せ、コンテナ間では api サービスへ流す
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://api:8000",
        changeOrigin: true,
      },
    },
  },
});
