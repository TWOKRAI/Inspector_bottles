# gui-graceful-close Task 1.1 — стадия 0, ревью текста задачи, раунд 1

**Дата:** 2026-11-06. **Ревьюер:** `reviewer` sonnet (agentId `a27b372c069f0a4d3`, ~194k, 39 вызовов, ничего не запускал — чтение). **Текст под ревью:** `plans/2026-10-20_gui-graceful-close/tasks/1.1.md` на коммите `main` после закрытия 0.1.
**Вердикт:** CHANGES REQUESTED (итерация 1 из 2). Файл отчёта записал лид: у роли `reviewer` нет Write.
**Проверка лидом:** п. 1, 3, 4, 8, 13 подтверждены чтением кода (отметка «✔ лид»); остальные приняты как ревью-вывод, гипотезы помечены.

| № | Тяжесть | Суть | Место | Решение лида |
|---|---|---|---|---|
| 1 | blocker | Тест `test_app_watchers_and_state_store_close_before_children_end_and_summary` (`process_manager_module/tests/test_process_root_pm_hazards.py:508-539`) ждёт `watchers, state_store, children, summary`; после переноса `children` станет красным при верной правке. Его нет в FILES; ADR-PMM-036 (~1736-1740) закрепляет прежний порядок. ✔ лид | hazards-тест, ADR-PMM-036 | → 1.1a: тест в FILES и REDS («меняется осознанно»), ADR-PMM-040 «заменяет пункт 036»; docs-проход: `app_module/orchestrator.py:87-99`, `process_module/README.md:1015`, `process_module/DECISIONS.md:4182,4249-4250` |
| 2 | major | Страж `test_root_close_order_golden` не содержит `plugins-stop`; `_ManagerDouble` без `request_stop`; на голом `ProcessModule` `_own_work_late` пуст. Позицию `plugins-stop` страж не сторожит | `test_process_root_acceptance.py:23-36,124` | → 1.1a: PM-RED «`request_stop` оркестратора раньше `children.join_until`»; фраза «сверяет со стражем» убрана |
| 3 | major | `_request_ui_restart` (`app.py:958-968`): `process._restart_ui = True; app.quit()` → `closeEvent` → после шага 4 `ignore()` + `request_close()` → рестарт UI гасит бэкенд или виснет. ✔ лид | `app.py:958-968` | → 1.1: `request_restart()` без `system.shutdown`, RED `test_ui_restart_quits_without_shutdown` |
| 4 | major | `closeEvent` «как сейчас» в `CLOSING` снова зовёт `confirm_discard_topology_changes` (`main_window.py:294`); «Не сохранять» `dirty` не снимает → второй вопрос; backend-initiated путь тоже. ✔ лид | `main_window.py:294,353-354` | → 1.1: в `CLOSING` `closeEvent` = геометрия + `super()`, без вопроса; RED на настоящем `MainWindow` |
| 5 | major, гипотеза | Бюджет `work` = `pm_total_s` (`pm_graceful_s + 2,0 + …`); после переноса `children` с `terminate`/`kill` съедает бюджет, на `workers` ≈0 → `message_processor` в `survivors`, отчёт не `ok` | `process_manager_process.py:3765-3771`, `core/stop_budget.py:53,91-101` | → 1.1a: hazard-RED «зависший ребёнок, `survivors == ()`, `shutdown() is True`»; если красный — доля на хвост в `_root_budget` |
| 6 | major | У `CloseCoordinator` нет интерфейса (конструктор, точки подмены, сигналы); `shutdown_sent` читается после возврата `run_gui` — нужен атрибут `GuiProcess`; `Module contract: impl-only` расходится с 2.2/2.4 (new-lite в том же пакете) | `process.py:326-327` | → 1.1: блок «Интерфейс»; `Module contract: new-lite` |
| 7 | major | Опрос: `request_system_command` ждёт 30 с по умолчанию; `RequestRunner` на общем `QThreadPool`; не заданы срок 1,0 с, один запрос в полёте, точка отсчёта, «Подождать», ответ при открытом вопросе. `QProgressDialog`: гипотеза Qt API — `minimumDuration` 4000, `autoClose/autoReset`, Esc | `command_sender.py`, `request_runner.py:111` | → 1.1: поведение опроса и диалога выписано; параметр срока проверяет teamlead первым шагом |
| 8 | major | «Событие взведено при RUNNING→STOPPING» читается двояко; ветка `process.should_stop()` (`app.py:1249`) не описана; 200 мс без причины | `app.py:1245-1259` ✔ лид | → 1.1: GUI не взводит, а наблюдает; `should_stop` в `RUNNING/CONFIRMING` → `CLOSING` сразу, в `STOPPING` не прерывает ожидание; 200 мс снято |
| 9 | minor | Перенос `summary` без причины; меняет момент публикации сводки | `process_manager_process.py:3803-3809` | → 1.1a: `summary` остаётся в `_own_work`, переезжает только `children` |
| 10 | major | Приёмка: «PM exitcode 0» не измеряется зондом; «≤ 3,0 с» недостижимо (база 3,4–4,8 с) и без источника; метка «окно скрыто» — строка кода под проверкой; нет разметки light/medium/heavy | `0.1-tails.md:10` | → 1.1: порог по замеру базы, видимость окна по PID, код PM — раннером стенда, разметка |
| 11 | major | Одна инъекция; нужен список с предсказаниями | — | → I1–I11 в обеих задачах |
| 12 | рекомендация | Размер: 2 области, 9 REDS при потолке 10, ревью добавляет ≥ 5 тестов | — | → разрез 1.1a (framework) / 1.1 (prototype, срез) |
| 13 | minor | Устаревшие якоря: `app.py:1115-1128` (верно 1245-1259), `process_manager_process.py:3610` (верно `_spawn_refused_after_system_stop` ~3878), `main_window.py:287-298`, якоря `design.md`; следующий ADR — 040 | — | → якоря исправлены; ADR-PMM-040 |

