# Handoff · Н2 сим-аудит GUI (сессия inspector-bottles-a2 [589037]) — 2026-11-22

Промпт полосы: `docs/handoffs/2026-11-22_lane-prompt-sim-audit-gui.md` (ветка `test/sim-wire-audit`, коммит `e4443c487`, дерево `../Inspector_bottles--sa-gui`).
Отчёт-черновик с предсказаниями ДО нажатий и таблицей результатов: `docs/reports/2026-11-22_sim-audit-gui.md` (в дереве `--sa-gui`, не закоммичен). Предсказания не править.
Ответы владельцу по-русски; первая строка ответа: «Н2 · сим-аудит GUI · <имя сессии с ref>».

## Особенность этого прогона (решение владельца)
Владелец захотел «свежие библиотеки»: стенд идёт на **Python 3.14.7, PySide6 6.12.0, opencv 5.1.0, numpy 2.5.5, pydantic 2.14.4, pymodbus 3.16.2** в отдельном venv
`/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/d4060aba-43b0-4c4d-a62d-58fd3c639339/scratchpad/venv314` (создан `uv venv --python 3.14`; откат = удалить папку). Основной `.venv` (3.12) не тронут. Все пакеты ставить в `venv314` через `uv pip install --python …/venv314/bin/python` (владелец разрешил ставить последние). Не `uv sync`.
Папка `…/scratchpad/run314/` держит рабочие файлы (лаунчер окна без venv-guard `launch_gui314.py`, записывалка `rec_ui.py`, логи `logs*/`, `ui_events*.jsonl`, `collect/`). Если scratchpad очищен — пересоздать по описанию ниже.

## Текущее состояние стенда (на момент handoff)
- Замок: `Inspector_bottles/stand.lock` — `simaudit-gui-inspector-bottles-a2 | 2026-11-22T17:24Z | measure | e4443c487 | 5021,8765,8766,8091,8092`. Нет `machine.lock` — старый протокол. Новой сессии: переписать строку на своё имя либо снять замок и взять заново, ничего не стирать `rm -rf`.
- Сим (`apps/line_sim/run.py`, из дерева `--sa-gui`, offscreen): PID 41206, порты 8766, 5021, 8091, 8092. Камера `scene.defect_rate 0.0` уже выставлена.
- Прототип с окном — **из дерева `../Inspector_bottles--pult-speed`** (ветка `feat/pult-belt-speed`, правки не закоммичены): PID 50286 (слушатель 8765 — PID 50289). Лог-каталог `run314/logs7`. Автологин `dev` (одноразовый `users.yaml` в `run314/auth3`, настоящий `~/.inspector_bottles/auth` не трогали).
- Сборщик `scripts.wire_audit.collect` PID 50329 → `run314/collect/`; записывалка UI-событий PID 50331 → `run314/ui_events4.jsonl` (формат: строки `{"t","seq","ev"}`, `ev.command` = `ui.event` / `command` / `system_command` / `state.changed`).
- Состояние системы: `system.run.state = running`, лента ходит (после последней проверки скорость 31 Гц).
- Остановить: `kill -TERM` PID прототипа 50286, сборщика 50329, записывалки 50331, сима 41206 (свои процессы; `pkill` запрещён правами). Потом убедиться, что порты 5021/8765/8766/8091/8092 свободны и `~/.multiprocess_framework/` пуст, снять `stand.lock` обычным `rm`.

## Как поднять заново (без venv-guard)
1. Сим: `BACKEND_CTL=1 BACKEND_CTL_PORT=8766 QT_QPA_PLATFORM=offscreen PYTHONPATH=<--sa-gui> PYTHONUTF8=1 venv314/bin/python apps/line_sim/run.py`; через 12 с `camera scene.defect_rate {"probability": 0.0}` (порт 8766).
2. Прототип с окном: `frontend/run.py` перебрасывает на основной `.venv` (venv-guard, `multiprocess_prototype/run.py:341`) — под 3.14 не годится. Использовать `run314/launch_gui314.py` (выставляет `INSPECTOR_PRESENTATION=<дерево>/multiprocess_prototype/frontend/presentation.yaml`, вызывает `multiprocess_prototype.main.main("letter_robot_sim", headless=None, autostart=None)` под `if __name__ == "__main__"`; без этого guard spawn-дети перезапускают main). Env: `TREE=<дерево> PYTHONPATH=<дерево> BACKEND_CTL=1 PYTHONUTF8=1 INSPECTOR_LOG_DIR=<новый каталог>`; НЕ ставить `--autostart` и `INSPECTOR_GUI_UNATTENDED` (нужны «ready» и модалка «✕»).
3. Без пользователя GUI показывает «гостя» без вкладок. Лечится так: `MULTIPROCESS_AUTH_USERS_PATH=INSPECTOR_AUTH_USERS_PATH=<свой users.yaml>`, `MULTIPROCESS_DEV_PASSWORD=INSPECTOR_DEV_PASSWORD=<одноразовый>`, `INSPECTOR_DEV_USERNAME=dev`, `INSPECTOR_AUTH_DEV_AUTO_LOGIN=1`, `INSPECTOR_DATA_DIR=<свой>`, один раз `python -m Services.auth.bootstrap`. Пароль в отчёты не писать.
4. Дерево `--pult-speed`: `data/models/` — обычные копии, `data/line_sim` — ссылка на основное дерево (уже сделано).
5. Сборщик: `python -m scripts.wire_audit.collect --proto-port 8765 --sim-port 8766 --out-dir <каталог>`. Записывалка: `rec_ui.py <файл.jsonl>` (подключается к 8766 и 8765, `watch_like_gui` + `ui_tap("gui")`, цикл `events_page("all")`). `PYTHONPATH` должен указывать на дерево с `backend_ctl`.
6. `qt-mcp` не подключился (CONNECTION_CLOSED): кнопки нажимает владелец по команде «нажмите …», запись ведётся через `ui_tap`.

