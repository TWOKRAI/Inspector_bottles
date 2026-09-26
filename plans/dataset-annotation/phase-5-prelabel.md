# Phase 5 — Подсказки разметки (опционально)

Часть плана [`plan.md`](plan.md). Фаза стартует только по решению владельца после Ф2 и Ф3: подсказки ускоряют
разметку, но без них датасет формируется полностью.

**Что есть для подсказок сегодня (сверено 2026-09-26):**
- Модели детекции нет: `ml_inference` умеет классификацию, `detection` объявлена только литералом типа
  (`Services/ml_inference/core/model_spec.py:17`), постобработки (NMS, декодирование рамок) нет; Ultralytics в стеке
  нет.
- Классический детектор есть: `blob_detector` / `contour_finder` отдают рамки в пайплайне инспекции. Их рамки,
  сохранённые при захвате (Task 3.1, `sources.meta_json.suggested`), — **единственный источник рамок-подсказок,
  доступный без новой модели**.
- Классификатор есть: текущая модель `ml_inference` (ONNX Runtime) может подсказать класс снимка.

**Канон:** как в Ф1.

---

### Task 5.1 — Подсказки от классического детектора

**Level:** Middle · **Assignee:** developer · **Module contract:** impl-only · **Layer:** services
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**DESIGN:**
- `dataset_get` отдаёт `suggested: [{cx, cy, w, h, source}]` из `sources.meta_json` (класса у подсказки нет —
  классический детектор класс дефекта не знает).
- На холсте подсказки — пунктир другого цвета; `Enter` на выбранной — принять текущим классом (операция
  `AnnotationDoc`, отменяется `Ctrl+Z`); `Shift+Enter` — принять все; подсказки в `labels` не пишутся, пока не
  приняты.
- Счётчик в `dataset_stats`: `suggestions_accepted / suggestions_shown` — чтобы решить, полезны ли они (число, не
  впечатление).

**Acceptance criteria:**
- [ ] Снимок с 3 подсказками: `Enter` на одной → в сохранении 1 рамка текущего класса; `Ctrl+Z` → 0.
- [ ] Непринятые подсказки не попадают в `dataset_save_labels` и в экспорт.
- [ ] Снимок без `suggested` → холст работает как в 2.4 (регресс-тест 2.4 зелёный).

**Инъекции:** писать подсказки в `labels` при открытии → тест «непринятые не попадают».
**Dependencies:** 3.1, 2.4.

---

### Task 5.2 — Подсказка класса снимка текущей моделью

**Level:** Middle+ · **Assignee:** developer · **Module contract:** impl-only · **Layer:** services
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**DESIGN:**
- `dataset_suggest_classes {model, filter?}` — долгая задача (шаблон 1.4) в процессе `dataset`: `InferenceEngine`
  из `Services.ml_inference` (импорт ленивый, без ML-стека команда отвечает `{"error": "ml_unavailable"}`), результат
  — `suggested_image_class: {class_name, confidence, model}` в `sources.meta_json` источника `model`.
- Сопоставление меток модели с классами `image` — по имени; метка без класса → пропуск, счётчик `unmapped`.
- В рабочем месте — плашка «модель думает: defect 0.93», `Enter` на плашке — принять.

**Acceptance criteria:**
- [ ] Dummy-ONNX (генерация как в тестах `ml_inference`) на 20 снимках → 20 подсказок, `unmapped == 0` при совпадающих
      именах.
- [ ] Без `onnxruntime` в окружении → `ml_unavailable`, процесс `dataset` жив.
- [ ] Отмена задачи на середине → `cancelled`, уже записанные подсказки остаются.

**Инъекции:** жёсткий импорт `onnxruntime` в модуле плагина → тест «без onnxruntime» (процесс падает на старте).
**Dependencies:** 1.4, 2.4.

---

## Позже (не задачи этого плана)

- **Рамки-подсказки от модели детекции.** Путь: модель, обученная в облаке на экспорте 4.4, → ONNX + sidecar в
  `data/models` → постобработка детекции в `ml_inference` (NMS, декодирование — отдельная задача сервиса
  `ml_inference`) → подсказки как в 5.2. Замыкает цикл «датасет → облако → модель → подсказки», но требует работы в
  `ml_inference`, которой сегодня нет.
- SAM и подобные ассистенты — не планируются (решение лида, `plan.md` → Out of scope).
