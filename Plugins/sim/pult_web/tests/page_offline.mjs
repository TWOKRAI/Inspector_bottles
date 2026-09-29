// Прогоняет НАСТОЯЩИЙ <script> страницы пульта (fetch с "/") против ЖИВОГО
// сервера плагина (двойник robot за ним) — та же техника, что у reviewer'а
// в ревью Task 2.3b (node:vm, страница как есть, без headless-браузера).
// Использование: node page_offline.mjs <port> <scenario>
import vm from "node:vm";
import zlib from "node:zlib";

const [port, scenario] = process.argv.slice(2);
const base = `http://127.0.0.1:${port}`;

const html = await (await fetch(base + "/")).text();
const src = html.match(/<script>([\s\S]*?)<\/script>/)[1];

// ---------------------------------------------------------------------------
// Task 1.3h-b: заглушки браузера для канвы редактора слоёв — программный 2D-контекст
// (drawImage/getImageData/clearRect с аффинной матрицей), Image с настоящей
// декодировкой PNG (node:zlib), указатель/клавиатура через fire(t, ev). Заглушка
// НЕ «всегда непрозрачная»: getImageData отвечает пикселями, которые реально
// нарисовали в этот холст, иначе тест выбора по альфе был бы вакуумным.
// ---------------------------------------------------------------------------
function decodePng(buf) {
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error("not a PNG");
  let pos = 8, w = 0, h = 0, depth = 0, ctype = 0;
  const idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos);
    const type = buf.toString("ascii", pos + 4, pos + 8);
    const data = buf.subarray(pos + 8, pos + 8 + len);
    if (type === "IHDR") {
      w = data.readUInt32BE(0);
      h = data.readUInt32BE(4);
      depth = data[8];
      ctype = data[9];
      if (data[12]) throw new Error("interlaced PNG is not supported by the harness");
    } else if (type === "IDAT") idat.push(data);
    else if (type === "IEND") break;
    pos += 12 + len;
  }
  const ch = { 0: 1, 2: 3, 4: 2, 6: 4 }[ctype];
  if (depth !== 8 || !ch) throw new Error("PNG: only 8-bit gray/gray+alpha/RGB/RGBA are supported");
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = w * ch;
  const out = new Uint8ClampedArray(w * h * 4);
  let prev = new Uint8Array(stride);
  for (let y = 0; y < h; y++) {
    const ft = raw[y * (stride + 1)];
    const line = Uint8Array.from(raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1)));
    for (let i = 0; i < stride; i++) {
      const a = i >= ch ? line[i - ch] : 0;
      const b = prev[i];
      const c = i >= ch ? prev[i - ch] : 0;
      let v = line[i];
      if (ft === 1) v += a;
      else if (ft === 2) v += b;
      else if (ft === 3) v += (a + b) >> 1;
      else if (ft === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      }
      line[i] = v & 255;
    }
    for (let x = 0; x < w; x++) {
      const o = (y * w + x) * 4;
      if (ch === 4) { out[o] = line[x * 4]; out[o + 1] = line[x * 4 + 1]; out[o + 2] = line[x * 4 + 2]; out[o + 3] = line[x * 4 + 3]; }
      else if (ch === 3) { out[o] = line[x * 3]; out[o + 1] = line[x * 3 + 1]; out[o + 2] = line[x * 3 + 2]; out[o + 3] = 255; }
      else if (ch === 2) { out[o] = out[o + 1] = out[o + 2] = line[x * 2]; out[o + 3] = line[x * 2 + 1]; }
      else { out[o] = out[o + 1] = out[o + 2] = line[x]; out[o + 3] = 255; }
    }
    prev = line;
  }
  return { w, h, data: out };
}

