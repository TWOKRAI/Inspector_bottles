# Handoff полосы К «W3 camera-device-service» — 2026-11-17

Лид К = сессия `inspector-bottles-20`. Координатор `inspector-bottles-26`, лид Ф `inspector-bottles-91`. Владелец русскоязычный; все ответы по-русски. Промпт полосы: `docs/handoffs/2026-11-16_lane-prompt-K-W3.md` (лежит только в worktree `.claude/worktrees/coord-prompts-1115`). План: `plans/2026-10-18_camera-device-service/` (`plan.md`, `matrix.md`, `wave-protocol.md`, `amendments.md`, `tasks/*.md`).

## Остановка (что владелец велел)

Владелец сказал: «после этого отчёт, коммит и тормози». Новая сессия сама ничего не запускает дальше пунктов 1–3 ниже без подтверждения владельца.

## Где что лежит

| Что | Где | Состояние |
|---|---|---|
| main | `e925ddb85` предок всех веток | в нём: 0.5, 2.3a(+4.1), 2.3b, 2.4 (2.4a+2.4b) |
| docs + стенд камеры | `feat/camera-device-w3`, дерево `.claude/worktrees/cam-w3` | чисто; docs-коммиты, стенд `camera_device_demo` (`8e976795b`), разрез 2.3c/2.3d (`b41f1575f`) |
| 2.3c | `feat/camera-2-3c`, дерево `cam-2-3c-dev`, HEAD `bb7ac56e5` | код + 2 раунда ревью Opus, правки сделаны; вердикта APPROVED по раунду 2 ещё нет |
| 2.3d | `feat/camera-2-3d`, дерево `cam-2-3d-dev`, HEAD `656d33eb5` (содержит 2.3c) | код, слепой файл (30) и hazard-тесты закоммичены; ревью Opus раунд 1 = CHANGES REQUESTED; правки НЕ закоммичены |

Временные деревья, которые надо удалить в конце волны: `cam-2-3c-tester`, `cam-2-3d-tester`, `cam-2-3c-inj`, `cam-2-4b-dev` и т. п. (`git worktree list`).

## Статус 2.3d на момент остановки

Незакоммичено в `cam-2-3d-dev` (проверь `git status --short`):
- Доки от `tech-writer` (готово, `validate.py` чист): `Services/camera_device/README.md`, `DECISIONS.md` (ADR-CAM-002 «Уточнение 2.3d»), `STATUS.md`, `plans/…/tasks/2.3d.md` (имена файлов тестов).
- Правки developer 2.3d (агент `a91a80cf1a3820227` на момент написания ещё работал, итерация 4): `plugin_base.py` (`bindings()` под `try`), `tests/test_live_apply_hazards.py`, `tests/test_live_apply_session.py`, `tests/test_plugin_device_commands_hazards.py`.
- Отчёт ревьюера: `docs/reviews/2026-11-16_plan-camera-device-service_task-2.3d-reviewer-opus.md` (untracked).

Задание developer (итерация 4, по ревью Opus):
1. Тест сторожа `test_live_apply_hazards.py` ~строка 321: взводить флаг ВНУТРИ `fn` (иначе мутация «сброс `_current` только для `call`» M12 выживает). Контроль зелёный, D10 и M12 красные.
2. Флейки 2.4a: `test_live_apply_session.py:178` и `test_live_apply_hazards.py:521` читают `rig.events` раньше, чем `on_state` отработал после замка (`session.py:533`, `:592-593`); сравнивать через `_await(...)` с дедлайном.
3. Тест ветки `describe_param → None → null`.
4. Тест «один `call` на `describe_params`» (нет `get_frame` между первой и последней записью `describe_param`; мутация M10 красная).
5. `self.bindings()` в `cmd_describe_params` внутрь `try`.
Контроль у developer: каталог `Services/camera_device/tests` 3 раза подряд зелёный, ruff, прогон D1–D10 целиком; раздел «Итерация 4» в `…2.3d-developer.md`.

## Что делать дальше, по порядку (после подтверждения владельца)

