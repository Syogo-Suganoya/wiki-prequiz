import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  api,
  loadRules,
  MODE_HELP,
  MODE_LABEL,
  playerId,
  saveRules,
  type AppConfig,
  type GameMode,
  type Room,
  type Rules,
} from "./api";
import { findEgg, type Egg } from "./easterEgg";
import { useConfig, useCountdown, useGame } from "./useGame";

const COLORS: Record<string, string> = {
  p1: "#FF7A1A",
  p2: "#25B75C",
  p3: "#1E86D6",
  p4: "#2ED0E8",
};

export function App() {
  const [roomId, setRoomId] = useState<string | null>(
    () => new URLSearchParams(location.search).get("room"),
  );
  const { room, error, serverNow } = useGame(roomId);

  const enter = (id: string) => {
    history.replaceState(null, "", `?room=${id}`);
    setRoomId(id);
  };

  // 部屋から出る。リロードはしないので、ニックネームや設定はそのまま残る。
  // 落とすのは ?room= だけ。"/" と書くと、本番では LP のパスへ飛んでしまう
  // （ゲームは /quiz に置いてある）
  const leave = () => {
    history.replaceState(null, "", location.pathname);
    setRoomId(null);
  };

  if (!roomId) return <Home onEnter={enter} />;
  if (error) return <Center><p className="err">接続エラー: {error}</p></Center>;
  if (!room) return <Center><p>読み込み中…</p></Center>;
  return <Game room={room} serverNow={serverNow} onExit={leave} />;
}

function Center({ children }: { children: React.ReactNode }) {
  return <main className="app"><div className="body pad">{children}</div></main>;
}

/** 残り時間をアナログ時計の針で見せる。針が中心から1周したら時間切れ。 */
function ClockHand({ progress, left }: { progress: number; left: number }) {
  const angle = Math.min(1, Math.max(0, progress)) * 360;
  const urgent = left <= 5;
  return (
    <svg className={`clock ${urgent ? "urgent" : ""}`} viewBox="0 0 40 40" aria-label={`残り${left}秒`}>
      <circle className="clock-face" cx="20" cy="20" r="17" />
      {/* 針は中心を軸に回す。目盛りや中心の点を足すと照準に見えるので置かない */}
      <line
        className="clock-needle"
        x1="20" y1="20" x2="20" y2="7"
        style={{ transform: `rotate(${angle}deg)` }}
      />
    </svg>
  );
}

/** ゲームモードの説明モーダル。 */
function ModeHelp({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="ゲームモードの説明" onClick={(e) => e.stopPropagation()}>
        <h2 className="modal-title">ゲームモード</h2>
        <p className="modal-lead">正解したときの点数の決まり方が変わります。</p>
        {MODE_HELP.map((m) => (
          <div className="modal-item" key={m.mode}>
            <h3>{MODE_LABEL[m.mode]}</h3>
            <p className="modal-formula">{m.formula}</p>
            <p className="modal-note">{m.note}</p>
          </div>
        ))}
        <p className="modal-note">※ 誤答すると、同じ点数だけ引かれます。</p>
        <button className="big" onClick={onClose}>とじる</button>
      </div>
    </div>
  );
}

/** 取り消せない操作の前に一度だけ聞く。ブラウザ既定のダイアログはこの画面では浮くので使わない。 */
function Confirm({
  title, lead, yes, onYes, onNo,
}: { title: string; lead: string; yes: string; onYes: () => void; onNo: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onNo();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onNo]);

  return (
    <div className="modal-bg" onClick={onNo}>
      <div className="modal" role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h2 className="modal-title">{title}</h2>
        <p className="modal-note">{lead}</p>
        <button className="big" onClick={onYes}>{yes}</button>
        <button className="back" onClick={onNo}>← ゲームに戻る</button>
      </div>
    </div>
  );
}

// ── ホーム ────────────────────────────────────────────────

type HomeView = "top" | "friend" | "matching" | "settings";