// `new Image()`: src принимает ТОЛЬКО data:image/png;base64 (контракт 1.3h-b);
// декодирование — асинхронно (setTimeout 0), onload/addEventListener("load")/decode().
class ImageStub {
  constructor(w, h) {
    this.width = w || 0;
    this.height = h || 0;
    this.naturalWidth = 0;
    this.naturalHeight = 0;
    this.complete = false;
    this.onload = null;
    this.onerror = null;
    this._l = {};
    this._src = "";
    this._px = null;
    this._done = Promise.resolve();
  }
  addEventListener(t, f) { (this._l[t] ||= []).push(f); }
  removeEventListener() {}
  decode() { return this._done; }
  get src() { return this._src; }
  set src(v) {
    this._src = String(v);
    this._px = null;
    this.complete = false;
    this._done = new Promise((res, rej) => {
      setTimeout(() => {
        let ok = true, err = null;
        try {
          const mm = /^data:image\/png;base64,([\s\S]*)$/.exec(this._src);
          if (!mm) throw new Error("harness Image: only data:image/png;base64 src is supported");
          this._px = decodePng(Buffer.from(mm[1], "base64"));
          this.width = this.naturalWidth = this._px.w;
          this.height = this.naturalHeight = this._px.h;
          this.complete = true;
        } catch (e) { ok = false; err = e; }
        const ev = { type: ok ? "load" : "error", target: this };
        const h = ok ? this.onload : this.onerror;
        if (typeof h === "function") h.call(this, ev);
        (this._l[ev.type] || []).forEach((f) => f(ev));
        if (ok) res(); else rej(err);
      }, 0);
    });
    this._done.catch(() => {});
  }
}

const r3 = (v) => Math.round(v * 1000) / 1000;