## Ответы ревьюера на вопросы лида (кратко)

- Шаги 1-2 реализуемы; порядок `plugins-stop → children → workers → …` получается при вызове `_own_work_late` между `process_module.py:280` и `:284`. Потребители `_own_work`: `ProcessModule`, `GenericProcess`, `GuiProcess`, `GenericProcessManagerApp`, тесты `test_process_executors_acceptance.py:91`, `test_process_root_acceptance.py:378`.
- Слух PM возвращается. Повторный `system.shutdown` идемпотентен (`_cmd_system_shutdown` 773-826); дубль `mode=force` теперь реально эскалирует срок.
- Новые риски: команды классов R/T исполняются во время стопа; гипотеза — `process.relay` в умирающего ребёнка может блокировать `message_processor` на `put`; SSM живёт дольше.
- Второй X в `STOPPING`/`CLOSING` — `ignore()` без повторной отправки (принудительный режим — Task 2.1).

## Что осталось открытым / ненадёжно (ревьюер)

- Не прочитаны `team-protocol` §1, §3, §5 и `.rules/framework.md`, `.rules/prototype.md`; чек-лист прогнан по тексту режима.
- П. 5 — гипотеза: `Scope`/`lifetime.py`, `ProcessRegistry.children_stop` не читались.
- П. 1 выведен чтением, прогоном не подтверждён; п. 7 по знанию Qt API; блокировка `process.relay` — гипотеза без места в коде.
- Не проверены: путь сокета `backend_ctl`, доступность `supervision.status` через `CommandSender`, живой стенд, `qt-mcp`, `sentrux check .`, `shutdown_timeout` в `inspection_full`.
- Номер ADR 040 — по заголовкам `DECISIONS.md`.

---

# Раунд 2 (итерация 2 из 2) — CHANGES REQUESTED, блокеров нет

