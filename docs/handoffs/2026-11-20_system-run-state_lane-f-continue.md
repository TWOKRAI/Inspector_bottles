# Handoff: run-state, полоса Ф — продолжение после 20.11

Автор: лид полосы Ф (сессия inspector-bottles-f1). Состояние: main `4e4e52254` + позже (проверь `git log -1 main`). Отчёт сессии: `docs/reports/2026-11-20_system-run-state_lane-f-stand-and-merges.md` (числа, таблица agentId). Предыдущий отчёт: `docs/reports/2026-11-20_system-run-state_lane-f-merges.md`. План: `plans/2026-10-27_system-run-state/plan.md`.

## Что в main (полоса Ф)
2.7 (+M2, 2.7d, M1) + 2.9, П3 (LeafCopy), 2.2 (S4a, S4b), S3doc, S6 = 2.2c, S5 (пульт), правка паузы 2.2 (стоп на каждом вызове), 2.9b (ключ `readiness` боевого рецепта), 5 пачек OPEN_QUESTIONS. Красных run-state нет; два красных `test_no_private_driver_state` (литерал 64/71) — на базе.

## Порядок слияния (ВАЖНО, изменилось 20.11)
Ветка `main` стоит в ОСНОВНОМ дереве `/Users/twokrai/Project_code/Inspector_bottles` (решение владельца). Слияние: `git -C /Users/twokrai/Project_code/Inspector_bottles merge --no-ff -F <файл> <ветка>`; перед этим `git branch --show-current` = `main`, `git status` без чужих ПРАВОК (4 неотслеживаемых отчёта `docs/reports/2026-11-17_visual-constructor-research*.md` — владельца, не трогать). Грязно — не сливать, прислать HEAD ветки файлом координатору. В `lane-f-merge` (detached) не коммитить. Тема слияния `feat(...)` (хук режет `merge(...)`), трейлеры одним блоком: Why/Layer/Refs/Decision/Co-Authored-By; Layer из списка (`docs|framework|infra|mixed|plugins|prototype|scripts|services|tests`), не `plugin`.

## Что делать дальше (по приоритету)
1. **Решения владельца — собрать и спросить итоговым списком** (координатор показывает владельцу): холодный старт — hub «сдался после 3 попыток», нет автопереподключения; камера в `stopping` при `auto_start` не блокирует START (варианты (а) `check_function` для `stopping` / (б) ключ `readiness` в рецепте камеры); Р1 (подпись пульта при `run_gate:false`), Р2 (`bool()` или `is not False`); ложные «разрыв revision» ADR-SS-015 ((а) водяной знак / (б) номера на подписчика / (в) только логирование); запрет `run_locked_commands` в `ready` при `run_gate:false` без `run_start`; В10, В4, SOFT/HARD/HALT, «fault на ходу» (умолчания лида приняты координатором); M3 `tick_fails_limit=3` стендом не уточнён.
2. **Task 2.8 (S1+П2)** — по слову владельца: стенд на симе выполнен, но нужны окно heavy, GUI-стенд четырёх вкладок, рассылка ≤ +10 %, инъекции красные (`tasks/2.8.md`, строка ~322); слепой tester и ветка не начаты (бриф `tester-brief-2.8.md` утерян, спека 50 КБ). Учесть: повтор затравки пульта (`run_control.py`, `_on_seed_result`) — отдельно от S5; затравка после `DELETED` возвращает подпись (OPEN_QUESTIONS 20.11).
3. **Коммит B 2.1** (`run_gate: true` + golden + литерал `True`): после S3c, S3c′, S5 (слиты) и условий — live recipe_service ×2, `test_frame_bridge_live`, `start_run` до `apply`; стенд на симе не заменяет.
4. **2.6, 2.4 (живая приёмка), 2.5** — не начаты; 2.4 живая правка перезахватывает порт внутри `grabbing` (согласовано с К).
5. **S4b (б), (в)**: `tick_fails_limit` — юнит-инъекция бросающего `_dispatch`/`_park.step` или задание под задержкой записи; повтор `pause` — на свежем подъёме подать `delay 3000` после входа `run_stop` в pause, и на рецепте без `vfd_belt`; полный список — OPEN_QUESTIONS (запись S4b).
6. **Хвосты правок:** `process_manager_process.py:1723` (описание `system.run.status` без `stop_allowed`/`ack_allowed`, файл Ф), `tasks/2.8.md:322`, ADR-PMM-049 «Известная цена» (после S5), статусы 2.7/2.9/2.2/S5/2.9b в `plan.md` (лид), индекс ADR `process_module`, README PM 46 КБ при бюджете 32 КБ, `backend_ctl/AGENTS.md` 53,8 КБ.
7. **После железа (≈ 22.11):** 3.2 (после тега 1.0), 3.4, 3.5, 3.6, 3.7, остатки 1.11 (Q2, Q3, A6); замер opening камеры (MVS), безвредность повторного SOFT stop v2 / `abort` режим 3 и отмены `park` на каждом повторе (`robot_driver_v2/ops.py:103`).

