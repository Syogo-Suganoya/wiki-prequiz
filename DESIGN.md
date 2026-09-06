# 1分間予習クイズ Webアプリ 基本設計書

> **ここに書くのは「なぜそうしたか」だけ。** 手順は別ファイルにある。
> 遊びかたは [README.md](README.md)、開発手順は [CONTRIBUTING.md](CONTRIBUTING.md)、
> デプロイ手順は [DEPLOY.md](DEPLOY.md)、残作業は [TODO.md](TODO.md)。

## 1. 概要

Wikipedia 記事を1分間予習し、その内容のクイズに**早押し**で対戦する Web アプリ。

**記事は1ゲームに1本。** それを1分読み、そこから複数問（既定3問）出す。
問題と選択肢が同時に出て、**最初に答えた1人だけ**が得点・失点する。
配点は記事のプロパティ（PV数・被リンク数・本文中の数値規模）から決まり、
どの記事が出るかで得点の桁が変わる。

フレンド対戦（ルームキー共有）、ランダムマッチング、待ち時間を消すボット参戦を持つ。

早押しであることの帰結:

* 1問につき解答者は1人。「全員の解答を開示する」画面は存在しない。
* **「押す」ボタンは置かない。** 選択肢を最初から見せ、最初に選んだ人で確定する。
* 成立は1人だけなので、サーバー側の排他制御が要る。
* 答えなかった人は増減なし。

### 参考動画（元ネタ）

