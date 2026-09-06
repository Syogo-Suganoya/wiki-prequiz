# ローカル（Docker Compose）と本番（Cloud Run）で同じイメージを使う。
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt


# ── 開発用: ソースはバインドマウントし、変更を監視して自動リロード ──
FROM base AS dev

COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# ── 本番 (Cloud Run) ────────────────────────────────────────────────
FROM base AS prod

COPY . .

# Cloud Run は待ち受けポートを $PORT で指定してくる（既定 8080）。
# 固定値にするとデプロイ後にヘルスチェックが通らないため必ず参照する。
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
