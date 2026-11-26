# W1-a — бриф tester

Спавн: `python scripts/plans_ledger.py brief W1-a.tester --plan plans/2026-11-25_multicam-observability`. Worktree на коммите ДО реализации; код реализации закрыт.

TASK: W1-a — слепые приёмочные тесты личности прибора, выбора по подсети и здоровья потока (RED до кода)   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: tester
CHAIN: лид (бриф, стадия 0) -> tester -> developer (делает тесты зелёными) -> лид (инъекции, ревью)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. КОНТРАКТ (`Services.camera_device`, имена экспортированы и из `interface`): `DeviceInfo(serial, model="", ip="", mask="", host_ip="", mac="", pixel_format="", width=0, height=0, enum_matches=1, enum_list=())`; `entry_text(e) == f"ip={e.ip} mask={e.mask} host_ip={e.host_ip} mac={e.mac}"`; `select_device(ident, entries) -> (индекс, DeviceInfo)`; `AmbiguousDeviceError(PortError)`: `kind "not_found"`, `where "open"`. Политика: одна запись — она; несколько, из них в подсети камеры одна и больше — наименьший `host_ip`; несколько и ни одной в подсети — отказ. `RawFrame.lost_packets` (0), `RawFrame.trigger_index` (`None`). Фейк `make_port(..., enum_entries=..., frame_meta=...)`: `enum_entries` — перечисляемые записи; `frame_meta` — `(frame_num, lost_packets, trigger_index)` на i-й ОТДАННЫЙ кадр после `start_grabbing`; `port.device_info` — `None` до `open` и после `close`.
  2. Импорты новых имён — внутри теста (RED по поведению, не по сбору). Ожидания — литералы брифа. Новый `.py`: `__all__ = []`, строка `Purpose:`.
  3. Стенд плагина — настоящие объекты по образцу `Services/camera_device/tests/test_slice_plugin.py` (`_Rig`): `CameraDevicePlugin`, `PluginContext(services=MockProcessServices(...))`, настоящий `WorkerManager`, `plugin_base.create_port` подменён на `lambda driver: port`, `port = make_port(frame_period_s=0.02, ...)`, конфиг `device_select "serial"`, `device_serial "DA1689923"`. Строки лога — из журнала двойника `MockProcessServices` (`multiprocess_framework/modules/process_module/plugins/testing`); уровни — записи `publish_metric`; события — `state_proxy.merge` по образцу `Services/camera_device/tests/test_plugin_observability.py`. `plugin_base._TICK_S` подменить на `0.05`. Ожидание — с дедлайном; зависающий вызов — в daemon-потоке с `join(timeout)`.
  4. Записи: `A = DeviceInfo(serial="DA1689923", model="MV-CS020-10GC", ip="192.168.1.20", mask="255.255.255.0", host_ip="169.254.49.100", mac="00:11:1c:f6:a2:3b")`; `B` = `A` с `host_ip="192.168.1.100"`; `B2` = `A` с `host_ip="192.168.1.101"`; `D` = `A` с `host_ip="10.0.0.5"`. Тексты: `eA = "ip=192.168.1.20 mask=255.255.255.0 host_ip=169.254.49.100 mac=00:11:1c:f6:a2:3b"`, `eB`, `eB2`, `eD` — так же с их `host_ip`.
  5. Сценарии:
     - `test_select_device_one_in_subnet_among_duplicates`: `select_device(DeviceIdentity("serial","DA1689923"), (A, B))` -> индекс 1, `host_ip "192.168.1.100"`, `enum_matches 2`, `enum_list (eA, eB)`.
     - `test_select_device_lowest_host_ip_when_several_in_subnet`: `(B2, B)` -> индекс 1, `host_ip "192.168.1.100"`, `enum_matches 2`, `enum_list (eB2, eB)`.
     - `test_select_device_refuses_when_none_in_subnet`: `(A, D)` -> `AmbiguousDeviceError`, `str(exc) == "open: not_found: неоднозначное перечисление serial=DA1689923 записей=2, ни одна запись не в подсети камеры; записи: " + eA + " | " + eD`; то же через `DeviceIdentity("ip","192.168.1.20")` -> текст начинается `open: not_found: неоднозначное перечисление ip=192.168.1.20 записей=2`; `(B,)` с `DeviceIdentity("serial","X1")` -> `PortError` `kind "not_found"`, не `AmbiguousDeviceError`.
     - `test_single_entry_outside_subnet_used_with_warning`: `select_device` на `(A,)` -> индекс 0, `enum_matches 1`; плагин на `enum_entries=(A,)` -> одна WARNING `CameraDevicePlugin: serial=DA1689923 единственная запись вне подсети камеры: ` + eA; захват идёт.
     - `test_duplicate_enumeration_warning_and_identity_block`: плагин на `(A, B)` -> ровно одна WARNING `CameraDevicePlugin: serial=DA1689923 перечислен 2 раз; выбрана запись host_ip=192.168.1.100; записи: ` + eA + ` | ` + eB; событие `identity`: `host_ip "192.168.1.100"`, `mac "00:11:1c:f6:a2:3b"`, `enum_matches 2`, `enum_list [eA, eB]`.
     - `test_ambiguous_enumeration_gives_not_found_with_list`: плагин на `(A, D)` -> событие `state` `"not_found"`, `last_error` содержит `host_ip=169.254.49.100` и `host_ip=10.0.0.5`.
     - `test_lost_frames_incomplete_lost_packets`: `frame_meta=((1, 0, None), (2, 3, None), (5, 0, None))` -> уровни `lost_frames 2`, `incomplete 1`, `lost_packets 3`; команда `reset_stats` -> следующее окно: все три `0`.
     - `test_trigger_lost_counts_index_gaps`: `frame_meta=((1, 0, 10), (2, 0, 11), (3, 0, 14))` -> `trigger_lost 2`, `lost_frames 0`.
     - `test_stream_block_and_open_info_line`: плагин на `(B,)` -> событие `stream == {"pixel_format": FRAME_PIXEL_FORMAT, "width": FRAME_WIDTH, "height": FRAME_HEIGHT}` (константы модуля `fake_port` — данные фейка); ровно одна INFO `CameraDevicePlugin: device opened serial=DA1689923 model=MV-CS020-10GC ip=192.168.1.20 mask=255.255.255.0 host_ip=192.168.1.100 mac=00:11:1c:f6:a2:3b pixel_format=<FRAME_PIXEL_FORMAT> width=<FRAME_WIDTH> height=<FRAME_HEIGHT> enum_matches=1`; WARNING нет.
     - `test_fake_device_info_lifecycle`: `make_port()` -> `device_info is None`; `open(DeviceIdentity("serial","00DB2156580"))` без `enum_entries` -> открыт, `device_info.serial "00DB2156580"`; `close()` -> `None`; `isinstance(port, DevicePort)` до `open` истинно.