* [バキ童チャンネル【ぐんぴぃ】](https://www.youtube.com/@bakibakiDT)
* 予習クイズ: [【Wikipedia1分予習クイズ】](https://www.youtube.com/watch?v=RWWp09sJ54I)
* 配点の元ネタ: [【数クイズ】桁違いの超インフレ！](https://www.youtube.com/watch?v=33jR5YAt23g)

### 設計上の最重要原則

| # | 原則 | 理由 |
| :-- | :--- | :--- |
| P1 | **正解・他人の回答はクライアントに送らない** | ドキュメントに入れた瞬間 DevTools で読める |
| P2 | **スコアと状態遷移の書き込みは 100% サーバー（Admin SDK）経由** | クライアント直書きを許すとスコア改竄が自明 |
| P3 | **フェーズ進行 API は冪等**（`phaseSeq`） | 常駐ループが無く、誰が叩くか分からない |
| P4 | **リクエストの中で待たない** | 遅延は「未来時刻の予約」としてデータに持つ。sleep はリクエスト枠を占有する |
| P5 | **インメモリの状態に依存しない** | Cloud Run は複数インスタンスへスケールしうる |
| P6 | **解答はサーバーのトランザクションで1人に確定させる** | 到着順をクライアントの自己申告に任せると成立しない |

---

## 2. システム構成・技術スタック

### アーキテクチャ

フロントエンドを Vercel、API を Cloud Run、リアルタイム同期を Firestore が担う。
API はコンテナなので、ローカルの Docker 環境がそのまま本番構成になる。

![本番アーキテクチャ](docs/architecture_production.png)

図は [`docs/architecture.py`](docs/architecture.py)（`diagrams`）から生成する。

```bash
brew install graphviz && pip install diagrams
python docs/architecture.py
```

**データフローが一方通行**である点が要。クライアント → サーバーは REST のみ、
サーバー → クライアントは Firestore 購読のみで、クライアントは一切書き込まない。
正解を持つ `rooms/{id}/private` へクライアントから到達する経路が無いことが設計の核。

### 技術スタック

| 区分 | 選定技術 | 用途 |
| :--- | :--- | :--- |
| フロントエンド | React + Vite + TypeScript | SPA。SSR 不要 |
| API | Python 3.12 + FastAPI（Cloud Run） | 記事取得、作問、判定、フェーズ進行 |
| データストア | Firebase Firestore | **唯一の永続化層** |
| 認証 | Firebase Authentication（匿名） | uid をルールの主体にする。**未実装** |
| AI | Google Gemini `gemini-3.8-flash`（`google-genai`） | 問題生成、表記揺れ判定 |
| 状態管理 | Zustand | Firestore スナップショットの薄いラッパ |
| ローカル環境 | Docker Compose（エミュレータ同梱） | 本番の Firestore を汚さない |
| LP | 静的 HTML（[`lp/`](lp/)） | 依存なしの1ファイル |
| CI/CD | GitHub Actions | main への Push で自動デプロイ |

#### API を Cloud Run に置く理由

当初は Vercel の Python Functions を検討したが変更した。

| | Vercel Python Functions | **Cloud Run（採用）** |
| :--- | :--- | :--- |
| バンドル制限 | 250MB。`firebase-admin` + `google-genai` で圧迫 | 実質なし |
| 実行時間 | `maxDuration` の引き上げが必要 | 最大60分 |
| ローカルとの一致 | Docker はローカル専用 | **同じコンテナが本番でも動く** |
| コールドスタート | 毎リクエスト起動しうる | `min-instances=1` で常時待機 |
| Firestore 認証 | サービスアカウント JSON を環境変数に置く | **紐付けるだけ**（鍵ファイル不要） |

`--min-instances=1` でコールドスタートを消す。個人開発の規模なら費用も小さい。

#### モデル選定

`gemini-3.8-flash`（2026-09 時点の Flash 系最新）。作問に長考は不要なので
**thinking level は `low`**。レイテンシとコストを抑える。

### 環境変数

| 変数名 | 配置 | 用途 |
| :--- | :--- | :--- |
| `VITE_API_BASE_URL` | クライアント | Cloud Run のサービス URL |
| `VITE_FIREBASE_*` | クライアント | Firebase Web SDK 初期化（購読・認証の実装後に要る） |
| `FIREBASE_PROJECT_ID` | 両方 | プロジェクト ID |
| `CORS_ORIGINS` | サーバー | 許可オリジン（Vercel の本番・プレビュー） |
| `USE_MOCK` | サーバー | **作問だけ**を切り替える。既定 `true` |
| `GEMINI_API_KEY` | サーバー | `USE_MOCK=false` のとき必須 |
| `GEMINI_MODEL` | サーバー | 既定 `gemini-3.8-flash` |
| `WIKIMEDIA_USER_AGENT` | サーバー | **常に必須**。連絡先が無いと Wikimedia が 403 を返す |
| `ADMIN_TOKEN` | サーバー | 記事プール構築の合言葉。未設定ならその操作は誰も通さない |
| `FIRESTORE_EMULATOR_HOST` | ローカル | 設定時は Admin SDK がエミュレータへ向く。**本番では未設定であること** |
| `FIREBASE_AUTH_EMULATOR_HOST` | ローカル | 同上 |

> `FIRESTORE_EMULATOR_HOST` が本番に残ると、存在しないエミュレータへ繋ごうとして
> 全機能が落ちる。しかもデプロイ自体は成功する。`/api/health` の `using_emulator` で確かめる。

#### モック判定

**`USE_MOCK` だけで決まる。切り替わるのは作問（AI）だけ。**

| `USE_MOCK` | 記事 | 問題 | 予習スキップ |
| :--- | :--- | :--- | :--- |
| `true`（既定） | Wikipedia（`mock_data` にあるタイトルに限る） | 手で書いた問題 | 出る |
| `false` | Wikipedia（プール全体） | Gemini が記事から作る | 出ない |

記事まで偽物にしないのは、**本物の長さと構造**（2,000〜20,000字、節見出しあり）で
画面を確かめたいため。取得は無料で速く、課金されるのは作問だけ。

既定を `true` にしてあるのは、うっかり実 API を叩いて課金される事故のほうが痛いから。
キーの有無からの推測にしないのは、「キーは置いてあるが呼びたくない」が表現できず、
逆に「本番のつもりが黙ってモック」も起こるため。

切り替えの主体はサーバー。URL のクエリでは切り替えない（クライアントが自称できてはいけない）。
`POST /rooms/{id}/skip` はサーバー側でも検査して、モックでなければ 403 を返す。

##### モックの作問（`mock_data`）

**Wikipedia の記事を読んで人が書いた問題**を、記事タイトルをキーに置いている。
モックのときだけ**記事を選ぶ範囲をそのタイトルに狭める**ので、予習した記事の問題が必ず出る。

正規表現で穴埋めを機械生成する実装（`quizgen`）も試したが消した。
「◯◯に入るのは？」の形にしかならず、読解ではなく文字列の記憶を問うだけになる。
**問題の質はゲームの質そのもの**で、そこを機械で埋めても確かめたいことが確かめられない。

代償は、記事の幅が10本に狭まることと、本文が書き換わると答えが古くなりうること。
前者があるので、記事まわりの見た目は `USE_MOCK=false` でも一度は見る。

---

## 3. クイズ形式・ゲームモード・ポイント設計

### クイズ形式

* **4択（`MULTIPLE_CHOICE`）**: サーバー側で文字列一致の自動採点。
* **自由記述（`FREE_TEXT`）**: 正規化して完全一致 → 不一致分のみ LLM で表記揺れ判定。

### ゲームモード（配点）

| モード | 基礎値 `basePoint` |
| :--- | :--- |
| ① 固定点 `FIXED` | 常に `1,000` |
| ② 人気度 `POPULARITY` | `直近30日のPV合計 + 被リンク数 × 100` |
| ③ 最大数値 `MAX_NUMBER` | 記事本文中で最大の「数量」 |

#### 得点計算式

```
得点 = round2(basePoint) × 結果係数

round2(n) = 有効数字2桁に切り捨て   例: 123,456,789 → 120,000,000

結果係数（settings.scoring）
  正解 +1.0 / 誤答 -1.0 / 答えない 0
```

* `round2` は桁で殴り合う快感を保ちつつ、端数を捨てて読みやすくする。
* **答えない選択に罰を与えない。** 早押しでは「答える」こと自体がリスクで、
  そこに賭けるかが中心。答えない人まで減点すると全員が損をするだけになる。
* **正解と誤答の絶対値を揃える。** 確信があるかだけで判断でき、係数を覚えなくてよい。

#### `MAX_NUMBER` の抽出ルール

**正規表現で取る。LLM は使わない**（[`api/app/maxnumber.py`](api/app/maxnumber.py)）。
数字だけ見ると年号や順序数を拾うが、**単位を手がかりにすれば大半は落とせる**。

* 対象: 単位のホワイトリスト（人・円・メートル・トン・件 …）。
* 除外: 「度」「%」「KB」（量と紛らわしい。「7度のノミネート」を拾う）。
* 除外: 直前が「第」、直後が「目」（第2次 / 346人目）。
* 「1億5000万キロメートル」のような漢数字混じりの連なりは解く。
* 上限 `1e15`（一発ゲーム終了の防止）。下限 `1,000`（見つからなければ 0 → 下限）。

抽出は `start_game` の中で要るので、1〜3秒かかる LLM 応答は待てない（P4）。
正規表現なら 38ms で開始できる。このモードの面白さは正確さではなく桁なので、
多少の取り違えはゲームを壊さない。

> 限界は承知の上。実データ19件では「100人の彼女」（作品名）を数量として拾い、
> 俳優やドラマの記事は数量が本文に無く 0 になった。前者は配点が少しずれ、
> 後者は下限に落ちるだけで実害は無い。

#### モードの選択

ホーム画面でどれか1つを選ぶ。既定は `FIXED`。記事は1本なので**配点は全問で同じ**。
モード名の横の「!」で3モードの説明モーダルを出す。

---

## 4. マッチング & ボット参戦

### 1人用モード

対戦相手を入れず、ロビーも挟まずに始める。**ボットも入れない**（「ひとり」と
言っておいて相手が出てくるのはおかしい）。専用の分岐はほとんど無く、
参加者1人のルームを作って即開始するだけ。フェーズ制御も採点も対戦と同じ経路を通る。

### ⓪ ゲームルールの設定

| 項目 | 選択肢 | 既定 | 置き場所 |
| :--- | :--- | :--- | :--- |
| ゲームモード | 固定点 / 人気度 / 最大数値 | 固定点 | ホーム画面 |
| 問題数 | 1 / 2 / 3 問 | 3問 | 設定画面 |
| 予習時間 | 30 / 60 / 90 秒 | 60秒 | 設定画面 |

モードは得点の出かたが丸ごと変わる「遊びの種類」なので遊ぶ直前に選ぶ位置に残す。
問題数と予習時間は毎回変えるものではないので設定画面へ移し、`localStorage` に保存する
（書き込めない環境でも既定値で遊べるようにしておく）。

選べる値は API 側の `ROUNDS_CHOICES` / `STUDY_SEC_CHOICES` が唯一の定義で、
`GET /api/config` で配る。範囲外はサーバーが 400 で弾く。

> 問題数の上限3問は、固定問題が記事あたり3問だった頃の名残。広げる余地はある。

### ① マッチング方式

* **フレンド対戦**: 6桁のルームキー（紛らわしい `0/O/1/I` を除いた32文字）または URL 共有。
* **マッチング**: **ルールが完全に一致する相手とだけ**引き合わせ、定員4人まで。

ルールを1本の文字列に畳んだ **`matchKey` = `{モード}:{問題数}:{予習ms}`** を鍵にする。
ルームの `openKey` には**募集中のときだけ** `matchKey` を入れ、満室・開始・放置で `null` に落とす。
等値ひとつで引けるので複合インデックスが要らない。

参加はトランザクション内で人数を数えてから書くので、最後の1席を取り合っても定員を超えない。

**放置ルームの TTL。** 閉じられたルームが募集中のまま残ると、後から来た人が吸い込まれて
誰も開始しない。最後に人を見かけてから45秒（`OPEN_ROOM_TTL`）を過ぎたものは候補から外し、
**通りがかった人が畳む**。掃除役の常駐プロセスを置かずに済ませるため。
待っている人は `heartbeat` を打ち続けるので、本当に待っているルームは落ちない。

**開始はホストに限定しない。** `start_game` は `LOBBY` 以外なら何もしないので、
全員が叩いても始まるのは1回だけ。ホストが離脱したルームが永久に始まらないのを避ける。

### ② ボット参戦

**待ち時間が尽きたら空席を埋める。この待ち時間もサーバーでは待たない。**
クライアントが締切超過を検知して `fill-bots` を叩き、サーバーが冪等に補填する。

#### 解答タイミングの予約

`ANSWERING` に入った瞬間、各ボットの「答えるか」「何ミリ秒後か」を先に決めて予約する。

```python
for bot in bots:
    knows = random.random() < bot.accuracy
    if not knows and random.random() > bot.aggression:
        continue                                     # 分からないので答えない

    base = bot.reaction_ms if knows else bot.reaction_ms * 1.8
    at = phase_started_at + timedelta(milliseconds=random.gauss(base, 700))
    room["bots"][bot.id] = {"buzzAt": at, "knows": knows}
```

`buzzAt` は公開領域に置いてよい。正解ではないし、先に見えていても人間が早く答えれば人間が勝つ。
クライアントは `buzzAt` を過ぎたボットを見つけたら `bot-answer` を代理で叩く。
成立の判定はサーバーのトランザクションなので、同時に代理送信されても結果は1つ（P6）。
サーバー側で `buzzAt <= now` を検証する。これが無いとクライアントがボットを操作できる。

`knows` が真なら正解、偽なら誤答候補から選ぶ。候補は作問時に一緒に作らせておくので
**実行時の LLM 呼び出しはゼロ**。

#### 何ミリ秒差で負けたか

`answer` は負けた人に `behindMs` と相手の名前を返す。

* **時刻はトランザクションに入る前に取る。** 中で取ると再試行の時間まで測ってしまい、
  横並びだったのに2秒差がついたように見えた。
* **解答権の判定は `status` より先に見る。** 成立した瞬間に `REVEALING` へ移るので、
  僅差で負けた人の要求は「もう `ANSWERING` ではない」状態で届く。
* 確定順で決まるので、到着が僅かに早くても負けうる。その場合 `behindMs` は 0 に丸める。
* 解答時間より大きい差は表示しない。競り負けではなく「もう終わっていた」だけ。

#### ボットのプロフィール

| 名前 | 色 | accuracy | reactionMs | aggression | キャラクター |
| :--- | :--- | ---: | ---: | ---: | :--- |
| ゆうき | `--p1` | 0.60 | 2800 | 0.25 | 標準的 |
| みなと | `--p2` | 0.85 | 2200 | 0.10 | 速くて正確。分からない問題には手を出さない |
| あおい | `--p4` | 0.35 | 1500 | 0.60 | やたら速いが当たらない |

> **ボットであることを UI に出さない。** 待ち時間を消すための仕組みであって見せ物ではない。

---

## 5. ゲームの進行フロー

### フェーズ状態機械

```
 LOBBY ──(start)──> GENERATING ──┐
                                  │ 記事1本の決定
                                  ▼
                             STUDYING (60s)   ← 予習は1ゲームに1回だけ
                                  │             この裏で作問が走る
                                  ▼
                    ┌───────> ANSWERING (15s) ──┐
                    │                            │ 誰かが答えた / 時間切れ
       次の問題あり   │                            ▼
                    └──────────────────────  REVEALING (8s)
                                                 │ 次の問題なし
                                                 ▼
                                              FINISHED
```

| フェーズ | 既定時間 | 画面 | 記事本文 |
| :--- | ---: | :--- | :--- |
| `LOBBY` | — | 参加者一覧・設定 | — |
| `GENERATING` | 数秒 | ローディング（記事タイトルを先に出す） | — |
| `STUDYING` | 60s（30/60/90） | 記事本文 + 時計 + 「この記事から◯問出ます」 | **表示** |
| `ANSWERING` | 15s | 問題文・配点バッジ・選択肢 | **非表示（重要）** |
| `REVEALING` | 8s | 誰が何と答えたか・正解・解説・「次の問題へ」 | 非表示 |
| `FINISHED` | — | 順位表・**読んだ記事へのリンク** | — |

> `ANSWERING` で記事を隠すのが「予習」というゲーム性の根幹。

15秒誰も答えなければ**流局**（全員増減なし）。1問につき解答は1回だけで、
誤答しても他の人に権利は移らない（1問あたりの時間が読めなくなるため）。

#### 作問は予習の裏で走らせる

`start` の中でまとめてやると、**押した人だけが数十秒待たされ、その間ほかの参加者には
何も見えない**。そこで2段に分ける。

1. `POST /rooms/{id}/start` … 記事を1本決めてすぐ `STUDYING` へ（`quizReady: false`）
2. `POST /rooms/{id}/prepare-questions` … 予習中にクライアントが叩き、そこで作問する

* **担当はトランザクションで1つに絞る**（`quizClaimedAt`）。全員が叩いても生成は1回。
* **担当は45秒で失効する**（`QUIZ_CLAIM_TTL`）。担当した端末が落ちたまま誰も作らない状態を避ける。
* **作問が終わるまで `STUDYING` から出さない。** 空の問題で出題へ入るより予習が延びるほうがまし。
* 失敗したら担当を解放し、`quizError` に理由を残す。次の呼び出しでやり直せる。

本文は作問に要るので `private/quizSet.extract` に持つ。公開領域の `article.extract` は
予習が終わると `null` にするため使えない。

#### 「押す」フェーズを設けない理由

当初は `BUZZING`（押す）と `ANSWERING`（答える）を分けていたが統合した。
押しボタンを挟むと「とりあえず押して考える」が有利になり、それを潰すために
時間切れペナルティという追加ルールが要る。選択肢を最初から見せれば押し得は構造的に発生しない。

### フェーズ進行の駆動主体

常駐サーバーがないため:

1. サーバーは遷移時に `phaseEndsAt`（絶対時刻）と `phaseSeq`（単調増加）を書く。
2. クライアントは `phaseEndsAt` を過ぎたら `POST /rooms/{id}/advance { expectedPhaseSeq }` を送る。
3. サーバーはトランザクションで `phaseSeq` の一致と `now >= phaseEndsAt - 1000ms`
   （1秒は時計誤差の許容）を検証し、満たすときだけ遷移する。

4人が同時に叩いても遷移は1回。全員が切断しても、誰かが再接続すれば超過を検知して復帰する。

### 時刻同期

クライアントの時計は数秒ずれうる。初回に `GET /api/time` でオフセットを取り
（往復時間の半分を補正）、表示残り時間 = `phaseEndsAt - (Date.now() + offset)` とする。

---

## 6. データ構造設計 (Firestore)

```
rooms/{roomId}                      公開状態。参加者は read のみ
  ├── private/quizSet               全ラウンド分の問題。クライアントからは read すら不可
  └── answers/{playerId}            自分の回答のみ read 可

articles/{articleId}                記事キャッシュ（本文・PV・被リンク）
```

### ルームドキュメント（公開領域）

```json
{
  "roomId": "K7M2XQ",
  "isPrivate": false,
  "status": "ANSWERING",
  "phaseSeq": 7,
  "phaseStartedAt": "2026-09-05T00:03:12.000Z",
  "phaseEndsAt": "2026-09-05T00:03:27.000Z",
  "hostId": "user_id_1",

  "settings": {
    "quizFormat": "MULTIPLE_CHOICE",
    "gameMode": "POPULARITY",
    "totalRounds": 3,
    "durations": { "studyMs": 60000, "answerMs": 15000, "revealMs": 8000 },
    "scoring": { "correctMul": 1.0, "wrongMul": -1.0 }
  },

  "currentRound": 2,
  "currentQuestion": {
    "articleTitle": "富士山",
    "articleUrl": "https://ja.wikipedia.org/wiki/富士山",
    "question": "この山が最後に噴火した年は西暦何年？",
    "choices": ["1707年", "1800年", "1603年", "1868年"],
    "basePoint": 84000,
    "correctAnswer": null,
    "explanation": null
  },

  "buzz": {
    "ownerId": null, "buzzedAt": null, "answeredAt": null,
    "answer": null, "isCorrect": null, "delta": null
  },

  "bots": { "bot_1": { "buzzAt": "2026-09-05T00:03:14.900Z" } },

  "players": {
    "user_id_1": {
      "username": "Player1", "color": "p1", "isBot": false,
      "score": 1000, "lastSeenAt": "2026-09-05T00:03:20.000Z"
    }
  },

  "createdAt": "2026-09-05T00:00:00Z"
}
```

**`buzz` が解答記録の中心。** 1問につき解答者は1人なので、プレイヤーごとの回答欄は要らない。
`ownerId` が `null` ならまだ誰も答えていない。`buzzedAt` はサーバー受信時刻（クライアント申告ではない）。

**`null` は P1 の実装。** `correctAnswer` / `explanation` と `buzz.answer` / `isCorrect` / `delta` は
`ANSWERING` 中は必ず `null` で、`REVEALING` へ移った瞬間にサーバーが非公開領域からコピーする。
締切前に正解や他人の回答が公開ドキュメントに存在しないことを保証する。

### 非公開ドキュメント (`rooms/{roomId}/private/quizSet`)

```json
{
  "questions": [{
    "round": 1,
    "question": "この山が最後に噴火した年は西暦何年？",
    "choices": ["1707年", "1800年", "1603年", "1868年"],
    "correctAnswer": "1707年",
    "explanation": "宝永大噴火は1707年12月16日に発生しました。",
    "evidence": "宝永大噴火（1707年）が最後の噴火である",
    "botWrongAnswers": ["1800年", "1603年", "1868年"]
  }]
}
```

`evidence` は記事本文からの引用。生成後に**本文に実際に含まれるか検証**し、
含まれなければ破棄して再生成する（ハルシネーション対策）。

### 記事キャッシュ (`articles/{articleId}`)

```json
{
  "title": "富士山",
  "extract": "富士山（ふじさん）は、静岡県と山梨県にまたがる…",
  "charCount": 8420,
  "pageviews30d": 62000,
  "backlinks": 220,
  "fetchedAt": "2026-09-04T12:00:00Z",
  "enabled": true
}
```

`fetchedAt` から24時間以内ならキャッシュを使う。

**最大数値は保存しない。** 本文から導けるので読むたびに出す。持たせると、
本文を取り直したときに数値だけ古いまま残る道ができる。

`enabled` は人手のスイッチ。人気記事の一覧には出題に向かない記事も混ざるので、
プールを補充したあとに目を通して落とす。抽出はこのフラグを見る。

### セキュリティルール

```js
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /rooms/{roomId} {
      allow read: if request.auth != null
                  && request.auth.uid in resource.data.players;
      allow write: if false;

      match /private/{doc}       { allow read, write: if false; }
      match /answers/{playerId}  {
        allow read: if request.auth != null && request.auth.uid == playerId;
        allow write: if false;
      }
    }
    match /articles/{articleId}  { allow read, write: if false; }
  }
}
```

Admin SDK はルールをバイパスするので、サーバー側の書き込みは影響を受けない。
全面 `allow write: if false` で、スコア改竄の経路を構造的に断つ。

### ライフサイクルとインデックス

| コレクション | 寿命 | 掃除方法 |
| :--- | :--- | :--- |
| `rooms/{id}` | 24時間 | `expiresAt` に Firestore の TTL ポリシー |
| `articles/{id}` | 永続 | 手動で補充（[DEPLOY.md §7](DEPLOY.md)） |

> サブコレクションは親ドキュメントを消しても**自動では消えない**。
> TTL に任せず、`FINISHED` 遷移時にサーバーが `private` を明示的に削除する。

インデックスは [`firebase/firestore.indexes.json`](firebase/firestore.indexes.json)。
`articles` の `randomKey`（登録時に入れる 0〜1 の乱数）は、
`where(randomKey >= X).limit(n)` で安価にランダム抽出するためのもの
（Firestore に `ORDER BY RANDOM()` が無い）。

### プレゼンス（切断検知）

Firestore には `onDisconnect` がない。

* クライアントは5秒ごとに `heartbeat` を送り、サーバーが `lastSeenAt` を更新。
* `now - lastSeenAt > 30s` は「切断中」と灰色表示。**ゲームは止めない**（無回答扱い）。
* リロード時は `localStorage` の `{ playerId, roomId }` で復帰。

---

## 7. API 設計

FastAPI（Cloud Run）。**認証は暫定で `X-Player-Id` ヘッダをそのまま uid として扱う。**
Firebase 匿名認証の ID トークン検証への差し替えは未実装（[TODO.md](TODO.md)）。

| メソッド / パス | 用途 |
| :--- | :--- |
| `GET  /api/time` | サーバー時刻。時計オフセット計測用 |
| `GET  /api/health` | Firestore 疎通、モック判定、足りない設定 |
| `GET  /api/config` | モックか否か、選べるルールの一覧 |
| `POST /api/rooms` | ルーム作成 |
| `POST /api/rooms/{id}/join` | 入室 |
| `POST /api/rooms/{id}/start` | 記事を1本決めて `STUDYING` へ（作問はまだ） |
| `POST /api/rooms/{id}/prepare-questions` | 予習中に作問する。担当は1つだけ |
| `POST /api/rooms/{id}/advance` | フェーズ進行（冪等） |
| `POST /api/rooms/{id}/answer` | **解答**（最初の1人だけ成立） |
| `POST /api/rooms/{id}/bot-answer` | ボットの解答をクライアントが代理送信 |
| `POST /api/rooms/{id}/ready` | 「次の問題へ」。全員そろえば締切を待たず進む |
| `POST /api/rooms/{id}/heartbeat` | プレゼンス更新 |
| `POST /api/rooms/{id}/fill-bots` | 空席をボットで埋める（冪等） |
| `POST /api/matchmake` | 同じルールで募集中のルームへ入る。無ければ立てる |
| `POST /api/articles/build-pool` | 記事プールの補充。**`X-Admin-Token` が要る** |
| `POST /api/rooms/{id}/skip` | 現フェーズの締切を今にする。**モック時のみ** |

### `advance` の遷移処理

| 遷移 | サーバー処理 |
| :--- | :--- |
| `STUDYING → ANSWERING` | 記事本文を公開領域から除去。ボットの `buzzAt` を予約 |
| `ANSWERING → REVEALING` | 誰も答えなければ流局。答えた場合は採点済みで即遷移 |
| `REVEALING → STUDYING` | 次ラウンドを `quizSet` から公開領域へ展開。`buzz` / `bots` / `ready` をリセット |
| `REVEALING → FINISHED` | 最終順位を確定 |

### `answer`

このゲームの中核。**トランザクションで最初の1人だけを成立させる。**

```python
@firestore.transactional
def claim(tx, room_ref, player_id):
    room = room_ref.get(transaction=tx).to_dict()
    if room["status"] != "ANSWERING" or room["currentRound"] != round_:
        return False
    if room["buzz"]["ownerId"] is not None:
        return False                      # 先に答えられた
    tx.update(room_ref, {
        "buzz.ownerId":  player_id,
        "buzz.buzzedAt": SERVER_TIMESTAMP,
    })
    return True
```

成立しなかった側には `accepted: false` を返すだけで、正誤は一切漏らさない。

### `ready`

`ready.{uid}` を立て、**人間の参加者が全員押したら**締切を待たずに進める。
ボットは最初から準備済みとみなす。`force=True` が飛ばすのは**締切の判定だけ**で、
`phaseSeq` による冪等性は維持する（そうしないと遅れて届いた要求が次のラウンドまで飛ばす）。
誰も押さなくても8秒で進む。

### 採点

早押しなので**採点対象は常に1件**。

```
1. 成立した解答を取得（誰も答えなければ流局）
2. MULTIPLE_CHOICE → 文字列一致
   FREE_TEXT       → ① 正規化（NFKC・小文字化・記号除去・カタカナ→ひらがな）して一致
                     ② 一致しなければ Gemini で表記揺れ判定（1回）
3. delta = round2(basePoint) × (correctMul | wrongMul)
4. players[ownerId].score += delta      ※ 押さなかった人は触らない
```

---

## 8. 外部 API 利用仕様

### Wikipedia / Wikimedia

| 用途 | エンドポイント | 備考 |
| :--- | :--- | :--- |
| 本文取得 | `w/api.php?action=query&prop=extracts&explaintext=1` | `exintro` は付けない（全文が要る） |
| PV数 | `rest_v1/metrics/pageviews/per-article/...` | **集計に1〜2日の遅延**。終端は `today - 2d` |
| 被リンク | `api.php?action=query&list=backlinks` | 上限500。**継続せずクリップ**（近似で十分） |
| 人気記事 | `rest_v1/metrics/pageviews/top/ja.wikipedia/...` | 記事プールの種 |

* `User-Agent` に連絡先を含めないと 403。
* 被リンクは `× 100` して PV とスケールを揃える。
* PV が 0 の記事は `basePoint` が下限 1,000 に落ちる。

### 記事プール（ランダム記事を直接使わない理由）

`action=query&list=random` はスタブ・曖昧さ回避・一覧記事を大量に引く。
60秒予習の題材として成立しないので、条件を満たす記事を貯めておく。

* 本文 2,000〜20,000字（短い＝問題が作れない / 長い＝60秒で読めない）
* タイトルに「一覧」「曖昧さ回避」を含まない
* 直近30日 PV が 1,000 以上

これでゲーム中の Wikipedia 呼び出しは実質キャッシュ参照だけになる。
補充は手動（[DEPLOY.md §7](DEPLOY.md)）。**定期実行は置かない** — 人気記事の顔ぶれは
日単位でしか動かず、出題に向かない記事が混ざるので人の目を通したい。

### Gemini

* SDK は `google-genai`（旧 `google-generativeai` は使わない）。
* **構造化出力（`responseSchema`）を必ず使う。** JSON パース失敗のリトライを設計から排除する。
* 混雑・一時障害（429/500/502/503/504）は最大3回まで待って再試行する。
  それ以外は待っても直らないので即座に諦め、**遊ぶ人に見せる日本語**にして画面へ返す。
* プロンプトの制約:
  * 本文に明示的な根拠がある問題のみ。`evidence` に原文を抜粋させる。
  * 選択肢は同一カテゴリ・同程度の文字数（正解が最長になるリークの防止）。
  * 生成後にサーバー側で必ずシャッフルする（LLM は先頭に正解を置きがち）。

---

## 9. 画面 (UI/UX) 設計方針

| 画面 | 主要素 |
| :--- | :--- |
| トップ | ニックネーム、ゲームモード、現在の設定、「マッチング」「フレンド対戦」「ひとりで遊ぶ」 |
| 設定 | 問題数・予習時間。`localStorage` に保存 |
| ロビー | 参加者一覧、開始ボタン。**ルームキーはフレンド対戦の部屋にだけ出す** |
| マッチング待機 | 「さがしています → マッチングしました → まもなく開始します」を順に出してそのまま開戦 |
| 予習 | 右上に時計、中央に記事本文（ここだけスクロール可）、上部に配点バッジ |
| 解答 | 問題文、配点バッジ、選択肢 |
| 開示 | 誰が何と答えたか、正解、解説、「次の問題へ」 |
| 結果 | 順位表、**読んだ記事へのリンク** |

### 演出

* **配点バッジ**が解答フェーズの主役。`+120,000,000` が出た瞬間がゲームの山場。
* **残り時間はアナログ時計の針1本。** 数字を読ませるより回る針のほうが焦りが伝わる。
  残り5秒で赤。目盛りと中心の点は置かない（十字が入ると照準に見える）。
* **選択肢は色と形の両方で見分ける**（丸・三角・四角・菱形）。色だけだと色覚特性のある人が
  選び違える。記号の中の数字はキーボードの割り当てと同じにして、覚えることを減らす。
* **数字キー 1〜4 で解答できる。** 早押しでタップだけだと PC の人が構造的に不利になる。
* **競り負けた人には何秒差だったかを見せる。** 差が見えないと勝負として成立しない。
  表示は**開示画面**で行う（成立した瞬間に画面が切り替わるので、出題画面には出せない）。
* **ボットであることを一切表示しない。**
* **ルームキーはフレンド対戦のロビーだけ**（`room.isPrivate` で判定）。
  誰かを呼ぶための道具なので、相手が自動で決まる導線には用がない。
* **最終結果に記事リンクを置く。** 答えられなかった問題の答えが載っている。
* **得点は画面下部に固定。** 誰がいくつ持っているかは常に見えている必要がある。
* **favicon は LP とアプリで同一ファイル**（`web/public/` の3点は `lp/` からの複製）。
  タブに並んだときに同じ product だと分かる必要がある。差し替えるときは両方。

### モバイル対応

60秒で記事を読む都合上、**スマホでの本文可読性が体験の生命線**。
本文は最低16px・行間1.8、選択肢は親指で押せる大きさ、
予習中は縦スクロール以外の操作を要求しない。

---

## 10. ローカル開発環境

手順は [CONTRIBUTING.md](CONTRIBUTING.md)。ここには**なぜその構成にしたか**だけ書く。

![ローカル開発環境](docs/architecture_local.png)

* **エミュレータの切り替えは環境変数だけ。** `FIRESTORE_EMULATOR_HOST` があれば
  Admin SDK も Web SDK も自動でエミュレータへ向く。アプリ側に分岐を書かない。
* **エミュレータには JDK 21 以上が要る。** Firestore エミュレータは JVM 上で動き、
  最近の `firebase-tools` は Java 17 を拒否する（bookworm 系の `default-jre` は失敗する）。
* **データは named volume に永続化する。** `--export-on-exit` / `--import` で、
  `docker compose down` を挟んでも記事プールが残る
  （[`firebase/start-emulators.sh`](firebase/start-emulators.sh)）。
* **Gemini と Wikimedia にはエミュレータがない。** ローカルでも実 API を叩く。
* **`node_modules` / `.venv` は匿名ボリュームで保護する。** ソースをバインドマウントすると
  ホスト側の空ディレクトリが依存関係を覆い隠す。
* **`/` が LP、`/quiz` がゲーム**という配置を本番と揃える（nginx の `lp` サービス）。
  パスの食い違いは本番でしか顔を出さないので、手元で同じ形にしておく。

| | ローカル | 本番 |
| :--- | :--- | :--- |
| API | Docker Compose（`uvicorn --reload`） | Cloud Run（同じイメージの prod ステージ） |
| Firestore | エミュレータ | 本番 Firestore |
| フロント | Vite dev server + nginx | Vercel（静的配信） |

---

## 11. CI/CD

Workflow は [`.github/workflows/`](.github/workflows/) に2つ。
**設定手順と Secrets は [DEPLOY.md §8](DEPLOY.md)。** ここには方針だけ。

| Workflow | 契機 | 内容 |
| :--- | :--- | :--- |
| `ci.yml` | Push / PR | `ruff` → `mypy` → `pytest` / `tsc` → `build` |
| `cd.yml` | `main` への Push（**現在は停止中**） | Firestore ルール → Cloud Run → Vercel |

* **CD は当面オフ。** デプロイ先が整う前に繋ぐと失敗通知が出続けるだけ。
  手動実行で通ることを確かめてから `push:` を開ける。
* **ルールを最初に出す。** 逆順だと、ルールが古いまま新しい API が動く時間帯ができる。
* **認証は Workload Identity 連携。** 鍵を GitHub Secrets に置かない。
  `attribute-condition` でリポジトリを限定する（付け忘れると他人のリポジトリからも使える）。
* **テストはエミュレータ上で回す。** CI でも本番 Firestore に触れない。
* **デプロイ直後に `/api/health` を叩く。** `using_emulator` が `false` であることを確かめる。
* **パスフィルタ。** `web/**` の変更で Cloud Run を再デプロイしない。

---

## 12. 実装状況

`docker compose up` で**1ゲームを最後まで遊べる**。データ構造とフェーズ制御は本書のとおり。

未実装は2点だけで、どちらも**サーバー側のゲームロジックに手を入れずに差し替えられる**
ように分離してある。

| 項目 | 状態 |
| :--- | :--- |
| Firestore 直接購読（`onSnapshot`） | ⏳ いまは 400ms の API ポーリングで代用 |
| Firebase 匿名認証 | ⏳ いまは `X-Player-Id` ヘッダで代用 |

本番へ出すまでの手順と残りは [TODO.md](TODO.md)。
