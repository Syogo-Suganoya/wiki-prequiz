import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig(({ command }) => ({
  // 本番は LP が `/`、ゲームが `/quiz` に並ぶので、アセットの参照先を
  // `/quiz/...` にする。開発サーバーは素の `/` のまま
  // （撮影コンテナも CONTRIBUTING も http://localhost:5173 を前提にしている）
  base: command === "build" ? "/quiz/" : "/",
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
}));
