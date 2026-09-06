/**
 * LP（lp/index.html）に載せる画面の写しを撮る。
 *
 *   docker compose --profile shots up --build shots
 *
 * 利用者と同じ順に操作して撮るので、画面を変えたら撮り直すだけで追随する。
 * 予習の60秒はモック用のスキップで飛ばす（API キーが未設定のときだけ出る）。
 */

const fs = require("fs");
const puppeteer = require("puppeteer");

const BASE = process.env.BASE_URL || "http://web:5173";
const OUT = process.env.OUT_DIR || "/work/lp/shots";
// LP の挿絵は横並びで小さく置くので、縦長のスマホ画面より
// 横幅のあるデスクトップ表示のほうが読める
const WIDTH = Number(process.env.SHOT_WIDTH || 900);
const HEIGHT = Number(process.env.SHOT_HEIGHT || 700);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: process.env.CHROME_BIN || "/usr/bin/chromium",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 2 });

  page.on("console", (m) => { if (m.type() === "error") console.log(`[画面] ${m.text()}`); });
  page.on("pageerror", (e) => console.log(`[画面] ${e.message}`));

  const shot = async (name) => {
    await sleep(500);
    await page.screenshot({ path: `${OUT}/${name}.png` });
    console.log(`撮影: ${name}.png`);
  };

  // 画面が切り替わるまで待つ。出ている文言で判断する。
  const waitForText = async (text) => {
    try {
      await page.waitForFunction(
        (t) => document.body.innerText.includes(t),
        // 予習の30秒を待つことがあるので長めに取る
        { timeout: 60000 },
        text,
      );
    } catch (e) {
      // 何が出ていたのかが分からないと直しようがない。
      const seen = await page.evaluate(() => document.body.innerText.slice(0, 300));
      throw new Error(`「${text}」が出なかった。画面にはこれが出ていた:\n${seen}`);
    }
    await sleep(500);
  };

  // 文言でボタンを押す。CSS セレクタより画面の見た目に近い。
  const clickText = async (text) => {
    const ok = await page.evaluate((t) => {
      const b = [...document.querySelectorAll("button")].find((x) => x.textContent.includes(t));
      if (!b) return false;
      b.click();
      return true;
    }, text);
    if (!ok) throw new Error(`ボタン「${text}」が見つからなかった`);
    await sleep(400);
  };

  await page.goto(BASE, { waitUntil: "networkidle0" });
  await waitForText("ニックネーム");
  await shot("01-home");

  // ゲームモードの説明
  await page.click(".help");
  await waitForText("正解したときの点数の決まり方");
  await shot("02-modes");
  await clickText("とじる");

  // 予習の待ち時間を設定画面で短くしておく。
  // モックでなくても撮影が回るようにするため
  await page.click(".settings-link");
  await waitForText("記事を読める時間");
  await shot("03-settings");
  await clickText("30秒");
  await clickText("決定");

  // マッチング演出
  await clickText("マッチング");
  await waitForText("対戦相手をさがしています");
  await shot("04-matching");

  // 予習（記事は1本。ここから全問が出る）
  await waitForText("この記事から");
  // モック用のスキップボタンは実際の対戦には無いので、写さない
  await page.addStyleTag({ content: ".study-foot{visibility:hidden}" });
  await shot("05-study");

  // 出題（選択肢は最初から出ている）。
  // スキップはモック構成のときしか出ないので、無ければ予習の30秒を待つ
  await clickText("予習をスキップ").catch(() => {});
  await waitForText("早い者勝ち");
  await shot("06-question");

  // 開示
  await waitForText("正解:");
  await shot("07-reveal");

  // 最終結果まで進める
  for (let i = 0; i < 12; i++) {
    const done = await page.evaluate(() => document.body.innerText.includes("最終結果"));
    if (done) break;
    await page.evaluate(() => {
      const b = [...document.querySelectorAll("button")]
        .find((x) => /次の問題へ|結果を見る/.test(x.textContent));
      if (b && !b.disabled) b.click();
    });
    await sleep(900);
  }
  await waitForText("最終結果");
  await shot("08-result");

  await browser.close();
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
