# Task W2-c2b: режим плашки на каждом экране, порог N с, перенос строки (GUI, поверх `dev/w2-c2`)

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Module contract:** impl-only (`app.py`, `image_panel/*`)
- **Dependencies:** W2-c2 (ветка `dev/w2-c2`, `d0a98012b` + `20899db90`). Схема и каталог дисплеев — W2-c2c: в одном дереве — последовательно (c2c, затем c2b); параллельно — только из отдельной ветки `dev/w2-c2c` от `20899db90`. Живая проверка лида с ключами `plate_*` в рецепте — после W2-c2c (без неё `Recipe.from_dict` их отвергает). В `main` W2-c2 входит только вместе с W2-c2b и W2-c2c (П6).
- **Gate:** `machine_gate.sh light <session>` по TESTS
- **Files:** `multiprocess_prototype/frontend/app.py`, `multiprocess_prototype/frontend/widgets/image_panel/{recipe_displays.py,display_slot.py}`, `multiprocess_prototype/frontend/tests/test_no_signal_plate.py`, `multiprocess_prototype/frontend/tests/test_plate_modes_blind.py` (tester)
- **Handoff:** lead -> tester (слепой, свой файл `test_plate_modes_blind.py`, по ACCEPTANCE и `plate-modes.md`) -> developer (тесты tester-а не правит) -> reviewer (sonnet)

Основание: П6, `plate-modes.md`. На ветке порог один на приложение (`_NO_SIGNAL_AFTER_S = 2.0`, `app.py:33`). Плашку получает любой экран, где молчат все отправители (`_on_silence`, `app.py:1143-1160`). Текст плашки без переноса (`display_slot.py:110`).

TASK: W2-c2b — `plate_mode` экрана: `hold` (умолчание, плашки нет), `silence` (после `plate_after_s` тишины), `trigger` (до W2-c3 — как `hold`); перенос строки   PLAN: plans/2026-11-25_multicam-observability/plan.md (П6)
ROLE: developer
CHAIN: lead -> tester -> you -> reviewer ; потребитель: W2-c3
DESIGN (decided by the lead — you type it, you do not derive it):
  1. `recipe_displays.py`, `build_plate_sources` (`:191-236`): в каждую запись `"mode"` и `"after_s"`.
     - `mode`: `"hold"`, `"silence"`, `"trigger"` возвращаются как есть; ключа нет -> `"hold"`; иное -> `"hold"`.
     - `after_s`: принимается только `type(v) is int` в 1..600 (то же правило, что валидатор домена W2-c2c); ключа нет -> `2`; иное (`True`, `"5"`, `5.0`, `0`, `601`) -> `2`.
     - На каждое негодное значение — WARNING с `display_id` и именем ключа, БЕЗ значения (`"дисплей 'd': негодный plate_mode, взят hold"`); один раз на `(display_id, key, repr(value))`, множество — модульное, как у шаблона.
     - `build_panel_displays` не трогать (`test_recipe_displays.py:46-49`).
  2. `app.py`:
     - `_NO_SIGNAL_AFTER_S` -> `_PUMP_SILENCE_S = 1.0`: это шаг сообщения насоса, а не порог экрана.
     - `_on_silence`, ветка с возрастом, строго в таком порядке:
       1. `_silent_age[key] = age_s`;
       2. `src = _plate_sources.get(d, {})`;
       3. `src.get("mode", "hold") != "silence"` -> return;
       4. `senders = _senders_of(d) | {key}`; не все в `_silent_age` -> return;
       5. `min(_silent_age[s] for s in senders) < src["after_s"]` -> return;
       6. показ, как на ветке.
     - Ветку `age_s is None` и `_rebuild_displays` не менять. Экран без записи (рецепт без `displays`, запасной `main`) -> `hold`.
  3. `display_slot.py`:
     - `show_no_signal`: `self._label.setWordWrap(True)`;
     - все три выхода из плашки — `leave_no_signal`, `update_pixmap`, `set_placeholder` при `_plate_shown` — ставят `setWordWrap(False)`.
  4. Правка тестов ветки (`test_no_signal_plate.py`, 14 тестов; reviewer: с DESIGN без правки 9 failed, 5 passed):
     - убрать `monkeypatch` `_NO_SIGNAL_AFTER_S`;
     - в четыре ожидаемых словаря `build_plate_sources` добавить `"mode": "hold", "after_s": 2`;
     - в `test_two_unbound_senders_on_main…` и `test_scan_found_sender_survives_rebuild` вместо `displays: []` поставить `[_display("main", "main")]` с `plate_mode "silence"`, `plate_after_s 1`. В остальных рецептах-словарях, где ждут плашку, — то же `silence`/1;
     - `_QUIET_S = 2.5`.
     - После правки — 14 passed, затем новые тесты (REDS).
FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_prototype/frontend/app.py
  2. multiprocess_prototype/frontend/widgets/image_panel/recipe_displays.py
  3. multiprocess_prototype/frontend/widgets/image_panel/display_slot.py
  4. multiprocess_prototype/frontend/tests/test_no_signal_plate.py — правка по п.4 и новые тесты
  5. multiprocess_prototype/frontend/tests/test_plate_modes_blind.py — пишет tester, developer только читает
REDS (developer, `test_no_signal_plate.py`; в каждом тесте режима — экран-контроль `c` `silence`/1 в том же прогоне):
  - test_hold_mode_by_default_no_plate (экран без `plate_mode`, тишина 2,5 с -> 0 вызовов; первый вызов контроля — ровно `"<имя c> · № — · —\nнет кадров, 1 с"`)
  - test_trigger_mode_no_plate_on_silence (`plate_mode "trigger"`, `plate_after_s 1`, тишина 2,5 с -> 0 вызовов; контроль как выше)
  - test_no_displays_section_no_plate (`displays: []`; отправитель шлёт один кадр, затем молчит 2,5 с -> 0 вызовов с текстом; шпион `pump._on_silence` видел возраст >= 2; без экрана-контроля)
  - test_silence_threshold_per_display (от проводки, кадров не слать: `d1` `after_s 1`, `d2` `after_s 3`; к 2,2 с — плашка только на `d1`; к 3,3 с — на обоих)
  - test_bad_mode_and_after_fall_back (`"silence"`, `"trigger"`, `1`, `600` — как есть; `"blink"` -> `"hold"`; `0`, `601`, `True`, `"5"`, `5.0` -> `2`; без ключей -> `"hold"`, `2`)
  - test_bad_values_warn_once_without_value (два вызова с `{"id": "warn_d", "plate_mode": "blink_once"}` -> ровно 1 WARNING; есть `warn_d` и `plate_mode`, нет `blink_once`)
  - test_plate_wraps_and_unwraps (`show_no_signal(<120 символов с пробелами>)` -> `wordWrap()` True; затем каждый из трёх выходов — `leave_no_signal` без кадра, `update_pixmap`, `set_placeholder` — даёт False)
ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_prototype/frontend/tests/test_no_signal_plate.py` -> exit 0, 21 passed (14 + 7)
  - `<py> -m pytest -q --tb=short multiprocess_prototype/frontend/tests/test_plate_modes_blind.py` -> exit 0 (число — в отчёте tester-а; каждый тест берёт свои `display_id`: множество WARNING живёт на процесс)
  - `<py> -m pytest -q --tb=short multiprocess_prototype/frontend/widgets/image_panel/tests multiprocess_prototype/frontend/tests/test_frame_intake_wiring.py multiprocess_prototype/frontend/tests/test_deferred_shm_copy.py multiprocess_prototype/frontend/tests/test_deferred_copy_hazards.py multiprocess_prototype/frontend/tests/test_frame_overload_real_objects.py multiprocess_prototype/frontend/tests/test_frame_wiring_sender_vs_display.py` -> exit 0, число — в отчёте
  - `ruff check -q` по пяти путям -> 0
  - Break-injection: `mode_ignored` -> `test_hold…`, `test_trigger…`; `global_threshold` -> `test_silence_threshold…`; `wrap_kept_after_update` -> `test_plate_wraps…`; `value_in_warning` -> `test_bad_values_warn…`; `after_s_bool_accepted` -> `test_bad_mode…`
  - Лид: qt-mcp `qt_screenshot` слота с длинным шаблоном — текст перенесён
TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_prototype/frontend/tests/test_no_signal_plate.py
OUT OF SCOPE: схема `DisplayDefinition`, `DisplaySpec`, вкладка Displays (W2-c2c); плашка режима `trigger` и «нет связи» (W2-c3); форма правки режима; `frame_pump.py`.
TRAPS: насос сообщает тишину на 1, 2, 3… с — порог экрана целый. Перенос внутри длинного слова (IP) Qt не делает — строка отчёта. `QT_QPA_PLATFORM=offscreen`, GUI-тесты не параллельно.
HANDOFF IN: W2-c2 — `build_plate_sources` с `template`, `_on_silence` «молчат все», `show_no_signal`/`leave_no_signal`.
REPORT: STATUS, files, вывод ACCEPTANCE, красные до/после, «Что оставил открытым / ненадёжно».
