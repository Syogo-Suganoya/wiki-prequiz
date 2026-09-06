import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AppConfig, type Room } from "./api";

const FALLBACK_CONFIG: AppConfig = {
  mock: false,
  roundsChoices: [1, 2, 3],
  studySecChoices: [30, 60, 90],
};

// 一度取れれば変わらない値なので、画面をまたいで使い回す
let configCache: AppConfig | null = null;

/**
 * サーバー側の構成。モックかどうかもここで分かる。
 * 取得できるまでは本番相当（モック用の操作を出さない）として扱う。
 */
export function useConfig(): AppConfig {
  const [config, setConfig] = useState<AppConfig>(configCache ?? FALLBACK_CONFIG);

  useEffect(() => {
    if (configCache) return;
    let alive = true;
    api.config().then((c) => {
      configCache = c;
      if (alive) setConfig(c);
    });
    return () => {
      alive = false;
    };
  }, []);

  return config;
}

/**
 * ルーム状態の購読と、フェーズ進行の駆動。
 *
 * 本来は Firestore の onSnapshot で購読するが、モック段階では
 * ポーリングで代用している。フェーズ進行の考え方（締切を過ぎたクライアントが
 * advance を叩き、サーバーが冪等に捌く）は設計どおり。
 */
export function useGame(roomId: string | null) {
  const [room, setRoom] = useState<Room | null>(null);
  const [error, setError] = useState<string | null>(null);
  const offsetRef = useRef(0);
  const busy = useRef(false);
  // 作問を促すのは1回だけ。毎回のポーリングで叩かない
  const prepared = useRef(false);

  // サーバーとの時計ずれを測る
  useEffect(() => {
    let alive = true;
    const t0 = Date.now();
    api.time().then((r) => {
      if (!alive) return;
      const rtt = Date.now() - t0;
      offsetRef.current = r.epoch_ms + rtt / 2 - Date.now();
    });
    return () => {
      alive = false;
    };
  }, []);

  const serverNow = useCallback(() => Date.now() + offsetRef.current, []);

  useEffect(() => {
    if (!roomId) return;
    let alive = true;
    prepared.current = false;

    const tick = async () => {
      if (!alive || busy.current) return;
      busy.current = true;
      try {
        const r = await api.getRoom(roomId);
        if (!alive) return;
        setRoom(r);
        setError(null);
        await drive(r);
      } catch (e) {
        if (alive) setError((e as Error).message);
      } finally {
        busy.current = false;
      }
    };

    // 締切超過の検知、ボットの代理押下・代理解答を行う
    const drive = async (r: Room) => {
      const now = serverNow();
      const ends = r.phaseEndsAt ? Date.parse(r.phaseEndsAt) : null;

      // 予習のあいだに問題を作らせる。担当はサーバーが1人に絞るので、
      // 全員が叩いても生成は1回だけ。ここで作っておかないと、
      // 予習が終わってから数十秒待たされる
      if (r.status === "STUDYING" && !r.quizReady && !prepared.current) {
        prepared.current = true;
        try {
          await api.prepareQuestions(roomId);
        } catch {
          // 失敗したら次のポーリングで別の端末が拾う
          prepared.current = false;
        }
        return;
      }

      if (r.status === "ANSWERING" && r.buzz.ownerId === null) {
        // 予約時刻を過ぎた対戦相手の解答を代理で送る（成立の判定はサーバー側）
        for (const [botId, v] of Object.entries(r.bots ?? {})) {
          if (Date.parse(v.buzzAt) <= now) {
            await api.botAnswer(roomId, r.currentRound, botId);
            return;
          }
        }
      }

      if (ends !== null && now >= ends - 300) {
        await api.advance(roomId, r.phaseSeq);
      }
    };

    tick();
    const id = setInterval(tick, 400);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [roomId, serverNow]);

  return { room, error, serverNow };
}

/**
 * フェーズの残り時間。サーバー時刻で補正する。
 * `progress` は 0（始まったばかり）→ 1（時間切れ）。時計盤の描画に使う。
 */
export function useCountdown(
  startedAt: string | null,
  endsAt: string | null,
  serverNow: () => number,
) {
  const [state, setState] = useState({ left: 0, progress: 0 });

  useEffect(() => {
    const calc = () => {
      if (!endsAt) return setState({ left: 0, progress: 0 });
      const end = Date.parse(endsAt);
      const start = startedAt ? Date.parse(startedAt) : end;
      const total = Math.max(1, end - start);
      const remain = Math.max(0, end - serverNow());
      setState({ left: Math.ceil(remain / 1000), progress: 1 - remain / total });
    };
    calc();
    const id = setInterval(calc, 100);
    return () => clearInterval(id);
  }, [startedAt, endsAt, serverNow]);

  return state;
}
