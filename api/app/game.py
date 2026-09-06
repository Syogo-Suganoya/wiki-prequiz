"""ゲーム進行のロジック。

Firestore を唯一の真実とし、状態遷移はすべてトランザクションで行う。
出題する記事をどこから取るか（固定データか Wikipedia + Gemini か）は
app.content が決めるので、ここでは区別しない。
"""

from __future__ import annotations

import random
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from google.cloud import firestore

from app import content
from app.firestore import get_db
from app.mock_data import BOTS, PLAYER_COLORS
from app.models import Article

# ルームキーに使う文字。0/O/1/I など読み間違えるものは除く
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

DEFAULT_DURATIONS = {"studyMs": 60000, "answerMs": 15000, "revealMs": 8000}
DEFAULT_SCORING = {"correctMul": 1.0, "wrongMul": -1.0, "timeoutMul": -1.0}

GAME_MODES = ("FIXED", "POPULARITY", "MAX_NUMBER")

# 部屋の定員。マッチングはここが埋まるまで相手を受け入れる
ROOM_CAPACITY = 4

# 募集中の部屋を「まだ人が待っている」とみなす時間。
# 途中で閉じられた部屋に後から来た人が吸い込まれ、
# 誰も開始しないまま待たされるのを防ぐ
OPEN_ROOM_TTL = timedelta(seconds=45)

# 参加者が選べるルールの範囲。UI と API の両方でここを基準にする
ROUNDS_CHOICES = (1, 2, 3)
STUDY_SEC_CHOICES = (30, 60, 90)


def now() -> datetime:
    return datetime.now(UTC)


