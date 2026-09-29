# Передача 2026-09-29 — B-1, severity, падающие тесты на main

`main` = `2272b466`. Всё ниже влито, ветки можно удалять.

## Что сделано (слияния в main)

| Merge | Что | Ключевое |
|---|---|---|
| `97bdcf9b` | B-1 + тест severity сводки стопа | `SourceProducer`/`IdleWorker`: темп на `perf_counter` (monotonic на Windows = GetTickCount64, 15.6 мс). Стенд `g1_perf_probe`: 21.3 → 29.6 fps (лог `frame_counter`). Тесты темпа гоняются и на эмуляции Windows-часов (CI на Linux). Условие CTO lifecycle «юнит-тест severity» — [x] |
| `d2216c8b` | `test_mark_only_after_confirmed_death` | Тест: `os.kill(pid, 0)` на Windows = CTRL_C_EVENT, не проба → psutil + положительный контроль. Продукт корректен |
| `09604ce8` | 10 падений sim + 12 в robot_comm + флики | Продукт: `sim_robot` слушатель с `SO_EXCLUSIVEADDRUSE`; журнал, окно монитора, dead-man jog на `perf_counter`; `fault.delay_ms` не короче заданного. Тесты: платформенные свойства, conftest сам ставит offscreen + шрифт |
| `25cbd7e3` | флейк p6 `layer_preview` | interval-поток по задумке от часов → p6 на spacing-потоке, сверка с эталоном до превью (раньше 99.2 % прогонов сравнивали пустые кадры) |
| `2272b466` | флейк pult_web (WinError 10053) | RST при close() с непрочитанным телом → `_linger_close` для всех ранних отказов; 501 на Transfer-Encoding, 400 на кривой Content-Length до команды |

Везде: слепой тестер или debugger → инъекции лида (предсказание до прогона) → синхронный ревьюер. Отчёты — `docs/reviews/2026-09-29_*`.

## Открыто (не сделано, решение владельца или отдельная задача)

1. **Флейки graceful stop на Windows** (давние, не регрессия): `test_graceful_stop_acceptance.py::TestMessageToLiveReaderDeliveredBeforeExit::test_message_to_live_reader_is_delivered_before_exit` и `test_pm_marks_gone_reader_hazards.py::test_stop_many_unblocks_writer_of_dead_reader_gracefully`. Замер: база `89d4f156` — 6/12 и 5/12, `main` — 1/8 и 1/8 (машина нагружена параллельными pytest). Домен — `lifecycle-stop-ownership` (рядом с флейком `children_exit_hook`).
2. **20 падений во фронтенде** (sandbox/dashboard) — видел ревьюер, не разбирались.
3. **L-7** (`defects.md`): сторож смерти родителя на Windows не срабатывает никогда и на редкой ветке шлёт Ctrl+C — задача lifecycle, логично с D1 (Linux/Orin).
4. **M-1** (`defects.md`): сводка `g1_perf_probe` пуста (`source_fps: null`) при живом тракте — цифры B-2 до починки брать из лога `frame_counter`.
5. Мелочи без стража (записаны): в pult_web `_MAX_DRAIN_BYTES`, `_body_consumed`, `get_all` в `_linger_close`; нит «`_make_bare_plugin` в conftest» не взят сознательно.
6. `C:\tmp_x` — пустая папка от тестера, удалить руками (защита не даёт удалить папку в корне диска).

## Уроки процесса (для следующей сессии)

- Скрипт инъекций с `git checkout -- <file>` стирает незакоммиченные правки в этом же файле — коммитить до инъекций (случилось дважды).
- Bash-инструмент съедает `\\` в heredoc/sed — строки с `\r\n`, `\d` писать через Write-файл или `chr(92)`.
- `git merge -F -` не читает stdin: `git merge --no-commit` + `git commit -F -`.
- `pytest.mark.timeout` без установленного `pytest-timeout` — пустая метка; сторож зависания — join-дедлайн / таймаут сокета.
- Имена соседних сессий меняются после resume — перед сообщением `ListAgents`.
