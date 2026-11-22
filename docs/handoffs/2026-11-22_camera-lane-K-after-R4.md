# Handoff: полоса К после R4 (2026-11-22)

Для следующей сессии полосы К. Заменяет `docs/handoffs/2026-11-22_camera-w4-r4-next.md` (он про состояние до слияния К4').

## Состояние
- К4' слит в `main` `6cb212213` (координатор `inspector-bottles-30`). R4 готов на ветке `feat/camera-r4` (дерево `Inspector_bottles--lane-K-w4`), три коммита рецепта β + docs-коммит; заявка — `docs/handoffs/2026-11-22_camera-R4-merge-request.md`. **Слияние делает лид по слову координатора, не я.**
- Резервные ветки (можно удалить после слияния R4): `feat/camera-w4`, `feat/camera-w4-wip`, `feat/camera-r4-pre-review`. Лишние worktree К: `Inspector_bottles--lane-K-4c`, `Inspector_bottles--tester-4c`, `Inspector_bottles--day1` (закреплён за днём №1 — не трогать до слова координатора).

## Что осталось у полосы К
1. После слияния R4: дни с железом — читать `docs/claude/OPEN_QUESTIONS.md`, записи «полоса К · камера W4, К4'» (11 пунктов) и «полоса К · R4». Проверки на визите: цвет красного предмета, фактический `PixelFormat`, `TriggerMode`, `GainAuto`, размер пакета, перезахват close/open, v2 на роботе (T0.3/T4.0), `P_ZONE_MAX`, F7.
2. Ждёт владельца: M2 (`mono8` BGR или gray; откат дешёвый — убрать `GRAY2BGR` в `Services/hikvision_camera/plugin/plugin.py` `_build_item` и ввести `output_color`).
3. Необязательно, только при свободной К (слово координатора): C-106 — мост сеанса `camera_device.session` на `get_std_logger` (4 файла + тесты ядра), C-109 — вынести каркас `test_plugin_on_core.py` в `conftest.py`.
4. Не начато: расширение `exposure_time` `enabled_if={"exposure_auto": ["Off"]}`, `gain_auto` в `BINDINGS` (амендмент 4.1), «Применить» вкладки с `registers_manager.set_value` (m3), `CommandPanel` со старыми командами (A1).

## Уроки (дополнение к прошлому handoff)
- Интерактивный rebase без редактора: `GIT_SEQUENCE_EDITOR="sed -i '' 's/^pick/edit/'" git rebase -i <база>`, на каждом стопе правка + `git commit --amend` + `git rebase --continue`; комментарии, описывающие поведение ключа, проверять тестом на реальном коде, не словами (ключ `readiness` я описал наоборот — поймало ревью).
- `VAR=1 eval "$cmd"` в zsh не передаёт переменную дочернему процессу — писать `PYTHONPATH=$PWD UPDATE_BUILD_SNAPSHOTS=1 bash …` прямо.
- Пересборка golden: `UPDATE_BUILD_SNAPSHOTS=1 … test_build_characterization.py`; дифф смотреть `git diff multiprocess_prototype/backend/tests/snapshots/ | grep -E "^[+-] "`.
- Стенд для К4' на `driver: fake` — только рецепт `camera_device_demo` (базовый плагин); вендорский `hikvision` берёт порт `mvs`, без SDK headless-рецепты камеры не дают кадров (но процесс жив, `take_device` -> error, readiness `not_ready`).
- `frames` в дереве state публикуется тиком 5 с: fps считать по `get_status.frames`.
