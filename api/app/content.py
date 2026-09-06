"""出題する記事と問題を用意する。

**記事はいつも実データ**（Wikipedia）。`USE_MOCK` が切り替えるのは作問だけで、
true なら Gemini の代わりに手で書いた問題（`mock_data`）を出す。
そのときは**記事を選ぶ範囲が、問題のあるタイトルに狭まる**。
予習した記事の問題が出ないとゲームとして成立しないため。
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app import gemini, maxnumber, mock_data, wikipedia
from app.config import get_settings
from app.firestore import get_db
from app.models import Article, Question

# キャッシュの寿命。PV も被リンクも日単位でしか動かないので1日で足りる
CACHE_TTL = timedelta(hours=24)


class NoArticleError(RuntimeError):
    """出題できる記事が用意できなかった。"""


def error_message(exc: Exception) -> str:
    """作問の失敗を、画面に出す一文にする。

    通すのは**遊ぶ人向けに書いた文言だけ**。想定外の例外メッセージには
    内部の事情が混ざりうるので、伏せて定型文にする。
    """
    if isinstance(exc, gemini.GeminiError):
        return str(exc)
    return "問題の準備に失敗しました。少し待つと再試行します"


def pick_article() -> Article:
    """記事を1本選ぶ。**問題はまだ作らない。**

    作問は予習の60秒のあいだに回す。ここで一緒に作ると、開始を押した人だけが
    数十秒待たされ、その間ほかの参加者には何も見えない。
    """
    if get_settings().use_mock:
        return _pick_real_article(list(mock_data.MOCK_QUESTIONS))
    return _pick_real_article()


def make_questions(title: str, extract: str, count: int) -> list[Question]:
    """記事から問題をつくる。予習の裏で走らせる想定。"""
    if get_settings().use_mock:
        return _mock_questions(title, count)
    return gemini.make_questions(title, extract, count)


def _mock_questions(title: str, count: int) -> list[Question]:
    """その記事のために書いておいた問題を返す。

    `pick_article` が問題のあるタイトルからしか選ばないので普通は当たる。
    外れるのは設定の間違い（切り替え前のゲームが残っている等）なので、そう分かる文言で落とす。
    """
    pool = mock_data.MOCK_QUESTIONS.get(title)
    if not pool:
        raise NoArticleError(f"モックの問題が用意されていない記事です: {title}")
    return random.sample(pool, min(count, len(pool)))


# ── 実データ ──────────────────────────────────────────────────────


def _pool_ref() -> Any:
    return get_db().collection("articles")


def _cached(doc: dict[str, Any]) -> Article | None:
    """キャッシュが生きていれば Article にして返す。"""
    fetched = doc.get("fetchedAt")
    if not isinstance(fetched, datetime):
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    if datetime.now(UTC) - fetched > CACHE_TTL:
        return None
    return _to_article(
        title=doc["title"],
        url=doc["url"],
        extract=doc["extract"],
        pageviews30d=int(doc.get("pageviews30d", 0)),
        backlinks=int(doc.get("backlinks", 0)),
    )


def _to_article(
    *, title: str, url: str, extract: str, pageviews30d: int, backlinks: int
) -> Article:
    """最大数値は保存せず、本文から毎回その場で出す。

    保存すると、本文を取り直したときに数値だけ古いまま残る道ができる。
    """
    value, context = maxnumber.extract(extract)
    return Article(
        title=title,
        url=url,
        extract=extract,
        pageviews30d=pageviews30d,
        backlinks=backlinks,
        max_number=value,
        max_number_context=context,
    )


def _store(article: Article) -> None:
    _pool_ref().document(article.title).set(
        {
            "title": article.title,
            "url": article.url,
            "extract": article.extract,
            "charCount": len(article.extract),
            "pageviews30d": article.pageviews30d,
            "backlinks": article.backlinks,
            "fetchedAt": datetime.now(UTC),
            "enabled": True,
        }
    )


def _refresh(title: str) -> Article:
    """Wikipedia から取り直してキャッシュへ入れる。**Gemini は呼ばない。**"""
    raw = asyncio.run(wikipedia.fetch_article(title))
    # 先に切り詰めてから判定する。長さの基準は「予習で読む本文」に対するもの
    text = wikipedia.trim_for_study(raw.extract)
    if not wikipedia.is_usable(raw, text):
        raise NoArticleError(f"題材として成立しません: {title}")

    article = _to_article(
        title=raw.title,
        url=raw.url,
        extract=text,
        pageviews30d=raw.pageviews30d,
        backlinks=raw.backlinks,
    )
    _store(article)
    return article


def _candidates(limit: int = 30) -> list[dict[str, Any]]:
    docs = _pool_ref().where("enabled", "==", True).limit(limit).stream()
    return [d.to_dict() or {} for d in docs]


def _pick_real_article(only: list[str] | None = None) -> Article:
    """プールから1本選ぶ。無ければ取りに行く。

    `only` を渡すと、その中からしか選ばない（モックでの使い方）。
    プールに無いタイトルでも Wikipedia から取ってくるので選べる。
    `only` が無くてプールも空なら、その場で人気記事から作る（初回起動でも遊べるように）。
    """
    pool = _candidates()
    by_title = {str(d.get("title")): d for d in pool}

    if only is not None:
        titles = list(only)
    else:
        titles = [str(d["title"]) for d in pool if d.get("title")]
        if not titles:
            titles = asyncio.run(wikipedia.fetch_popular_titles(limit=20))
    random.shuffle(titles)
    errors: list[str] = []

    # 数本ぶんだけ試す。1本ダメでもゲームが始まらないのは避けたいが、
    # 延々と再試行してリクエストを占有するのも困る
    for title in titles[:5]:
        try:
            article = _cached(by_title[title]) if title in by_title else None
            if article is None:
                article = _refresh(title)
            return article
        except Exception as exc:  # 次の記事で挽回できるので握りつぶす
            errors.append(f"{title}: {exc}")

    raise NoArticleError("記事を用意できませんでした: " + " / ".join(errors[:3]))


# ── プール構築（バッチから呼ぶ）────────────────────────────────


def build_pool(limit: int = 50) -> dict[str, Any]:
    """人気記事から題材になるものを選んでプールへ貯める。

    ゲーム中には呼ばない。開始時に何十本も取りに行くとレイテンシが跳ねる。
    """
    titles = asyncio.run(wikipedia.fetch_popular_titles(limit=limit))
    added, skipped = 0, 0
    for title in titles:
        try:
            _refresh(title)
            added += 1
        except Exception:  # 1本落ちても全体は続ける
            skipped += 1
    return {"added": added, "skipped": skipped, "seen": len(titles)}
