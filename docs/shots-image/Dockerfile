# LP 用スクリーンショット撮影コンテナ。
# Chromium を同梱して、利用者と同じ操作で画面を撮る。
FROM node:22-trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       chromium fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Chromium は apt で入れたものを使うので、puppeteer 側のダウンロードは止める
ENV PUPPETEER_SKIP_DOWNLOAD=1 \
    CHROME_BIN=/usr/bin/chromium

RUN npm install -g puppeteer@23

# グローバル導入した puppeteer を require で解決できるようにする
ENV NODE_PATH=/usr/local/lib/node_modules

WORKDIR /work
CMD ["node", "docs/shots.js"]
