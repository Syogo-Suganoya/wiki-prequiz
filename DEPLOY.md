# デプロイ手順

デプロイ先は3つに分かれる。

| 対象 | デプロイ先 | 中身 |
| :--- | :--- | :--- |
| `api/` | **Cloud Run**（`asia-northeast1`） | FastAPI。ローカルと同じイメージの `prod` ステージ |
| `web/` | **Vercel** | Vite でビルドした静的ファイル |
| `firebase/` | **Firebase** | Firestore のセキュリティルールとインデックス |

各手順に **CLI** と **GUI** の両方を載せる。どちらでやっても結果は同じ。

## この文書で使う具体名

以降のコマンドはこの名前で書いてある。**そのままコピーして使える。**

| 項目 | 値 |
| :--- | :--- |
| GitHub リポジトリ | `Syogo-Suganoya/wiki-prequiz` |
| GCP / Firebase プロジェクト ID | `wiki-prequiz` |
| リージョン | `asia-northeast1`（東京） |
| Cloud Run サービス名 | `prequiz-api` |
| 実行用サービスアカウント | `prequiz-api@wiki-prequiz.iam.gserviceaccount.com` |
| デプロイ用サービスアカウント | `prequiz-deployer@wiki-prequiz.iam.gserviceaccount.com` |
| Secret Manager のシークレット名 | `gemini-api-key` |
| Vercel プロジェクト名 | `wiki-prequiz` |
| 本番ドメイン | `https://wiki-prequiz.vercel.app` |

リポジトリ名は `wiki-prequiz`、内部の識別子は `prequiz-*` で揃えてある。
`prequiz` が語幹なので、`prequiz-api` は「wiki-prequiz の API」として読める。
Compose のコンテナ名（`prequiz-api` / `prequiz-web`）とも一致する。

> **プロジェクト ID は全世界で一意。** `wiki-prequiz` が既に使われていたら
> `wiki-prequiz-1` などにして、以降の `wiki-prequiz` を読み替える。
> **ID は後から変更できない**ので、作成時に確定させること。
>
> `<PROJECT_NUMBER>` だけはプロジェクト作成後に決まるので、ここでは伏せてある。
> ```bash
> gcloud projects describe wiki-prequiz --format='value(projectNumber)'
> ```

> **原則**: サービスアカウントの鍵ファイル（JSON）は作らない。
> Cloud Run にはサービスアカウントを紐付け、GitHub Actions からは Workload Identity 連携を使う。
> 鍵を発行すると、漏れたときに失効させる以外の手段がなくなる。

---

## 0. 事前準備

### CLI

```bash
# Google Cloud SDK と Firebase CLI
brew install --cask google-cloud-sdk
npm install -g firebase-tools vercel

gcloud auth login
gcloud projects create wiki-prequiz --name="wiki-prequiz"
gcloud config set project wiki-prequiz
firebase login

# 使う API を有効化する
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  iamcredentials.googleapis.com
```

### GUI