## Что уже снято (подробно — в таблице отчёта)
- «ЗАПУСТИТЬ» 2/3: `running` через 0,026 и 0,079 с; `kind=command` НЕ приходит (только `ui.event` kind=button) — находка; на проводе ничего.
- «ОСТАНОВИТЬ» 2/3: `ready` через 1,092 и 0,933 с (предсказание ≤ 1 с); одна запись `STOP_REQ`, значения 9, 13, 17, 21 — счётчик с шагом 4, предсказанных «5» и «двух записей» нет; на проводе `SERVO` 0, `0x1200 = 0`, `0x1204 = 1`.
- «ОСТАНОВИТЬ» в `ready` (второй клик): `ui.event` записан, эффекта нет; активность кнопки в `ready` владелец не подтвердил. В `running`: «ЗАПУСТИТЬ» серая, «ОСТАНОВИТЬ» активна (по скриншоту владельца).
- «Лента пуск»: идёт командой `devices.vfd_run` (`kind=command` +0,001 с), на проводе `0x1202`, `0x1201=0`, `0x1200=1`, `0x1204=1`, клик → провод 17 мс. Предсказание «в бэкенд командой не идёт» опровергнуто.
- «ЗАПУСТИТЬ» ленту не запускает; «ОСТАНОВИТЬ» пишет `0x1200 = 0` (стоп ленты) — после стопа лента стоит, пока не нажата «Лента пуск». Находка по дизайну, решает владелец.
- Скорость ленты: в пульте рецептов не было контрола. Добавлен `belt_freq` (поле Гц 1–50) в `letter_robot_sim.yaml` и `hikvision_letter_robot.yaml` + починен `VfdClient.run()` без частоты (запоминает последнюю; раньше затирал `default_freq_hz` 10 Гц). Проверено на проводе: 31 Гц → пуск на 3100. 737 тестов зелёные (`Services/vfd_comm`, `Plugins/hub/device_hub`, контракты рецептов).

## Что осталось снять (пункты промпта)
2. «Домой» в `ready` и при диске в полёте (≥ 3 успешных захвата, потерянный диск → C-104 в `system.log`: `[health] ResourceUnavailable @ robot_io.forward.refused`); ждём `devices.robot_park {device_id: robot_main}`, на проводе SERVO 0 (+ SC_RUN только если робот не дома). Диски подавать командой сима (образец `scripts/alpha_sim/run_alpha.py`, импортировать нельзя).
3. «Серво ВКЛ»: `robot_servo value=on` → SERVO 1; диск до «Серво ВКЛ» → отказ C-104, после — CVT_JOB.
4. Ленточные: «Лента стоп» (`vfd_stop`), скорость — частично снято.
5. Поле «Слово» + Enter: `target_word` ≤ 0,05 с; смена слова на ходу (B → D → C одним заходом, S6); фокус-аут без Enter не применяется.
6. «✕»: модалка закрытия, ветки «Yes» и «No» (прототип запущен БЕЗ сторожа `INSPECTOR_GUI_UNATTENDED`), снять `system_shutdown`, шаги pre_stop, `gui terminated`/C-105.
7. Каждую кнопку ≥ 3 раза (ЗАПУСТИТЬ и ОСТАНОВИТЬ — по 2 из 3; Лента пуск — 3 клика есть, но в серии с переменной скоростью).
8. Проверка провода аудитом: `python -m scripts.wire_audit …` (аргументы из `stages.json` цепочки, `--zone-max-mm 600`), открыть `wire_commands.md` рядом с `audit.md`.
Время клик → команда ≤ 0,05 с, команда → провод ≤ 0,15 с (замеры есть для «Лента пуск»: 0,001 и 0,017 с).

## Побочные находки (в отчёт)
- `chain_check.yaml --gui` только не добавляет `--headless` к `run.py`; без `frontend/run.py` окна не будет («overlay не задан»). Не проверено отдельно.
- Каждый стоп пишет ровно одну запись `STOP_REQ` — расходится с диагностикой `docs/reports/2026-11-22_sim-audit-stop-req-diagnosis.md` («5 и 9»).
- Скриншот владельца: «Войти»-гость без вкладок, пока не настроен автологин — ловушка из `docs/claude/memory/feedback_gui_stand_in_worktree_needs_user_and_recipe_by_name.md`.

## Не закоммичено / что решать
- Ветка `feat/pult-belt-speed` (дерево `../Inspector_bottles--pult-speed`): `Services/vfd_comm/core/client.py`, `Services/vfd_comm/tests/test_client.py`, два рецепта. Нужны коммит с `Why:`/`Layer:` (Conventional Commits, трейлеры одной строкой), ревью `reviewer` (стадия 5; Services — это не «рецепты read-only» полосы, делалось по прямой просьбе владельца), слияние через координатора `inspector-bottles-95 [3d753e]`. Не коммитить без слова владельца.
- Решение по безопасности пуска для реального ПЧ: «Лента пуск» теперь стартует на последней заданной скорости, а не на `default_freq_hz` (запоминается до рестарта процесса `devices`).
- Отчёт полосы `docs/reports/2026-11-22_sim-audit-gui.md` довести до формы (Суть / Итог / Проверка / Проблемы→решение / Агенты / Открыто / Дальше / Подробно) после последнего прогона.
- Координатор: `inspector-bottles-95 [3d753e]`; лид-родитель полосы Н: `inspector-bottles-ee [534a0e]` (не путать с `inspector-bottles-95 [bbfb26]`).
