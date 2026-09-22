// Прогоняет НАСТОЯЩИЙ <script> страницы пульта (fetch с "/") против ЖИВОГО
// сервера плагина (двойник robot за ним) — та же техника, что у reviewer'а
// в ревью Task 2.3b (node:vm, страница как есть, без headless-браузера).
// Использование: node page_offline.mjs <port> <scenario>
import vm from "node:vm";

const [port, scenario] = process.argv.slice(2);
const base = `http://127.0.0.1:${port}`;

const html = await (await fetch(base + "/")).text();
const src = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function makeEl(id) {
  return {
    id,
    value: id === "freqNum" || id === "freq" ? "25" : "101.1",
    checked: false,
    textContent: "",
    h: {},
    addEventListener(t, f) {
      (this.h[t] ||= []).push(f);
    },
    fire(t) {
      (this.h[t] || []).forEach((f) => f({ type: t }));
    },
  };
}
const els = {};
function el(id) {
  return (els[id] ||= makeEl(id));
}
const win = {
  h: {},
  addEventListener(t, f) {
    (this.h[t] ||= []).push(f);
  },
  fire(t) {
    (this.h[t] || []).forEach((f) => f({}));
  },
};
const doc = {
  hidden: false,
  h: {},
  getElementById: el,
  addEventListener(t, f) {
    (this.h[t] ||= []).push(f);
  },
  fire(t) {
    (this.h[t] || []).forEach((f) => f({}));
  },
};
const ctx = {
  document: doc,
  window: win,
  fetch: (p, o) => fetch(base + p, o),
  setInterval,
  clearInterval,
  parseFloat,
  JSON,
  console,
};
vm.createContext(ctx);
vm.runInContext(src, ctx);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function run() {
  if (scenario === "no_press") {
    // Ни одного pointerdown не было — jogTimer никогда не заводился.
    el("jogFwd").fire("pointerleave");
    await sleep(50);
    win.fire("blur");
    await sleep(50);
    doc.hidden = true;
    doc.fire("visibilitychange");
    await sleep(200);
  } else if (scenario === "multitouch") {
    el("jogFwd").fire("pointerdown"); // палец 1 на ▶
    el("jogRev").fire("pointerdown"); // палец 2 на ◀ — таймер ▶ должен быть снят, не осиротеть
    await sleep(100);
    el("jogRev").fire("pointerup");
    el("jogFwd").fire("pointerup");
    await sleep(1000); // достаточно для минимум 4 тиков осиротевшего таймера, если он есть
  } else if (scenario === "slow_jog_hold") {
    el("jogFwd").fire("pointerdown");
    await sleep(900);
    el("jogFwd").fire("pointerup");
    await sleep(900); // jog, висящий до ~1150 мс, возвращается, затем уходит stop
  } else if (scenario === "status_error") {
    await sleep(400); // >= один цикл опроса (250 мс)
    process.stdout.write(JSON.stringify({ statusText: el("status").textContent }));
  }
  process.exit(0);
}

run();
