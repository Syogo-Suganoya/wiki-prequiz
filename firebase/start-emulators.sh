#!/bin/sh
set -eu

# 書き出し先は、マウントされたボリューム**の下**に掘る。
# firebase-tools は export の直前に出力先を rmdir するので、
# マウントポイントそのものを指すと EBUSY で毎回失敗し、
# 「終了時に保存しているつもりで実は何も残っていない」状態になる。
VOLUME=/opt/firebase/.data
DATA_DIR="${VOLUME}/export"
PROJECT="${GCLOUD_PROJECT:-prequiz-local}"

mkdir -p "${VOLUME}"

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
