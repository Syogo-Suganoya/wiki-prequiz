"""出題する記事を1本用意する。

`USE_MOCK` の値だけで、固定データか実データかが切り替わる。
game 側はどちらから来たかを知らない（app.models.Article に揃えてある）。

実データの経路は「プールから選ぶ → キャッシュを見る → 無ければ取りに行く」。
ゲーム中に Wikipedia を叩くのは、キャッシュが切れていたときだけ。
LLM を呼ぶのは作問だけで、記事を集める段には呼ばない。
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from app import gemini, maxnumber, wikipedia
from app.config import get_settings
from app.firestore import get_db
from app.mock_data import ARTICLES
from app.models import Article, Question

# キャッシュの寿命。PV も被リンクも日単位でしか動かないので1日で足りる
CACHE_TTL = timedelta(hours=24)


class NoArticleError(RuntimeError):
    """出題できる記事が用意できなかった。"""


def pick_article() -> Article:
    """記事を1本選ぶ。**問題はまだ作らない。**

    作問は予習の60秒のあいだに回す。ここで一緒に作ると、ゲーム開始を
    押した人だけが数十秒待たされ、その間ほかの参加者は何も見えない。
    """
    if get_settings().use_mock:
        return random.choice(ARTICLES)
    return _pick_real_article()


def make_questions(title: str, extract: str, count: int) -> list[Question]:
    """記事から問題をつくる。予習の裏で走らせる想定。

    呼び出し側は記事の実体を持たなくてよい（タイトルと本文だけで足りる）。
    """
    if get_settings().use_mock:
        # モックは記事に問題が同梱されている。経路は実データと同じにしておく
        article = next((a for a in ARTICLES if a.title == title), None)
        questions = article.questions[:count] if article else []
        if not questions:
            raise NoArticleError(f"固定データに問題がありません: {title}")
        return questions
    return gemini.make_questions(title, extract, count)


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

    正規表現なので一瞬で終わる。保存すると、本文を取り直したときに
    数値だけ古いまま残る道ができてしまう。導出できるものは持たない。
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
    """Wikipedia から取り直してキャッシュへ入れる。**Gemini は呼ばない。**

    記事を集めるのに LLM は要らない。本文も PV も被リンクも Wikimedia が返し、
    最大数値は本文から正規表現で出せる（[`maxnumber`](maxnumber.py)）。
    LLM を使うのは作問だけ。
    """
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


def _pick_real_article() -> Article:
    """プールから1本選ぶ。無ければ取りに行く。

    プールが空なら、その場で人気記事から作る。初回起動でも遊べるようにするため。
    """
    pool = _candidates()
    random.shuffle(pool)

    titles = [str(d["title"]) for d in pool if d.get("title")]
    if not titles:
        titles = asyncio.run(wikipedia.fetch_popular_titles(limit=20))
        random.shuffle(titles)

    by_title = {str(d.get("title")): d for d in pool}
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

    ゲーム中ではなく、定期実行から呼ぶことを想定している
    （ゲーム開始時に何十本も取りに行くとレイテンシが跳ねるため）。
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
