# 開発の手引き

ここは**手元で動かして直すため**の文書。

## 必要なもの

Docker / Docker Compose だけ。Node も Python もコンテナ内で完結する。
本番相当で動かすなら Gemini の API キー。

## 起動

```bash
cp .env.example .env
docker compose up
```

| URL | 内容 |
| :--- | :--- |
| http://localhost:3000 | **LP。ここから入る**（本番と同じ形） |
| http://localhost:3000/quiz | ゲーム本体 |
| http://localhost:5173/quiz/ | ゲーム本体（Vite に直接。nginx を挟まない） |
| http://localhost:8000/api/health | API と Firestore の疎通確認 |
| http://localhost:8000/docs | OpenAPI |
| http://localhost:4000 | Emulator UI |

**手元の配置は本番と同じ。** `/` が LP、`/quiz` がゲームで、`lp` サービス（nginx）が
`lp/` を配って `/quiz` を `web` へ流す（[`docs/lp-nginx.conf`](docs/lp-nginx.conf)）。
パスの食い違いは本番でしか顔を出さないので、手元で同じ形にしておく。
開発サーバーにも `base: "/quiz/"` が効くので、Vite へ直接つなぐときも末尾の `/quiz/` が要る。

### モックと実データ

`.env` を書かなくても起動する。既定はモックなので、キーが無くても遊べる。

**`USE_MOCK` が切り替えるのは作問（AI）だけ。記事はいつも本物。**

| | 記事 | 問題 | 予習スキップ |
| :--- | :--- | :--- | :--- |
| `USE_MOCK=true`（既定） | Wikipedia（`mock_data` にある10本） | 手で書いた問題 | 出る |
| `USE_MOCK=false` | Wikipedia（プール全体） | Gemini が記事から作る | 出ない |

**`WIKIMEDIA_USER_AGENT` は常に必須。** `GEMINI_API_KEY` が要るのは `USE_MOCK=false` のときだけ。

モックの問題は [`api/app/mock_data.py`](api/app/mock_data.py) にある。
**記事を読んで人が書いた問題**で、記事タイトルがキー。モックのときはこの辞書にある
タイトルからしか記事を選ばないので、予習した記事の問題が必ず出る。
その代わり記事の幅は10本なので、記事まわりの見た目は一度は `USE_MOCK=false` で見ること。

**問題を足すには**、プールを貯めて Firestore の `articles` から本文を読み、
**読んだうえで**書いて `MOCK_QUESTIONS` に足す。タイトルは記事名と完全一致させる。

動かないときは `GET /api/health`。足りない設定が `missing_settings` に並ぶ。

### 実データで動かす

```bash
# .env に USE_MOCK=false / GEMINI_API_KEY / ADMIN_TOKEN を書いてから
docker compose up -d

curl -X POST 'http://localhost:8000/api/articles/build-pool?limit=30' \
  -H "X-Admin-Token: $ADMIN_TOKEN"
```

プールが空でもゲームは始まる（その場で人気記事から作る）が、`start` のレイテンシが
跳ねるので普段は貯めておく。**プール構築は合言葉が要る** — Wikipedia を何十回も呼ぶ操作なので、
URL を知っているだけで叩けては困る。未設定なら誰も通さない（503）。

## サービス構成

| サービス | 中身 | ポート |
| :--- | :--- | :--- |
| `emulator` | Firestore + Auth エミュレータ + Emulator UI | 8080 / 9099 / 4000 |
| `api` | FastAPI（`uvicorn --reload`） | 8000 |
| `web` | Vite dev server（HMR）。`base` は `/quiz/` | 5173 |
| `lp` | nginx。`/` で `lp/` を配り、`/quiz` を `web` へ流す | 3000 |
| `shots` | LP 用スクリーンショット撮影（`--profile shots`） | — |

## 確認コマンド

```bash
docker compose exec api ruff check .        # 静的検査
docker compose exec api ruff format .       # 整形
docker compose exec api mypy --strict app   # 型検査
docker compose exec api pytest              # テスト
docker compose exec web npx tsc --noEmit    # 型検査（フロント）
docker compose exec web npm run build       # 本番ビルドが通るか
```

CI が回すのも同じ内容。手元で通してから push する。

## LP 用スクリーンショットの撮影

```bash
docker compose --profile shots up --build shots
```

Chromium 入りのコンテナで [`docs/shots.js`](docs/shots.js) を実行し、
**利用者と同じ順に画面を操作しながら** `lp/shots/` へ書き出す。
画面を変えたら撮り直すだけで LP の図版が追随する。

* ホストの Chrome には触れない。
* 冒頭で予習時間を30秒にする。モック構成でなくても回るようにするため。
* ビューポートは 900×700。LP では図版を文章の脇に横並びで置くので、縦長だと読めなくなる。
* 画面を増やしたら `docs/shots.js` の連番と [`lp/index.html`](lp/index.html) を両方直す。

## アーキテクチャ図の生成

```bash
brew install graphviz && pip install diagrams
python docs/architecture.py
```

## 詰まりやすいところ

* **依存を足したのに反映されない** — `node_modules` / `.venv` を匿名ボリュームで
  隠しているため、古いものが残ることがある。
  ```bash
  docker compose up -d --force-recreate --renew-anon-volumes web
  ```
* **エミュレータが起動しない** — Firestore エミュレータは JVM で動き、最近の
  `firebase-tools` は Java 17 を拒否する。ベースイメージは `node:22-trixie-slim` +
  `openjdk-21-jre-headless`（bookworm 系の `default-jre` は Java 17 で失敗する）。
* **エミュレータのデータを消したい** — `docker compose down -v`
* **`web` というホスト名が拒否される** — 撮影用コンテナから来る場合。
  `vite.config.ts` の `allowedHosts` に入れてある。

## ニックネームの仕掛け

[`web/src/easterEgg.ts`](web/src/easterEgg.ts) は、特定の名前で始めたときだけ AA を
一枚挟む演出。**気づく余地を残したいので README と LP には書かない。**
消しても壊れないが、消さないでほしい。

絵は [`web/src/aa/`](web/src/aa/) の `.txt` を `?raw` で読む。差し替えはファイルの
置き換えだけでよく、コードは触らない。**1文字＝正方形のドット**として並べるので、
桁と行の比がそのまま絵の縦横比になる。

## コードの約束

* **コメントと docstring は日本語。** 何をしているかではなく、**なぜそうしたか**を書く。
  コードを読めば分かることは書かない。
* 設計原則は6つ。**正解を公開領域に置かない / 書き込みはサーバー経由 /
  フェーズ進行は冪等 / リクエストの中で待たない / インメモリ状態に依存しない /
  解答はトランザクションで1人に確定**。迷ったらこの6つに照らす。
