# Task 0.2 — быстрый принудительный стоп `backend_ctl` (`system.shutdown mode=force`) — отчёт

Полоса Ф, лид inspector-bottles-cc, 2026-10-20. План: `plans/2026-10-20_gui-graceful-close/plan.md`, бриф
`tasks/0.2.md`. Ветка `feat/gui-close-force-stop` (worktree `.claude/worktrees/gui-close-0.2`), от `main 8a308d22b`.
Подробности: реализация — [`…_T0.2_impl.md`](2026-10-20_gui-graceful-close_T0.2_impl.md), инъекции и стенд —
[`…_T0.2_injections.md`](2026-10-20_gui-graceful-close_T0.2_injections.md).

## Итог

`backend_ctl` гасит систему за `deadline_s` с зависшим ребёнком: выход PM 1,547–1,922 с (медиана 1,718) против
5,656–6,094 с без обрезки срока. Нового потока и нового `kill` в PM нет: срок хранит `_ChildrenStop`, эскалацию делает
штатная фаза 3 области. Попутно исправлен старый дефект `launch.py` (каталог логов PM закреплялся первым `build()`).

## Что сделано (коммиты ветки)

| Коммит | Что |
|---|---|
| `f2008ee01` | docs(plans): открытие, бриф после 2 раундов стадии 0 (Opus) — таймер заменён сроком в `_ChildrenStop` (R4) |
| `9ea23994b` | слепые тесты tester (Sonnet) U/D/L — RED: 18 failed, 2 passed |
| `b8197afd1` | реализация: PM `mode=force` + `deadline_s`, драйвер `system_shutdown`, MCP-инструмент (escalated), ADR-PMM-038 |
| `11c21b574` | авторский тест: отказ PM → драйвер не ждёт (закрыл И11) |
| `9d64241ac` | L-тесты: вердикт по каждому прогону, таблица чисел (просьба координатора) |
| `4b8da041c` | `launch.py`: явный `log_dir` без env оператора → присваивание `INSPECTOR_LOG_DIR`; 8 мелких замечаний ревью |

## Числа

- Юнит U+D+авторские+страж `launch`: 37 passed; соседи: 277 passed, 5 skipped, 2 failed — `test_build_characterization`,
  красный и без правки (дрейф снимка канала `robot_exchange_file`, передан полосе Р2).
- `validate.py`: те же 3 FAIL, что на main (память, BY-MODULE, G6 R1 `thread_split_probe.py:210`), новых нет.
- Юнит-матрица v2: 12 инъекций, все пойманы; 11 — набор красных поимённо как прогноз, И6 — один лишний красный.
- Стенд T1–T4 (HEAD `4b8da041c`) — совпал с прогнозом по каждому ассерту:

| Прогон | Наблюдено |
|---|---|
| T1 вся L | L6 5/5 по 6 пунктам, медиана 1,718 с; smoke ✓; L7 20/20, медиана force 1,297 против graceful 1,281, terminate 0 |
| T2 И1 (без обрезки) | только «< 4,0» ✗ ×5 (5,656–6,094 с), медиана 5,781 ✗ |
| T3 И8 (обрезка и после kill) | только exit0 ✗ (76) и «ВЫЖИЛИ» ✗ ×5; время 1,141–1,266 с |
| T4 И12 (`setdefault` в `launch.py`) | только info ✗ у прогонов 1–4; прогон 0 весь ✓ |

- Ревью Opus: р.1 APPROVED с 8 мелкими → исправлены; р.2 APPROVED (итерация 2 из 2).

## Находки о процессе

- Сводная таблица агента стенда (Haiku) записала L7 зелёным при красном сыром хвосте; `tail -60` в брифе лида скрыл
  причины падений S1–S4. Правило: сводку агента сверять с сырым выводом, полный вывод — в файл.
- Первый стенд (S1–S4) не в зачёт: L6 краснел уже на реализации (логи PM прогонов 1–4 в `run_0`); И1/И8 на красном тесте
  ничего не доказывали (замечание координатора).
- Вызов `bash` из Python на Windows находит WSL-релей System32 — только полный путь к Git Bash.

## Что осталось открытым

- Мелочи ревью р.2, не исправлены: (1) предикат `launch.py` можно упростить до `_ENV_LOG_DIR_OVERRIDE is None` + тест на
  пустой `log_dir` (в проде `log_dir` задан, `system.yaml:10`); (2) драйвер: потеря соединения ДО отправки выглядит как
  `pm_gone=True` — проверять `connection_lost` до запроса; (3) метки ✓/✗ в L-таблице упадут при `-s` без `PYTHONUTF8`;
  (4) нет теста, что MCP не приводит `deadline_s` через `float()`; (5) имя `test_operator_env_without_explicit_dir_stays`.
- C-14 (координатор): полная правка — явный `log_dir` в bundle PM (фреймворк), на приёмку CTO фазы. Нынешняя правка
  не спасает, если в той же сессии pytest стоит `MULTIPROCESS_LOG_DIR` из `modules/conftest.py`.
- Причина красного L7 в первом стенде (S2) не установлена; в T1 он зелёный 20/20 — гипотеза: нагрузка CPU 77 %.
- Пределы ADR-PMM-038 (а)–(д) остаются: до LSO 1.9b ожидание в очереди PM до 5 с; `outcomes: null` до 1.10;
  `force` в фазе 2 срок не сокращает; kill после join воркеров PM; короткий срок обрывает и здоровых детей.
- Гейт слияния (4b8da041c, против базы main): framework suite — 2 failed, 11912 passed, 44 skipped, 1 xfailed (1048,7 с).
  Оба красных не от ветки: `test_std_logger_guard::test_no_bare_stdlib_logger_outside_whitelist` красный и на main
  `99405f964` (хит `Services/robot_comm/gui/line_source.py:45`, зона Р2, передан координатору);
  `test_watcher::test_reload_on_atomic_replace` при одиночном повторе зелёный на ветке и на main (тайминг под нагрузкой).
  `validate.py` — 3 FAIL = C-13; `multiprocess_prototype/backend/tests` — 2 failed: `phone_sketch` (C-15),
  `hikvision_letter_robot` (дрейф снимка от Р2). Новых красных от ветки — 0.
- Worktree `gui-close-0.2-tester`, `gui-close-0.2-review` — удалить после слияния; `l9-control` — из прошлой сессии.

## Агенты

| Роль | Модель | agentId | Итог |
|---|---|---|---|
| reviewer, стадия 0 (2 раунда) | Opus | a4fc77ef4098bb7e2 | бриф закрыт |
| tester, слепые тесты + перестройка L | Sonnet | a74572d7e6c84d49a | 18 RED / 2 стража; L по прогонам |
| teamlead, реализация + правки | Opus | a3bc067b244eea450 | 3 коммита кода |
| junior, юнит-матрицы v1/v2 | Haiku | af5ffebf8b1c3b975 | 11 + 12 инъекций |
| junior, стенд S1–S4 | Haiku | a9225d3ddcc9d39a8 | строка L7 ошибочна |
| investigator, логи PM | Opus | ac52c4bc554a2b6a2 | причина `launch.py:669` |
| reviewer, стадия 5 (2 раунда) | Opus | ae8b37f1a0eb676a7 | APPROVED ×2 |
| junior, стенд T1–T4 | Haiku | abe23ff4c915239cc | сырой вывод |
