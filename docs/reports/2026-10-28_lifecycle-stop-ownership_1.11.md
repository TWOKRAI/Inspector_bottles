# Отчёт: Task 1.11 — окно стопа на ребёнка из конфига процесса

Полоса Ф, лид — сессия inspector-bottles-b4, 2026-10-28 (стадии 0–3 — inspector-bottles-22 и -bd, 2026-10-27). План —
[`plans/lifecycle-stop-ownership.md`](../../plans/lifecycle-stop-ownership.md), бриф — [`T1.11.md`](../../plans/lifecycle-stop-ownership/tasks/T1.11.md),
факты тестов, матрицы и стенда — [`T1.11_tests.md`](../../plans/lifecycle-stop-ownership/tasks/T1.11_tests.md). Ветка `feat/lifecycle-stop-window`.

## Что сделано

- Ключ конфига процесса `stop_window_s` (окно ребёнка, секунды) и ключ конфига PM `max_stop_window_s` (потолок `C`); проверка один раз
  при регистрации (`int`/`float`, не `bool`, конечное, `> 0`; негодное — WARNING и поведение без ключа); `w_i = min(stop_window_s, C)`
  с WARNING при обрезке.
- Окна живут в `ProcessRegistry` (`_stop_windows`, снимаются в `remove_process`) и доезжают до `ChildProcessStop(windows_s=…)` на всех
  путях стопа; внешние сроки PM и спавнера — от функции `G` (`core/stop_budget.py`). Без ключей и потолка поведение байт в байт прежнее.
- Правка по ревью (F1): при `C > g` на пути `children` карта окон строится по всем именам, процесс без ключа получает `g`, а не `G`.
  F2 — WARNING про `shutdown_timeout` один; F3 — комментарий у литерала `"stop_window_s"` в `process_launch_config.py`.
- Стенд `stand_l9.py`: сценарий S7 (ключ 10,0, потолок 12, стоп 6,0 с, ×3) и контроль без ключа `--s7-control`.
- ADR-блок Task 1.11 в `process_manager_module/DECISIONS.md`, исключение в DESIGN 4.

## Числа

| Что | Итог |
|---|---|
| Стадия 0 (пилот №3/6, sonnet ‖ opus) | р.1–р.2 оба CHANGES REQUESTED; р.3 — эскалация `teamlead`, M1 + m1–m8 закрыты текстом |
| Слепой тестер (Sonnet) | 20 тестов R1–R9: RED 18 по делу + 2 стража, после ремонта стенда тестера |
| `teamlead` GREEN | 9 файлов +533; heavy `process_manager_module/tests` 1451 passed, 0 failed (до ревью) |
| Матрица И1–И18 | 13 из 18 по прогнозу; I8 вакуумная → закрыта H7; I13/R9[nan-recipe] зелёный от чужого WARNING (C-79) |
| Ревью Opus, ветка | р.1 CHANGES REQUESTED (F1 blocker, F2, F3 minor; F1 воспроизведён: B без ключа умирает на 12,047 с вместо 5,0 с) → р.2 APPROVED (B на 5,031 с одиночно и 5,032 с рядом с A) |
| Break-injection правки F1 | без F1 красен ровно H9 («B без ключа умер на 12.39 с», у ревьюера 12.109 с); без F2 красен ровно F2-тест; прогноз совпал |
| Hazards-файл | 10 passed (7 + H9 + два теста F2) |
| `process_manager_module/tests` (heavy, на `aa4507cda`) | 1455 passed, 32 skipped, 0 failed, 397,6 с |
| Framework suite `multiprocess_framework/modules` без `process_manager_module`, `--deselect` теста C-78 (heavy) | 12527 passed, 46 skipped, 1 deselected, 1 xfailed, 0 failed, 24 мин 7 с |
| `validate.py` | rc=0, ошибок и предупреждений нет |
| `sentrux check .` | 41 правило, все проходят |

## Стенд (прогноз записан до прогона — `T1.11_stand_prediction.md`, коммит `18bc9b21d`)

| Строка | Прогноз | Факт | Совпало |
|---|---|---|---|
| S7 до правки F1 (3) | `exited`, 6,0–6,6 с | 3 из 3, 6,125 / 6,172 / 6,203 с | да |
| S7 после правки F1 (3) | то же | 3 из 3, 6,109 / 6,172 / 6,187 с, `dns` 0 | да |
| S7-контроль без ключа | `terminated`, 5,0–5,3 с | `terminated`, 5,062 с (до F1) и 5,047 с (после) | да |
| S1 без ключа (10) | `exited` 10/10, ответ в полосе факта T1.10 | `exited` 10/10; 0,359 / 0,508 / 0,688 с; стенд FAIL по устаревшему литералу 0,85–1,20 (ошибка прогноза 1.9b, как в T1.10) | частично |
| S5 `system.shutdown` без `slow` (10) | выход дерева < 2,0 с, 10/10 | **0 из 10**: 2,469 и 4,844–5,578 с, медиана 5,156 | **нет** |
| S5 на чистом main `9ed4e597e` (A/B) | не прогнозировалось | 0 из 10: 2,922 и 4,562–5,234 с, медиана 5,000 | — |

