/**
 * ニックネームに出演者の名前を入れた人にだけ出る、ちょっとした仕掛け。
 *
 * ゲームの進行には一切関わらない。名前はそのまま username としてサーバーへ送り、
 * ここで足すのは「開始を押してから遷移するまでの2秒」だけ。
 */

// 絵は .txt のまま持つ。TS のテンプレート文字列に貼ると
// バッククォートや \ や ${ の取り扱いが要るうえ、差し替えのたびに
// 中身を書き換える必要が出る。生ファイルなら丸ごと置き換えるだけで済む
import gunpy from "./aa/gunpy.txt?raw";
import haruhiko from "./aa/haruhiko.txt?raw";
import tsuchioka from "./aa/tsuchioka.txt?raw";

export type Egg = {
  /** 写真から起こした濃淡の絵。「@ が濃く . が薄い」向きで描いてある */
  art: string;
  /** 絵の下に出す一言 */
  line: string;
  /**
   * 桁数。1文字＝正方形のドットとして扱うので、
   * 表示側はこれで文字幅を割り出し、同じ値を行送りに使う
   */
  cols: number;
};

/** 生ファイルから、桁数を測って Egg にする。 */
function art(raw: string, line: string): Egg {
  const lines = raw.replace(/\n+$/, "").split("\n");
  return {
    art: lines.join("\n"),
    line,
    cols: Math.max(...lines.map((l) => l.length)),
  };
}

/**
 * 表記ゆれをならす。
 *
 * 「ぐんぴぃ」「グンピィ」「ぐんぴい」を別物として扱いたくない。
 * ひらがなに寄せ、小書きを大書きにし、長音と空白を落とすと、
 * どれも「ぐんぴい」という同じ綴りに落ちる。
 */
function normalize(raw: string): string {
  const small: Record<string, string> = {
    ぁ: "あ", ぃ: "い", ぅ: "う", ぇ: "え", ぉ: "お",
    っ: "つ", ゃ: "や", ゅ: "ゆ", ょ: "よ", ゎ: "わ",
  };
  return raw
    .trim()
    .normalize("NFKC")
    .toLowerCase()
    // カタカナ → ひらがな
    .replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60))
    .replace(/[ぁぃぅぇぉっゃゅょゎ]/g, (c) => small[c])
    .replace(/[ー\s]/g, "");
}

// 一言は3人とも同じ形にそろえる。人によって言い回しが違うと、
// 名前ではなく文句のほうが目立って、誰が出たのかが伝わりにくい
const GUNPY: Egg = art(gunpy, "ぐんぴぃ、参戦");
const TSUCHIOKA: Egg = art(tsuchioka, "土岡哲朗、参戦");
const HARUHIKO: Egg = art(haruhiko, "春とヒコーキ、参戦");

/**
 * 照合表。キーも同じ正規化にかけて突き合わせるので、綴りは代表的なものだけでよい。
 *
 * ただし**漢字は正規化で読みに変わらない**。「春とヒコーキ」と書く人と
 * 「はるとひこーき」と書く人は別の綴りに落ちるので、両方を並べておく。
 */
const EGGS: { keys: string[]; egg: Egg }[] = [
  { keys: ["ぐんぴぃ", "バキ童", "ばきどう"], egg: GUNPY },
  { keys: ["土岡哲朗", "土岡", "つちおかてつろう", "つちおか"], egg: TSUCHIOKA },
  { keys: ["春とヒコーキ", "はるとひこーき"], egg: HARUHIKO },
];

/** 名前が出演者と一致すれば、その AA を返す。ふつうの名前なら null。 */
export function findEgg(name: string): Egg | null {
  const key = normalize(name);
  if (!key) return null;
  for (const { keys, egg } of EGGS) {
    if (keys.some((k) => normalize(k) === key)) return egg;
  }
  return null;
}
