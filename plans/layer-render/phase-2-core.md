# Фаза 2 (новая нарезка) — ядро сервиса `Services/layer_render`

Родитель: [plan.md](plan.md), архитектура — [cto-verdict-2026-10-01.md](cto-verdict-2026-10-01.md). Старый
[phase-3.md](phase-3.md) — прежняя нарезка (бывш. 3.1 = 2.1, 3.3 = 2.2, 3.2 = 2.3), тексты переиспользованы.

Итог фазы: примитивы композиции, эффекты, слои, пресет, фабрика, каталог и превью живут в `layer_render`; одна
функция кадра `render_scene`. Это переезд: внешнее поведение не меняется ни на байт. Старые места импорта остаются
реэкспортом (явные имена, не `*`); ни один потребитель вне `Files` не правится.

---

### Task 2.1 — `compose.py` + `io.py` переезжают, старые модули — реэкспорт (бывш. 3.1)

- **Статус:** [IN PROGRESS] волна 2 · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (`layer_render` получает `compose`, `io`; `dataset_gen.core.compose` и
  `imread_unicode`/`imwrite_unicode` в `dataset_gen.core.catalog` — реэкспорт)
- **CHAIN:** `tester`(RED, worktree до кода) → `developer`(GREEN) → инъекции лида → `reviewer`
- **Dependencies:** Ф1 (1.1)
- **Gate:** RED тестера → GREEN; инъекции записаны; `reviewer` APPROVED по SHA; grep рамки — 0

**Goal:** `composite`, `rotate_expand`, `crop_to_alpha`, `fit_longest_side`, `cast_contact_shadow` определены в
`Services/layer_render/compose.py`, `imread_unicode`/`imwrite_unicode` — в `Services/layer_render/io.py`; старые
места — только реэкспорт. Попутно закрыть ниты ревью 1.1 в `background.py`/README.

**Files:**
1. `Services/layer_render/compose.py` (новый) — тело `Services/dataset_gen/core/compose.py` без изменений логики
2. `Services/dataset_gen/core/compose.py` — реэкспорт пяти имён (явный список)
3. `Services/layer_render/io.py` (новый) — `imread_unicode`/`imwrite_unicode`, тело из `dataset_gen/core/catalog.py` без изменений
4. `Services/dataset_gen/core/catalog.py` — импорт двух функций из `layer_render.io` (имена остаются доступны из `catalog`)
5. `Services/layer_render/__init__.py`, `README.md` (таблица Public API), `STATUS.md`
6. `Services/layer_render/background.py` — ниты ревью 1.1: дубль проверки `solid` в `_validate_item` и `SolidFill.__post_init__`
   (оставить одну), лишние `tuple(...)`/`first.copy()` — **только если** тесты алиасинга 1.1 остаются зелёными (ревью 1.1 ит.1
   нашло алиасинг тайлов именно здесь — копию, которая его закрывает, не трогать); README — «цена ∝ min(th, высота кадра)»,
   read-only копия в таблице Public API
- тесты тестера: `Services/layer_render/tests/test_acceptance_2_1_compose_io.py`; старые тесты compose/catalog в `dataset_gen` остаются где есть

**Acceptance:**
- [ ] A1. Для каждого из пяти имён: `Services.dataset_gen.core.compose.<name> is Services.layer_render.compose.<name>`;
      `<name>.__module__ == "Services.layer_render.compose"`. Для `imread_unicode`/`imwrite_unicode`:
      `Services.dataset_gen.core.catalog.<f> is Services.layer_render.io.<f>`, `__module__ == "Services.layer_render.io"`.
- [ ] A2. В `Services/dataset_gen/core/compose.py` нет ни одного `def`/`class` (AST) — только реэкспорт.
- [ ] A3. Ни один модуль `Services/layer_render/**` (кроме `tests/`) не импортирует `Services.dataset_gen`, `Services.line_sim`,
      `Services.ml_train` (AST по всем `.py`, включая `import x` и `from x import y`).
- [ ] A4. `imwrite_unicode` → `imread_unicode` на пути с не-ASCII символами (кириллица) возвращает те же байты BGR/BGRA; флаг
      `cv2.IMREAD_UNCHANGED` по умолчанию сохраняет альфу.
- [ ] A5. Поведение compose не изменилось: на фиксированных входах (seed) результаты `composite`/`rotate_expand`/`crop_to_alpha`/
      `fit_longest_side`/`cast_contact_shadow` из `layer_render` побайтно равны sha256-литералам, снятым тестером **на коде до
      переезда** (литералы в тесте, не вычисленные из тестируемого кода).
- [ ] A6. Золотые эталоны плана ([goldens.md](goldens.md)) — зелёные без правки литералов; тесты 1.1 (`Services/layer_render/tests/`) — зелёные.
- [ ] A7. `sentrux check .` — зелёный; grep рамки (`grep -inE "letter|букв|disk|диск"` по новым файлам механизма) — 0 вне примеров README.
- [ ] A8. Потребители не правились: `git diff --name-only` против базы — только файлы из списка выше + тесты; число строк
      `from Services.dataset_gen.core.compose import` / `imread_unicode` в репо до и после — в отчёт, равны.

**Out of scope:** перевод потребителей (`line_sim`, `ml_train`, плагины) на новые импорты; `effects` (2.2); слои (2.3).