S5 красный и на main: разница медиан +0,156 с при разбросе ~0,7 с; S5 идёт без потолка и без ключа, путь кода ветки по построению
совпадает с main (ревью Opus, п.5). Находка записана во входящие реестра дефектов
(`plans/queue/inbox/2026-10-28_inspector-bottles-b4_2.md`).

## Отклонения от брифа

- Acceptance «выход дерева на `system.shutdown` без `slow` < 2,0 с 10/10» **не выполнен в абсолютной форме** — ни на ветке, ни на main.
  Относительно main регрессии нет. Решение о merge при этом красном принял лид (merge — решение лида); владелец может его пересмотреть.
- Вместо «корневого suite» прогнан framework-suite `multiprocess_framework/modules` (без `process_manager_module`, он прогнан отдельно) с
  `--deselect` теста из C-78: полный корневой suite идёт ~56 мин (C-75) и в окно не влез. Корневые красные из реестра (C-71…C-74, C-61) не
  проверялись.
- R1–R9 и ревью-прогоны шли частями на `light` (gate выдавал 75 `NO WINDOW` для `--timed medium`); каталог целиком прогнан в heavy.
- I13/R9[nan-recipe]: hazard H8 на текст WARNING реестра не добавлен (решение лида); R9[nan-recipe] станет настоящим сторожем после C-79.
- Прежний исполнитель (`teamlead` `a9b1eedd6320b2054`) недоступен; правки стенда и ревью-правки сделали свежие `developer` с отчётами и diff.

## Что оставил открытым / ненадёжно

- S5 ≈ 5 с — причина не выяснена (гипотеза: один процесс дерева не выходит за окно PM 5,0, `TerminateJobObject` в логе спавнера). Нужен
  `investigator`: какой процесс последний в живых через 2,0 с после `System shutdown requested`.
- Остаток F2: явный негодный `stop(timeout)` + негодный `shutdown_timeout` + годный потолок могут дать WARNING про `shutdown_timeout`
  дважды (`spawner.py:210`) — совет ревьюера, воспроизведения нет.
- Гонка `kill()` ↔ `_name_escalate` (проверка `_name_signalled` и `terminate()` не под одним локом) и отсутствие прямого теста
  `_rollback_to_snapshot` с ключом — советы ревьюера, воспроизведения нет.
- Маркеры `pytest.mark.timeout` инертны (`pytest-timeout` не установлен); H9 идёт ~6 с реального времени и импортирует rig из acceptance-файла.
- Полоса S1 по литералу 0,85–1,20 — устаревший порог стенда; правка литерала — отдельное решение, не здесь.
- Матрица инъекций — по одному прогону, под heavy соседа; повторяемость не мерена.
- `DECISIONS.md` модуля 290 КБ при бюджете 32 КБ — было до задачи.
- Корневые красные из реестра не перепроверялись (см. выше).

## agentId

| Роль | agentId | Состояние |
|---|---|---|
| стадия 0 sonnet / opus | `a7d76162f766bb315` / `a410ed42da5535d92` | р.1–р.2, сессия -22 |
| слепой тестер (sonnet) | `ac6a8b7b5245056c1` | RED + ремонт стенда; повторно на механизм не звать |
| teamlead (opus): р.3, GREEN, матрица, H7 | `a9b1eedd6320b2054` | недоступен (сессия -22) |
| developer: стенд S7 | `a9d3fb046d63d33e7` | закончил, 135k |
| reviewer Opus (ветка), р.1–р.2 | `a656bc8947f10073f` | APPROVED, ~209k |
| developer: правки F1–F3 | `a8028e0670fa34807` | закончил, 97k |

## Файлы

Код: `process_manager_module/{core/process_registry.py, core/stop_budget.py, core/child_process_stop.py, launcher/spawner.py,
process/process_manager_process.py, topology/blueprint.py, DECISIONS.md}`, `process_module/configs/process_launch_config.py`; тесты —
`tests/test_per_child_stop_window_{acceptance,hazards}.py`. Стенд — `docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/`; результаты —
`docs/reports/2026-10-28_lifecycle-stop-ownership_1.11-stand/`. Ревью — `docs/reviews/2026-10-28_task-1.11-review-opus.md`.
