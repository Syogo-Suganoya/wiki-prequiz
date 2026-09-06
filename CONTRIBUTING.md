# 開発の手引き

設計の意図（なぜその作りなのか）は [DESIGN.md](DESIGN.md) にある。
本番へ出す手順は [DEPLOY.md](DEPLOY.md)。ここは**手元で動かして直すため**の文書。

## 必要なもの

* Docker / Docker Compose（これ以外は要らない。Node も Python もコンテナ内で完結する）
* 本番相当で動かすなら Gemini の API キー

## 起動

```bash
cp .env.example .env
docker compose up
```

| URL | 内容 |
| :--- | :--- |
| http://localhost:5173 | アプリ本体 |
| http://localhost:8000/api/health | API と Firestore の疎通確認 |
| http://localhost:8000/docs | OpenAPI（FastAPI の自動生成） |
| http://localhost:4000 | Emulator UI（Firestore の中身を目視で確認する） |

`.env` を書かなくても起動する。既定はモックなので、キーが無くても遊べる。

| `USE_MOCK` | 問題の出どころ | 予習スキップ |
| :--- | :--- | :--- |
| `true`（既定） | `api/app/mock_data.py` の固定問題 | 出る |
| `false` | Wikipedia + Gemini。`GEMINI_API_KEY` と `WIKIMEDIA_USER_AGENT` が必須 | 出ない |

**モックかどうかを決めるのは `USE_MOCK` だけ**で、URL のクエリでは切り替えられない。
切り替えの主体はサーバー側にあるべきで、クライアントが自称できてはいけないため。
クライアントは `GET /api/config` の `mock` を見て、開発用の操作を出し分けている。

`USE_MOCK=false` にしたのに動かないときは `GET /api/health` を見る。
足りない設定が `missing_for_real` に並ぶ。

### 実データで動かす

```bash
# .env に USE_MOCK=false と GEMINI_API_KEY と ADMIN_TOKEN を書いてから
docker compose up -d

# 記事プールを貯めておく（ゲーム開始時に何十本も取りに行かせないため）
curl -X POST 'http://localhost:8000/api/articles/build-pool?limit=30' \
  -H "X-Admin-Token: $ADMIN_TOKEN"
```

プールが空でもゲームは始まる（その場で人気記事から作る）が、
`start` のレイテンシが跳ねるので普段は貯めておく。

**プール構築は合言葉（`ADMIN_TOKEN`）が要る。** Wikipedia と Gemini を
何十回も呼ぶ操作なので、URL を知っているだけで課金させられては困る。
未設定なら誰も通さない（503）。設定を忘れて素通しになるより、
通らないほうが気づける。

**定期実行は置いていない。** 人気記事の顔ぶれは日単位でしか動かないし、
Wikimedia の人気一覧は出題に向かない記事も返すので、人の目を通したい。
貯めたいときに手で叩く運用にしてある。

## サービス構成

| サービス | 中身 | ポート |
| :--- | :--- | :--- |
| `emulator` | Firestore + Auth エミュレータ + Emulator UI | 8080 / 9099 / 4000 |
| `api` | FastAPI（`uvicorn --reload`） | 8000 |
| `web` | Vite dev server（HMR） | 5173 |
| `shots` | LP 用スクリーンショット撮影。通常の起動には含まれない | — |

## 確認コマンド

```bash
docker compose exec api ruff check .        # 静的検査
docker compose exec api ruff format .       # 整形
docker compose exec api mypy --strict app   # 型検査
docker compose exec api pytest              # テスト
docker compose exec web npx tsc --noEmit    # 型検査（フロント）
docker compose exec web npm run build       # 本番ビルドが通るか
```

CI が回すのもこれと同じ内容。手元で通してから push する。

## LP 用スクリーンショットの撮影

```bash
docker compose --profile shots up --build shots
```

Chromium 入りのコンテナ（[`docs/shots-image/`](docs/shots-image/)）で
[`docs/shots.js`](docs/shots.js) を実行し、**利用者と同じ順に画面を操作しながら**
`lp/shots/` へ書き出す。画面を変えたら撮り直すだけで LP の図版が追随する。

