FROM node:22-slim AS base

ENV NODE_ENV=development
WORKDIR /app

COPY package.json package-lock.json* ./
# lock ファイルがまだ無い初期状態でも通るようにする
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi


# ── 開発用: ソースはバインドマウントし Vite の HMR を効かせる ──
FROM base AS dev

EXPOSE 5173
# コンテナ外のブラウザから繋げるよう 0.0.0.0 で待ち受ける
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]


# ── 静的ビルド（Vercel へは通常このステップを Vercel 側が実行する）──
FROM base AS build
COPY . .
RUN npm run build
