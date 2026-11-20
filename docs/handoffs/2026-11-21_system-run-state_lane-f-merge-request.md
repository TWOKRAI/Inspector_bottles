# Запрос на слияние: полоса Ф (run-state) — P3r, R3c, S4b2, docs (2026-11-21)

Автор: лид полосы Ф (сессия inspector-bottles-9a). Отчёт: `docs/reports/2026-11-21_system-run-state_lane-f-p3r-r3c-s4b2.md`. Основа веток — `main` `dc56f14df`; на `e836b2db5` `git merge-tree` без конфликтов у всех четырёх (проверено). Слияние делает координатор; в main я не коммитил. Тема слияния — `feat(...): merge …` (хук режет `merge(...)`) + `Why:`/`Layer:`/`Refs: plans/2026-10-27_system-run-state/plan.md`; сообщение — из файла (`git merge -F -` stdin не читает).

## Порядок (условие Opus-ревью: P3r первым, OQ последним)

| # | Ветка | HEAD | Layer слияния | Что |
|---|---|---|---|---|
| 1 | `fix/run-state-p3-node-read` | `4a8403bf9` | `mixed` (scripts + docs) | P3r (`backend_ctl`), шапки `plan.md`, спеки P3r/R3c/S4b2 |
| 2 | `test/run-state-s4b2` | `50b016570` | `plugins` | тест hub на настоящем драйвере v2, допуск в `tasks/2.7.md` (ссылается на `tasks/S4b2.md` из ветки 1) |
| 3 | `feat/state-proxy-gap-classification` | `43ceeb801` | `framework` | R3c: счётчики/троттлинг разрывов revision |
| 4 | `docs/run-state-oq3` | `git rev-parse docs/run-state-oq3` | `docs` | `OPEN_QUESTIONS` 2026-11-21, отчёт, эта заявка; записи верны только после слияния 1–2 |

**НЕ сливать:** `feat/run-state-2-1-commit-b` (`1fbefc6d8`) — коммит B 2.1 (`run_gate: true`): ждёт живого стенда на сим-линии и слова координатора; golden перегенерировать на новом main.

## Проверки на слитом дереве (прошу прогнать после слияния)
- `backend_ctl/tests` (medium; на ветке 1: 917 passed, 72 skipped), `multiprocess_framework/modules/state_store_module/tests` (medium; 796 passed), `Plugins/hub/device_hub/tests/test_tick_fails_limit_real_driver_v2.py` (light; 11 passed), `python scripts/validate.py`, `python -m scripts.sync --check` — на ветках 1, 3, 4 и их слиянии exit 0.
- Не запускались (окно/класс heavy): `frontend_module/bridge`, `frontend_module/state`, `sentrux check .`, `make gate`.

## Что нужно от координатора
1. Слияние 1→4 (или решение разнести).
2. Решения владельца/CTO списком (не мои): уровень WARNING `diverged` и защита собственных записей клиента в окне ресинка; Р1, Р2, В10, 2.2c; задача на общий помощник чтения узла в framework и починку `io_debug_section.py:250`, `telemetry_view_model.py:258`.
3. Окно стенда на сим-линии: стендовый замер R3c (WARNING за 25 с против базы 106–111) и `heavy`-условия коммита B 2.1.
4. Файл PM (`process_manager_process.py`, C-36/A) — не тронут; слот по слову координатора после дня №1.
