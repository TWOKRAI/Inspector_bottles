# Полоса Д2, п.1: красные `process_manager_module/tests` на macOS

Автор: лид полосы Д2 (сессия inspector-bottles-6a), 2026-11-19. Режим — только диагностика; код PM не менялся. Дерево — detached `main` `767d61329`, Darwin 27.2.1, Python 3.12.13, `kern.posix.sem.max` = 10000.

## Итог

Красные каталога на macOS — платформенное ограничение (исчерпание POSIX-семафоров), а не дефект кода. Реальный дефект один (устаревший литерал числа рецептов в двух тестовых файлах, C-94); он исправлен на ветке `fix/lane-D2-reds-on-main`.

## Прогоны

| # | Что | Результат |
|---|---|---|
| 1 | Весь `process_manager_module/tests`, один процесс pytest, класс heavy через `machine_gate.sh` | `127 failed, 2225 passed, 7 skipped, 1 xfailed, 1 warning, 3 errors` за 530,64 с; код выхода 1 |
| 2 | 14 красных файлов, каждый в своём процессе, последовательно | 12 файлов зелёные (151 тест: 21+16+34+13+8+8+8+7+8+8+11+9, `Errno 28` нигде не найден), 2 красных — оба `assert 23 == 22` |
| 3 | Два красных файла после правки литералов (ветка `fix/lane-D2-reds-on-main`) | `80 passed` за 4,07 с |

Расхождение с Ф (141 failed + 5 errors на `c6bae7d09`): у нас 127 + 3 на `767d61329`. Число красных от ENOSPC зависит от накопленных семафоров и нагрузки машины, поэтому точное совпадение не ожидалось; набор «что красное» совпадает по смыслу (те же файлы со spawn).

## Группировка красных по причинам

| Причина | Красных | Платформа или дефект |
|---|---|---|
| `OSError [Errno 28]` из `multiprocessing/synchronize.py:57` (`SemLock.__init__`); все 252 трассы с `Errno 28` в логе начинаются там же | 125 (+ часть из 3 errors в `test_t54_ready_event_wiring.py`) | **платформа macOS** — лимит POSIX-семафоров, не диск (`df` показывает 274 ГиБ свободных) |
| `assert 23 == 22` — число `recipes/*.yaml` | 2 | **дефект теста** (C-94): `camera_device_demo.yaml` добавлен `24f29e1cb` (2026-11-15, Task 1.8) без правки литералов |

Красные по файлам в прогоне №1: `test_unapplied_metadata_check` 24, `test_system_launcher` 21, `test_stop_wave_last_guards` 15, `test_supervision_status_system_stop` 12, `test_t54_ready_event_wiring` 9 (+3 errors), `test_wait_until_ready` 8, `test_supervisor_restart_incarnation_hazards` 8, `test_supervisor_restart_incarnation` 8, `test_system_shutdown_pre_stop` 7, `test_t54_generic_process_preroll_hazards` 6, `test_supervision_status_system_stop_hazards` 4, `test_stop_wave_last` 3, `test_wire_status_refused_switch_acceptance` 1, `test_dotted_process_name` 1.

## Список для лида Ф: что гонять по отдельности

Эти 12 файлов зелёные, когда каждый идёт в своём процессе (время одного файла 1–27 с):

`test_system_launcher.py`, `test_stop_wave_last_guards.py`, `test_supervision_status_system_stop.py`, `test_t54_ready_event_wiring.py`, `test_wait_until_ready.py`, `test_supervisor_restart_incarnation_hazards.py`, `test_supervisor_restart_incarnation.py`, `test_system_shutdown_pre_stop.py`, `test_t54_generic_process_preroll_hazards.py`, `test_supervision_status_system_stop_hazards.py`, `test_stop_wave_last.py`, `test_wire_status_refused_switch_acceptance.py`.

Два оставшихся файла (`test_unapplied_metadata_check.py`, `test_dotted_process_name.py`) зелёные только после правки литералов C-94 (ветка `fix/lane-D2-reds-on-main`). Остальные файлы каталога в этом разборе по отдельности не гонялись: набор выше — только те, что краснели в общем прогоне.

Практическое правило на macOS: гонять PM-тесты по одному файлу на процесс (или небольшими пачками) и не запускать два прогона параллельно.

## Что осталось открытым / ненадёжно

- **Источник утечки семафоров найден 2026-11-20 (дополнение, строка C-93 в `defects.md`):** `std_facade._CACHE` держит каждый PM процесса; 12410 живых SemLock по 146 файлам при лимите 10000. Не проверено: сам прогон каталога до Errno 28 (он уронил бы чужие стенды на общей машине), аддитивность на всех 146 файлах (проверена на паре: 2662 = 2662), цепочка удержания для стендов кроме fifo `Rig`; ядерное поведение xnu про слот семафора не проверено.
- **Три errors** в `test_t54_ready_event_wiring.py` отдельно не разбирались: в изоляции файл зелёный (13 passed), значит, это тоже ENOSPC по косвенным признакам, не по трассе.
- **Каждый прогон — один раз.** Стабильность красных и зелёных не проверена повторами; тайминги измерены на машине с параллельной работой агентов.
- **Расхождение 127 против 141** с цифрами Ф не разобрано до конца (разные коммиты и нагрузка).
- Из 7 skipped и 1 xfailed причины не смотрел; одно предупреждение pytest не разбирал.
- Windows и Linux не проверялись: вывод «платформа» относится к macOS.
- Реестр: C-93 (платформа), C-94 (литерал). Правки кода PM не делались (граница полосы Ф).