1. Дождаться отчёта developer `a91a80cf1a3820227` (`ListAgents`; если агента нет — свежий developer с брифом: отчёт `…2.3d-developer.md` + список выше + дифф).
2. Проверить сам: `git status`, каталог `Services/camera_device/tests` через `machine_gate.sh medium inspector-bottles-20 …` (ожидание: 368+ passed, 10 skipped; новые тесты добавят число), hikvision_camera + `test_one_connector_per_point` (306 passed / 15 skipped).
3. Поправить числа тестов в `Services/camera_device/STATUS.md` (там счёт `grep -c "def test_"`: 2.3c 33+17, 2.3d 30+11; у ревьюера 12 hazard-тестов у автора — выяснить), закоммитить в `feat/camera-2-3d` двумя коммитами: тесты/код (`fix(camera_device): …`) и доки (`docs(camera_device): …`); сообщение — файлом (`git commit -F`), трейлеры `Why:`, `Layer:`, `Refs: plans/2026-10-18_camera-device-service/plan.md`, `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; тема ≤ 72 символов (предупреждение хука не блокирует, но лучше короче).
4. Ревью Opus раунд 2 по 2.3d: `SendMessage` ревьюеру `a2bd8e0996027e902` (re-summon; его спенд 188k — норма) с диффом правок. Раунд 2 — последний; третья итерация → teamlead.
5. 2.3c: раунд 2 ревью `ad3e1c8a3f510004f` дал последнюю находку (тест окна fps на Windows), она исправлена (`bb7ac56e5`); попросить у него подтверждение APPROVED коротким прогоном.
6. Слияние в main: актуализировать main в ветки, прогнать camera_device/hikvision_camera/test_one_connector_per_point, прислать координатору 26 HEAD для ff (сначала `feat/camera-2-3c`, затем `feat/camera-2-3d`, и docs из `feat/camera-device-w3`). Слот `machine_gate merge-begin/merge-end` берёт сам координатор по правилам. Сводные файлы (ORDER.md, индекс ADR, `scripts.sync`) правит слот слияния; `scripts.sync` в 2.3d-ветке ничего не изменил в отслеживаемых файлах.
7. 2026-11-21: таблица координатору «готово/в работе/блокер» по 0.5/2.3a/2.3b/2.4/4.1 (+2.3c/2.3d); без прогноза «успеем».
8. Дальше W4: 4.2a (deps 0.2, 2.3c, 2.3d, 2.4a, 2.4b, 4.1), …6.3. 3.1/3.2/3.3/6.4 вне 1.0.

## Результаты break-injection 2.3d (для отчёта волны)

Прогнозы закоммичены ДО прогона (`d16a0442c`), факт — `…2.3d-injections.md` и `…2.3d-injections-run.md`. D1–D6, D8 совпали; D7 частично (прогноз неполный, красные закономерны); D9 выжила как предсказано (замок `refs` фейка, под GIL не ловится); D10 выжила (пробел теста) → закрыто `656d33eb5`; M12 нашёл ревьюер, правка в итерации 4.

## Пронесённый риск и открытое

- Нагрузочные флейки 2.4a: найден механизм (ревью п.3), правка в итерации 4; если красные вернутся — сохранить текст ошибки.
- Гонка `start()` против `acquire` на пути 2 `list_devices` по чтению недостижима (ревью Opus: `start()` только из `cmd_take_device`, до запуска `message_processor`); не воспроизведено, замка нет — не гарантия.
- Блокировка приёма команд до ~7 с (`_CALL_TIMEOUT_S` 2,0 + `watchdog_s` 5,0) — расчёт, в живом процессе не мерено.
- Безопасность `MV_CC_EnumDevices` при открытом handle (межпроцессно) не измерена.
- `on_device` в opening/busy/error не прогонялся; `process.pause` не меняет статус (проверка правки «в паузе» не сделана); таймаут `opening` — в `docs/claude/OPEN_QUESTIONS.md`.
- Вопросы владельцу: цвет `rgb8`/BGR и дебайер (до 4.2a); 8 вопросов по дню №1 на железе; `contract.lock`; многокамерность в одном процессе (в OPEN_QUESTIONS, спрашивал владелец 11-16 — ответ про независимые процессы и опцию нескольких в одном дан, решение владельца ждёт).
- Мутация «сброс `_current` только для `name == "call"`» (M12): после итерации 4 должна краснеть; проверить в отчёте developer.
- `amendments.md`, амендмент 6: историческая строка про исключение Р1 не переписана; тексты 2.3a/2.4b/2.4 местами «команды Р7 → 2.3c».
- Заметка: гонка `publish_metric("frames", 0)` принята.

## Стыки с лидом Ф (`inspector-bottles-91`)

- Пульт S5 и run-state (2.7–2.9, П3) — их задачи, не мои. Правок в `state_store_module`, `state_proxy`, `bindings.py`, пульте у меня нет.
- Проверено ими запуском: `merge` на узле `processes.<p>.state.plugins.camera_device` с dict-ключами при П3 соседей не затирает; код камеры менять не надо. Когда П3 войдёт в main, Ф пингует; мой ход — камерный стенд на фейке (`state_get_subtree` по плагину) с числом.
- Ф пришлёт файлом контракт readiness для плагина камеры (4.2a): хук `readiness(ctx)` → `[{severity, reason}]`, ключ `run_locked_commands` в config плагина, политика `readiness: {hold_s, severity}` в YAML рецепта; ориентир 18–19.11. Место под readiness в `plugin_base.py` — ниже `cmd_get_status`.
- Мой список `run_locked_commands` (предложение, итог за владельцем): блокировать в running `release_device`, `take_device`; не блокировать `apply_params`, `read_params`, `get_status`, `list_devices`, `describe_params`, `reset_stats`, `trigger_software`.

## Таблица agentId (re-summon по agentId, не по имени)

| Роль | agentId |
|---|---|
| developer 2.3b/2.4b | `a9bfbf8fc8ff5ec37` |
| developer 2.4a | `a310dbbbbf72101a2` |
| developer 2.3c | `a9a565ebc1e76137f` |
| developer 2.3d (spend ~190k) | `a91a80cf1a3820227` |
| tech-writer (доки 2.3c/2.3d; spend ~270k) | `a610bffcff3f31e20` |
| reviewer sonnet 2.3b | `a2af58fcaa90d6bbe` |
| reviewer opus стадия 0 2.4 | `a2805f1062be6288d` |
| reviewer opus ревью 2.4 | `acd15802fc6b334a2` |
| reviewer sonnet стадия 0 2.3c/2.3d | `ad026f16780a9cfb7` |
| reviewer opus ревью 2.3c | `ad3e1c8a3f510004f` |
| reviewer opus ревью 2.3d | `a2bd8e0996027e902` |
| tester 2.4a / 2.4b | `ad7b092eaa8f9ede1` / `a974f5666f35c58d1` |
| tester 2.3c / 2.3d | `a884b057659a53cf1` / `af955ed0bdfbe6690` |
| Haiku мутации 2.3b / 2.4a / 2.3c / 2.3d | `a554bc2155ef76b31` / `a93efd3c19cd6dba5` / `aefd788e998aeb2ca` / `a118fd4d784f93584` |
| стенд 2.4 | `afe3e70128ab55a39` |
| диагностика метрик | `a8cfb1097eabd925f` |

Скрипты мутаций: `scratchpad/inj_23c.py`, `scratchpad/inj_23d.py` (сессионный scratchpad может быть очищен; при потере — восстановить из отчётов `…injections.md`).

## Правила, которые держать

- Конвейер задачи: стадия 0 → слепой tester до кода → developer → break-injection (прогнозы коммитом ДО прогона; механика Haiku) → ревью Opus → правки автором; лимит 2 итерации, третья → teamlead. Слепой файл автор не правит.
- Любая команда с pytest — через `machine_gate.sh [--timed] heavy|medium|light inspector-bottles-20 <cmd>`; без `machine.lock` — falls back на `stand.lock`. В worktree: основной `.venv` + `PYTHONPATH=<корень worktree>`; никогда `uv sync`.
- Windows: `time.monotonic` шаг 15,6 мс на Python 3.12 — тесты окон ждут больше шага часов.
- Субагенты не коммитят и не пушат; коммитит лид (хук `protect-branch` режет коммиты субагентов в worktree). `git add` явными путями, после коммита `git show --stat HEAD`.
- Агентам при брифах не по шаблону TDD — строка `BRIEF-OVERRIDE: <причина>`.
- MEMORY LESSONS от ревьюеров (записать в `docs/claude/memory/` в конце волны): «пробная запись пакета должна повторять каждый запрещающий шаг боевой записи (права поля `can_modify`)» и «тест окна ждёт дольше шага часов».
- В конце волны: отчёт `docs/reports/<дата>_camera-device-service_W3.md` (по-русски, числа, «что осталось открытым», таблица agentId), handoff `docs/handoffs/<дата>_camera-wave3-done.md`, метрики волны, удалить временные worktrees.
