# 残っていること

本番を「モックで動くデモ」から「実データで遊べる状態」へ持っていくまでの手順。
**上から順に。** それぞれ前のものが済んでいないと成立しない。

手順の詳細は [DEPLOY.md](DEPLOY.md) にある。ここは順番と現在地だけ。

## いまの状態

| | 状態 |
| :--- | :--- |
| LP `https://wiki-prequiz.vercel.app/` | ✅ 公開済み |
| ゲーム `https://wiki-prequiz.vercel.app/quiz` | ✅ 公開済み。API の宛先も埋まっている |
| Cloud Run `prequiz-api` | ✅ 動作中。Firestore 疎通 OK |
| 出題 | ⚠️ **モック**（`mock: true` / 固定5問） |
| 記事プール（本番） | ❌ 空 |
| CD（GitHub Actions） | ❌ 停止中（`workflow_dispatch` のみ） |

ローカルのエミュレータには実データ19件が入っている。本番とは別物。

---

## 0. 手元の変更を push する

すべての前提。API 側に**認証と最大数値の抽出**が入っていないと、
以下の手順は成立しない。

```bash
git add -A && git commit && git push
```

含まれるもの:

* `POST /api/articles/build-pool` の合言葉（`ADMIN_TOKEN`）
* 最大数値の抽出を Gemini から正規表現へ（`api/app/maxnumber.py`）
* `.vercelignore`（`api/` を Vercel に渡さない）

push すると Vercel は自動でビルドするが、**Cloud Run は自動では出ない**。
CD がまだ止まっているので、手順 2 で自分でデプロイする。

---

## 1. `ADMIN_TOKEN` を用意する

記事プールを補充する口を、合言葉つきにする。未設定だとその操作は
誰にも通らない（503）ので、これを先にやる。

```bash
openssl rand -hex 32 | tr -d '\n' | gcloud secrets create admin-token \
  --data-file=- --project=wiki-prequiz

gcloud secrets add-iam-policy-binding admin-token \
  --member="serviceAccount:prequiz-api@wiki-prequiz.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" --project=wiki-prequiz
```

`tr -d '\n'` を落とさないこと。改行が混ざると、手で叩くときの値と一致しない。

---

## 2. 本番のモックを外して再デプロイ

`USE_MOCK=false` と `ADMIN_TOKEN` を同時に反映する。
新しいコードを載せるので `--source api` からのデプロイになる。

```bash
gcloud run deploy prequiz-api \
  --source api --region asia-northeast1 --project wiki-prequiz \
  --service-account prequiz-api@wiki-prequiz.iam.gserviceaccount.com \
  --min-instances=1 --allow-unauthenticated \
  --update-env-vars "USE_MOCK=false" \
  --update-secrets "GEMINI_API_KEY=gemini-api-key:latest,ADMIN_TOKEN=admin-token:latest"
```

確認:

```bash
curl -s https://prequiz-api-412961422899.asia-northeast1.run.app/api/health
```

* `"mock": false` になっていること
* `"missing_for_real": []` が空のままであること
* `"using_emulator": false` であること

> **`GEMINI_API_KEY` が本物かどうかは、ここで初めて分かる。**
> 手元の `.env` はプレースホルダのままで、**Gemini の実呼び出しは一度も
> 成功していない**。モックを外すと作問が Gemini に切り替わるので、
> キーが無効なら予習は始まっても問題が出てこない。
> 予習画面に「問題を準備しています…」が出たまま進まなければ、これを疑う。

---

## 3. 記事プールを貯める（URL を叩く）

定期実行は置かない。**貯めたいときに手で叩く。**

```bash
TOKEN=$(gcloud secrets versions access latest --secret=admin-token --project=wiki-prequiz)

curl -X POST \
  'https://prequiz-api-412961422899.asia-northeast1.run.app/api/articles/build-pool?limit=50' \
  -H "X-Admin-Token: $TOKEN"
```

`{"added": 42, "skipped": 8, "seen": 50}` のように返る。50件で20秒ほど。

### 3-1. 貯めたら必ず目を通す

**人気記事の一覧は、出題に向かない記事を返す。**
ローカルで19件試したときは、こういうものが混ざった。

* `真夏の夜の淫夢` — 公序良俗
* `闇サイト殺人事件` — 実在の被害者がいる事件
* タイタニック関連が4件 — 同じ題材ばかりで飽きる

タイトルの正規表現（`一覧|曖昧さ回避|Template:` …）では弾けない。
Firestore コンソールで `articles` を開き、外したい記事の `enabled` を
`false` にする。抽出はこのフラグを見ている。

**この一手間は自動化しない。** 何が不適切かは人が決めることなので。

---

## 4. 通しで遊んで確かめる

`https://wiki-prequiz.vercel.app/quiz` で「ひとりで遊ぶ」。

* 記事がモックの5本（太陽・カピバラ・万里の長城・富士山・…）**ではない**こと
* 予習画面に「予習をスキップ（モック）」が**出ない**こと
* 60秒待たずに問題が出ること（予習の裏で作問が終わっている）
* `最大数値` モードで、配点が 1,000 以外になる記事があること

---

## 5. CD をオンにする

ここまでが手で通ってから。デプロイ先が無い状態で自動化しても、
失敗通知が出続けるだけで何の役にも立たない。

`.github/workflows/cd.yml` 冒頭の `push:` ブロックのコメントを外す。
**その前に**下の3つを済ませる（詳細は [DEPLOY.md §8](DEPLOY.md)）。

- [ ] **Workload Identity 連携** — 鍵ファイルを置かずに GCP へ入る
- [ ] **GitHub Secrets** — `GCP_*` / `VERCEL_*` / `FIREBASE_TOKEN` など10件
- [ ] **手動で1回流す** — Actions → CD → Run workflow

> Vercel は Git 連携で既に自動ビルドされている。`cd.yml` の web ジョブと
> **二重にデプロイが走る**ので、どちらかに寄せること。
> Vercel 側を止めるなら `vercel.json` に `"ignoreCommand": "exit 0"`。

---

## そのうち

急がないが、放っておくと効いてくるもの。

- [ ] **Firestore の直接購読（`onSnapshot`）** — いまは 400ms ポーリング。
      早押しの精度と Firestore の読み取り回数の両方に効く
- [ ] **Firebase 匿名認証** — いまは `X-Player-Id` ヘッダをそのまま信じている。
      他人の ID を名乗れる
- [ ] **記事プールの手動キュレーション用の画面** — Firestore コンソールで
      `enabled` を触るのは、続けるなら面倒
