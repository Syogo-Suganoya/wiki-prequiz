# Firebase エミュレータ（Firestore + Auth）専用イメージ。
# Firestore エミュレータは JVM 上で動き、firebase-tools は JDK 21 以上を要求する。
# bookworm 系の default-jre は Java 17 で起動に失敗するため trixie を使う。
FROM node:22-trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-21-jre-headless curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g firebase-tools@latest

WORKDIR /opt/firebase

# エミュレータ本体を事前ダウンロードしておく（初回起動を速くする）
RUN firebase setup:emulators:firestore \
    && firebase setup:emulators:ui

RUN mkdir -p /opt/firebase/.data

COPY start-emulators.sh /usr/local/bin/start-emulators.sh
RUN chmod +x /usr/local/bin/start-emulators.sh

EXPOSE 4000 8080 9099

CMD ["/usr/local/bin/start-emulators.sh"]
