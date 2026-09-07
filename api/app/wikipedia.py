"""Wikipedia / Wikimedia からの記事取得。

ゲーム中に叩くのは原則キャッシュ（`articles` コレクション）だけ。
ここは「プールを作るバッチ」と「キャッシュが切れたときの取り直し」で使う。

`action=query&list=random` は使わない。スタブ・曖昧さ回避・一覧記事を
大量に引いてしまい、60秒予習の題材として成立しないため。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings

API = "https://ja.wikipedia.org/w/api.php"
REST = "https://wikimedia.org/api/rest_v1"

# 予習の題材として成立する長さ。短いと問題が作れず、長いと1分では読めない
MIN_CHARS = 2000
MAX_CHARS = 20000

# 誰も知らない記事だとクイズにならない
MIN_PAGEVIEWS = 1000

# 被リンクの全件カウントは重い。500 で打ち切って近似とする
BACKLINK_LIMIT = 500

# 題材にならないページ。タイトルで弾く
EXCLUDED_TITLE_PATTERNS = re.compile(
    r"一覧|曖昧さ回避|Template:|Category:|Wikipedia:|Portal:"
)


class WikipediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class RawArticle:
    """Wikipedia から取れる素の情報。作問はまだ載っていない。"""

    title: str
    url: str
    extract: str
    pageviews30d: int
    backlinks: int


def _headers() -> dict[str, str]:
    ua = get_settings().wikimedia_user_agent.strip()
    if not ua:
        # Wikimedia は識別できない UA を 403 で弾く。黙って失敗させない
        raise WikipediaError(
            "WIKIMEDIA_USER_AGENT が未設定です。連絡先を含む文字列を設定してください"
        )
    return {"User-Agent": ua, "Accept": "application/json"}


def article_url(title: str) -> str:
    return f"https://ja.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"


async def _get_json(
    client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None
) -> Any:
    res = await client.get(url, params=params, headers=_headers(), timeout=15.0)
    res.raise_for_status()
    return res.json()


async def fetch_extract(client: httpx.AsyncClient, title: str) -> str:
    """本文（プレーンテキスト）。`exintro` は付けない。全文が要る。"""
    data = await _get_json(
        client,
        API,
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
            "titles": title,
        },
    )
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        raise WikipediaError(f"記事が見つかりません: {title}")
    return str(pages[0].get("extract") or "")


async def fetch_pageviews30d(client: httpx.AsyncClient, title: str) -> int:
    """直近30日の閲覧数。

    集計に1〜2日の遅れがあるため、終端を `today - 2d` に固定する。
    「いま取った値」にすると、同じ記事でも取得時刻で配点が変わってしまう。
    """
    end = datetime.now(UTC).date() - timedelta(days=2)
    start = end - timedelta(days=30)
    path = (
        f"{REST}/metrics/pageviews/per-article/ja.wikipedia/all-access/user/"
        f"{quote(title.replace(' ', '_'), safe='')}/daily/"
        f"{start:%Y%m%d}/{end:%Y%m%d}"
    )
    try:
        data = await _get_json(client, path)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return 0  # 新規記事などデータが無い。下限へクランプされる
        raise
    return sum(int(item.get("views", 0)) for item in data.get("items", []))


async def fetch_backlinks(client: httpx.AsyncClient, title: str) -> int:
    """被リンク数。500 で打ち切る（全件は重く、配点には近似で足りる）。"""
    data = await _get_json(
        client,
        API,
        {
            "action": "query",
            "list": "backlinks",
            "bltitle": title,
            "bllimit": BACKLINK_LIMIT,
            "blnamespace": 0,
            "format": "json",
            "formatversion": 2,
        },
    )
    return len(data.get("query", {}).get("backlinks", []))


async def fetch_article(title: str) -> RawArticle:
    """1本の記事に必要な情報をまとめて取る。3本は並列でよい。"""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        extract, pageviews, backlinks = await asyncio.gather(
            fetch_extract(client, title),
            fetch_pageviews30d(client, title),
            fetch_backlinks(client, title),
        )
    return RawArticle(
        title=title,
        url=article_url(title),
        extract=extract,
        pageviews30d=pageviews,
        backlinks=backlinks,
    )


async def fetch_popular_titles(limit: int = 50) -> list[str]:
    """記事プールの種。前日の人気記事から、題材になりそうなものだけを拾う。"""
    day = datetime.now(UTC).date() - timedelta(days=2)
    path = f"{REST}/metrics/pageviews/top/ja.wikipedia/all-access/{day:%Y/%m/%d}"
    async with httpx.AsyncClient(follow_redirects=True) as client:
        data = await _get_json(client, path)

    titles: list[str] = []
    for item in data.get("items", [{}])[0].get("articles", []):
        title = str(item.get("article", "")).replace("_", " ")
        if not title or title.startswith("特別:") or title == "メインページ":
            continue
        if EXCLUDED_TITLE_PATTERNS.search(title):
            continue
        titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def is_usable(article: RawArticle, text: str | None = None) -> bool:
    """60秒予習の題材として成立するか。

    長さは**切り詰めたあとの本文**で見る。素の全文で判定すると、
    富士山のような充実した記事が「長すぎる」だけで落ちてしまう。
    """
    body = article.extract if text is None else text
    if EXCLUDED_TITLE_PATTERNS.search(article.title):
        return False
    if not (MIN_CHARS <= len(body) <= MAX_CHARS):
        return False
    return article.pageviews30d >= MIN_PAGEVIEWS


def trim_for_study(text: str) -> str:
    """1分で読める分量に切り詰める。

    脚注・出典の節は問題の根拠にならないので、そこから先は落とす。

    見出しの「== ==」はここでは外さない。どの行が見出しかを知らないと
    画面側で太字にできないし、作問に渡す本文でも節の区切りは手がかりになる。
    記号を外すのは表示の都合なので、表示側でやる（App.tsx の Article）。
    """
    for marker in ("\n== 脚注", "\n== 出典", "\n== 参考文献", "\n== 関連項目", "\n== 外部リンク"):
        idx = text.find(marker)
        if idx > MIN_CHARS:
            text = text[:idx]
            break
    return text[:MAX_CHARS].strip()

