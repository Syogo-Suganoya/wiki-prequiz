"""Gemini による作問。

構造化出力（`response_schema`）を必ず使う。JSON のパース失敗を
リトライで拾う設計にすると、失敗が本番でだけ顔を出すため。
"""

from __future__ import annotations

import logging
import random
import time
from functools import lru_cache

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field

from app.config import get_settings
from app.models import Question

log = logging.getLogger(__name__)

# 記事1本からの作問に長考は要らない
THINKING_LEVEL = types.ThinkingLevel.LOW

# もう一度頼めば通る見込みのあるもの。400 番台の大半は何度やっても同じなので入れない
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# 待ち時間。予習は最短30秒なので、そこに収まる範囲で刻む（長さ＝再試行の回数）
BACKOFF_SEC = (1.0, 3.0, 6.0)

# 待っても直らない失敗の文言
SETUP_PROBLEM = "AI の利用設定に問題があります（管理者の対応が要ります）"


class GeneratedQuestion(BaseModel):
    question: str = Field(description="記事の内容から答えられる問題文")
    correct_answer: str = Field(description="正解の選択肢")
    wrong_answers: list[str] = Field(description="誤答の選択肢を3つ")
    explanation: str = Field(description="なぜその答えになるかの短い説明")
    evidence: str = Field(description="根拠となる記事本文の抜粋をそのまま")


class GeneratedQuestions(BaseModel):
    questions: list[GeneratedQuestion]


class GeminiError(RuntimeError):
    """作問に失敗した。

    **メッセージはそのまま画面に出る**（`rooms/{id}.quizError`）。
    状況と次の行動が分かる日本語を入れること。
    """


def _friendly(exc: genai_errors.APIError) -> str:
    """「待てば直るのか、人を呼ぶのか」が分かる一文にする。"""
    code = getattr(exc, "code", None)
    if code in (429, 503):
        return "AI が混み合っています。少し待つと出題が始まります"
    if code in (500, 502, 504):
        return "AI 側で一時的な問題が起きています。少し待つと出題が始まります"
    if code in (401, 403):
        return SETUP_PROBLEM
    if code == 400:
        # キーが無効なときも 400。記事のせいにすると直すべき場所を見誤らせる
        if "api key" in str(getattr(exc, "message", "")).lower():
            return SETUP_PROBLEM
        return "この記事からは問題を作れませんでした"
    return "問題の準備に失敗しました。少し待つと再試行します"


def _generate(contents: str, schema: type[BaseModel]) -> types.GenerateContentResponse:
    """混雑や一時障害は数回まで待って粘る。

    実測で 503 が2回続いてから通ったことがある。予習の数十秒のうちに間に合わせたい。
    キーが違うような直らない失敗は、待っても無駄なのですぐ諦める。
    """
    model = get_settings().gemini_model
    client = _client()

    for attempt, wait in enumerate((*BACKOFF_SEC, None), start=1):
        try:
            return client.models.generate_content(
                model=model, contents=contents, config=_config(schema)
            )
        except genai_errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code not in RETRYABLE_STATUS or wait is None:
                log.warning("Gemini 呼び出しに失敗 (%s回目, code=%s)", attempt, code)
                raise GeminiError(_friendly(exc)) from exc
            log.info("Gemini が %s を返した。%s秒後に再試行 (%s回目)", code, wait, attempt)
            time.sleep(wait)

    raise GeminiError("問題の準備に失敗しました")  # ここには来ない


@lru_cache
def _client() -> genai.Client:
    key = get_settings().gemini_api_key.strip()
    if not key:
        # これは設定漏れなので、画面に出ても管理者に伝わる文にしておく
        raise GeminiError(SETUP_PROBLEM)
    return genai.Client(api_key=key)


def _config(schema: type[BaseModel]) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_level=THINKING_LEVEL),
    )


QUESTION_PROMPT = """あなたはクイズの作問者です。
次の Wikipedia 記事から、4択クイズを{n}問つくってください。

制約:
- 記事本文に明示的な根拠がある問題だけをつくる。推測が要る問題は出さない。
- `evidence` には根拠となる本文をそのまま抜き出す。要約しない。
- 誤答は正解と同じ種類・同程度の長さにする（年号なら年号、地名なら地名）。
  正解だけが極端に長い／具体的だと、読まなくても当てられてしまう。
- 記事の別々の箇所から出題する。同じ一文から複数問つくらない。
- 問題文に答えを含めない。

記事タイトル: {title}

本文:
{text}
"""

def make_questions(title: str, text: str, count: int) -> list[Question]:
    """記事から4択問題をつくる。選択肢は必ずこちらでシャッフルする。"""
    res = _generate(
        QUESTION_PROMPT.format(n=count, title=title, text=text), GeneratedQuestions
    )
    parsed = res.parsed
    if not isinstance(parsed, GeneratedQuestions) or not parsed.questions:
        raise GeminiError("この記事からは問題を作れませんでした")

    questions: list[Question] = []
    for g in parsed.questions[:count]:
        wrong = [w for w in g.wrong_answers if w.strip() and w != g.correct_answer][:3]
        if len(wrong) < 3:
            continue  # 4択にならないものは捨てる
        choices = [g.correct_answer, *wrong]
        # LLM は先頭に正解を置きがちなので、順番はこちらで決める
        random.shuffle(choices)
        questions.append(
            Question(
                question=g.question,
                choices=choices,
                correct_answer=g.correct_answer,
                explanation=g.explanation,
            )
        )

    if not questions:
        raise GeminiError("この記事からは4択が作れませんでした")
    return questions

