"""Gemini による作問と、記事中の最大数値の抽出。

構造化出力（`response_schema`）を必ず使う。JSON のパース失敗を
リトライで拾う設計にすると、失敗が本番でだけ顔を出すため。
"""

from __future__ import annotations

import random
from functools import lru_cache

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.config import get_settings
from app.models import Question

# 長考は要らない。記事1本からの作問でレイテンシとコストを無駄に増やさない
THINKING_LEVEL = types.ThinkingLevel.LOW


class GeneratedQuestion(BaseModel):
    question: str = Field(description="記事の内容から答えられる問題文")
    correct_answer: str = Field(description="正解の選択肢")
    wrong_answers: list[str] = Field(description="誤答の選択肢を3つ")
    explanation: str = Field(description="なぜその答えになるかの短い説明")
    evidence: str = Field(description="根拠となる記事本文の抜粋をそのまま")


class GeneratedQuestions(BaseModel):
    questions: list[GeneratedQuestion]


class MaxNumber(BaseModel):
    value: int = Field(description="記事中で最大の数量。見つからなければ 0")
    context: str = Field(description="その数値が何を指すか（例: 標高3776m）")


class GeminiError(RuntimeError):
    pass


@lru_cache
def _client() -> genai.Client:
    key = get_settings().gemini_api_key.strip()
    if not key:
        raise GeminiError(
            "GEMINI_API_KEY が未設定です。USE_MOCK=true で起動するか、キーを設定してください"
        )
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

MAX_NUMBER_PROMPT = """次の Wikipedia 記事の本文から、最も大きい「数量」を1つ抜き出してください。

対象: 人口・金額・距離・面積・質量・件数など、量を表す数値。
除外: 西暦・元号・順序数（第N回）・章番号・電話番号・型番。
見つからなければ value に 0 を入れてください。

本文:
{text}
"""


def make_questions(title: str, text: str, count: int) -> list[Question]:
    """記事から4択問題をつくる。選択肢は必ずこちらでシャッフルする。"""
    model = get_settings().gemini_model
    res = _client().models.generate_content(
        model=model,
        contents=QUESTION_PROMPT.format(n=count, title=title, text=text),
        config=_config(GeneratedQuestions),
    )
    parsed = res.parsed
    if not isinstance(parsed, GeneratedQuestions) or not parsed.questions:
        raise GeminiError("問題が生成できませんでした")

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
        raise GeminiError("4択として成立する問題がありませんでした")
    return questions


def extract_max_number(text: str) -> tuple[int, str]:
    """記事中の最大数値。`MAX_NUMBER` モードの配点に使う。

    正規表現だと「1707年」「第2次」を拾ってしまうので LLM に判定させる。
    """
    model = get_settings().gemini_model
    res = _client().models.generate_content(
        model=model,
        contents=MAX_NUMBER_PROMPT.format(text=text),
        config=_config(MaxNumber),
    )
    parsed = res.parsed
    if not isinstance(parsed, MaxNumber) or parsed.value <= 0:
        return 0, ""
    # 天文学的な数値による一発ゲーム終了を防ぐ
    return min(parsed.value, 10**15), parsed.context