function Home({ onEnter }: { onEnter: (id: string) => void }) {
  const config = useConfig();
  const [view, setView] = useState<HomeView>("top");
  const [name, setName] = useState("わたし");
  const [rules, setRulesState] = useState<Rules>(loadRules);

  // 選んだ内容はその場で覚える。次に遊ぶときに選び直さなくてよい
  const setRules = (next: Rules) => {
    setRulesState(next);
    saveRules(next);
  };
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [help, setHelp] = useState(false);

  // 出演者の名前で始めたときだけ下りる幕。ゲームには関わらない演出
  const [egg, setEgg] = useState<Egg | null>(null);
  // 幕が上がったあとに走らせる処理。state に関数を入れると更新関数と紛れるので ref
  const after = useRef<() => void>(() => {});

  const withEgg = (run: () => void) => {
    const hit = findEgg(name);
    if (!hit) return run();
    after.current = run;
    setEgg(hit);
  };

  const eggDone = useCallback(() => {
    setEgg(null);
    after.current();
  }, []);

  const createRoom = async () => {
    setBusy(true);
    try {
      const { roomId } = await api.createRoom({ ...rules, username: name || "わたし" });
      onEnter(roomId);
    } finally {
      setBusy(false);
    }
  };

  // ひとりで遊ぶ。対戦相手を入れず、ロビーも挟まずそのまま始める
  const soloGame = async () => {
    setBusy(true);
    try {
      const { roomId } = await api.createRoom({
        ...rules,
        username: name || "わたし",
        bot_count: 0,
      });
      await api.start(roomId);
      onEnter(roomId);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const joinRoom = async () => {
    const c = code.trim().toUpperCase();
    if (!c) return;
    setBusy(true);
    try {
      await api.join(c, name || "わたし");
      onEnter(c);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (view === "matching") {
    return <Matching name={name} rules={rules} onEnter={onEnter} onBack={() => setView("top")} />;
  }

  return (
    <main className="app">
      <div className="body pad">
        <h1 className="logo">1分間予習クイズ</h1>

        {view === "top" && (
          <>
            <label className="field">
              <span>ニックネーム</span>
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={12} />
            </label>

            <div className="field">
              <span className="field-label">
                ゲームモード
                <button className="help" onClick={() => setHelp(true)} aria-label="ゲームモードの説明">!</button>
              </span>
              <div className="chips">
                {(["FIXED", "POPULARITY", "MAX_NUMBER"] as GameMode[]).map((m) => (
                  <button
                    key={m}
                    className={`chip ${rules.game_mode === m ? "on" : ""}`}
                    onClick={() => setRules({ ...rules, game_mode: m })}
                  >
                    {MODE_LABEL[m]}
                  </button>
                ))}
              </div>
            </div>

            {/* 問題数と予習時間は設定画面へ。ここには今の値だけを出す */}
            <button className="settings-link" onClick={() => setView("settings")}>
              <span className="gear" aria-hidden="true">⚙</span>
              <span className="settings-cur">{rules.total_rounds}問 / 予習{rules.study_sec}秒</span>
              <span className="settings-go">設定</span>
            </button>

            <button className="big" onClick={() => withEgg(() => setView("matching"))}>マッチング</button>
            <button className="big ghost" onClick={() => setView("friend")}>フレンド対戦</button>
            <button className="big ghost" onClick={() => withEgg(soloGame)} disabled={busy}>ひとりで遊ぶ</button>
            <p className="note">マッチングでは、同じルールを選んだ人と対戦します</p>
          </>
        )}

        {view === "settings" && (
          <Settings
            rules={rules}
            config={config}
            onChange={setRules}
            onBack={() => setView("top")}
          />
        )}

        {view === "friend" && (
          <>
            <p className="lead">友だちと遊ぶ</p>
            <button className="big" onClick={() => withEgg(createRoom)} disabled={busy}>ルームを作る</button>
            <div className="sep">または</div>
            <label className="field">
              <span>ルームキー</span>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                maxLength={6}
                placeholder="A2C4EF"
              />
            </label>
            <button className="big ghost" onClick={joinRoom} disabled={busy}>ルームに参加</button>
            <button className="back" onClick={() => setView("top")}>← 戻る</button>
          </>
        )}
      </div>
      {help && <ModeHelp onClose={() => setHelp(false)} />}
      {egg && <EggCurtain egg={egg} onDone={eggDone} />}
    </main>
  );
}

/** 出演者の名前で始めた人にだけ下りる幕。2秒で自分から上がり、押せばすぐ飛ばせる。 */
function EggCurtain({ egg, onDone }: { egg: Egg; onDone: () => void }) {
  const artRef = useRef<HTMLPreElement>(null);
  const [scale, setScale] = useState(0);

  useEffect(() => {
    const id = setTimeout(onDone, 2000);
    return () => clearTimeout(id);
  }, [onDone]);

  // 絵は100桁を超える。画面幅から font-size を逆算する手もあるが、
  // 1文字の実寸はフォントごとに違うので必ずずれる。実際に描かせて測る。
  useLayoutEffect(() => {
    const el = artRef.current;
    if (!el) return;
    const fit = () => {
      // 元絵は1文字＝正方形のドットとして写真から起こしてある。
      // 行送りを文字幅と同じにしないと、顔が縦に伸びて別人になる
      el.style.lineHeight = `${el.offsetWidth / egg.cols}px`;
      // offsetWidth / offsetHeight は transform の影響を受けないので、
      // 縮めたあとに測り直しても値が転がらない
      const fitted = Math.min(
        (window.innerWidth * 0.94) / el.offsetWidth,
        (window.innerHeight * 0.72) / el.offsetHeight,
      );
      // 画面が測れない状況（描画が止まったタブなど）で 0 を掛けると
      // 絵が消えたまま戻らない。測れなければ縮めない
      setScale(fitted > 0 ? fitted : 1);
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [egg]);

  return (
    <div className="egg-bg" onClick={onDone}>
      <div className="egg-stage">
        <pre
          ref={artRef}
          className="egg-art"
          style={{ transform: `translate(-50%,-50%) scale(${scale})`, opacity: scale ? 1 : 0 }}
        >
          {egg.art}
        </pre>
      </div>
      <p className="egg-line">{egg.line}</p>
    </div>
  );
}

/** 対戦のルールを決める画面。選んだ内容は保存され、次回もそのまま使う。 */
function Settings({
  rules, config, onChange, onBack,
}: {
  rules: Rules;
  config: AppConfig;
  onChange: (r: Rules) => void;
  onBack: () => void;
}) {
  return (
    <>
      <p className="lead">設定</p>

      <div className="field">
        <span>問題数</span>
        <div className="chips">
          {config.roundsChoices.map((n) => (
            <button
              key={n}
              className={`chip ${rules.total_rounds === n ? "on" : ""}`}
              onClick={() => onChange({ ...rules, total_rounds: n })}
            >
              {n}問
            </button>
          ))}
        </div>
        <p className="note">1本の記事から、この数だけ出題します</p>
      </div>

      <div className="field">
        <span>予習時間</span>
        <div className="chips">
          {config.studySecChoices.map((s) => (
            <button
              key={s}
              className={`chip ${rules.study_sec === s ? "on" : ""}`}
              onClick={() => onChange({ ...rules, study_sec: s })}
            >
              {s}秒
            </button>
          ))}
        </div>
        <p className="note">記事を読める時間。短いほど、ヤマの張り方が問われます</p>
      </div>

      <p className="note">
        マッチングでは、ここで選んだ内容が同じ人とだけ対戦します。
        設定は次に遊ぶときも引き継がれます。
      </p>

      <button className="big" onClick={onBack}>決定</button>
    </>
  );
}

const MATCH_STEPS = ["対戦相手をさがしています", "マッチングしました", "まもなくゲームを開始します"];

// 人が集まるのを待つ上限。これを過ぎたら残りの席を埋めて始める
const MATCH_WAIT_MS = 5000;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** 同じルールを選んだ相手と引き合わせ、ルームキーの入力も開始ボタンも挟まずゲームへ入る。 */
function Matching({
  name, rules, onEnter, onBack,
}: { name: string; rules: Rules; onEnter: (id: string) => void; onBack: () => void }) {
  const [step, setStep] = useState(0);

  useEffect(() => {
    let alive = true;

    (async () => {
      // 同じルールで募集中の部屋に入る。無ければ自分が募集側になる
      const { roomId } = await api.matchmake({ ...rules, username: name || "わたし" });

      // 相手が入ってくるのを待つ。定員が埋まるか、待ち時間が尽きるまで
      const deadline = Date.now() + MATCH_WAIT_MS;
      while (alive && Date.now() < deadline) {
        // 待っていることを知らせる。放置された部屋と区別してもらうため
        await api.heartbeat(roomId);
        const r = await api.getRoom(roomId);
        if (r.status !== "LOBBY") break; // 先に始まっていた
        if (Object.keys(r.players).length >= 4) break;
        await sleep(600);
      }
      if (!alive) return;

      setStep(1);
      await sleep(1400);
      if (!alive) return;
      setStep(2);

      // 席が余っていれば埋めて開始する。開始は冪等なので、
      // 同じ部屋の全員がここに来ても実際に始まるのは1回だけ
      await api.fillBots(roomId);
      await api.start(roomId);
      await sleep(1200);
      if (alive) onEnter(roomId);
    })();

    return () => {
      alive = false;
    };
  }, [name, rules, onEnter]);

  const done = step > 0;
  return (
    <main className="app">
      <div className="body pad center">
        <div className={`radar ${done ? "found" : ""}`}>{done ? "✓" : ""}</div>
        <h2 className="matching">{MATCH_STEPS[step]}</h2>
        <p className="lead">
          {MODE_LABEL[rules.game_mode]} / {rules.total_rounds}問 / 予習{rules.study_sec}秒
        </p>
        {step === 0 && <button className="back" onClick={onBack}>← やめる</button>}
      </div>
    </main>
  );
}

// ── ゲーム ────────────────────────────────────────────────

/** 僅差で負けたときの記録。どの問題で、何ミリ秒差で、誰に負けたか。 */
type NearMiss = { round: number; behindMs: number; winner: string };

function Game({
  room, serverNow, onExit,
}: { room: Room; serverNow: () => number; onExit: () => void }) {
  const me = playerId();
  const { left, progress } = useCountdown(room.phaseStartedAt, room.phaseEndsAt, serverNow);
  const playing = room.status !== "LOBBY" && room.status !== "FINISHED";
  const quizzing = room.status === "ANSWERING" || room.status === "REVEALING";
  // ひとりで遊んでいるか。サーバーに旗を持たせなくても、部屋の顔ぶれで分かる
  const solo = Object.keys(room.players).length === 1;
  const [quitting, setQuitting] = useState(false);

  // 進行中に抜けるのは取り返しがつかないので一度聞く。
  // ロビーと結果画面は押した意図がはっきりしているのでそのまま戻す
  const quit = () => (playing ? setQuitting(true) : onExit());

  // 「先を越された」は出題画面ではなく、ここで持つ。
  // 解答が成立した瞬間に開示へ切り替わるので、出題画面に置くと
  // 返事が届くころには画面が消えていて、いちばん知りたい人に何も出せない
  const [nearMiss, setNearMiss] = useState<NearMiss | null>(null);
  const miss = nearMiss?.round === room.currentRound ? nearMiss : null;

  return (
    <main className="app">
      <header className="bar">
        {/* 右端は時計が占めているので、抜ける口は左端に置く */}
        <button className="quit" onClick={quit} aria-label="ゲームをやめる">×</button>
        {/* ルームキーが要るのは、友だちを呼ぶロビーだけ。
            マッチングで入った部屋では誰にも教える必要がない */}
        {room.status === "LOBBY" && room.isPrivate && <span className="code">{room.roomId}</span>}
        <span className="mode">{MODE_LABEL[room.settings.gameMode]}</span>
        {room.status === "STUDYING" && <span className="round">予習</span>}
        {quizzing && <span className="round">第{room.currentRound}問 / {room.settings.totalRounds}</span>}
        {room.phaseEndsAt && (
          <span className="timer"><ClockHand progress={progress} left={left} /></span>
        )}
      </header>

      <div className="body">
        {room.status === "LOBBY" && <Lobby room={room} />}
        {room.status === "STUDYING" && room.article && <Study room={room} />}
        {room.status === "ANSWERING" && room.currentQuestion && (
          <Answer room={room} solo={solo} miss={miss} onMiss={setNearMiss} />
        )}
        {room.status === "REVEALING" && room.currentQuestion && (
          <Reveal room={room} me={me} solo={solo} miss={miss} />
        )}
        {room.status === "FINISHED" && <Result room={room} solo={solo} onExit={onExit} />}
      </div>

      {playing && <ScoreBar room={room} me={me} />}

      {quitting && (
        <Confirm
          title="ゲームをやめますか？"
          lead={
            solo
              ? "ここまでの得点は残りません。"
              : "ここまでの得点は残りません。対戦中の相手のところにも戻れなくなります。"
          }
          yes="やめてホームへ"
          onYes={onExit}
          onNo={() => setQuitting(false)}
        />
      )}
    </main>
  );
}

function ScoreBar({ room, me }: { room: Room; me: string }) {
  const answered = room.status === "REVEALING" ? room.buzz.ownerId : null;
  const sorted = Object.entries(room.players).sort((a, b) => b[1].score - a[1].score);
  return (
    <footer className="scorebar">
      {sorted.map(([id, p]) => (
        <div key={id} className={`sc-item ${answered === id ? "hit" : ""} ${id === me ? "self" : ""}`}>
          <span className="dot" style={{ background: COLORS[p.color] ?? "#999" }} />
          <span className="nm">{p.username}</span>
          <span className="sc">{p.score.toLocaleString()}</span>
        </div>
      ))}
    </footer>
  );
}

function Lobby({ room }: { room: Room }) {
  const alone = Object.keys(room.players).length < 2;
  return (
    <div className="pad center">
      {/* ルームキーは友だちを呼ぶための道具。マッチングの部屋では出さない */}
      {room.isPrivate && (
        <>
          <p className="lead">ルームキー</p>
          <p className="big-code">{room.roomId}</p>
        </>
      )}
      <ul className="members">
        {Object.entries(room.players).map(([id, p]) => (
          <li key={id}>
            <span className="dot" style={{ background: COLORS[p.color] ?? "#999" }} />
            {p.username}
          </li>
        ))}
      </ul>
      {alone && (
        <p className="note">
          {room.isPrivate ? "このルームキーを友だちに送ってください" : "対戦相手を待っています"}
        </p>
      )}
      <button className="big" onClick={() => api.start(room.roomId)}>ゲーム開始</button>
    </div>
  );
}

/** 予習画面。ページ全体はスクロールせず、記事だけがスクロールする。 */
function Study({ room }: { room: Room }) {
  const a = room.article!;
  // 予習のスキップはモック構成でだけ出す。有無を決めるのはサーバー（API キーの有無）
  const { mock } = useConfig();
  return (
    <div className="study">
      <div className="study-head pad-x">
        <p className="badge">正解 +{a.basePoint.toLocaleString()} / 誤答 −{a.basePoint.toLocaleString()}</p>
        <h2 className="title">{a.title}</h2>
        {/* 問題はこの60秒のあいだに作られる。出来ていないことは隠さない。
            予習が延びた理由が分からないと、止まったように見える */}
        <p className="note">
          {room.quizReady
            ? `この記事から${room.settings.totalRounds}問出ます`
            : "この記事から出題します（問題を準備しています…）"}
        </p>
      </div>
      <div className="article">{a.extract}</div>
      {mock && (
        <div className="study-foot pad-x">
          <button className="skip" onClick={() => api.skip(room.roomId)}>予習をスキップ（モック）</button>
        </div>
      )}
    </div>
  );
}

// 選択肢の見分け。色だけに頼らず形も変えるので、色の見分けがつかなくても選び違えない。
// 数字はそのままキーボードの割り当てでもある
const CHOICE_MARKS = [
  // dy は数字の位置合わせ。三角は下半分に面積が寄るので、数字も下げないと
  // 細い頂点側に重なって読めなくなる
  { shape: "circle", color: "#E8352B", fg: "#fff", dy: 0 },
  { shape: "triangle", color: "#1E86D6", fg: "#fff", dy: 4 },
  { shape: "square", color: "#F5A623", fg: "#16161C", dy: 0 },
  { shape: "diamond", color: "#25B75C", fg: "#fff", dy: 0 },
] as const;

function ChoiceMark({ index }: { index: number }) {
  const { shape, color, fg, dy } = CHOICE_MARKS[index % CHOICE_MARKS.length];
  return (
    <span className="mark" aria-hidden="true">
      <svg viewBox="0 0 32 32">
        {shape === "circle" && <circle cx="16" cy="16" r="15" fill={color} />}
        {shape === "triangle" && <path d="M16 1 L31 30 L1 30 Z" fill={color} />}
        {shape === "square" && <rect x="1" y="1" width="30" height="30" rx="4" fill={color} />}
        {shape === "diamond" && <path d="M16 0 L32 16 L16 32 L0 16 Z" fill={color} />}
      </svg>
      <b style={{ color: fg, transform: `translateY(${dy}px)` }}>{index + 1}</b>
    </span>
  );
}

function Answer({
  room, solo, miss, onMiss,
}: { room: Room; solo: boolean; miss: NearMiss | null; onMiss: (m: NearMiss) => void }) {
  const q = room.currentQuestion!;
  const point = room.article?.basePoint ?? 0;
  const taken = room.buzz.ownerId !== null;

  const choose = async (c: string) => {
    const r = await api.answer(room.roomId, room.currentRound, c);
    if (r.accepted || r.reason !== "TAKEN" || r.behindMs === undefined) return;
    // 解答できる時間より大きい差は、競り負けではなく「もう終わっていた」だけ。
    // それを「21.98秒差で負けました」と出しても意味がないので黙っておく
    if (r.behindMs > (room.settings.durations.answerMs ?? 15000)) return;
    onMiss({ round: room.currentRound, behindMs: r.behindMs, winner: r.winnerName ?? "相手" });
  };

  // 早押しは指の速さを競うので、タップより速いキーボードも受ける
  useEffect(() => {
    if (taken) return;
    const onKey = (e: KeyboardEvent) => {
      const n = Number(e.key);
      if (n >= 1 && n <= q.choices.length) {
        e.preventDefault();
        void choose(q.choices[n - 1]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // 押したあとの一言と、押す前の一言。ひとりのときに「早い者勝ち」と言われても、
  // competing 相手がいないので意味が通らない
  const hint = taken
    ? solo ? "解答しました" : "解答が入りました"
    : solo ? "答えられるのは1回だけ。選んだら確定です" : "早い者勝ち。最初に選んだ人の解答で決まります";

  return (
    <div className="pad center pad-mid">
      <div className="mid">
        <p className="badge">正解 +{point.toLocaleString()} / 誤答 −{point.toLocaleString()}</p>
        <h2 className="q">{q.question}</h2>
        <div className="choices">
          {q.choices.map((c, i) => (
            <button key={c} disabled={taken} onClick={() => void choose(c)}>
              <ChoiceMark index={i} />
              <span className="label">{c}</span>
            </button>
          ))}
        </div>
        {miss ? (
          <NearMissLine miss={miss} />
        ) : (
          <p className="note">
            {hint}
            {/* キーボードのある端末にだけ出す。判定は CSS がやる（.kbd） */}
            <span className="kbd">（1〜4キーでも押せます）</span>
          </p>
        )}
      </div>
    </div>
  );
}

/** 何秒差で負けたか。0.01秒まで出す。「わずかに遅かった」が伝わらないと悔しくない。 */
function NearMissLine({ miss }: { miss: NearMiss }) {
  return (
    <p className="behind">
      {(miss.behindMs / 1000).toFixed(2)}秒差で{miss.winner}に先を越されました
    </p>
  );
}

function Reveal({
  room, me, solo, miss,
}: { room: Room; me: string; solo: boolean; miss: NearMiss | null }) {
  const q = room.currentQuestion!;
  const b = room.buzz;
  const who = b.ownerId ? room.players[b.ownerId] : null;
  const humans = Object.entries(room.players).filter(([, p]) => !p.isBot);
  const readyCount = humans.filter(([id]) => room.ready?.[id]).length;
  const iAmReady = Boolean(room.ready?.[me]);
  const last = room.currentRound >= room.settings.totalRounds;

  return (
    <div className="pad center pad-mid">
      <div className="mid">
        {who ? (
          <>
            <p className={`verdict ${b.isCorrect ? "ok" : "ng"}`}>
              {who.username}「{b.answer}」{b.isCorrect ? "◯" : "×"}
            </p>
            <p className={`delta ${b.isCorrect ? "ok" : "ng"}`}>
              {b.delta !== null ? `${b.delta > 0 ? "+" : ""}${b.delta.toLocaleString()}` : ""}
            </p>
          </>
        ) : (
          // ひとりの場に「誰も答えませんでした」と出すと、責められているようにしか読めない
          <p className="verdict">{solo ? "時間切れ" : "誰も答えませんでした"}</p>
        )}
        {/* 競り負けた人にだけ、どれだけ惜しかったかを見せる */}
        {miss && <NearMissLine miss={miss} />}

        <h2 className="q">正解: {q.correctAnswer}</h2>
        <p className="exp">{q.explanation}</p>

        <button className="big next" disabled={iAmReady} onClick={() => api.ready(room.roomId)}>
          {iAmReady ? "ほかの人を待っています…" : last ? "結果を見る" : "次の問題へ"}
        </button>
        <p className="note">
          {humans.length > 1 ? `${readyCount} / ${humans.length} 人が準備完了・` : ""}
          時間が来ると自動で進みます
        </p>
      </div>
    </div>
  );
}

function Result({ room, solo, onExit }: { room: Room; solo: boolean; onExit: () => void }) {
  const ranked = Object.values(room.players).sort((a, b) => b.score - a.score);
  const a = room.article;
  // ひとりのときの得点。プラスかマイナスかは色でも分かるようにする
  const solo0 = ranked[0]?.score ?? 0;
  const soloTone = solo0 > 0 ? "ok" : solo0 < 0 ? "ng" : "";
  return (
    <div className="pad center">
      <h2 className="result-title">最終結果</h2>
      {solo ? (
        // ひとりで「1位」を出しても意味がないので、順位表ではなく得点を見せる。
        // 正解数はサーバーが持っていない（得点からは誤答の分だけずれる）ので出さない
        <div className="solo-score">
          <p className="note">{room.settings.totalRounds}問おわり</p>
          <p className={`delta ${soloTone}`}>
            {solo0 > 0 ? "+" : ""}{solo0.toLocaleString()}
          </p>
        </div>
      ) : (
        <ol className="rank">
          {ranked.map((p, i) => (
            <li key={p.username} className={i === 0 ? "top" : ""}>
              <span className="place">{i + 1}</span>
              <span className="dot" style={{ background: COLORS[p.color] ?? "#999" }} />
              <span className="nm">{p.username}</span>
              <b>{p.score.toLocaleString()}</b>
            </li>
          ))}
        </ol>
      )}

      {a && (
        <section className="sources">
          <h3>今回の記事</h3>
          <ul>
            <li>
              <a href={a.url} target="_blank" rel="noopener noreferrer">
                {a.title}
              </a>
            </li>
          </ul>
        </section>
      )}

      {/* 同じ相手との再戦ではなくホームへ戻るだけなので、そう書く。
          リロードしないぶん、ニックネームと設定を選び直さずに次を始められる */}
      <button className="big" onClick={onExit}>ホームに戻る</button>
    </div>
  );
}
