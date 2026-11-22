# Заявка на слияние полосы Ф: RN1 + PS1 — 2026-11-22

Автор: лид полосы Ф. Отчёт: `docs/reports/2026-11-22_system-run-state_lane-f-RN1.md`. В main не коммитил.

| Ветка | База | Коммиты | Что |
|---|---|---|---|
| `docs/run-state-ps1` | main `15858154e` | `18661e679` | `plan.md` 24 925 Б + `decisions.md` (перенос побайтово) |
| `feat/run-state-rn1` | main `15858154e` | `536c60dee` бриф ред. 2, `0a956c638` тесты tester, код (`Layer: mixed`), `ddf230cf3` доки, `86db29dff` правки по ревью, последний — отчёт, заявка, handoff, OPEN_QUESTIONS (docs) | чтение узла из листьев |

Порядок любой (файлы не пересекаются, кроме `docs/claude/OPEN_QUESTIONS.md`, если координатор допишет его сам). Слияние: тема `merge: …` + `Why:`/`Layer:`/`Refs:` из файла (`git merge -F -` stdin не читает); ветка с `feat/` — тип `feat`, не `merge(...)` (память).

Проверки координатора на слитом дереве: `validate.py`; `sync --check`; `plans_progress --check` (0 новых блокирующих); радиус RN1 — `telemetry_readmodel_module/tests`, `frontend_module/tests/state`, `backend_ctl/tests/test_p3r_node_read.py`, `test_replay_live_parity.py`, `test_p3r_replay_await.py`, `test_await_condition.py` (было 299 passed), `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests` (626 passed). Файлы Н (`logger_module/adapters/std_facade.py`, `logger_core.py`, `log_channel.py`, `state_store_module/core/freshness.py`) не тронуты.

Не входит: файл PM, `launcher/spawner.py`, `state_proxy.py`; правки входов без `--autostart` (список с рекомендацией — в отчёте, ждёт слова владельца).

## Что я оставил открытым / ненадёжным
Радиус на слитом дереве не гонял. `test_red7` вероятностный. Ветки `--lane-F-rn1-tester`/`-inj` (detached worktree) — одноразовые, можно удалить `git worktree remove`.
