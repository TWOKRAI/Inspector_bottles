# Ревью стадии 5 — Task 1.1 system-run-state (reviewer sonnet, HEAD af817927b)

Вердикт: **APPROVED** — блокеров 0, major 0, minor 1, nit 4. Отчёт записал лид (у reviewer нет Write); сжато, находки дословно по смыслу.

Проверил сам: 232 passed (5 файлов задачи) + 74 passed (тест лида, соседи, `test_t54_*`); `sentrux check .` — 43 правила, All rules pass; ruff чист; импортов Services/Plugins/prototype в диффе нет; таблица `transition()` сверена ячейка за ячейкой с DESIGN п.1 (7×7), расхождений нет.

| № | Сер. | Где | Суть | Решение лида |
|---|---|---|---|---|
| M1 | minor | `source_producer.py:154-156` | `self._run_event.is_set()` на каждой итерации, и при `run_gate: false`. 1,96 мкс/вызов (macOS, 200 000). Воспроизведён механизм: читатель убит `SIGKILL` внутри `is_set()` → `set()` у родителя повис в 3 из 5 прогонов; PM держит `_run_lock` → встанет `system.run.*` и обработка `system.shutdown`. Оценка вероятности ≈ 5·10⁻⁵ на одно убийство ребёнка (не измерена в проде). До 1.1 ни один `mp.Event` не опрашивался на каждом кадре | не блокирует слияние; принятый риск записан в `OPEN_QUESTIONS` и в ADR Task 2.5; варианты: (б) опрос реже/кэш на кадр, (в) `mp.RawValue` без замка |
| N1 | nit | `_run_apply` | состояние писалось раньше `set()/clear()`; при исключении события `state == running` при снятом событии | **исправлено** (событие первым, состояние после), тест `test_event_switch_failure_leaves_state_unchanged` красен на старом порядке |
| N2 | nit | `generic_process.py:357` | `run_gated` не-bool (`"false"`, `0`) молча оставляет гейт | в Task 2.1 (проверка типа в схеме плагина) |
| N3 | nit | `_cmd_system_run_stop` | не смотрит на системный стоп (в отличие от `start`) | вместе с окном `start` — Task 1.4 п.5 (подача `shutdown` в машину) |
| N4 | nit | `process_registry.py:372` | `custom.pop("run_event")` — защитный мёртвый код | оставлен (повторяет соседние ключи) |

Наблюдение: ветка гейта не зовёт `record()` — `effective_hz`/`cycle_duration_ms` остаются на последних значениях в `ready` и после STOP (как у `pause_event`); учесть в GUI-задачах (индикатор FPS).
Граница механизма: процессы без `GenericProcess` + `SourceProducer` гейта не видят — при `run_gate: true` кадры у них идут в `ready`; в ADR 2.5 и учесть в Task 2.1.

Не проверял (по словам reviewer): матрицу инъекций и стенд (взял у лида), путь `initialize()`, Windows-spawn, WARNING не-bool `run_gate` в реальном процессе до поднятия логгера, повторный вход в `_run_apply` из обработчика стора, долгое простаивание в `ready`, полные каталоги тестов (семафоры macOS).