FORBIDDEN PATHS (no edits, no reads of implementation): Services/camera_device/interface.py, Services/camera_device/__init__.py, Services/camera_device/plugin_base.py, Services/camera_device/testing/fake_port.py, Services/camera_device/tests/test_stream_health_hazards.py, Services/hikvision_camera/driver.py, plans/2026-11-25_multicam-observability/tasks/W1-a.md, plans/2026-11-25_multicam-observability/tasks/W1-a2.md, docs/reviews/2026-11-25_obs-audit-multicam.md, docs/reviews/2026-11-25_obs-audit-multicam-2-control-tasks.md, docs/reviews/2026-11-25_obs-audit-multicam-3-reliability-cto-map.md
FILES (complete list — nothing else; need another file -> stop and report):
  1. Services/camera_device/tests/test_identity_stream_contract.py — new

REDS (expected RED before code):
  - Services/camera_device/tests/test_identity_stream_contract.py::test_select_device_one_in_subnet_among_duplicates
  - Services/camera_device/tests/test_identity_stream_contract.py::test_select_device_lowest_host_ip_when_several_in_subnet
  - Services/camera_device/tests/test_identity_stream_contract.py::test_select_device_refuses_when_none_in_subnet
  - Services/camera_device/tests/test_identity_stream_contract.py::test_single_entry_outside_subnet_used_with_warning
  - Services/camera_device/tests/test_identity_stream_contract.py::test_duplicate_enumeration_warning_and_identity_block
  - Services/camera_device/tests/test_identity_stream_contract.py::test_ambiguous_enumeration_gives_not_found_with_list
  - Services/camera_device/tests/test_identity_stream_contract.py::test_lost_frames_incomplete_lost_packets
  - Services/camera_device/tests/test_identity_stream_contract.py::test_trigger_lost_counts_index_gaps
  - Services/camera_device/tests/test_identity_stream_contract.py::test_stream_block_and_open_info_line
  - Services/camera_device/tests/test_identity_stream_contract.py::test_fake_device_info_lifecycle

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/camera_device/tests/test_identity_stream_contract.py

OUT OF SCOPE: драйвер `mvs` (W1-a2), реализация, существующие тесты пакета.
REPORT: STATUS (DONE|BLOCKED), files, число собранных и красных; RED падает внутри теста, не на сборе.
