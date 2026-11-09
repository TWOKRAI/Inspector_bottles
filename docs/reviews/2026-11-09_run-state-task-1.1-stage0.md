# Стадия 0, Task 1.1 (system-run-state), раунд 1 — reviewer Sonnet, HEAD 48ae8f1da

Вердикт: **CHANGES REQUESTED** — блокеров 2, major 7, minor 3. Ревьюер не имеет Write: полный отчёт был в его ответе; здесь — выжимка и решения лида. Токены ревьюера ~0,22M. Пилот «в тень» не засчитан: номера N/6 от координатора нет (его в этой сессии нет) — обычная стадия 0 на Sonnet.

Посылки текста сверены с кодом: `_create_components` `:188`, `ProcessRegistry(` `:214`, шестой позиционный runner — `new_session`, `source_producer.py:143-147` точно; проводка идёт наследованием `Process(kwargs=...)` (Windows-spawn ловушка не нарушена). Сдвиги: `_state_op` `:2076` (образец `:2454-2469`), `generic_process.py:337-354`, `_create_process` вместо `create_process`.

| № | Серьёзность | Суть | Решение лида |
|---|---|---|---|
| F1 | blocker | не назван держатель состояния, нет источника `tick` в 1.1 | принято: `_run_state/_run_since/_run_lock`, единая точка записи `_run_apply` |
| F2 | blocker | `set()/clear()` события не привязаны к замку; инъекция «убрать clear() в STOP» без красного | принято: инвариант `is_set() == (state == running)` в `_run_apply`; RED `…event_follows_state`, race-тест |
| F3 | major | `_state_op` образец устарел, порядок публикации не определён | принято: `_publish_run_state` под `_run_publish_lock`, порядок как `_publish_system_stop` |
| F4 | major | событие `shutdown` никто не подаёт | принято: в 1.1 отказ `shutting_down` у start/stop; подача — в 1.4 п.5 |
| F5 | major | противоречия `transition()` с design §3.2, не вся таблица покрыта | принято: таблица 7×7 литералом, 1.1 реализует всю; строка в design.md §3.2 |
| F6 | major | формы ответов и место `settled` после boot не заданы | принято: литералы status/start/stop, `settled` после `_wait_boot_ready()` |
| F7 | major | шов `run_gated` не определён | принято своим решением: `PluginOrchestrator.config_of(plugin)` (FILES 7), kwarg `run_gated` |
| F8 | major | acceptance без названного счётчика | принято: `cycles`, не `effective_hz`; путь листа — на стенде |
| F9 | major | тесты проводки не ловят снимок значения и фантомный атрибут | принято: два RED проводки (оба фронта, `…sets_run_event_before_initialize`) |
| F10 | minor | `run_gate` читается небезопасно | принято: `is True` + WARNING |
| F11 | minor | устаревшие ссылки внутри 1.1 | принято, заменены |
| F12 | minor | Gate через `machine_gate.sh`, Out of scope | принято |

## Устаревшее вне 1.1 (указатели, не правилось)
- `plan.md:66-67`, `:91`; `tasks/1.4.md:8,18,56` — «`pre_stop.py` ещё не существует» (есть, ADR-PMM-044); 1.4 п.5 («shutdown graceful в running: один проход pre_stop») сталкивается с `_shutdown_graceful` (`:1205`) — решение лида до брифа 1.4. `_run_pre_stop` нельзя брать целиком (`finally → _finish_pre_stop` взводит системные события стопа) — только `run_pre_stop_step`/`_pre_stop_step_outcome`.
- `design.md:3-4,24-25,30` номера строк; `:169` источник `pre_stop` — конфиг PM, не рецепт.
- `tasks/2.1.md:19-22` FILES гадает `app.yaml`: реально `backend/launch.py:748-757` + `backend/config/schemas.py:235`.
- `tasks/2.5.md`: следующий свободный номер ADR — ADR-PMM-045 (сверить перед записью).

## Что осталось открытым / ненадёжно
- Ничего не запускалось: «каждый RED красный до кода» и «инъекция без красного» — выводы чтением.
- Не читаны целиком тела 1.2, 1.3, 1.5, 1.6, 1.8, 1.9, 2.2–2.5, standards.md.
- Путь листа `cycles` в state/`backend_ctl` и синхронность `handle_state_set` (инверсия блокировок) не проверены; публикация вынесена за `_run_lock` по осторожности.
- Форма ответа STOP (`"state": "stopping"` при уже наступившем `ready`) — выбор лида, совпадает с 1.4 п.1.
- Раунд 2 стадии 0 по правленому тексту не проведён.
