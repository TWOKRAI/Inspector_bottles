# Task W2-q: команда `fake_cable` — вынуть и вставить кабель фейк-порта в живом процессе (ч.1 из 2)

- **Статус:** [PENDING] · **Level:** Middle · **Assignee:** developer
- **Module contract:** public-api-change (новая команда в `CameraDevicePlugin.commands`; `interface.py`/`__init__.py` не меняются)
- **Dependencies:** нет (на `integ` есть `FakePort.disconnect/restore`, `link`, поля `reconnect`/`link_silence_s`/`reconnect_interval_s`). Последовательно с W2-g: оба правят `Services/camera_device/plugin_base.py` — одна ветка, порядок решает лид.
- **Gate:** `machine_gate.sh light <session>` по TESTS; радиус `Services/camera_device/tests` и `Services/hikvision_camera/tests` (medium)
- **Files:** `Services/camera_device/plugin_base.py`, `Services/camera_device/README.md`, `Services/camera_device/tests/{test_fake_cable_command.py,test_plugin_commands.py,test_plugin_device_commands.py}`, `Services/hikvision_camera/tests/test_plugin_on_core_contract.py`
- **Acceptance:** блок ACCEPTANCE
- **Handoff:** developer (REDS в брифе, красный прогон до правки src, break-injection) -> reviewer (стадия 5, sonnet)
- **Параллельно с:** W2-c2, W2-c3, W2-r. **Следом:** W2-q2 (рецепт `fake_quad_synth`; файлы не пересекаются, но ручная приёмка рецепта нужна с командой).

Сегодня: `FakePort.disconnect()`/`restore()` (`Services/camera_device/testing/fake_port.py:251-258`) зовут только тесты; ни команды, ни регистра, ни переменной окружения нет. Команды плагина — словарь `commands` (`plugin_base.py:225-235`, 9 имён), регистрирует их база (`multiprocess_framework/modules/process_module/plugins/base.py:1775-1789`). Плагин держит порт в `self._port` (`plugin_base.py:806-815`), тот же объект — у сеанса (`plugin_base.py:842`). `HikvisionCameraPlugin` наследует набор команд — получит `fake_cable` и отказ на настоящем порте. Регистр `driver` у настоящего Hikvision может быть `"fake"` — по нему защищаться нельзя и печатать его нельзя. Решение владельца 5: без железа всё принимается на синтетике.

TASK: W2-q — команда `fake_cable {"plugged": bool}` в `CameraDevicePlugin`: вынимает/вставляет кабель фейк-порта в работе; на любом другом порте и без порта — отказ   PLAN: plans/2026-11-25_multicam-observability/plan.md (П2, П4)
ROLE: developer
CHAIN: lead -> you -> reviewer (стадия 5) ; потребитель: W2-q2
DESIGN (decided by the lead — you type it, you do not derive it):
  1. `plugin_base.py`:
     a. `commands`: добавить `"fake_cable": "cmd_fake_cable"` последней строкой. Докстринг класса (список команд) — строка `fake_cable`.
     b. Докстринг модуля (абзац `plugin_base.py:41-44` про «порт и SDK зовёт только тот поток, который их держит») — строка-исключение: `fake_cable` ставит флаги фейк-порта из потока команды (присваивание `bool`, читает поток-владелец, `fake_port.py:243-245`); SDK не зовётся.
     c. `cmd_fake_cable(self, data: dict) -> dict` рядом с `cmd_reset_stats` (`plugin_base.py:928`), вид ответа — как у соседних `cmd_*` (повторить, не придумывать):
        - ленивый импорт `from .testing.fake_port import FakePort` ВНУТРИ команды (ядро не тянет фейк без нужды, как `create_port`);
        - `port = self._port`; `port is None` -> отказ «fake_cable: порт ещё не создан (сначала take_device)»; порт НЕ создавать (`_ensure_port` не звать);
        - `not isinstance(port, FakePort)` -> отказ `f"fake_cable: только для порта fake (порт плагина — {type(port).__name__})"`; ни один метод порта не вызывать. Регистр `driver` в тексте не печатать;
        - `plugged = (data or {}).get("plugged")`; `type(plugged) is not bool` (отсекает `0`, `1`, `"no"`, `None`) -> отказ «fake_cable: plugged: true|false»;
        - `False` -> `port.disconnect()`; `True` -> `port.restore()`; лог WARNING `"имитация: кабель фейк-порта вынут"` / `"имитация: кабель фейк-порта вставлен"` (слово «имитация» обязательно: строка не должна читаться как настоящий обрыв);
        - ответ `{"success": True, "plugged": plugged}` (ключи успеха — как у соседних).
        - Сеанс, замки, `_session` НЕ трогать. В `run_locked_commands` команду НЕ добавлять: она нужна в работе.
  2. `README.md`: в таблице/списке команд — `fake_cable {plugged: bool}`: «только фейк-порт; на ином порте и без порта отказ; имитация обрыва для приёмки без железа; перезапуск процесса = кабель вставлен (флаги живут в объекте порта)». В строку «Не блокируются …» (`README.md:323`) добавить `fake_cable`.
  3. Пины набора команд 9 -> 10 (лид разрешает правку литералов, только эти): `Services/camera_device/tests/test_plugin_commands.py:581,583` (ожидаемый словарь + `"fake_cable": "cmd_fake_cable"`); `Services/camera_device/tests/test_plugin_device_commands.py:406,410,414,426` (в `:414` литерал `11 -> 12`; имя теста `:409` «одиннадцать» -> «двенадцать»; «девять» в `test_plugin_commands.py:568` переименовать по тексту; множество `NINE` -> добавить `fake_cable`; имя константы и тестов с «девять» — переименовать в «десять» по тексту, не логику); `Services/hikvision_camera/tests/test_plugin_on_core_contract.py:69` (`NEW_COMMANDS` + `fake_cable`).
FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. Services/camera_device/plugin_base.py — `commands`, докстринги, `cmd_fake_cable`
  2. Services/camera_device/README.md — строка команды, «Не блокируются»
  3. Services/camera_device/tests/test_fake_cable_command.py — новый
  4. Services/camera_device/tests/test_plugin_commands.py — пин набора
  5. Services/camera_device/tests/test_plugin_device_commands.py — пин набора
  6. Services/hikvision_camera/tests/test_plugin_on_core_contract.py — пин набора
REDS (predicted red tests):
  - Services/camera_device/tests/test_fake_cable_command.py::test_refused_on_foreign_port (порт-заглушка не `FakePort`, С методами `disconnect`/`restore`, которые пишут вызовы в список; регистр `driver "fake"`; `{"plugged": False}` и `{"plugged": True}` -> оба `success False`, текст содержит `"только для порта fake (порт плагина — "` и имя класса заглушки, НЕ содержит `"драйвер"`; список вызовов пуст)
  - …::test_refused_without_port (`self._port is None` -> текст `"fake_cable: порт ещё не создан (сначала take_device)"`; после вызова `_port` всё ещё `None`)
  - …::test_bad_plugged_refused (`{"plugged": "no"}`, `{}`, `None` как `data`, `{"plugged": 0}`, `{"plugged": 1}` -> `success False`; флаги фейка `_link_down`/`_stale_stream` не изменились)
  - …::test_pull_then_restore_with_reconnect_returns_frames (настоящий плагин + `DeviceSession` + фейк, `reconnect True`, `link_silence_s` малое > 0, `reconnect_interval_s >= 0.5`: кадры идут -> `plugged False` -> `link.state "lost"` за дедлайн -> `plugged True` -> `link.state "up"`; `frames` растёт при вызовах `produce()` из теста)
  - …::test_pull_without_reconnect_stays_lost (`reconnect False`: `plugged False` -> ждать `link.state "lost"` -> `plugged True` -> 3 с `link.state` остаётся `"lost"`; `frames` не растёт при вызовах `produce()`)
  - …::test_command_not_run_locked (на `_Rig` из `test_run_locked_commands_camera.py:68` с взведённым запретом прогона: контроль — `release_device` отвечает `_REFUSAL` (`:32`); `fake_cable {"plugged": False}` через `cm.handle_command` -> `success True`)
  - Services/camera_device/tests/test_plugin_commands.py::<тест набора `:581-583`> (красный до правки пина)
  - Services/camera_device/tests/test_plugin_device_commands.py::<тесты `:406`, `:410`, `:414`, `:426`> (красные до правки пина)
  - Services/hikvision_camera/tests/test_plugin_on_core_contract.py::test_команды_плагина_ровно_девять_имён_ядра (красный до правки пина; новое имя — «десять»)
ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short Services/camera_device/tests/test_fake_cable_command.py` -> exit 0, 6 passed
  - medium: `<py> -m pytest -q --tb=short Services/camera_device/tests Services/hikvision_camera/tests` -> красные те же, что в снимке лида до правки (новых нет)
  - `ruff check -q` по путям .py -> 0
  - Слой: `git grep -nE "^\s*(from|import) +multiprocess_prototype" -- Services/camera_device` -> пусто (простой `git grep multiprocess_prototype` даёт строки текстов — не годится)
  - Break-injection (предсказания лида): `flag_check_instead_of_isinstance` (проверка `self._reg.driver == "fake"`) -> `test_refused_on_foreign_port`; `hasattr_guard` (проверка `hasattr(port, "disconnect")`) -> `test_refused_on_foreign_port`; `restore_calls_disconnect` -> `test_pull_then_restore…`; `truthy_plugged` (`bool(plugged)`) -> `test_bad_plugged_refused`; `ensure_port_on_none` -> `test_refused_without_port`; `command_not_in_commands` (метод есть, в `commands` нет) -> `test_command_not_run_locked` и пины набора
TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/camera_device/tests/test_fake_cable_command.py
OUT OF SCOPE: рецепт `fake_quad_synth` (W2-q2); кнопка в GUI (карточки W2-r — только показ; кнопки — следующая задача по слову владельца); имитация обрыва считывателя (П4 п.8); разные `serial`/`ip` у фейков (`fake_port.py:69,324`); событие SDK `0x8001` у фейка (`LinkEventFakePort` — только тесты); политика прогона (Р-W2-1); смена умолчания `link_silence_s` (решение владельца: 0 — отдельная правка; тест задаёт поле явно).
TRAPS: имя команды снаружи — голое `fake_cable`: `send_command("cam_0", "fake_cable", {"plugged": False})`. `restore()` сам кадры не возвращает: поток умер, нужен новый `open` (`fake_port.py:255-257`) — без `reconnect` камера НЕ вернётся, это и есть приёмка П2. При `link_silence_s 0` (новое умолчание владельца) потеря не объявляется — тест задаёт `link_silence_s > 0` явно. Кадры в тесте растут только от вызовов `produce()`. Тест с потоком-владельцем — вызов в daemon-потоке с дедлайном join.
HANDOFF IN: W2-a/W2-a1 — `link` в дереве, поля `reconnect`, `link_silence_s`, `reconnect_interval_s`; W1-a — `FakePort.disconnect/restore`.
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
