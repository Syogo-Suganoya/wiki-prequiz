"""FastAPI アプリケーションのエントリポイント。

ローカルでは uvicorn（Docker）で、本番では Cloud Run で同じイメージを動かす。

モック段階のため認証は簡略化し、`X-Player-Id` ヘッダをそのまま uid として扱う。
本番では Firebase Authentication の ID トークン検証に差し替える。
"""

import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import content, game
from app.config import get_settings
from app.firestore import get_db

settings = get_settings()

app = FastAPI(title="1分間予習クイズ API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 共通 ──────────────────────────────────────────────────────────


def require_player(x_player_id: str | None) -> str:
    if not x_player_id:
        raise HTTPException(status_code=401, detail="X-Player-Id ヘッダが必要です")
    return x_player_id


def require_admin(x_admin_token: str | None) -> None:
    """運用者だけが叩ける操作の入口。

    Cloud Run は全体を公開しないと遊べないので、IAM では個別の口を守れない。
    合言葉を1つ持たせて、それを知っている人だけ通す。

    **未設定なら誰も通さない。** 「設定を忘れたら素通し」だと、
    忘れたことに気づく機会がないまま開けっ放しになる。
    """
    expected = get_settings().admin_token
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN が未設定です")
    # 文字列の比較にかかる時間から中身を推測されないようにする
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="X-Admin-Token ヘッダが不正です")


class TimeResponse(BaseModel):
    server_time: datetime
    epoch_ms: int


@app.get("/api/time", response_model=TimeResponse)
def get_time() -> TimeResponse:
    """クライアントの時計オフセット補正に使う。"""
    n = datetime.now(UTC)
    return TimeResponse(server_time=n, epoch_ms=int(n.timestamp() * 1000))


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        get_db().collection("_healthcheck").document("ping").get()
        firestore_status = "ok"
    except Exception as exc:
        # 起動確認用のエンドポイントなので、理由をそのまま見せる
        firestore_status = f"error: {exc}"
    return {
        "status": "ok",
        "firestore": firestore_status,
        "using_emulator": settings.use_emulator,
        "gemini_model": settings.gemini_model,
        "mock": settings.is_mock,
        # 記事はいつも Wikipedia。切り替わるのは問題の出どころだけ
        "article_source": "wikipedia",
        "question_source": "fixed" if settings.is_mock else "gemini",
        # 足りない設定。空でなければ出題が失敗する
        "missing_settings": settings.missing_settings,
    }


@app.get("/api/config")
def client_config() -> dict[str, Any]:
    """クライアントが起動時に読む設定。

    モックかどうかは URL のパラメータではなくサーバーが決める（`USE_MOCK`）。
    モックのときだけ予習スキップなどの開発用操作が開く。
    """
    return {
        "mock": settings.is_mock,
        "roundsChoices": list(game.ROUNDS_CHOICES),
        "studySecChoices": list(game.STUDY_SEC_CHOICES),
    }


# ── ルーム ────────────────────────────────────────────────────────


class RuleFields(BaseModel):
    """参加者が決めるゲームルール。値の妥当性は game 側で一括して見る。"""

    game_mode: str = "FIXED"
    total_rounds: int = 3
    study_sec: int = 60


class CreateRoomRequest(RuleFields):
    username: str = Field(min_length=1, max_length=20)
    bot_count: int = Field(default=0, ge=0, le=3)


@app.post("/api/rooms")
def create_room(
    body: CreateRoomRequest,
    x_player_id: str | None = Header(default=None),
) -> dict[str, str]:
    player_id = require_player(x_player_id)
    try:
        room_id = game.create_room(
            player_id,
            body.username,
            game_mode=body.game_mode,
            total_rounds=body.total_rounds,
            study_sec=body.study_sec,
            bot_count=body.bot_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"roomId": room_id}


class MatchmakeRequest(RuleFields):
    username: str = Field(min_length=1, max_length=20)


@app.post("/api/matchmake")
def matchmake(
    body: MatchmakeRequest,
    x_player_id: str | None = Header(default=None),
) -> dict[str, str]:
    """同じルールで募集中の相手と引き合わせる。空きが無ければ新しく募集を立てる。"""
    player_id = require_player(x_player_id)
    try:
        room_id = game.matchmake(
            player_id,
            body.username,
            game_mode=body.game_mode,
            total_rounds=body.total_rounds,
            study_sec=body.study_sec,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"roomId": room_id}


class JoinRequest(BaseModel):
    username: str = Field(min_length=1, max_length=20)


@app.post("/api/rooms/{room_id}/join")
def join(
    room_id: str,
    body: JoinRequest,
    x_player_id: str | None = Header(default=None),
) -> dict[str, bool]:
    player_id = require_player(x_player_id)
    try:
        game.join_room(room_id, player_id, body.username)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"joined": True}


