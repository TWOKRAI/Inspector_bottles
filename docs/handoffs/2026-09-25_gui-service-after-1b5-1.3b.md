# Handoff: gui-service после 1b.5 и 1.3b (2026-09-25)

**Состояние:** main = `e5758a3f` (= `feat/gui-service`). Worktree зонтичной ветки — `.claude/worktrees/gui-lead`.
Неслитых веток gui-service нет. Живых стендов нет.

## Закрыто сегодня (все в main)

| Задача | Merge | Приёмка |
|---|---|---|
| 1.3a — SocketChannel без head-of-line | `4cb0e6df` | `docs/reviews/2026-09-25_gui-1.3a-lead.md` |
| 1b.2a — каталог плагинов от хаба | `ad8fc601` (+ фикс `c9ae9b06`) | `docs/reviews/2026-09-25_gui-1b.2a-lead.md` |
| 1b.5 — сервисы на хабе (`service.*`, `RemoteServiceManager`) | `52f5e6c3` | `docs/reviews/2026-09-25_gui-1b.5-lead.md` |
| 1.3b — самоответ в `reply_to_request`, `system.shutdown` не теряет ответ | `ea17a4e7` | `docs/reviews/2026-09-25_gui-1.3b-lead.md` |

## Следующий шаг (выбор владельца)

1. **Блокер пути к Пульту:** ревью владельцем `plans/frontend-constructor/gui-bootstrap-design.md` (T4.1, решения
   Р-A…Р-F не утверждены). Без него стоят T4.2–T4.4 → 1.4 → 1b.3 → Ф3.
2. Без блокера можно брать:
   - **1b.4** — auth на бэкенде (после 1b.5 — готово);
   - **предусловие 1b.2b** — `RegistersManager.from_catalog` без `set_value`/`validate` (правка формы молча не
     дойдёт до бэкенда); `app.py` не трогает.
3. Канон на каждую задачу: tester RED в worktree до кода → teamlead/developer → инъекции лида → стенд → reviewer
   синхронно. Бриф агента — по `.claude/plugins/dev/templates/executor-brief.md` (хук `lint-brief`: DESIGN ≥ 3
   строк, FILES ≤ 6, REDS ≤ 10, REPORT).

## Открыто / ненадёжно

- ~~Красный инвентарь `emergency_log` от сторожа lifecycle 1.5~~ — закрыт сессией 4a (`ae328398`, +2 с доводом); каскад
  `test_declarations_leak_order_independence` снова зелёный.
- `config_module/tests/test_watcher.py::test_foreign_file_in_the_same_directory_is_ignored` — красный и до наших
  слияний, похоже на ФС macOS, не разобран.
- `test_build_matches_snapshot` краснеет в общем прогоне после других тестов (протечка `MULTIPROCESS_LOG_DIR`) —
  отдельно зелёный.
- 1b.5: приёмка тестера не ловит блокирующий `start` (держат hazard-тесты автора); 9-с `connect` modbus живьём не
  проверен; GUI на `RemoteServiceManager` не переведён (1b.3).
- 1.3b: доказательство — инъекция 5/5 → 0/5 и 60/60 живьём; редкие естественные потери такой выборкой не ловятся.
- Гонка признака `(system-wide)` в хуке выхода (lifecycle) — открыта, запись в `OPEN_QUESTIONS.md`.
- Всё мерилось на macOS; Linux (Orin) не проверялся.

## Соседи

- lifecycle-stop-ownership — сессия 4a, Task 1.6 (`process_runner.py` конец `run_process_function`,
  `stop_all/shutdown` в `process_manager_process.py`); её живые порты 9800–9899.
- Наши живые порты: 7900–7999 (тесты 1b.5 — 7910; `system_shutdown_live` зашит на 8860+ — перед прогоном
  проверить `lsof` и спросить соседей).

## Уроки (в памяти)

`.claude/memory/feedback_merge_radius_skips_live_and_contract_tests.md` — радиус слияния шире «изменённых
каталогов» (`statistics_module`, `app_module`, `modules/tests`), живые — только с `--backend-live`.
Плюс сегодняшнее: инъекции гонять только по **закоммиченному** коду (откат `git checkout` съел незакоммиченный фикс);
в zsh `$VAR` со списком путей не разбивается — скрипты инъекций запускать через `bash -c`.
