"""記事本文から「いちばん大きい数量」を取り出す。`MAX_NUMBER` モードの配点に使う。

**LLM は使わない。** 理由は2つある。

1. `start_game` の中で呼ぶので、1〜3秒かかる LLM 応答を待つわけにいかない
   （DESIGN.md の P4「リクエストの中で待たない」）。
2. このモードの面白さは「桁違いの数字で一発逆転」であって、正確さではない。
   多少の取り違えはゲームを壊さない。

代わりに、**単位を手がかりにする**。数字だけを見ると年号や順序数を拾うが、
「人」「円」「メートル」のような量の単位が後ろに付いているものだけを数えれば、
その大半は落とせる。
"""

from __future__ import annotations

import re

# 天文学的な値による一発ゲーム終了を防ぐ上限
MAX_VALUE = 10**15

# 量を表す単位。ここに無いものは数えない。
#
# 紛らわしいものは意図的に外してある:
#   「度」  … 「7度のノミネート」のような回数と区別できない
#   「KB」  … 実データで、番組固有の得点単位を拾う例があった
#   「%」   … 100 を超えないので、最大値としては意味を持たない
UNITS = (
    "平方キロメートル|キロメートル|センチメートル|ミリメートル|メートル|センチ|km|cm|mm|m|"
    "ヘクタール|エーカー|坪|畳|"
    "キログラム|グラム|トン|kg|"
    "人|名|世帯|社|校|店|軒|棟|機|隻|両|台|基|頭|匹|羽|冊|枚|個|件|票|席|部屋|"
    "円|ドル|ユーロ|ウォン|"
    "リットル|ミリリットル|"
    "ケルビン|ワット|キロワット|馬力|ヘルツ|ボルト|"
    "光年|天文単位|"
    "カ国|か国|箇所|カ所|"
    "バイト|GB|MB|TB"
)

# 単位に見えて量でないもの。単位の直後にこれが続くなら数えない。
#   「346人目」「3作目」… 順序
#   「20カ所目」        … 同上
FOLLOW_DENY = "目|以下"

# 「1億5000万キロメートル」のように、漢数字の桁が挟まる形に対応する
_NUM = r"\d[\d,]*(?:\.\d+)?"
_CHAIN = rf"(?:{_NUM}\s*[兆億万]\s*)*{_NUM}"
# 「第2次」を弾くため、直前が「第」なら見送る
PATTERN = re.compile(rf"(?<!第)({_CHAIN})\s*({UNITS})(?!{FOLLOW_DENY})")


def _to_int(chunk: str) -> int | None:
    """「1億5000万」→ 150000000。読めなければ None。"""
    rest = chunk.replace(",", "").replace(" ", "")
    total = 0.0
    for unit, scale in (("兆", 10**12), ("億", 10**8), ("万", 10**4)):
        if unit in rest:
            head, rest = rest.split(unit, 1)
            try:
                total += (float(head) if head else 1.0) * scale
            except ValueError:
                return None
    if rest:
        try:
            total += float(rest)
        except ValueError:
            return None
    return int(total)


def extract(text: str) -> tuple[int, str]:
    """最大の数量と、それが何を指すかの手がかりを返す。

    見つからなければ `(0, "")`。配点側で下限に丸められる。
    """
    best = 0
    best_at: tuple[int, int] | None = None

    for m in PATTERN.finditer(text):
        value = _to_int(m.group(1))
        if value is None or value <= 0 or value > MAX_VALUE:
            continue
        if value > best:
            best, best_at = value, (m.start(), m.end())

    if best_at is None:
        return 0, ""

    # 何の数値かは、前後をそのまま切り出して見せる。
    # 意味を要約するには結局 LLM が要るので、原文を出すほうが誠実
    start, end = best_at
    left = max(0, start - 16)
    right = min(len(text), end + 6)
    context = text[left:right].replace("\n", " ").strip()
    return best, context
