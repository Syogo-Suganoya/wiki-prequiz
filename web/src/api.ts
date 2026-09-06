export type Phase = "LOBBY" | "STUDYING" | "ANSWERING" | "REVEALING" | "FINISHED";

export type GameMode = "FIXED" | "POPULARITY" | "MAX_NUMBER";

export type PlayerState = {
  username: string;
  color: string;
  isBot: boolean;
  score: number;
  lastSeenAt: string | null;
};

export type Room = {
  roomId: string;
  /** フレンド対戦で作った部屋だけが真。マッチングで入った部屋は公開 */
  isPrivate: boolean;
  status: Phase;
  phaseSeq: number;
  phaseStartedAt: string | null;
  phaseEndsAt: string | null;
  hostId: string;
  settings: {
    gameMode: GameMode;
    totalRounds: number;
    durations: Record<string, number>;
  };
  currentRound: number;
  /** 作問が終わったか。予習の裏で走るので、終わるまで出題へは進まない */
  quizReady?: boolean;
  quizError?: string | null;
  /** 1ゲームに1本。予習が終わると extract は null になる */
  article: {
    title: string;
    url: string;
    extract: string | null;
    basePoint: number;
    pointBreakdown: Record<string, unknown>;
  } | null;
  currentQuestion: {
    question: string;
    choices: string[];
    correctAnswer: string | null;
    explanation: string | null;
  } | null;
  buzz: {
    ownerId: string | null;
    buzzedAt: string | null;
    answer: string | null;
    isCorrect: boolean | null;
    delta: number | null;
  };
  bots: Record<string, { buzzAt: string; knows?: boolean }>;
  ready: Record<string, boolean>;
  players: Record<string, PlayerState>;
};

// モック段階では Firebase 匿名認証の代わりに、ブラウザごとの ID を localStorage に持つ
export function playerId(): string {
  const KEY = "prequiz.playerId";
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = `u_${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(KEY, id);
  }
  return id;
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-Player-Id": playerId() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

/** 解答の結果。負けたときだけ、何ミリ秒差だったかが入る。 */
export type AnswerResult = {
  accepted: boolean;
  reason?: "TAKEN" | "CLOSED" | "NOT_FOUND" | "NOT_A_PLAYER" | "TOO_EARLY";
  behindMs?: number;
  winnerName?: string;
};

/** 参加者が決めるルール。マッチングはこれが完全に一致する相手とだけ成立する。 */
export type Rules = {
  game_mode: GameMode;
  total_rounds: number;
  study_sec: number;
};

export const DEFAULT_RULES: Rules = {
  game_mode: "FIXED",
  total_rounds: 3,
  study_sec: 60,
};

/** 設定画面で決めた内容は次に遊ぶときも引き継ぐ。毎回選び直させない。 */
const RULES_KEY = "prequiz.rules";

export function loadRules(): Rules {
  try {
    const saved = localStorage.getItem(RULES_KEY);
    if (saved) return { ...DEFAULT_RULES, ...(JSON.parse(saved) as Partial<Rules>) };
  } catch {
    // 壊れていたら既定に戻すだけでよい
  }
  return DEFAULT_RULES;
}

export function saveRules(rules: Rules): void {
  try {
    localStorage.setItem(RULES_KEY, JSON.stringify(rules));
  } catch {
    // 保存できなくても遊べる
  }
}

/** モックかどうかはサーバーが決める（USE_MOCK）。 */
export type AppConfig = {
  mock: boolean;
  roundsChoices: number[];
  studySecChoices: number[];
};

export const api = {
  time: () => call<{ epoch_ms: number }>("/time"),
  config: () => call<AppConfig>("/config"),
  getRoom: (id: string) => call<Room>(`/rooms/${id}`),
  createRoom: (b: Rules & { username: string; bot_count?: number }) =>
    call<{ roomId: string }>("/rooms", b),
  matchmake: (b: Rules & { username: string }) => call<{ roomId: string }>("/matchmake", b),
  join: (id: string, username: string) => call(`/rooms/${id}/join`, { username }),
  fillBots: (id: string) => call<{ added: number }>(`/rooms/${id}/fill-bots`, {}),
  start: (id: string) => call(`/rooms/${id}/start`, {}),
  advance: (id: string, expectedPhaseSeq: number) =>
    call<{ advanced: boolean }>(`/rooms/${id}/advance`, { expectedPhaseSeq }),
  answer: (id: string, round: number, answer: string) =>
    call<AnswerResult>(`/rooms/${id}/answer`, { round, answer }),
  botAnswer: (id: string, round: number, botId: string) =>
    call(`/rooms/${id}/bot-answer`, { round, botId }),
  ready: (id: string) => call<{ advanced: boolean }>(`/rooms/${id}/ready`, {}),
  prepareQuestions: (id: string) =>
    call<{ prepared: boolean; count?: number }>(`/rooms/${id}/prepare-questions`, {}),
  heartbeat: (id: string) => call<{ ok: boolean }>(`/rooms/${id}/heartbeat`, {}),
  skip: (id: string) => call(`/rooms/${id}/skip`, {}),
};

export const MODE_LABEL: Record<GameMode, string> = {
  FIXED: "固定点",
  POPULARITY: "人気度",
  MAX_NUMBER: "最大数値",
};

export const MODE_HELP: { mode: GameMode; formula: string; note: string }[] = [
  {
    mode: "FIXED",
    formula: "正解すると 1,000点",
    note: "いつでも同じ点数。いちばん素直なルールです。",
  },
  {
    mode: "POPULARITY",
    formula: "PV数 ＋ 被リンク数 × 100",
    note: "記事の有名さがそのまま点数になります。みんなが知っている記事ほど、外したときに痛い。",
  },
  {
    mode: "MAX_NUMBER",
    formula: "記事の中でいちばん大きい数字",
    note: "「太陽まで1億5000万km」と書いてあれば、それが点数。記事によって桁が大きく振れます。",
  },
];