1. [Google Cloud コンソール](https://console.cloud.google.com/) で
   プロジェクト ID `wiki-prequiz` を指定して作成する。
2. **APIとサービス → ライブラリ** で以下を「有効にする」。
   Cloud Run Admin API / Cloud Build API / Artifact Registry API /
   Cloud Firestore API / Secret Manager API / IAM Service Account Credentials API
3. [Firebase コンソール](https://console.firebase.google.com/) で
   **プロジェクトを追加 → 既存の Google Cloud プロジェクト `wiki-prequiz` を選択**。

---

## 1. Firestore の作成

### CLI

```bash
gcloud firestore databases create \
  --location=asia-northeast1 \
  --type=firestore-native \
  --project=wiki-prequiz
```

### GUI

Firebase コンソール → **Firestore Database** → **データベースの作成** →
本番環境モード → ロケーション `asia-northeast1`。

> **ロケーションは後から変更できない。** Cloud Run と同じリージョンにする。
> 本番環境モードで作れば既定で全拒否になり、次の手順でルールを流し込むまで安全側に倒れる。

---

## 2. サービスアカウントの用意

Cloud Run が Firestore に触るための身元。鍵は作らない。

### CLI

```bash
gcloud iam service-accounts create prequiz-api \
  --display-name="wiki-prequiz API (Cloud Run)" \
  --project=wiki-prequiz

gcloud projects add-iam-policy-binding wiki-prequiz \
  --member="serviceAccount:prequiz-api@wiki-prequiz.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

### GUI

1. **IAMと管理 → サービスアカウント → サービスアカウントを作成**。
   ID は `prequiz-api`。
2. **IAMと管理 → IAM → アクセスを許可** で、いま作ったサービスアカウントに
   ロール **Cloud Datastore ユーザー** を付与する。
3. **鍵は作らない。**「キー」タブには触れない。

---

## 3. Firestore ルールとインデックスの反映

**アプリより先にこれを流す。** ルールは「クライアントからの書き込みを全面禁止」という
設計の実体そのものなので、後回しにすると一時的に無防備な本番ができる。

### CLI

```bash
cd firebase
firebase deploy --only firestore:rules,firestore:indexes --project wiki-prequiz
```

### GUI

Firebase コンソール → **Firestore Database → ルール** に
[`firebase/firestore.rules`](firebase/firestore.rules) の中身を貼って**公開**。
インデックスは **インデックス** タブから
[`firebase/firestore.indexes.json`](firebase/firestore.indexes.json) の定義を手で登録する。

> GUI での貼り付けはファイルとの食い違いが起きやすい。CLI を勧める。

---

## 4. API を Cloud Run へ

### Gemini のキーを Secret Manager に置く

環境変数に直接書かない。リビジョンの設定に平文で残り、閲覧権限のある全員に見えるため。

```bash
printf '%s' 'AIza...' | gcloud secrets create gemini-api-key \
  --data-file=- --project=wiki-prequiz

gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:prequiz-api@wiki-prequiz.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=wiki-prequiz
```

### CLI

```bash
gcloud run deploy prequiz-api \
  --source api \
  --region asia-northeast1 \
  --project wiki-prequiz \
  --service-account prequiz-api@wiki-prequiz.iam.gserviceaccount.com \
  --min-instances=1 \
  --allow-unauthenticated \
  --set-env-vars "FIREBASE_PROJECT_ID=wiki-prequiz,GEMINI_MODEL=gemini-3.8-flash,WIKIMEDIA_USER_AGENT=WikiPreQuiz/1.0 (https://github.com/Syogo-Suganoya/wiki-prequiz),CORS_ORIGINS=https://wiki-prequiz.vercel.app" \
  --set-secrets "GEMINI_API_KEY=gemini-api-key:latest"
```

### GUI

1. **Cloud Run → サービスを作成**。サービス名 `prequiz-api`、
   リージョン `asia-northeast1`、認証は **未認証の呼び出しを許可**。
2. **コンテナ → 変数とシークレット** で環境変数を入れる。

   | 変数 | 値 |
   | :--- | :--- |
   | `FIREBASE_PROJECT_ID` | `wiki-prequiz` |
   | `GEMINI_MODEL` | `gemini-3.8-flash` |
   | `WIKIMEDIA_USER_AGENT` | `WikiPreQuiz/1.0 (https://github.com/Syogo-Suganoya/wiki-prequiz)` |
   | `CORS_ORIGINS` | `https://wiki-prequiz.vercel.app` |
   | `GEMINI_API_KEY` | シークレット `gemini-api-key` の `latest` を参照 |

3. **コンテナ → 全般** でインスタンスの最小数を **1** にする。
4. **セキュリティ** タブでサービスアカウントに `prequiz-api` を選ぶ。

> `WIKIMEDIA_USER_AGENT` には**連絡が取れる URL かメールアドレスが要る**。
> Wikimedia は識別できない User-Agent を 403 で弾く。
> ここではリポジトリの URL を連絡先にしている。

### 確認

```bash
curl https://<Cloud Run の URL>/api/health
```

```jsonc
{
  "status": "ok",
  "firestore": "ok",
  "using_emulator": false,  // ← ここが false であること
  "mock": false             // ← キーが通っていれば false
}
```

> **`using_emulator` が `true` なら本番設定が壊れている。**
> `FIRESTORE_EMULATOR_HOST` が環境変数に紛れ込んでいる。
> 残っていると存在しないエミュレータへ繋ごうとして全機能が落ちる。

---

## 5. フロントエンドを Vercel へ

### CLI

```bash
cd web
vercel link --project wiki-prequiz
vercel env add VITE_API_BASE_URL production        # Cloud Run の URL
vercel env add VITE_FIREBASE_PROJECT_ID production # wiki-prequiz
vercel --prod
```

### GUI

1. [Vercel](https://vercel.com/) → **Add New → Project** で
   `Syogo-Suganoya/wiki-prequiz` を選ぶ。
2. **Root Directory** に `web` を指定する（リポジトリ直下ではない）。
   フレームワークは Vite が自動検出される。
3. **Settings → Environment Variables** に以下を入れる。

   | 変数 | 値 |
   | :--- | :--- |
   | `VITE_API_BASE_URL` | Cloud Run のサービス URL |
   | `VITE_FIREBASE_PROJECT_ID` | `wiki-prequiz` |
   | `VITE_FIREBASE_API_KEY` ほか | Firebase コンソールのウェブアプリ設定から |

4. **Deploy**。

> `VITE_` の付いた値は**ビルド時にバンドルへ埋め込まれ、閲覧者から見える**。
> Firebase のウェブ API キーは公開前提の値なので問題ないが、
> Gemini のキーをここに置いてはいけない。あれはサーバー専用。

### デプロイ後

ブラウザ → Cloud Run はクロスオリジンになる。
Vercel が発行した本番ドメインが `https://wiki-prequiz.vercel.app` 以外になった場合は、
Cloud Run の `CORS_ORIGINS` を実際のドメインに直す。
プレビューデプロイも使うなら、そのドメインもカンマ区切りで足す。

---

## 6. LP

[`lp/`](lp/) は依存のない静的ファイル。Vercel でも GitHub Pages でも置ける。
公開時は [`lp/index.html`](lp/index.html) の「遊んでみる」の
リンク先（開発中は `http://localhost:5173/`）を
`https://wiki-prequiz.vercel.app/` に書き換える。

---

## 7. CD（GitHub Actions）

[`.github/workflows/`](.github/workflows/) に2つ置いてある。

| ファイル | 契機 | 内容 |
| :--- | :--- | :--- |
| [`ci.yml`](.github/workflows/ci.yml) | Push / PR | 静的検査・型検査・テスト・ビルド |
| [`cd.yml`](.github/workflows/cd.yml) | `main` への Push | Cloud Run / Vercel / Firestore ルールへデプロイ |

### CD はいま止めてある

`cd.yml` の `on:` は **`workflow_dispatch` だけ**にしてあり、`main` に push しても動かない。
デプロイ先がまだ無い状態で自動デプロイを繋ぐと、失敗通知が出続けるだけで何の役にも立たないため。

有効にするには、`cd.yml` 冒頭の `push:` ブロックのコメントを外す。
**その前に**下の3つを済ませておくこと。済んでいないと初回から失敗する。

#### ① Workload Identity 連携（鍵ファイルなしで GCP に入る）

```bash
PROJECT_NUMBER=$(gcloud projects describe wiki-prequiz --format='value(projectNumber)')

gcloud iam service-accounts create prequiz-deployer \
  --display-name="wiki-prequiz deployer (GitHub Actions)" \
  --project=wiki-prequiz

for ROLE in roles/run.admin roles/iam.serviceAccountUser roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding wiki-prequiz \
    --member="serviceAccount:prequiz-deployer@wiki-prequiz.iam.gserviceaccount.com" \
    --role="$ROLE"
done

gcloud iam workload-identity-pools create github \
  --location=global --display-name="GitHub Actions" --project=wiki-prequiz

gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github --project=wiki-prequiz \
  --display-name="GitHub" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='Syogo-Suganoya/wiki-prequiz'" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# デプロイ用サービスアカウントに、この連携からの成りすましを許す
gcloud iam service-accounts add-iam-policy-binding \
  prequiz-deployer@wiki-prequiz.iam.gserviceaccount.com \
  --project=wiki-prequiz \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/Syogo-Suganoya/wiki-prequiz"
```

`attribute-condition` を必ず付ける。無いと**他人のリポジトリからも**このプールを
使えてしまう。

GUI でやるなら **IAMと管理 → Workload Identity 連携 → プールを作成**。
プロバイダは OIDC、発行元は `https://token.actions.githubusercontent.com`、
属性条件に `assertion.repository=='Syogo-Suganoya/wiki-prequiz'` を入れる。

#### ② GitHub Secrets

`Syogo-Suganoya/wiki-prequiz` の
**Settings → Secrets and variables → Actions** に登録する。

| 名前 | 中身 |
| :--- | :--- |
| `GCP_PROJECT_ID` | `wiki-prequiz` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/providers/github` |
| `GCP_SERVICE_ACCOUNT` | `prequiz-deployer@wiki-prequiz.iam.gserviceaccount.com` |
| `CLOUD_RUN_SERVICE_ACCOUNT` | `prequiz-api@wiki-prequiz.iam.gserviceaccount.com` |
| `CORS_ORIGINS` | `https://wiki-prequiz.vercel.app` |
| `WIKIMEDIA_USER_AGENT` | `WikiPreQuiz/1.0 (https://github.com/Syogo-Suganoya/wiki-prequiz)` |
| `FIREBASE_TOKEN` | `firebase login:ci` で発行 |
| `VERCEL_TOKEN` / `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID` | Vercel の管理画面から |

`VERCEL_ORG_ID` と `VERCEL_PROJECT_ID` は `web/` で `vercel link` を実行すると
`.vercel/project.json` に書き出される。

#### ③ 手で1回流して確かめる

**Actions → CD → Run workflow** から手動実行する。
`workflow_dispatch` を残してあるのはこのため。ここが通ってから `push:` を開ける。

### パスフィルタ

`web/**` を直しただけで Cloud Run を再デプロイしないよう、ジョブごとに
`paths` で振り分けてある。デプロイ時間と、無意味なリビジョン増加を避けるため。