## Стенд на сим-линии (как воспроизвести)
Дерево `/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/lane-f-stand` (detached, gitignored данные: `data/line_sim` симлинк, `data/models/mobilenet_*` КОПИИ — симлинки на модели песочница отвергает). Скрипты и конфиги — в scratchpad сессии `f/stand/{scripts,stage2,stage2s4b}` (/private/tmp, может быть очищен; ценные — `start_sim.sh`, `start_proto.sh`, `shutdown.py`, `lib.py`, `proxy.py` TCP-прокси хаб→сим 5031→5021). Приёмы: `run.py --headless` БЕЗ имени рецепта берёт рецепт из tmp `app.yaml`; `await_condition state_path` требует предварительной `state_subscribe`; у сим-робота v2 нет `fault.*` (инъекции — через прокси); `machine.lock` нет — гейт идёт через `stand.lock`, окна не требуются; остановка: `shutdown.py 8765`, затем `8766`. Прототип/сим держат порты 8765/8766/5021/8091/8092 — освобождать.

## Уроки процесса (по ходу 20.11)
- `lint-brief` требует блоки `DESIGN`/`FILES`/`REDS`/`REPORT` в форме шаблона либо строку `BRIEF-OVERRIDE: <причина>` в начале брифа (слепой tester, стенд, расследование, ревью).
- Субагентам часто отказано в `Write` отчёта и `pkill` — отчёт приходит в ответе, остановка стенда — через `shutdown.py`. Права на Bash запрашиваются по агенту: ответить может только владелец.
- Слепой tester получает урезанную спеку из scratchpad (без DESIGN) и дерево на базе до реализации; его файлы переносит лид.
- Слепой тест, кодировавший отменённое решение (r9b), правит лид, не developer.
- Предупреждения `StateProxy … разрыв revision` ≈ 4,2/с на узкой подписке — не потеря пакетов и не регресс П3 (ADR-SS-015); проверять подпиской `**` и DEBUG-счётом resync.
- Qt: у непоказанного дочернего виджета `isHidden()` False до явного `hide()` — предсказание инъекции «убран `setVisible`» дало 3 красных, не 1 (урок не внесён в память: индекс > 8 КБ).

## Временные деревья (можно убрать `git worktree remove` после слияния/ненадобности)
`lane-f-29b`, `lane-f-s3doc`, `lane-f-s5`, `lane-f-s5-tester`, `lane-f-22p`, `lane-f-2.2c-rev`, `lane-f-stand-preP3`, `lane-f-oq2` (ветки `feat/run-state-2-9b`, `docs/run-state-s3doc`, `feat/run-state-s5`, `feat/run-state-2-2-pause-every-call`, `docs/run-state-oq2` — все влиты); `lane-f-stand` держит gitignored данные стенда — удалять вместе со стендом. Старые деревья 2.x (`lane-f-2.7`, `lane-f-2.8a` с ruff-шумом в `state_store_module`, `lane-f-2.2` с чужим `test_no_private_access.py`) не коммитить.