* ホストの Chrome には触れない。コンテナ内の Chromium だけを使う。
* 撮影の冒頭で設定画面から予習時間を **30秒**にする。モック構成でなくても回るようにするため。
* ビューポートは 900×700（デスクトップ）。LP では図版を文章の脇に横並びで置くので、
  縦長のスマホ画面だと縮小されて読めなくなる。
* 画面を増やしたら [`docs/shots.js`](docs/shots.js) の連番と、
  [`lp/index.html`](lp/index.html) の参照を両方直す。

## アーキテクチャ図の生成

```bash
brew install graphviz && pip install diagrams
python docs/architecture.py
```

## 詰まりやすいところ

* **依存を足したのに反映されない** — バインドマウントの下に匿名ボリュームで
  `node_modules` / `.venv` を隠しているため、古いものが残ることがある。
  ```bash
  docker compose up -d --force-recreate --renew-anon-volumes web
  ```
* **エミュレータが起動しない** — Firestore エミュレータは JVM で動き、最近の
  `firebase-tools` は Java 17 を拒否する。ベースイメージは `node:22-trixie-slim` +
  `openjdk-21-jre-headless`（bookworm 系の `default-jre` は Java 17 で失敗する）。
* **エミュレータのデータを消したい**
  ```bash
  docker compose down -v
  ```
* **`web` というホスト名が拒否される** — 撮影用コンテナから来る場合。
  `vite.config.ts` の `allowedHosts` に入れてある。

## ニックネームの仕掛け

[`web/src/easterEgg.ts`](web/src/easterEgg.ts) は、特定の名前で始めたときだけ
AA を一枚挟む演出。**気づく余地を残したいので README と LP には書かない。**
ゲーム進行には関わらないので、消しても壊れないが、消さないでほしい。

絵は [`web/src/aa/`](web/src/aa/) の `.txt` を `?raw` で読んでいる。
差し替えるときはファイルを丸ごと置き換えるだけでよく、コードは触らない。
**1文字＝正方形のドット**として並べる前提なので、桁と行の比がそのまま絵の縦横比になる。

## コードの約束

* **コメントと docstring は日本語。** 何をしているかではなく、
  **なぜそうしたか**を書く。コードを読めば分かることは書かない。
* **クライアントは Firestore に一切書き込まない。** 書き込みはすべて
  Admin SDK 経由（サーバー）。セキュリティルールは全面 `allow write: if false`。
* **正解を公開領域に置かない。** 正解と解説は `rooms/{id}/private/quizSet` にあり、
  `REVEALING` に入った時点でサーバーが公開領域へ写す。
* **リクエストの中で待たない。** 遅延は「未来時刻の予約」としてデータに持たせる
  （ボットの `buzzAt` が実例）。Cloud Run のリクエスト枠を占有しないため。
* **インメモリの状態に依存しない。** 複数インスタンスにスケールしうる。
  真実は常に Firestore 側にある。
* **フェーズ進行は冪等に。** `phaseSeq` を突き合わせるトランザクションで、
  誰が何度叩いても遷移は1回だけになるようにする。

以上は [DESIGN.md](DESIGN.md) の設計原則 P1〜P6 の要約。
迷ったら原文を読む。

## 実装の状況

何が動いていて何がモックのままかは、[DESIGN.md §12](DESIGN.md) の表にまとめてある。
現時点で未着手なのは、Firestore の直接購読と Firebase 匿名認証の2点。
どちらも**サーバー側のゲームロジックに手を入れずに差し替えられる**よう分離してある。

記事の取得と作問は実装済み（`app/wikipedia.py` / `app/gemini.py` / `app/content.py`）。
ただし **Gemini の実呼び出しはまだ動かせていない**（手元に有効なキーが無いため）。
`app/content.py` に閉じてあるので、`game.py` は記事がどこから来たかを知らない。