// Программный 2D-контекст: drawImage (translate/scale/rotate/setTransform, ближайший
// сосед, source-over), clearRect, getImageData/putImageData/createImageData.
// Остальные методы рисования — пустышки. Журнал drawImage — в `.log` (для основной
// канвы отдаётся тесту: куда и какой слой положили).
function makeCtx2d(node) {
  let W = -1, H = -1, buf = null;
  const ensure = () => {
    const w = node.width | 0, h = node.height | 0;
    if (!buf || w !== W || h !== H) { W = w; H = h; buf = new Uint8ClampedArray(Math.max(0, w * h * 4)); }
  };
  let m = [1, 0, 0, 1, 0, 0];
  const stack = [];
  const mul = (a, b) => [
    a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
    a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
    a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5],
  ];
  const pt = (u, v) => [m[0] * u + m[2] * v + m[4], m[1] * u + m[3] * v + m[5]];
  const log = [];
  const c = {
    canvas: node,
    log,
    fillStyle: "#000", strokeStyle: "#000", lineWidth: 1, globalAlpha: 1, font: "10px sans-serif",
    imageSmoothingEnabled: true, textAlign: "start", textBaseline: "alphabetic", lineDashOffset: 0,
    save() { stack.push(m.slice()); },
    restore() { if (stack.length) m = stack.pop(); },
    translate(x, y) { m = mul(m, [1, 0, 0, 1, x, y]); },
    scale(x, y) { m = mul(m, [x, 0, 0, y, 0, 0]); },
    rotate(a) { const s = Math.sin(a), co = Math.cos(a); m = mul(m, [co, s, -s, co, 0, 0]); },
    transform(a, b, cc, d, e, f) { m = mul(m, [a, b, cc, d, e, f]); },
    setTransform(a, b, cc, d, e, f) {
      m = a && typeof a === "object" ? [a.a, a.b, a.c, a.d, a.e, a.f] : [a, b, cc, d, e, f];
    },
    resetTransform() { m = [1, 0, 0, 1, 0, 0]; },
    getTransform() { return { a: m[0], b: m[1], c: m[2], d: m[3], e: m[4], f: m[5] }; },
    measureText() { return { width: 0 }; },
    createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
    getImageData(x, y, w, h) {
      ensure();
      const out = new Uint8ClampedArray(w * h * 4);
      const x0 = Math.trunc(x), y0 = Math.trunc(y);
      for (let j = 0; j < h; j++) {
        for (let i = 0; i < w; i++) {
          const sx = x0 + i, sy = y0 + j;
          if (sx < 0 || sy < 0 || sx >= W || sy >= H) continue;
          const si = (sy * W + sx) * 4, di = (j * w + i) * 4;
          out[di] = buf[si]; out[di + 1] = buf[si + 1]; out[di + 2] = buf[si + 2]; out[di + 3] = buf[si + 3];
        }
      }
      return { width: w, height: h, data: out };
    },
    putImageData(id, x, y) {
      ensure();
      for (let j = 0; j < id.height; j++) {
        for (let i = 0; i < id.width; i++) {
          const dx = Math.trunc(x) + i, dy = Math.trunc(y) + j;
          if (dx < 0 || dy < 0 || dx >= W || dy >= H) continue;
          const si = (j * id.width + i) * 4, di = (dy * W + dx) * 4;
          for (let k = 0; k < 4; k++) buf[di + k] = id.data[si + k];
        }
      }
    },
    clearRect(x, y, w, h) {
      ensure();
      const cs = [pt(x, y), pt(x + w, y), pt(x, y + h), pt(x + w, y + h)];
      const xs = cs.map((p) => p[0]), ys = cs.map((p) => p[1]);
      const x0 = Math.max(0, Math.floor(Math.min(...xs))), x1 = Math.min(W, Math.ceil(Math.max(...xs)));
      const y0 = Math.max(0, Math.floor(Math.min(...ys))), y1 = Math.min(H, Math.ceil(Math.max(...ys)));
      for (let yy = y0; yy < y1; yy++) for (let xx = x0; xx < x1; xx++) {
        const i = (yy * W + xx) * 4;
        buf[i] = buf[i + 1] = buf[i + 2] = buf[i + 3] = 0;
      }
    },
    drawImage(img, ...a) {
      const src = img && (img._px || (img._pixels && img._pixels()));
      if (!src) return; // не загруженная картинка ничего не рисует — как в браузере
      ensure();
      let sx = 0, sy = 0, sw = src.w, sh = src.h, dx, dy, dw, dh;
      if (a.length === 2) { [dx, dy] = a; dw = src.w; dh = src.h; }
      else if (a.length === 4) { [dx, dy, dw, dh] = a; }
      else { [sx, sy, sw, sh, dx, dy, dw, dh] = a; }
      const cs = [pt(dx, dy), pt(dx + dw, dy), pt(dx, dy + dh), pt(dx + dw, dy + dh)];
      const xs = cs.map((p) => p[0]), ys = cs.map((p) => p[1]);
      const bx0 = Math.min(...xs), bx1 = Math.max(...xs), by0 = Math.min(...ys), by1 = Math.max(...ys);
      log.push({ src: img.src || "canvas", bbox: [r3(bx0), r3(by0), r3(bx1), r3(by1)] });
      if (log.length > 4000) log.shift();
      const det = m[0] * m[3] - m[1] * m[2];
      if (!det || !dw || !dh) return;
      const px0 = Math.max(0, Math.floor(bx0)), px1 = Math.min(W, Math.ceil(bx1));
      const py0 = Math.max(0, Math.floor(by0)), py1 = Math.min(H, Math.ceil(by1));
      const ga = typeof c.globalAlpha === "number" ? c.globalAlpha : 1;
      for (let y = py0; y < py1; y++) {
        for (let x = px0; x < px1; x++) {
          const X = x + 0.5 - m[4], Y = y + 0.5 - m[5];
          const u = (m[3] * X - m[2] * Y) / det, v = (-m[1] * X + m[0] * Y) / det;
          if (u < dx || u >= dx + dw || v < dy || v >= dy + dh) continue;
          const spx = Math.min(src.w - 1, Math.max(0, Math.floor(sx + ((u - dx) / dw) * sw)));
          const spy = Math.min(src.h - 1, Math.max(0, Math.floor(sy + ((v - dy) / dh) * sh)));
          const si = (spy * src.w + spx) * 4, di = (y * W + x) * 4;
          const sa = (src.data[si + 3] / 255) * ga;
          if (sa <= 0) continue;
          const da = buf[di + 3] / 255;
          const oa = sa + da * (1 - sa);
          for (let k = 0; k < 3; k++) buf[di + k] = (src.data[si + k] * sa + buf[di + k] * da * (1 - sa)) / oa;
          buf[di + 3] = oa * 255;
        }
      }
    },
  };
  for (const n of ["fillRect", "strokeRect", "beginPath", "closePath", "moveTo", "lineTo", "arc", "arcTo",
    "rect", "ellipse", "fill", "stroke", "clip", "fillText", "strokeText", "setLineDash",
    "quadraticCurveTo", "bezierCurveTo"]) c[n] = () => {};
  node._pixels = () => { ensure(); return { w: W, h: H, data: buf }; };
  node._ctxLog = () => log;
  return c;
}