def new_room_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def round2(n: float) -> int:
    """有効数字2桁に切り捨てる。桁の派手さは保ちつつ、端数の無意味な精度を捨てる。"""
    i = int(n)
    if i < 100:
        return i
    unit = 10 ** (len(str(i)) - 2)
    return int((i // unit) * unit)


def base_point(article: Article, mode: str) -> tuple[int, dict[str, Any]]:
    """ゲームモードに応じた配点と、その内訳を返す。"""
    detail: dict[str, Any]
    if mode == "POPULARITY":
        raw = article.pageviews30d + article.backlinks * 100
        detail = {"pageviews": article.pageviews30d, "backlinks": article.backlinks}
    elif mode == "MAX_NUMBER":
        raw = min(article.max_number, 10**15)
        detail = {
            "maxNumber": article.max_number,
            "context": article.max_number_context,
        }
    else:
        raw = 1000
        detail = {}
    return max(round2(raw), 1000), detail


# ── ルーム作成・参加 ──────────────────────────────────────────────


@dataclass
class Player:
    id: str
    username: str
    is_bot: bool
    color: str


def _player_doc(p: Player) -> dict[str, Any]:
    return {
        "username": p.username,
        "color": p.color,
        "isBot": p.is_bot,
        "score": 0,
        "lastSeenAt": now() if not p.is_bot else None,
    }


def _rules(game_mode: str, total_rounds: int, study_sec: int) -> dict[str, Any]:
    if game_mode not in GAME_MODES:
        raise ValueError(f"不明なゲームモード: {game_mode}")
    if total_rounds not in ROUNDS_CHOICES:
        raise ValueError(f"問題数は {ROUNDS_CHOICES} から選んでください")
    if study_sec not in STUDY_SEC_CHOICES:
        raise ValueError(f"予習時間は {STUDY_SEC_CHOICES} 秒から選んでください")
    return {
        "quizFormat": "MULTIPLE_CHOICE",
        "gameMode": game_mode,
        "totalRounds": total_rounds,
        "durations": {**DEFAULT_DURATIONS, "studyMs": study_sec * 1000},
        "scoring": dict(DEFAULT_SCORING),
    }


def match_key(settings: dict[str, Any]) -> str:
    """ルールが完全に一致する部屋どうしだけをマッチングさせるための鍵。

    「募集中の公開部屋」にだけ入れておき、開始・満室で消す。
    こうすると等値1つで引けるので、複合インデックスが要らない。
    """
    return "{}:{}:{}".format(
        settings["gameMode"],
        settings["totalRounds"],
        settings["durations"]["studyMs"],
    )


def create_room(
    host_id: str,
    username: str,
    *,
    game_mode: str = "FIXED",
    total_rounds: int = 3,
    study_sec: int = 60,
    is_private: bool = True,
    bot_count: int = 0,
) -> str:
    settings = _rules(game_mode, total_rounds, study_sec)

    db = get_db()
    room_id = new_room_code()

    players = {host_id: _player_doc(Player(host_id, username, False, PLAYER_COLORS[0]))}
    for bot in BOTS[:bot_count]:
        players[bot.id] = _player_doc(Player(bot.id, bot.username, True, bot.color))

    db.collection("rooms").document(room_id).set(
        {
            "roomId": room_id,
            "isPrivate": is_private,
            # 募集中の公開部屋にだけ入る。満室・開始で None にする
            "openKey": None if is_private else match_key(settings),
            "status": "LOBBY",
            "phaseSeq": 0,
            "phaseStartedAt": now(),
            "phaseEndsAt": None,
            "hostId": host_id,
            "settings": settings,
            "currentRound": 0,
            "article": None,
            "currentQuestion": None,
            "buzz": _empty_buzz(),
            "bots": {},
            "ready": {},
            "players": players,
            "createdAt": now(),
        }
    )
    return room_id


def join_room(room_id: str, player_id: str, username: str) -> None:
    """部屋に入る。最後の1席を同時に取り合っても定員を超えないようにする。"""
    db = get_db()
    ref = db.collection("rooms").document(room_id)

    @firestore.transactional
    def txn(tx: firestore.Transaction) -> None:
        snap = ref.get(transaction=tx)
        room = snap.to_dict()
        if room is None:
            raise LookupError("ルームが見つかりません")
        if player_id in room["players"]:
            return
        if room["status"] != "LOBBY":
            raise ValueError("すでに開始しているルームには参加できません")
        if len(room["players"]) >= ROOM_CAPACITY:
            raise ValueError("ルームが満員です")

        count = len(room["players"])
        color = PLAYER_COLORS[count % len(PLAYER_COLORS)]
        updates: dict[str, Any] = {
            f"players.{player_id}": _player_doc(Player(player_id, username, False, color)),
        }
        if count + 1 >= ROOM_CAPACITY:
            updates["openKey"] = None  # 満室。もう募集しない
        tx.update(ref, updates)

    txn(db.transaction())


def _is_waiting(room: dict[str, Any]) -> bool:
    """まだ人が待っている部屋かどうか。

    待っているあいだクライアントが heartbeat を打つので、
    最後に見かけた時刻が新しければ生きているとみなす。
    """
    seen = [
        _as_dt(p["lastSeenAt"])
        for p in room.get("players", {}).values()
        if not p["isBot"] and p.get("lastSeenAt")
    ]
    seen.append(_as_dt(room.get("createdAt")))
    return now() - max(seen) < OPEN_ROOM_TTL


def _close_recruiting(db: firestore.Client, room_id: str) -> None:
    """放置された部屋を募集から外す。見つけた人が畳んでいく。"""
    db.collection("rooms").document(room_id).update({"openKey": None})


def matchmake(
    player_id: str,
    username: str,
    *,
    game_mode: str,
    total_rounds: int,
    study_sec: int,
) -> str:
    """同じルールで募集中の部屋へ入る。無ければ自分が募集を立てる。

    ルールが1つでも違う部屋には入れない。問題数や予習時間が食い違うと、
    そもそも同じ勝負にならないため。
    """
    key = match_key(_rules(game_mode, total_rounds, study_sec))

    db = get_db()
    # 募集中の部屋にしか openKey は入っていないので、等値ひとつで引ける
    candidates = db.collection("rooms").where("openKey", "==", key).limit(10).stream()
    for snap in candidates:
        room = snap.to_dict() or {}
        if room.get("status") != "LOBBY" or len(room.get("players", {})) >= ROOM_CAPACITY:
            continue
        if player_id in room.get("players", {}):
            return str(room["roomId"])
        if not _is_waiting(room):
            _close_recruiting(db, str(room["roomId"]))
            continue
        try:
            join_room(str(room["roomId"]), player_id, username)
        except (LookupError, ValueError):
            continue  # 直前に埋まった。次の候補へ
        return str(room["roomId"])

    return create_room(
        player_id,
        username,
        game_mode=game_mode,
        total_rounds=total_rounds,
        study_sec=study_sec,
        is_private=False,
        bot_count=0,
    )


def fill_bots(room_id: str, target: int = ROOM_CAPACITY) -> int:
    """不足枠をボットで埋める。冪等。"""
    db = get_db()
    ref = db.collection("rooms").document(room_id)
    room = (ref.get().to_dict()) or {}
    if room.get("status") != "LOBBY":
        return 0

    existing = set(room["players"])
    added = 0
    updates: dict[str, Any] = {}
    for bot in BOTS:
        if len(existing) + added >= target:
            break
        if bot.id in existing:
            continue
        updates[f"players.{bot.id}"] = _player_doc(Player(bot.id, bot.username, True, bot.color))
        added += 1

    if updates:
        if len(existing) + added >= target:
            updates["openKey"] = None  # 埋まったので募集を止める
        ref.update(updates)
    return added


# ── 出題 ──────────────────────────────────────────────────────────


def _empty_buzz() -> dict[str, Any]:
    return {
        "ownerId": None,
        "buzzedAt": None,
        "answeredAt": None,
        "answer": None,
        "isCorrect": None,
        "delta": None,
    }


def _public_article(article: Article, mode: str) -> dict[str, Any]:
    """記事は1ゲームに1本。予習フェーズのあいだだけ本文を載せる。"""
    point, detail = base_point(article, mode)
    return {
        "title": article.title,
        "url": article.url,
        "extract": article.extract,
        "basePoint": point,
        "pointBreakdown": detail,
    }


def _public_question(question: str, choices: list[str]) -> dict[str, Any]:
    """公開してよい部分だけ。正解と解説は開示フェーズまで入れない。"""
    return {
        "question": question,
        "choices": list(choices),
        "correctAnswer": None,
        "explanation": None,
    }


def start_game(room_id: str) -> None:
    """記事を1本選び、その記事から全問を作って予習フェーズに入る。"""
    db = get_db()
    ref = db.collection("rooms").document(room_id)
    room = (ref.get().to_dict()) or {}
    if room.get("status") != "LOBBY":
        return

    mode = room["settings"]["gameMode"]
    # モックか実データかは content 側が決める（USE_MOCK）
    article = content.pick_article()

    # 作問はまだ。予習の裏で回す（prepare_questions）
    ref.collection("private").document("quizSet").set(
        {
            "articleTitle": article.title,
            "extract": article.extract,  # 作問に要る。公開領域には入れない
            "questions": [],
        }
    )

    d = room["settings"]["durations"]
    ref.update(
        {
            "status": "STUDYING",
            "openKey": None,  # 始まったので、もう誰も入れない
            "currentRound": 0,  # 予習中はまだ出題していない
            "article": _public_article(article, mode),
            "currentQuestion": None,
            "buzz": _empty_buzz(),
            "bots": {},
            "ready": {},
            "quizReady": False,  # 作問が終わったら真になる
            "quizError": None,
            "quizClaimedAt": None,
            "phaseSeq": room["phaseSeq"] + 1,
            "phaseStartedAt": now(),
            "phaseEndsAt": now() + timedelta(milliseconds=d["studyMs"]),
        }
    )


# 作問の担当を取ってから、諦めて別の人に譲るまでの時間。
# 担当した端末が落ちたまま誰も作らない、という状態を避ける
QUIZ_CLAIM_TTL = timedelta(seconds=45)


def prepare_questions(room_id: str) -> dict[str, Any]:
    """予習のあいだに問題を作る。

    生成には数秒〜数十秒かかるので、ゲーム開始のリクエストの中では作らない。
    誰が叩いても実際に走るのは1回だけになるよう、担当をトランザクションで取る。
    """
    db = get_db()
    ref = db.collection("rooms").document(room_id)

    @firestore.transactional
    def claim(tx: firestore.Transaction) -> dict[str, Any] | None:
        room = ref.get(transaction=tx).to_dict()
        if room is None or room.get("status") != "STUDYING":
            return None
        if room.get("quizReady"):
            return None  # もう出来ている
        claimed = room.get("quizClaimedAt")
        if claimed is not None and now() - _as_dt(claimed) < QUIZ_CLAIM_TTL:
            return None  # 誰かが作っている最中
        tx.update(ref, {"quizClaimedAt": now(), "quizError": None})
        return {"totalRounds": room["settings"]["totalRounds"]}

    taken: dict[str, Any] | None = claim(db.transaction())
    if taken is None:
        return {"prepared": False}

    quiz = ref.collection("private").document("quizSet").get().to_dict() or {}
    try:
        questions = content.make_questions(
            quiz["articleTitle"], quiz.get("extract", ""), taken["totalRounds"]
        )
    except Exception as exc:
        # 担当を解放して、次の呼び出しでやり直せるようにする
        ref.update({"quizClaimedAt": None, "quizError": str(exc)})
        raise

    ref.collection("private").document("quizSet").update(
        {
            "questions": [
                {
                    "round": i + 1,
                    "question": q.question,
                    # 出題のたびに記事を引き直さずに済むよう、選択肢もここに置く。
                    # 実データでは ARTICLES のような参照先が存在しないため
                    "choices": list(q.choices),
                    "correctAnswer": q.correct_answer,
                    "explanation": q.explanation,
                    "botWrongAnswers": q.wrong_answers,
                }
                for i, q in enumerate(questions)
            ]
        }
    )
    ref.update({"quizReady": True, "settings.totalRounds": len(questions)})
    return {"prepared": True, "count": len(questions)}


def _question_by_round(ref: firestore.DocumentReference, round_no: int) -> dict[str, Any]:
    quiz = ref.collection("private").document("quizSet").get().to_dict()
    return next(x for x in quiz["questions"] if x["round"] == round_no)


def _enter_round(
    ref: firestore.DocumentReference, room: dict[str, Any], round_no: int
) -> dict[str, Any]:
    """次の問題を出す。記事はもう見せない。

    出題に要るものは全部 `private/quizSet` に入っているので、
    記事の実体を引き直さない。実データでは引き直す先が無い。
    """
    d = room["settings"]["durations"]
    q = _question_by_round(ref, round_no)
    return {
        "status": "ANSWERING",
        "currentRound": round_no,
        "currentQuestion": _public_question(q["question"], q["choices"]),
        "article.extract": None,  # 予習は終わり。以降は本文を見せない
        "buzz": _empty_buzz(),
        "ready": {},
        "bots": _schedule_bots(room),
        "phaseEndsAt": now() + timedelta(milliseconds=d["answerMs"]),
    }


# ── フェーズ進行（冪等）──────────────────────────────────────────


def advance(
    room_id: str, expected_phase_seq: int, *, force: bool = False
) -> dict[str, Any] | None:
    """`expectedPhaseSeq` が一致し、かつ締切を過ぎているときだけ次へ進める。

    誰が叩いても結果が同じになるよう、判定と更新を1つのトランザクションで行う。
    `force=True` は「参加者全員が次へ進む意思を示した」場合にだけ使い、
    締切の判定だけを飛ばす（`phaseSeq` による冪等性は維持する）。
    """
    db = get_db()
    ref = db.collection("rooms").document(room_id)

    @firestore.transactional
    def txn(tx: firestore.Transaction) -> dict[str, Any] | None:
        snap = ref.get(transaction=tx)
        room = snap.to_dict()
        if room is None:
            return None
        if room["phaseSeq"] != expected_phase_seq:
            return None  # 誰かが先に進めた

        ends = room.get("phaseEndsAt")
        if not force and ends is not None and now() < _as_dt(ends) - timedelta(seconds=1):
            return None  # まだ早い

        updates = _next_phase_updates(room, ref, tx)
        if updates is None:
            return None
        updates["phaseSeq"] = room["phaseSeq"] + 1
        updates["phaseStartedAt"] = now()
        tx.update(ref, updates)
        return {"status": updates.get("status", room["status"]), "phaseSeq": updates["phaseSeq"]}

    result: dict[str, Any] | None = txn(db.transaction())
    return result


def _as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return now()


def _next_phase_updates(
    room: dict[str, Any],
    ref: firestore.DocumentReference,
    tx: firestore.Transaction,
) -> dict[str, Any] | None:
    status = room["status"]

    if status == "STUDYING":
        # 作問が終わるまでは進めない。締切が来ても待つ。
        # 空の問題で出題フェーズへ入るくらいなら、予習を延長するほうがまし
        if not room.get("quizReady"):
            return None
        # 予習は1ゲームに1回だけ。ここから先はずっと出題が続く
        return _enter_round(ref, room, 1)

    if status == "ANSWERING":
        # 誰も答えないまま時間切れ＝流局。スコアは動かさない
        return {"status": "REVEALING", **_reveal_updates(room, ref, tx, scored=False)}

    if status == "REVEALING":
        nxt = room["currentRound"] + 1
        if nxt > room["settings"]["totalRounds"]:
            return {"status": "FINISHED", "phaseEndsAt": None}
        return _enter_round(ref, room, nxt)

    return None


def _schedule_bots(room: dict[str, Any]) -> dict[str, Any]:
    """各ボットが「押すか」「いつ押すか」を先に決めて予約する。サーバーは待たない。"""
    start = now()
    scheduled: dict[str, Any] = {}
    for bot in BOTS:
        if bot.id not in room["players"]:
            continue
        knows = random.random() < bot.accuracy
        if not knows and random.random() > bot.aggression:
            continue  # 分からないので押さない
        base = bot.reaction_ms if knows else bot.reaction_ms * 1.8
        delay = max(400.0, random.gauss(base, 700))
        scheduled[bot.id] = {
            "buzzAt": start + timedelta(milliseconds=delay),
            "knows": knows,
        }
    return scheduled


# ── 解答（早い者勝ち）────────────────────────────────────────────


def answer(room_id: str, player_id: str, round_no: int, choice: str) -> dict[str, Any]:
    """最初に選んだ人の解答で確定させる。

    「押す」と「答える」を分けず、選択肢を選んだ瞬間に解答権の取得と解答を
    1つのトランザクションで済ませる。同時に選んでも成立するのは1人だけ。

    負けた人には**何ミリ秒差だったか**を返す。早押しは差が見えないと
    ただ「押せなかった」だけになり、勝負として成立しないため。
    差はサーバーに届いた時刻どうしの比較で、クライアントの自己申告は使わない。
    """
    # 時刻はトランザクションに入る**前**に取る。
    # 同時に押されるとトランザクションが競合して再試行が入るため、
    # 中で時刻を取ると「再試行に何秒かかったか」を測ってしまい、
    # 実際は横並びだったのに何秒も差がついたように見える。
    arrived_at = now()

    db = get_db()
    ref = db.collection("rooms").document(room_id)

    @firestore.transactional
    def txn(tx: firestore.Transaction) -> dict[str, Any]:
        room = ref.get(transaction=tx).to_dict()
        if room is None:
            return {"accepted": False, "reason": "NOT_FOUND"}
        if room["currentRound"] != round_no:
            return {"accepted": False, "reason": "CLOSED"}
        if player_id not in room["players"]:
            return {"accepted": False, "reason": "NOT_A_PLAYER"}

        # 解答権の判定は status より先に見る。
        # 解答が成立した瞬間に REVEALING へ移るので、僅差で負けた人の要求は
        # たいてい「もう ANSWERING ではない」状態で届く。status を先に見ると、
        # 本来いちばん差を知りたい人に何も返せなくなる
        owner = room["buzz"]["ownerId"]
        if owner is not None:
            # 先を越された。どれだけ遅かったかを添えて返す。
            # 勝敗はトランザクションの確定順で決まるので、到着が僅かに早くても
            # 負けることがある。その場合は 0 に丸める（ほぼ同着なので嘘にならない）
            behind = arrived_at - _as_dt(room["buzz"]["buzzedAt"])
            return {
                "accepted": False,
                "reason": "TAKEN",
                "behindMs": max(0, int(behind.total_seconds() * 1000)),
                "winnerName": room["players"][owner]["username"],
            }

        if room["status"] != "ANSWERING":
            return {"accepted": False, "reason": "CLOSED"}

        # 対戦相手（ボット）の代理送信は、予約時刻を過ぎていることを検証する。
        # これがないとクライアントが好きなタイミングで操作できてしまう。
        bot_state = room.get("bots", {}).get(player_id)
        if room["players"][player_id]["isBot"] and (
            bot_state is None or arrived_at < _as_dt(bot_state["buzzAt"])
        ):
            return {"accepted": False, "reason": "TOO_EARLY"}

        tx.update(ref, {"buzz.ownerId": player_id, "buzz.buzzedAt": arrived_at})
        return {"accepted": True}

    claimed: dict[str, Any] = txn(db.transaction())
    if not claimed["accepted"]:
        return claimed

    # 解答権が取れたので採点して開示へ進む
    room = ref.get().to_dict()
    assert room is not None
    ref.collection("answers").document(player_id).set(
        {"round": round_no, "answer": choice, "submittedAt": now()}
    )
    updates = _reveal_updates(room, ref, None, scored=True, answer=choice)
    ref.update(
        {
            "status": "REVEALING",
            "phaseSeq": room["phaseSeq"] + 1,
            "phaseStartedAt": now(),
            **updates,
        }
    )
    return {"accepted": True}


def _reveal_updates(
    room: dict[str, Any],
    ref: firestore.DocumentReference,
    tx: firestore.Transaction | None,
    *,
    scored: bool,
    answer: str | None = None,
) -> dict[str, Any]:
    """正解を公開領域へ写し、解答した人のスコアだけを更新する。"""
    d = room["settings"]["durations"]
    quiz = ref.collection("private").document("quizSet").get().to_dict()
    q = next(x for x in quiz["questions"] if x["round"] == room["currentRound"])

    updates: dict[str, Any] = {
        "currentQuestion.correctAnswer": q["correctAnswer"],
        "currentQuestion.explanation": q["explanation"],
        "phaseEndsAt": now() + timedelta(milliseconds=d["revealMs"]),
    }

    owner = room["buzz"]["ownerId"]
    if not scored or owner is None:
        return updates  # 流局：誰のスコアも動かさない

    is_correct = (answer or "").strip() == q["correctAnswer"]
    scoring = room["settings"]["scoring"]
    mul = scoring["correctMul"] if is_correct else scoring["wrongMul"]

    delta = int(round2(room["article"]["basePoint"]) * mul)
    updates["buzz.answer"] = answer
    updates["buzz.isCorrect"] = is_correct
    updates["buzz.delta"] = delta
    updates["buzz.answeredAt"] = now()
    updates[f"players.{owner}.score"] = room["players"][owner]["score"] + delta
    return updates


def bot_answer(room_id: str, bot_id: str, round_no: int) -> bool:
    """対戦相手が答える。実行時の LLM 呼び出しはない。"""
    db = get_db()
    ref = db.collection("rooms").document(room_id)
    room = ref.get().to_dict()
    if room is None or room["status"] != "ANSWERING":
        return False

    quiz = ref.collection("private").document("quizSet").get().to_dict()
    q = next(x for x in quiz["questions"] if x["round"] == round_no)
    knows = room.get("bots", {}).get(bot_id, {}).get("knows", False)
    choice = q["correctAnswer"] if knows else random.choice(q["botWrongAnswers"])
    return bool(answer(room_id, bot_id, round_no, choice)["accepted"])


def mark_ready(room_id: str, player_id: str) -> bool:
    """開示画面で「次の問題へ」を押した状態にする。

    人間の参加者が全員押したら、10秒を待たずにその場で次へ進める。
    ボットは待たせる意味がないので最初から準備済みとみなす。
    """
    db = get_db()
    ref = db.collection("rooms").document(room_id)
    room = ref.get().to_dict()
    if room is None or room["status"] != "REVEALING":
        return False
    if player_id not in room["players"]:
        return False

    ref.update({f"ready.{player_id}": True})

    humans = {pid for pid, p in room["players"].items() if not p["isBot"]}
    ready = set(room.get("ready") or {}) | {player_id}
    if humans <= ready:
        # 全員そろったので締切を待たずに進める
        advance(room_id, room["phaseSeq"], force=True)
        return True
    return False


def skip_phase(room_id: str) -> bool:
    """モック用: 現在のフェーズの締切を今にして先へ進める。"""
    ref = get_db().collection("rooms").document(room_id)
    room = ref.get().to_dict()
    if room is None or room.get("phaseEndsAt") is None:
        return False
    ref.update({"phaseEndsAt": now()})
    return True


def heartbeat(room_id: str, player_id: str) -> None:
    get_db().collection("rooms").document(room_id).update(
        {f"players.{player_id}.lastSeenAt": now()}
    )
