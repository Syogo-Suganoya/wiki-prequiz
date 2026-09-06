#!/bin/sh
set -eu

DATA_DIR=/opt/firebase/.data
PROJECT="${GCLOUD_PROJECT:-prequiz-local}"

# 前回の --export-on-exit で書き出されたデータがある場合だけ --import する。
# 空ディレクトリに --import すると firebase-tools がエラー終了するため。
if [ -f "${DATA_DIR}/firebase-export-metadata.json" ]; then
  echo "[emulator] 既存データを ${DATA_DIR} から復元します"
  set -- --import="${DATA_DIR}"
else
  echo "[emulator] 保存データなし。空の状態で起動します"
  set --
fi

exec firebase emulators:start \
  --only firestore,auth \
  --project "${PROJECT}" \
  --export-on-exit="${DATA_DIR}" \
  "$@"