@app.post("/api/rooms/{room_id}/fill-bots")
def fill_bots(room_id: str) -> dict[str, int]:
    return {"added": game.fill_bots(room_id)}


@app.post("/api/rooms/{room_id}/start")
def start(room_id: str) -> dict[str, bool]:
    """記事を1本用意して予習フェーズへ。

    実データのときはここで Wikipedia と Gemini を呼ぶ。用意できなければ
    502 を返す。黙って空のゲームを始めるよりも、理由が見えるほうがよい。
    """
    try:
        game.start_game(room_id)
    except content.NoArticleError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"started": True}


@app.post("/api/articles/build-pool")
def build_pool(
    limit: int = 30,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """記事プールを貯める。**運用者が手で叩く。**

    定期実行は置いていない。人気記事の顔ぶれは日単位でしか動かないうえ、
    プールには人の目で選別を入れたい（Wikimedia の人気一覧は
    出題に向かない記事も返す）ので、勝手に増えていくほうが困る。

    ゲーム開始時に何十本も取りに行くとレイテンシが跳ねるため、
    普段はここで貯めたものを使う。
    """
    # USE_MOCK では分岐しない。記事の取得に AI は関わらないので、
    # モック構成でもプールは本物を貯める
    require_admin(x_admin_token)
    return content.build_pool(limit=limit)


@app.post("/api/rooms/{room_id}/prepare-questions")
def prepare_questions(room_id: str) -> dict[str, Any]:
    """予習のあいだに問題を作る。クライアントが予習開始直後に叩く。

    担当はサーバーが1つだけに絞るので、全員が叩いても生成は1回。
    """
    try:
        return game.prepare_questions(room_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"作問に失敗しました: {exc}") from exc


class AdvanceRequest(BaseModel):
    expected_phase_seq: int = Field(alias="expectedPhaseSeq")


@app.post("/api/rooms/{room_id}/advance", status_code=200)
def advance(room_id: str, body: AdvanceRequest) -> dict[str, Any]:
    """フェーズ進行。冪等なので、誰が何度叩いても遷移は1回だけ。"""
    result = game.advance(room_id, body.expected_phase_seq)
    if result is None:
        # 既に進行済み、または締切前。黙って無視する
        return {"advanced": False}
    return {"advanced": True, **result}


class AnswerRequest(BaseModel):
    round: int
    answer: str


@app.post("/api/rooms/{room_id}/answer")
def answer(
    room_id: str,
    body: AnswerRequest,
    x_player_id: str | None = Header(default=None),
) -> dict[str, Any]:
    """解答。最初に選んだ1人だけが成立する（サーバーのトランザクションで確定）。

    負けた場合は `behindMs`（何ミリ秒差だったか）と相手の名前を返す。
    """
    player_id = require_player(x_player_id)
    return game.answer(room_id, player_id, body.round, body.answer)


class BotAnswerRequest(BaseModel):
    round: int
    bot_id: str = Field(alias="botId")


@app.post("/api/rooms/{room_id}/bot-answer")
def bot_answer(room_id: str, body: BotAnswerRequest) -> dict[str, bool]:
    """対戦相手の解答をクライアントが代理で送る。予約時刻はサーバーが検証する。"""
    return {"answered": game.bot_answer(room_id, body.bot_id, body.round)}


@app.post("/api/rooms/{room_id}/ready")
def ready(room_id: str, x_player_id: str | None = Header(default=None)) -> dict[str, bool]:
    """開示画面の「次の問題へ」。全員が押したら待たずに次のラウンドへ進む。"""
    player_id = require_player(x_player_id)
    return {"advanced": game.mark_ready(room_id, player_id)}


@app.post("/api/rooms/{room_id}/skip")
def skip(room_id: str) -> dict[str, bool]:
    """モック用: 予習の60秒などを飛ばす。本番構成では受け付けない。"""
    if not settings.is_mock:
        raise HTTPException(status_code=403, detail="モック時のみ利用できます")
    return {"skipped": game.skip_phase(room_id)}


@app.post("/api/rooms/{room_id}/heartbeat")
def heartbeat(room_id: str, x_player_id: str | None = Header(default=None)) -> dict[str, bool]:
    game.heartbeat(room_id, require_player(x_player_id))
    return {"ok": True}


@app.get("/api/rooms/{room_id}")
def get_room(room_id: str) -> dict[str, Any]:
    """公開状態の取得。

    本来はクライアントが Firestore を直接購読するが、モックでは
    ポーリングで代用して動作確認を優先する。
    返すのは公開領域のみで、正解は `REVEALING` 以降しか入っていない。
    """
    snap = get_db().collection("rooms").document(room_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="ルームが見つかりません")
    room: dict[str, Any] = _jsonable(snap.to_dict() or {})
    return room


def _jsonable(value: Any) -> Any:
    """Firestore が返す datetime を ISO 文字列へ落とす。"""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    return value