function attachCanvas(node, w, h) {
  node.width = w;
  node.height = h;
  Object.defineProperty(node, "clientWidth", { get() { return node.width; } });
  Object.defineProperty(node, "clientHeight", { get() { return node.height; } });
  node.getBoundingClientRect = () => ({
    left: 0, top: 0, x: 0, y: 0, right: node.width, bottom: node.height, width: node.width, height: node.height,
  });
  let cx = null;
  node.getContext = (kind) => (kind === "2d" ? (cx ||= makeCtx2d(node)) : null);
  node._ctxLog = () => (cx ? cx.log : []);
}

// Записи присваивания `.innerHTML =` на ЛЮБОМ узле (созданном через
// getElementById ИЛИ createElement) — Task 1.2h ит.2, Н3: тест на
// экранирование `layer.name` проверяет, что вредоносная строка никогда не
// попадает в этот сток, а не только что страница не падает.
const innerHtmlWrites = [];
function makeEl(id, tag) {
  const node = {
    id: id || "",
    tagName: (tag || "div").toUpperCase(),
    // presetZoom — числовое поле «масштаб, %», в разметке значение по умолчанию 100
    // (контракт 1.3h-b); прочим неизвестным id по-прежнему "101.1".
    value: id === "freqNum" || id === "freq" ? "25" : id === "presetZoom" ? "100" : "101.1",
    checked: false,
    textContent: "",
    className: "",
    children: [],
    style: {},
    dataset: {},
    h: {},
    appendChild(child) {
      // Реальный DOM: строит дерево. Здесь достаточно не падать — getElementById
      // остаётся независимым реестром по id (находка ревью 5.3a), поэтому дерево
      // самих объектов никто не обходит (кроме 1.3h-b: строки #presetLayers).
      this.children.push(child);
      return child;
    },
    removeChild(child) {
      const i = this.children.indexOf(child);
      if (i >= 0) this.children.splice(i, 1);
      return child;
    },
    setAttribute() {},
    getAttribute() { return null; },
    focus() {},
    blur() {},
    setPointerCapture() {},
    releasePointerCapture() {},
    addEventListener(t, f) {
      (this.h[t] ||= []).push(f);
    },
    // fire(t, ev): ev дописывается в объект события (offsetX/offsetY, key, ...);
    // без ev — как раньше {type}. Task 1.3h-b: указатель и клавиатура.
    fire(t, ev) {
      const e = Object.assign({ type: t, target: node, preventDefault() {}, stopPropagation() {} }, ev || {});
      (this.h[t] || []).forEach((f) => f(e));
      // Страница вешает часть обработчиков свойством (`el.onchange = ...`), а не
      // addEventListener — без этой ветки сценарий «сменили частоту» молча ничего
      // не звал бы и тест был бы вакуумным.
      if (typeof this["on" + t] === "function") this["on" + t](e);
    },
  };
  node.classList = {
    _t: () => String(node.className).split(/\s+/).filter(Boolean),
    add(c) { const t = this._t(); if (!t.includes(c)) t.push(c); node.className = t.join(" "); },
    remove(c) { node.className = this._t().filter((x) => x !== c).join(" "); },
    toggle(c, force) {
      const want = force === undefined ? !this._t().includes(c) : !!force;
      if (want) this.add(c); else this.remove(c);
      return want;
    },
    contains(c) { return this._t().includes(c); },
  };
  if (tag === "canvas") attachCanvas(node, id === "presetCanvas" ? 640 : 300, id === "presetCanvas" ? 480 : 150);
  let _innerHTML = "";
  Object.defineProperty(node, "innerHTML", {
    get() {
      return _innerHTML;
    },
    set(v) {
      _innerHTML = v;
      node.children = []; // как в DOM: присваивание innerHTML сносит потомков
      innerHtmlWrites.push(String(v));
    },
  });
  return node;
}
const els = {};
function el(id) {
  return (els[id] ||= makeEl(id, id === "presetCanvas" ? "canvas" : ""));
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
  // Task 1.2h ит.2, Н3: renderPresetLayers строит строку слоя через
  // document.createElement + textContent (не innerHTML) — харнессу нужен сам
  // createElement, иначе loadPreset() падает при первом же непустом preset.get.
  // Узел БЕЗ id (в отличие от getElementById) не кэшируется в `els` — он не
  // адресуется по id со страницы, только через appendChild родителя.
  createElement(tag) {
    return makeEl("", tag);
  },
  createTextNode(text) {
    return { nodeValue: text, textContent: text };
  },
  addEventListener(t, f) {
    (this.h[t] ||= []).push(f);
  },
  fire(t, ev) {
    // ev — поля события (key/shiftKey для keydown, Task 1.3h-b); без него — как раньше.
    const e = ev ? Object.assign({ type: t, preventDefault() {}, stopPropagation() {} }, ev) : {};
    (this.h[t] || []).forEach((f) => f(e));
  },
};
// Журнал fetch страницы: маршрут, метод, тело, HTTP-статус (Task 1.3h-b: сколько раз
// страница просила раскладку, с каким телом, каким кодом ответил плагин).
const fetchLog = [];
const ctxFetch = (p, o) => {
  const entry = { path: p, method: (o && o.method) || "GET", body: o && o.body ? String(o.body) : null, status: null };
  fetchLog.push(entry);
  return fetch(base + p, o).then((r) => {
    entry.status = r.status;
    return r;
  });
};
const ctx = {
  document: doc,
  window: win,
  fetch: ctxFetch,
  setInterval,
  clearInterval,
  setTimeout,
  clearTimeout,
  requestAnimationFrame: (f) => setTimeout(() => f(Date.now()), 16),
  cancelAnimationFrame: (id) => clearTimeout(id),
  Image: ImageStub,
  atob: (v) => Buffer.from(String(v), "base64").toString("binary"),
  btoa: (v) => Buffer.from(String(v), "binary").toString("base64"),
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
  } else if (scenario === "freq_change") {
    // Кнопку «Пуск» НЕ нажимаем: проверяем ровно то, что смена частоты сама доходит
    // до ленты, пока она едет (владелец 2026-09-23: «гц не регулируются»).
    // Ждём хотя бы один цикл опроса статуса — из него страница узнаёт, едет ли лента.
    await sleep(400);
    el("freqNum").value = "15";
    el("freq").fire("change");
    await sleep(300);
  } else if (scenario === "status_error") {
    await sleep(400); // >= один цикл опроса (250 мс)
    process.stdout.write(JSON.stringify({ statusText: el("status").textContent }));
  } else if (scenario === "truth_line") {
    // Приёмка 5.3a §2: опрос /api/truth раз в 1000 мс, читаем отданный текст #truth.
    await sleep(1200); // >= один цикл опроса правды (1000 мс)
    process.stdout.write(JSON.stringify({ truthText: el("truth").textContent }));
  } else if (scenario === "truth_unavailable") {
    // §2 «Независимость разделов»: правда недоступна, журнал — как раньше.
    await sleep(1200);
    process.stdout.write(
      JSON.stringify({ truthText: el("truth").textContent, journalText: el("journal").textContent })
    );
  } else if (scenario === "truth_reset") {
    // §2: кнопка btnTruthReset -> POST /api/truth/reset, сразу повторный опрос.
    await sleep(1200); // дождаться первого опроса, чтобы кнопка не читала пустой раздел
    el("btnTruthReset").fire("click");
    await sleep(300); // время на POST + повторный GET /api/truth
    process.stdout.write(JSON.stringify({ truthText: el("truth").textContent }));
  } else if (scenario === "wire" || scenario === "wire_acc") { // wire_acc — имя из приёмки тестера 6.2
    // Раздел «Что дошло до робота»: опрос /api/journal раз в 1000 мс, читаем #wire.
    await sleep(1200);
    process.stdout.write(JSON.stringify({ wireText: el("wire").textContent }));
  } else if (scenario === "preset_edit_save") {
    // Task 1.2h, приёмка H7 / сценарии П1-П2: открыть (первый GET /api/preset
    // при загрузке страницы), править offset_px первого слоя, «сохранить».
    // Id полей ("layer0_offset_x", "btnPresetSave") — догадка тестера, контракт
    // 1.2h не даёт литералов разметки редактора (см. test_acceptance_1_2h_preset.py).
    await sleep(300); // время на начальный preset.get при загрузке страницы
    el("layer0_offset_x").value = "15";
    el("layer0_offset_x").fire("change");
    el("btnPresetSave").fire("click");
    await sleep(300); // время на POST /api/preset/commit
  } else if (scenario === "preset_edit_conflict_then_retry") {
    // Task 1.2h, приёмка H8 / сценарий П5: commit -> conflict -> правка не
    // теряется -> повторное «сохранить» уходит с current_rev как base_rev.
    await sleep(300);
    el("layer0_offset_x").value = "15";
    el("layer0_offset_x").fire("change");
    el("btnPresetSave").fire("click"); // первый save -> conflict (двойник настроен в Python-тесте)
    await sleep(300);
    const offsetXAfterConflict = el("layer0_offset_x").value;
    el("btnPresetSave").fire("click"); // повторный save -> должен уйти с current_rev как base_rev
    await sleep(300);
    process.stdout.write(JSON.stringify({ offsetXAfterConflict }));
  } else if (scenario === "scene_overloaded") {
    // Ф6.1b: клик «Выпусти брак» на overloaded (двойник отвечает overloaded на
    // scene.defect_now) -> страница обязана повторить тот же POST ровно один раз.
    el("btnSceneDefectNow").fire("click");
    await sleep(300); // время на POST + повторный POST
  } else if (scenario === "scene_pause_sync") {
    // Ф6.1b, находка ревью: галка паузы идёт за ДВИЖКОМ (/api/scene), а не за нажатием.
    await sleep(1200);
    process.stdout.write(JSON.stringify({ pauseChecked: el("scenePause").checked }));
  } else if (scenario === "scene_error_when_down") {
    // Ф6.1b, находка ревью итерации 2: отказ виден и когда сама сцена не отвечает.
    el("btnSceneDefectRate").fire("click");
    await sleep(1400); // дать опросу перерисовать строку хотя бы раз
    process.stdout.write(JSON.stringify({ sceneText: el("sceneStatus").textContent }));
  } else if (scenario === "scene_error_text") {
    // Ф6.1b, находка ревью: отказ сцены виден оператору в строке состояния.
    // Читаем сразу после клика, но опрос отказ НЕ затирает — он держится в `sceneError`
    // до следующей принятой заявки (ревью итерации 2 проверило это на 2600 мс).
    el("btnSceneDefectRate").fire("click");
    await sleep(200);
    process.stdout.write(JSON.stringify({ sceneText: el("sceneStatus").textContent }));
  } else if (scenario === "scene_status") {
    // Ф6.1b §2: опрос /api/scene тем же таймером, что /api/truth (1000 мс).
    await sleep(1200);
    process.stdout.write(JSON.stringify({ sceneText: el("sceneStatus").textContent }));
  } else if (scenario === "preset_undo_restores_field") {
    // Task 1.2h ит.2, Н2: правка поля БЕЗ единого «Сохранить», затем «Отмена» —
    // обязана вернуть прежнее значение (сценарий П6). before/afterUndo должны
    // совпасть; до этой правки стек пополнялся только перед commit, поэтому
    // здесь при первой правке было пусто и «Отмена» ничего не делала.
    await sleep(300); // время на начальный preset.get при загрузке страницы
    const before = el("layer0_offset_x").value;
    el("layer0_offset_x").value = "15";
    el("layer0_offset_x").fire("change");
    el("btnPresetUndo").fire("click");
    await sleep(50);
    process.stdout.write(JSON.stringify({ before, afterUndo: el("layer0_offset_x").value }));
  } else if (scenario === "preset_layer_name_escaped") {
    // Task 1.2h ит.2, Н3: имя слоя с тегом не должно попасть ни в один
    // .innerHTML сырым (перехват записи — innerHtmlWrites). revText в выводе
    // доказывает, что страница ДОШЛА до рендера, а не тихо упала до записи
    // (иначе innerHtmlLeaked=false был бы вакуумным «доказательством»).
    await sleep(300);
    const leaked = innerHtmlWrites.some((v) => v.indexOf("onerror") !== -1);
    process.stdout.write(
      JSON.stringify({ innerHtmlLeaked: leaked, revText: el("presetRev").textContent })
    );
  } else if (scenario === "preset_state_probe") {
    // Task 1.2h ит.2, Н4: engine/rev — состояние после начального preset.get,
    // без правок. Один сценарий, три конфигурации preset.get со стороны Python.
    await sleep(300);
    process.stdout.write(
      JSON.stringify({
        engineWarnText: el("presetEngineWarn").textContent,
        revText: el("presetRev").textContent,
        saveDisabled: !!el("btnPresetSave").disabled,
      })
    );
  } else if (scenario === "stub_selfcheck") {
    // Task 1.3h-b: самопроверка заглушек харнесса БЕЗ страницы — getImageData
    // отвечает пикселями нарисованного PNG (не «всегда непрозрачно»), матрица
    // translate/scale учитывается. Вход — JSON {имя: {url, probes: [[x, y], ...]}}.
    const spec = JSON.parse(process.argv[4] || "{}");
    const res = {};
    for (const [name, item] of Object.entries(spec)) {
      const img = new ImageStub();
      img.src = item.url;
      await img._done;
      const alphaAt = (draw, cw, ch, probes) => {
        const c = doc.createElement("canvas");
        c.width = cw;
        c.height = ch;
        const g = c.getContext("2d");
        draw(g);
        return probes.map(([x, y]) => g.getImageData(x, y, 1, 1).data[3]);
      };
      res[name] = {
        w: img.width,
        h: img.height,
        plain: alphaAt((g) => g.drawImage(img, 0, 0), img.width, img.height, item.probes),
        shifted: alphaAt(
          (g) => { g.translate(10, 10); g.drawImage(img, 0, 0); },
          img.width + 20, img.height + 20, item.probes.map(([x, y]) => [x + 10, y + 10])
        ),
        scaled: alphaAt(
          (g) => g.drawImage(img, 0, 0, img.width * 2, img.height * 2),
          img.width * 2, img.height * 2, item.probes.map(([x, y]) => [x * 2, y * 2])
        ),
      };
    }
    process.stdout.write(JSON.stringify(res));
  } else if (scenario === "canvas_script") {
    // Task 1.3h-b: сценарий из JSON-шагов (argv[4]) над НАСТОЯЩЕЙ страницей.
    // Координаты `at`/`from`/`to` — смещения в пикселях канвы ОТ ЦЕНТРА канвы.
    // Итог — JSON: снимки (snap), результаты ожиданий, лог drawImage основной канвы,
    // лог fetch маршрутов /api/preset*. Провал ожидания прерывает сценарий (aborted),
    // страница при этом не роняет процесс — тест сам скажет, чего не хватило.
    setTimeout(() => {
      process.stdout.write(JSON.stringify({ watchdog: true }));
      process.exit(3);
    }, 20000).unref();
    const steps = JSON.parse(process.argv[4] || "[]");
    const cv = el("presetCanvas");
    const out = { snaps: {}, waits: [], aborted: null };
    let held = null;
    const mask = (b) => (b === 0 ? 1 : b === 2 ? 2 : b === 1 ? 4 : 0);
    const ptr = (at, extra) => {
      const x = cv.width / 2 + at[0], y = cv.height / 2 + at[1];
      return Object.assign(
        { pointerId: 1, pointerType: "mouse", isPrimary: true, shiftKey: false,
          offsetX: x, offsetY: y, clientX: x, clientY: y, pageX: x, pageY: y, x, y, layerX: x, layerY: y },
        extra
      );
    };
    const selectedNames = () =>
      (el("presetLayers").children || [])
        .filter((r) => String(r.className).split(/\s+/).includes("selected"))
        .map((r) => (r.children[0] && r.children[0].textContent) || "");
    const layoutCount = () => fetchLog.filter((e) => e.path === "/api/preset/layout" && e.method === "POST").length;
    const press = (at, button) => {
      held = button || 0;
      cv.fire("pointerdown", ptr(at, { button: held, buttons: mask(held) }));
    };
    const move = (at) => cv.fire("pointermove", ptr(at, { button: -1, buttons: held === null ? 0 : mask(held) }));
    const release = (at) => {
      cv.fire("pointerup", ptr(at, { button: held === null ? 0 : held, buttons: 0 }));
      held = null;
    };
    for (let i = 0; i < steps.length && out.aborted === null; i++) {
      const st = steps[i];
      if (st.op === "sleep") await sleep(st.ms);
      else if (st.op === "wait_drawn") {
        // ждём, пока на ОСНОВНУЮ канву drawImage'нуто >= n разных картинок слоёв
        const deadline = Date.now() + 2500;
        let ok = false;
        while (Date.now() < deadline) {
          if (new Set(cv._ctxLog().map((e) => e.src)).size >= st.n) { ok = true; break; }
          await sleep(20);
        }
        out.waits.push({ n: st.n, ok, seen: new Set(cv._ctxLog().map((e) => e.src)).size });
        if (!ok) out.aborted = i;
        else await sleep(30);
      } else if (st.op === "zoom") {
        el("presetZoom").value = String(st.pct);
        el("presetZoom").fire("input");
        el("presetZoom").fire("change");
      } else if (st.op === "press") { press(st.at, st.button); await sleep(5); }
      else if (st.op === "move") { move(st.at); await sleep(8); }
      else if (st.op === "release") { release(st.at); await sleep(5); }
      else if (st.op === "click") { press(st.at, 0); await sleep(5); release(st.at); await sleep(5); }
      else if (st.op === "drag") {
        press(st.from, st.button);
        await sleep(8);
        const n = st.steps || 4;
        for (let k = 1; k <= n; k++) {
          move([st.from[0] + ((st.to[0] - st.from[0]) * k) / n, st.from[1] + ((st.to[1] - st.from[1]) * k) / n]);
          await sleep(8);
        }
        release(st.to);
        await sleep(5);
      } else if (st.op === "key") {
        doc.fire("keydown", {
          key: st.key, code: st.key, shiftKey: !!st.shift, ctrlKey: false, altKey: false, metaKey: false,
          repeat: false, target: cv,
        });
        await sleep(40);
      } else if (st.op === "press_button") { el(st.id).fire("click"); await sleep(30); }
      else if (st.op === "set_field") {
        el(st.id).value = String(st.value);
        el(st.id).fire("change");
        await sleep(10);
      } else if (st.op === "snap") {
        const fields = {};
        (st.ids || []).forEach((id) => { fields[id] = el(id).value; });
        out.snaps[st.tag] = {
          fields,
          selected: selectedNames(),
          error: el("presetLayoutError").textContent,
          rev: el("presetRev").textContent,
          layoutCount: layoutCount(),
        };
      }
    }
    out.canvas = [cv.width, cv.height];
    out.draws = cv._ctxLog().slice(-300);
    out.fetchLog = fetchLog.filter((e) => e.path.indexOf("/api/preset") === 0);
    // лог может быть большим: process.exit до сброса канала обрезал бы вывод (Windows, pipe)
    await new Promise((r) => process.stdout.write(JSON.stringify(out), r));
  }
  process.exit(0);
}

run();
