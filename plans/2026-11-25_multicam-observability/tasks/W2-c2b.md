# Task W2-c2b: режим плашки на каждом экране из рецепта, порог N с, перенос строки (поверх `dev/w2-c2`)

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Module contract:** public-api-change (`DisplayDefinition`: четыре необязательных поля) + impl-only (`app.py`, `image_panel/*`)
- **Dependencies:** W2-c2 (ветка `dev/w2-c2`, `d0a98012b` + `20899db90`, не слита). Писать на той же ветке. В `main` W2-c2 входит только вместе с этой задачей (П6).
- **Gate:** `machine_gate.sh light <session>` по TESTS; радиус W2-c2 и `multiprocess_prototype/adapters/tests/test_recipe_canonical.py`
- **Files:** `multiprocess_prototype/frontend/app.py`, `multiprocess_prototype/frontend/widgets/image_panel/{recipe_displays.py,display_slot.py}`, `multiprocess_prototype/domain/entities/display.py`, `multiprocess_prototype/frontend/tests/test_no_signal_plate.py`, `multiprocess_prototype/domain/tests/test_display_plate_fields.py`
- **Acceptance:** блок ACCEPTANCE
- **Handoff:** developer (REDS в брифе, красный прогон до правки src, break-injection) -> reviewer (стадия 5, sonnet)
- **Параллельно с:** W2-t1, W2-t2 (файлы не пересекаются). **Следом:** W2-c3.

Основание: П6, `plate-modes.md` (контракт ключей экрана). На ветке сегодня: порог один на всё приложение (`_NO_SIGNAL_AFTER_S = 2.0`, `app.py:33`, насос `app.py:1166`); плашку получает любой экран, где молчат все отправители (`_on_silence`, `app.py:1143-1160`). Значит, экран камеры по триггеру при стоящей линии покажет ложную плашку. `show_no_signal` (`display_slot.py:110`) без переноса строки — длинный текст обрезан справа. Ключей `plate_*` в `DisplayDefinition` нет (`extra="forbid"`, `domain/entities/display.py:120-124`), поэтому рецепт с ними не проходит `Recipe.from_dict`.

TASK: W2-c2b — режим `plate_mode` на экран (`hold` по умолчанию — плашки нет; `silence` — после `plate_after_s` тишины; `trigger` — пока как `hold`, до W2-c3); перенос строки; поля в схеме   PLAN: plans/2026-11-25_multicam-observability/plan.md (П6)
ROLE: developer
CHAIN: lead -> you -> reviewer ; потребитель: W2-c3
DESIGN (decided by the lead — you type it, you do not derive it):
  1. `domain/entities/display.py`, `DisplayDefinition` — после `crop`, с `FieldMeta`:
     - `plate_mode: str = "hold"` с валидатором `{"hold", "silence", "trigger"}` (как `_validate_fit`);
     - `plate_after_s: int = 2` с валидатором 1..600;
     - `plate_text: str = ""`;
     - `plate_source: str = ""`.
     `extra="forbid"` не трогать.
  2. `recipe_displays.py`, `build_plate_sources` (`:191-236`): в каждую запись добавить `"mode"` и `"after_s"`. Разбор терпимый, без исключения: `mode` вне набора — `"hold"`; `after_s` — `int`, вне 1..600, `bool` или не число — `2`. WARNING один раз на `(display_id, значение)` — как WARNING шаблона. `build_panel_displays` не трогать: `test_recipe_displays.py:46-49` сравнивает словари слотов целиком.
  3. `app.py`:
     - `_NO_SIGNAL_AFTER_S` переименовать в `_PUMP_SILENCE_S = 1.0`: это шаг сообщения насоса, а не порог экрана. Насос сообщает каждую целую секунду тишины от 1 с;
     - в `_on_silence` (ветка с возрастом), до проверки «молчат все»: `src = _plate_sources.get(d, {})`. Если `src.get("mode", "hold") != "silence"` — выйти: `hold` и `trigger` в этой задаче плашку по тишине не ставят. Если `min(возрастов отправителей) < src["after_s"]` — выйти;
     - ветку `age_s is None` (снятие плашки) не менять. Снятие плашек в `_rebuild_displays` не менять;
     - экран без записи в `_plate_sources` (рецепт без `displays`, запасной `main`) -> `hold`: поведение как до W2-c2.
  4. `display_slot.py`:
     - `show_no_signal`: `self._label.setWordWrap(True)`;
     - снятие стиля плашки (`leave_no_signal`, `update_pixmap`, `set_placeholder` при `_plate_shown`): `setWordWrap(False)`, чтобы раскладка слота с кадром не менялась.
     - Строки шаблона по-прежнему делит `\n`. Перенос внутри длинного слова (IP без пробелов) Qt не делает — строка отчёта, не правка.
  5. Тесты ветки (`test_no_signal_plate.py`, 14 тестов) рассчитывают на плашку при любом экране: подменять `_PUMP_SILENCE_S` не нужно. В рецепты-словари тестов, где ждут плашку, дописать `plate_mode: "silence"`, `plate_after_s: 1`. Ожидаемые литералы текста не менять.
FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_prototype/frontend/app.py — шаг насоса, фильтр режима и порога
  2. multiprocess_prototype/frontend/widgets/image_panel/recipe_displays.py — `mode`, `after_s`
  3. multiprocess_prototype/frontend/widgets/image_panel/display_slot.py — перенос строки
  4. multiprocess_prototype/domain/entities/display.py — четыре поля
  5. multiprocess_prototype/frontend/tests/test_no_signal_plate.py — правка рецептов-словарей, новые тесты
  6. multiprocess_prototype/domain/tests/test_display_plate_fields.py — новый (каталог `domain/tests` не проверен: нет — СТОП и вопрос лиду)
REDS (predicted red tests):
  - test_no_signal_plate.py::test_hold_mode_by_default_no_plate (экран без `plate_mode`, отправитель молчит 2,5 с -> 0 вызовов `show_no_signal` с текстом)
  - test_no_signal_plate.py::test_trigger_mode_no_plate_on_silence (`plate_mode "trigger"`, тишина 2,5 с -> 0 вызовов)
  - test_no_signal_plate.py::test_silence_threshold_per_display (`a -> d1` с `after_s 1`, `b -> d2` с `after_s 3`; оба молчат 2,2 с -> плашка на `d1`, на `d2` нет; к 3,3 с — на обоих)
  - test_no_signal_plate.py::test_bad_mode_and_after_fall_back (`build_plate_sources`: `plate_mode "blink"` -> `"hold"`; `plate_after_s 0`, `True`, `"5"` -> `2`; без исключения)
  - test_no_signal_plate.py::test_plate_wraps_and_unwraps (`show_no_signal(<120 символов с пробелами>)` -> `_label.wordWrap()` True; кадр, затем `leave_no_signal` -> False)
  - test_display_plate_fields.py::test_accepts_plate_fields (`from_dict({"id": "d", "plate_mode": "silence", "plate_after_s": 5, "plate_text": "{title}", "plate_source": "cam_0.camera_device"})` проходит)
  - test_display_plate_fields.py::test_rejects_bad_mode_and_range (`plate_mode "blink"`, `plate_after_s 0`, `601` -> `ValidationError`)
  - test_display_plate_fields.py::test_minimize_drops_defaults (`minimize(("displays", 0), <полная форма>)` без ключей `plate_*`)
ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_prototype/frontend/tests/test_no_signal_plate.py multiprocess_prototype/domain/tests/test_display_plate_fields.py` -> exit 0, 22 passed (14 + 5 + 3)
  - `<py> -m pytest -q --tb=short multiprocess_prototype/adapters/tests/test_recipe_canonical.py multiprocess_prototype/frontend/widgets/image_panel/tests` -> красные те же, что в снимке лида до правки
  - `ruff check -q` по шести путям -> 0
  - Break-injection: `mode_ignored` (фильтра режима нет) -> `test_hold_mode…`, `test_trigger_mode…`; `global_threshold` (порог 2 для всех) -> `test_silence_threshold_per_display`; `wrap_kept_after_leave` -> `test_plate_wraps_and_unwraps`; `no_validator` -> `test_rejects_bad_mode_and_range`
  - Лид: qt-mcp `qt_screenshot` слота с длинным шаблоном — текст перенесён, без обрезки справа
TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_prototype/frontend/tests/test_no_signal_plate.py multiprocess_prototype/domain/tests/test_display_plate_fields.py
OUT OF SCOPE: плашка режима `trigger` (W2-c3 по блоку `frame_watch`); «нет связи» (W2-c3); правка режима во вкладке Displays (только YAML); ключи в рецептах `integ` (по слову лида после слияния); `frame_pump.py`.
TRAPS: при `_PUMP_SILENCE_S = 1.0` насос сообщает тишину на 1, 2, 3… с — порог экрана целый, плашка ставится на первом сообщении, где возраст >= `after_s`. Валидатор `plate_after_s` — `int`; `bool` — подкласс `int`, отсечь явно. `QT_QPA_PLATFORM=offscreen`, GUI-тесты не параллельно.
HANDOFF IN: W2-c2 — `build_plate_sources` с `template`, `_on_silence` «молчат все», `show_no_signal`/`leave_no_signal`.
REPORT: STATUS, files, вывод ACCEPTANCE, красные до/после, «Что оставил открытым / ненадёжно».
