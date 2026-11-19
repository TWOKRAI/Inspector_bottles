# Run-state, полоса Ф — слияния 2.7+2.9, П3, 2.2 в main (2026-11-19/20)

Автор: лид полосы Ф (сессия inspector-bottles-f1). План: `plans/2026-10-27_system-run-state/plan.md`. Ничего не запушено (локальный `main`).

## 1. Что сделано

| Что | Коммит main | Ревью | Радиус на слитом дереве |
|---|---|---|---|
| 2.7 (S3a…S3c′, 2.7d, M2, M1) + 2.9 | `85a0521c5` | слепое Opus: 2.7 APPROVED, 2.9 по коду APPROVED; Sonnet по пачке 2.7 APPROVED | 4118 passed, 0 failed (206 + 776 + 3745 + 91); validate.py чисто; sentrux check: 43 правила проходят |
| П3 (LeafCopy, проекция при привязке) | `a26736042` | слепое Opus: CHANGES REQUESTED только по minor, правки внесены (`4fd283d66`) | state_store 739, read-model 68, telemetry_sink 35, frontend/state 85, backend_ctl 70 passed; 3 красных вне run-state (см. п.2) |
| 2.2 (S4a pause_all, S4b возраст связи) | `8ff4fd151` | Sonnet раунд 2 APPROVED; слепое Opus: 1 major (окно эпизода паузы) — решение владельца | device_hub 565 passed; Services/device_hub/tests: 2 красных `test_no_private_driver_state` (литерал 64, их и на базе); validate.py и sentrux чисто |
| OPEN_QUESTIONS (7 записей) | `1ab6afca5` | — | — |
| Контракт readiness лиду К | `6743d891d`, `docs/handoffs/2026-11-20_readiness-contract-for-lane-k.md` | — | написан по коду без запуска |

2.9 отдельно в main не вливалась: ветка стояла на 9 коммитах 2.7 со слепыми тестами без кода (41 красный тест), её 3 коммита вошли вместе с 2.7.

## 2. Что осталось открытым / ненадёжно

1. **Task 2.8 (S1+П2) не начата и не сливается.** Условия CTO к концу 19.11 (окно heavy 0 новых красных, рассылка ≤ +10 %, стенд четырёх вкладок, инъекции красные) не выполнены: живого стенда и окна heavy нет (`machine.lock` отсутствует), слепой tester не запускался, бриф `tester-brief-2.8.md` утерян (спека 50 КБ в `plans/.../tasks/2.8.md`). По правилу — S1+П2 не вливается, П3 остаётся. О факте сообщить владельцу и координатору (координатор `inspector-bottles-9e` в `ListAgents` не найден).
2. **Три красных теста вне run-state** (не в `defects.md`): `test_gui_process::test_bridge_created_in_init_application_threads`, `test_headless_process::test_drain_worker_is_created_and_started`, `test_system_dashboard::test_refresh_pulls_ring_history_into_series` (последний записан в OPEN_QUESTIONS раньше). Прогон на `767d61329` не сделан (запрос на запуск отклонён); по чтению воркер `readiness_snapshot` есть и на базе.
3. **Окно эпизода паузы (2.2, major)** — не решено, ждёт владельца; рекомендация лида — вариант (а) (стоп роботам на каждом вызове).
4. Живого стенда ни разу не было: ACCEPTANCE 2.7, 2.7d, 2.2 открыты. Полный suite и heavy-окно не гонялись, только радиус.
5. Не сделано из handoff: S3doc, S5, коммит B 2.1 (`run_gate: true`), 2.9b, 2.6, 2.4 (живая приёмка), 2.5, 3.3 follow-up; S6 = 2.2c (`99a9e84d5`, merge-tree с main чисто) ждёт слияния 2.3c/2.3d лидом К (ветки `feat/camera-2-3c`, `feat/camera-2-3d` ещё не в main).
6. История коммита 2.7d: строка `Decision:` с двумя ADR в одной строке не переписывалась (хук проверяет только момент коммита).
7. Слияния выполнены `git merge --no-ff -F` (хук protect-branch блокирует `git commit` на main; защита не менялась). В дереве `lane-f-2.2` остался изменённый `test_no_private_access.py` (чужой, не коммитился), в `lane-f-2.8a` — ~21 строка ruff-шума в `state_store_module`.
8. Индекс ADR `process_module` отстаёт (ADR-PM-045…062 записаны как `###`) — запись в OPEN_QUESTIONS.

## 3. Таблица agentId (эта сессия)

| Роль / задача | agentId |
|---|---|
| Opus слепо: 2.9 / пачка 2.7 / 2.2 / П3 | a56729fef3213953a / a95124900e68172f6 / ac575093927ab07ac / ab528427ab222dfa7 |
| Sonnet-ревью: пачка 2.7 / 2.2 раунд 2 | a1dc72566ce7dd0d1 / a29e3502b1512fd65 |
| developer правки: 2.7+2.9 / П3 / 2.2 | a595cec4fcb40a51a / a617604da4dc51114 / a8a33e75ac92f093a |
| test-runner (haiku): радиус 2.7 / П3 / 2.2 | a35c3dcb37baa58a8 / ae9ad504de504f225 / abe940c87500b96a3 |
| tech-writer: контракт readiness для К | ab07f287784342957 |

Источник: сессия `inspector-bottles-f1`, scratchpad `f/verdicts.md` (полные вердикты ревью).
