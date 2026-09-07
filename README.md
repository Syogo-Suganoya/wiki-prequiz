# 1分間予習クイズ

![alt text](lp/shots/top.png)

Wikipedia の記事を **1分だけ予習**して、あとは早押しでクイズに答えるオンライン対戦ゲーム。

記事は1ゲームに1本だけ。その1本を全員で読んでから、そこから3問が出ます。

> [バキ童チャンネル【ぐんぴぃ】](https://www.youtube.com/@bakibakiDT) の
> [テスト期間を思い出せ！お題のWiki記事を1分だけ予習できる山張り暗記クイズ](https://www.youtube.com/watch?v=ynQPsNxLPOo) を元ネタにしました。
> さらに、点数計算は [【数クイズ】クイズの答えがそのまま得点になるクイズで盛り上がろう！](https://www.youtube.com/watch?v=l1G6pRrfMZg) を参考にしました。
> 個人開発の非公式ファンメイド作品です。チャンネルおよび動画制作者とは関係ありません。

## 遊びかた

1. **予習（60秒）** — 渡された Wikipedia の記事を読む。全員が同じ記事を読みます。
<img src="lp/shots/05-study.png" alt="予習画面。東京タワーの記事本文が表示されている">

2. **クイズ** — **記事が消えて**問題と選択肢が出る。
<img src="lp/shots/06-question.png" alt="解答画面。記事が消えて4択が出ている">

3. **結果** — 順位と、今回読んだ記事へのリンクが出ます。
<img src="lp/shots/08-result.png" alt="結果画面。順位と読んだ記事へのリンク">

遊びかたは3つ。

* **マッチング** — 同じルールを選んだ人と自動で対戦
* **フレンド対戦** — 6桁のルームキーを共有して、友だちと対戦
* **ひとりで遊ぶ** — 相手なし。自分のペースで記事を読んで答えるだけ

### ゲームモード

正解したときの点数の決まり方が変わります。既定は固定点。

<img src="lp/shots/02-modes.png" alt="3つのゲームモードの説明モーダル">

| モード | 配点 |
| :--- | :--- |
| **固定点** | 常に 1,000 点 |
| **人気度** | 記事の PV 数 ＋ 被リンク数 × 100 |
| **最大数値** | 記事の中でいちばん大きい数字 |

<br clear="all">

問題数（1〜3問）と予習時間（30/60/90秒）は設定画面で変更できます。

## 技術構成

![本番構成](docs/architecture_production.png)

**フロントエンド**

![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?style=flat-square&logo=vite&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-7-3178C6?style=flat-square&logo=typescript&logoColor=white)
![Zustand](https://img.shields.io/badge/Zustand-5-433E38?style=flat-square)
![Vercel](https://img.shields.io/badge/Vercel-000000?style=flat-square&logo=vercel&logoColor=white)

**API**

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Cloud Run](https://img.shields.io/badge/Cloud%20Run-4285F4?style=flat-square&logo=googlecloud&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)

**データ・AI**

![Firestore](https://img.shields.io/badge/Firestore-FFCA28?style=flat-square&logo=firebase&logoColor=black)
![Gemini](https://img.shields.io/badge/Gemini%203.8%20Flash-8E75B2?style=flat-square&logo=googlegemini&logoColor=white)
![Wikipedia](https://img.shields.io/badge/Wikimedia%20REST%20API-000000?style=flat-square&logo=wikipedia&logoColor=white)

**開発・CI**

![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?style=flat-square&logo=githubactions&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black)
![mypy](https://img.shields.io/badge/mypy--strict-2A6DB2?style=flat-square)

## 今後の展望

遊べる状態にはなっていますが、代用のまま残しているところがあります。
上の2つは**早押しゲームとしての土台**なので、他より先に手を入れます。

| やること | いまの状態 | なぜ |
| :--- | :--- | :--- |
| **Firestore の直接購読**（`onSnapshot`） | 400ms ごとの API ポーリング | ミリ秒を競うゲームで、画面の切り替わりが**最大0.4秒遅れる**。読み取り回数も無駄に増える |
| **Firebase 匿名認証** | `X-Player-Id` ヘッダを信用 | 他人の ID を名乗れてしまう。セキュリティルールが前提にしている `request.auth` も埋まらない |
| **自由記述モード** | 4択のみ | 設計はしてあるが未実装。正規化で一致を見て、揺れだけ AI に判定させる |
| **記事プールの管理画面** | Firestore コンソールで `enabled` を手で切り替え | 出題に向かない記事を落とす作業が続くなら、専用の画面が要る |
| **1ゲームの問題数を増やす** | 上限3問 | 記事1本から何問まで出せて、60秒の予習で答えられるかは試していない |
