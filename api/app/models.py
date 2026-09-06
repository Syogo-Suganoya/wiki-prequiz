"""出題データの型。

モックでも実データ（Wikipedia + Gemini）でも、この形に揃えて game へ渡す。
ゲーム進行のロジックが「どこから来た記事か」を気にしなくて済むようにするため。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Question:
    question: str
    choices: list[str]
    correct_answer: str
    explanation: str

    @property
    def wrong_answers(self) -> list[str]:
        return [c for c in self.choices if c != self.correct_answer]


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    extract: str
    pageviews30d: int
    backlinks: int
    max_number: int
    max_number_context: str
    questions: list[Question] = field(default_factory=list)

    def with_questions(self, questions: list[Question]) -> "Article":
        """問題を付けた複製を返す。記事の取得と作問を別々の段階にできる。"""
        return Article(
            title=self.title,
            url=self.url,
            extract=self.extract,
            pageviews30d=self.pageviews30d,
            backlinks=self.backlinks,
            max_number=self.max_number,
            max_number_context=self.max_number_context,
            questions=questions,
        )
