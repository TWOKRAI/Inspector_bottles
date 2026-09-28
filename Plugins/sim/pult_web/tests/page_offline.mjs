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
      // Страница вешает часть обработчиков свойством (`el.onchange = ...`), а не
      // addEventListener — без этой ветки сценарий «сменили частоту» молча ничего
      // не звал бы и тест был бы вакуумным.
      if (typeof this["on" + t] === "function") this["on" + t]({ type: t });
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
  }
  process.exit(0);
}

run();
