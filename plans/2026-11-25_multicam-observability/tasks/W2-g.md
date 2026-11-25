# Task W2-g: выбор камеры по ip/index через сеанс и ожидаемая карта ПК (`device_host_ip`)

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Module contract:** impl-only (новое поле регистра `device_host_ip`; путь `device_select ip|index` — существующий контракт)
- **Dependencies:** W2-a, W2-a1, W2-a2 (те же `session.py`, `plugin_base.py`, `registers_base.py`; та же ветка, после них)
- **Gate:** `machine_gate.sh light <session>` по файлам TESTS; радиус `Services/camera_device/tests` (medium)
- **Files:** `Services/camera_device/session.py`, `Services/camera_device/plugin_base.py`, `Services/camera_device/registers_base.py`, `Services/camera_device/tests/test_device_select_session.py`
- **Acceptance:** блок ACCEPTANCE
- **Handoff:** developer (REDS в брифе, красный прогон до правки src, break-injection) -> reviewer (стадия 5, sonnet)

Основание. Ревью W1-a: `device_select ip/index` через `DeviceSession` не открывается никогда — `_resolve_ident` сравнивает `(kind, value)` (`session.py:598-601`), а перечисление отдаёт `kind "serial"`, если серийник есть (`driver.py:219`, фейк `fake_port.py:185-186`); `index` не совпадает никогда (Explore-карта, `mco-d-w1-a`). Публичный путь без живого вызова — контракт (принцип 3): чинится, не удаляется. Вариант C решения владельца 4 («ожидаемый адрес в рецепте как контракт»): поле `device_host_ip`.

TASK: W2-g — `_resolve_ident` выбирает запись по запрошенному виду; `device_host_ip` сужает выбор до карты ПК   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: developer
CHAIN: lead -> you -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `session.py`, `_resolve_ident`: сравнение по запрошенному виду, а не по виду записи. `serial` -> запись, чей серийник равен значению; `ip` -> запись, чей IP равен значению (IP записи — из записей перечисления W1-a, поле `ip`; у `DeviceIdentity` без IP — из соответствующей записи `enum_entries`); `index` -> `found[int(value)]` в порядке перечисления, вне диапазона -> `PortError("not_found", "enum_devices")`.
  2. `registers_base.py`: `device_host_ip: str = ""` (`FieldMeta("IP карты ПК", info="Ожидаемый адрес сетевой карты ПК для этой камеры; пусто — политика подсети")`), без `apply`.
  3. `device_host_ip` не пуст -> из совпадений по п.1 остаются записи с этим `host_ip`; ни одной -> `PortError("not_found", "enum_devices")` и WARNING `session: камера <вид>=<значение> не видна через карту <device_host_ip>; видна через: <список host_ip>`. Пусто -> политика подсети W1-a без изменений.
  4. `plugin_base.py`: передать `device_host_ip` сеансу там же, где идентичность (`plugin_base.py:400-403`).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. Services/camera_device/session.py — `_resolve_ident`
  2. Services/camera_device/plugin_base.py — передача `device_host_ip`
  3. Services/camera_device/registers_base.py — поле
  4. Services/camera_device/tests/test_device_select_session.py — новый

REDS (predicted red tests):
  - Services/camera_device/tests/test_device_select_session.py::test_select_by_ip_opens_through_session
  - Services/camera_device/tests/test_device_select_session.py::test_select_by_index_opens_second_device
  - Services/camera_device/tests/test_device_select_session.py::test_index_out_of_range_is_not_found
  - Services/camera_device/tests/test_device_select_session.py::test_host_ip_narrows_double_enumeration (две записи одного serial, `host_ip` 169.254.49.100 и 192.168.1.100, `device_host_ip "169.254.49.100"` -> открыта запись .49.100, без отказа)
  - Services/camera_device/tests/test_device_select_session.py::test_host_ip_not_seen_refuses_with_list

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short Services/camera_device/tests/test_device_select_session.py` -> exit 0
  - радиус `Services/camera_device/tests` (medium) -> красные = снимок лида; `ruff check -q` по четырём путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/camera_device/tests/test_device_select_session.py

OUT OF SCOPE: рецепт (W2-h); драйвер.
TRAPS: имя поля IP записи и `host_ip` — как в W1-a (`enum_entries` фейка, `DeviceInfo`); не вводить второго имени. Переподключение W2-a идёт через тот же `_resolve_ident` — выбор должен совпадать с первым открытием.
HANDOFF IN: W2-a, W2-a1, W2-a2 — последние версии `session.py`, `plugin_base.py`.
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