**Ревьюер:** тот же `reviewer` sonnet (`a27b372c069f0a4d3`, ~241k, чтение). Разрез и порог «окно скрыто» принял. Закрыты: п. 1, 2, 5, 9 раунда 1. Проверка лидом по коду: A4 (`_force_at` читается один раз — `process_manager_process.py:4733-4741`), B2 (PM есть в `processes` с `alive: True` — `:875-881`), B3 (ответ handler'а плоский `{"success", "epoch", "processes"}` — `:896`) — подтверждены ✔ лид. Остальное принято как ревью-вывод.

| № | Суть | Решение лида |
|---|---|---|
| A1 | I1: PM 4 остаётся зелёным (`plugins-stop` регистрируется последним независимо от места `children`); не указан PM 6 | I1 → PM 1, 2, 3, 6 + hazards; PM 4, 5, 7 зелёные |
| A2 | I3: PM 7 не красный, если `summary` уехал вместе с `children` | PM 7 утверждает «`children`, `workers`, `state_store` раньше `summary`»; I3 → PM 7 + hazards |
| A3 | I4: `process.restart` отвергает шлюз L раньше спавн-отказа | I4a (шлюз) → PM 3; I4b (спавн) → новый PM 8 `test_restart_refused_at_spawn_layer_after_system_stop` |
| A4 | PM 6: «`force` сокращает срок» недостижимо; I6 не патч | PM 6 утверждает только ответ и учёт; эффект на идущее ожидание — OUT OF SCOPE и `docs/claude/OPEN_QUESTIONS.md` 2026-11-06; I6 = «снять защиту от повторного `request_stop`» |
| A5 | I5 не патч; хвост включает `summary` и SSM | I5 = `budget_s=pm_total_s` + фейковая группа; PM 5 утверждает один `state_store` и одну `summary` |
| A6 | TRAPS двусмысленны | ответ раньше конца стопа ребёнка — в PM 1 |
| B1 | неразрешимое состояние при мёртвом PM (регрессия против «X закрывает сразу») | после `force_stop()` ещё `no_answer_s` тишины → `commit_close()` + WARNING; CC 7[dead_pm_tail…]; I16 |
| B2 | PM в `processes` с `alive: True` → окно ждало бы выхода PM | параметр `ignore_names` (gui + PM); `alive: None` ≠ мёртв; I17 |
| B3 | `poll_status` синхронный, опрос асинхронный; формат ответа | выписано: `RequestRunner.submit`, `qtbot.waitUntil`, плоский литерал; условие «нет параметра срока» снято (`timeout=` есть); teamlead сверяет форму живым вызовом |
| B4 | как `MainWindow` получает координатор; существующие тесты без него | `set_close_coordinator`; без координатора прежнее поведение |
| B5 | исключения в `confirm_discard`/`send_shutdown` блокируют окно | try/except по шагу 2, случаи в CC 1 и CC 3 |
| B6 | «только наблюдает» без шага | наблюдение — Task 2.1; в 1.1 внешний стоп как сейчас |
| B7 | `should_stop()` у `gui` в `STOPPING` ложен; `backend_gone()` без живого триггера; I9 без красного | шаг 11 заменён подтверждением ссылками; тик вынесен в `on_safety_tick`; I9 снят из предсказаний красного, закрыт приёмкой |
| B8 | свойства без теста; CC красные тривиально | CC 7 параметризован; I14–I17; лид прогоняет набор на заглушке с теми же сигнатурами |
| B9 | зонд: окно PID включает `QProgressDialog` | t «скрыто» = исчезло последнее видимое окно PID |

## Что осталось открытым / ненадёжно (ревью р.2)

- Отчёт раунда 1 с таблицей решений ревьюер не читал. B2 — по комментарию кода, `previous_states` монитора не читал. B1 — сторож родителя на Windows по одной строке `process_runner.py:166`; Job Object launcher'а не читал. Формат ответа `request_system_command` и живой стенд не проверялись. A3 — гипотеза до написания PM 3. Писатели `_stop_requested` проверены только в `process_module`, `app.py`, `process.py`. Бюджет (PM 5) — гипотеза. `team-protocol` §1, §3, §5 и `.rules/*` не читались. Существование строки `shut down successfully` ревьюер не проверял — лид видел её в `2026-11-02_system-run-state_smoke-h1h2.md` (таблица БЛ).
