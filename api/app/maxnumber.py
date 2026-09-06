"""記事本文から「いちばん大きい数量」を取り出す。`MAX_NUMBER` モードの配点に使う。

**LLM は使わない。** `start_game` の中で呼ぶので LLM の1〜3秒を待てない（P4）し、
このモードの面白さは桁であって正確さではないので、多少の取り違えは壊れない。

代わりに**単位を手がかりにする**。数字だけ見ると年号や順序数を拾うが、
量の単位が後ろに付くものだけ数えれば大半は落とせる。
"""

from __future__ import annotations

import re

# 天文学的な値による一発ゲーム終了を防ぐ上限
MAX_VALUE = 10**15

# 量を表す単位。ここに無いものは数えない。
# 「度」（7度のノミネート）「KB」「%」は紛らわしいので意図的に外してある。
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

# 単位の直後にこれが続くなら数えない。「346人目」は順序であって量ではない。
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
    """最大の数量と、それが何を指すかの手がかりを返す。見つからなければ `(0, "")`。"""
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

    # 何の数値かは前後をそのまま切り出す。要約するには結局 LLM が要る
    start, end = best_at
    left = max(0, start - 16)
    right = min(len(text), end + 6)
    context = text[left:right].replace("\n", " ").strip()
    return best, context
