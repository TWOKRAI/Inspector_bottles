# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты C10.1: ``cam_cfg.py`` — чтение/запись любых узлов ID3013 с сохранением
исходного и откатом. Написаны ДО реализации по брифу (строки приёмки A1-A10).

Контракт, который проверяется (шов для тестов):
  * ``cam_cfg.main(argv, *, api=None, orig_path=None) -> int``; ``api`` заменяет ``MvCodeReaderApi()``,
    ``orig_path`` заменяет константу ``ORIG``; вывод — в stdout;
  * ``get <ip> NODE:TYPE ...`` — только чтение, строки ``GET <node> = <v>`` / ``GET <node> = ERR <msg>``;
  * ``set <ip> NODE:TYPE=VALUE ...`` — в порядке аргументов: прочитать, сохранить исходное в orig-файл
    (файл записан ДО вызова setter), записать, прочитать обратно, напечатать строку ``SET <node>: ...``;
    первое исходное не перезаписывается; первый отказ setter — стоп и код 1;
  * ``revert <ip>`` — все сохранённые узлы в ОБРАТНОМ порядке сохранения; ``value: null`` пропускается
    строкой ``SKIP <node>``; старый формат (плоские значения) работает с типами enum/enum/int;
  * дескриптор закрывается ровно один раз за запуск, в т.ч. при отказе setter;
  * неизвестный TYPE -> ненулевой выход до открытия прибора.

Все тесты идут на фейке ``FakeApi`` (состояние узлов по ip, запись меняет чтение, журнал вызовов с порядком).
К настоящим приборам тесты не обращаются.

ПРЕДПОЛОЖЕНО (бриф молчит; одно место правки — константы/хелперы ниже):
  * ``GET`` для enum печатает ``cur`` (целое), для int/float — ``cur``;
  * ненулевой выход — либо возвращённый код, либо ``SystemExit`` с ненулевым кодом (хелпер ``run`` сводит оба);
  * ``err`` в orig-файле содержит текст исключения (проверка по вхождению).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from Services.code_reader.tools import cam_cfg

IP = "192.168.1.10"
OTHER_IP = "192.168.1.20"

# узел -> (вид, значение): состояние каждого прибора на старте
DEFAULT_NODES = {
    "TriggerMode": ("enum", 0),
    "TriggerSource": ("enum", 0),
    "TriggerSelfTriggerPeriod": ("int", 300),
    "ExposureTime": ("float", 1000.0),
    "LightEnable": ("bool", False),
}
ENUM_NAMES = {"Off": 0, "On": 1, "SelfTrigger": 7}


class FakeApi:
    """Фейк ``MvCodeReaderApi``: состояние узлов по ip, запись меняет чтение, журнал вызовов с порядком."""

    def __init__(self, orig_path):
        self.orig_path = orig_path
        self.state = {ip: dict(DEFAULT_NODES) for ip in (IP, OTHER_IP)}
        self.devices = [
            SimpleNamespace(ip=OTHER_IP, model="ID3013-B"),
            SimpleNamespace(ip=IP, model="ID3013"),
        ]
        self.fail_set: set[str] = set()  # setter этого узла всегда отказывает
        self.fail_get: set[str] = set()  # getter этого узла всегда падает
        self.fail_get_once: set[str] = set()  # первый getter этого узла падает, дальше читает
        self.calls: list[tuple] = []  # ("open", ip) / ("get_int", node) / ("set_int", node, value) / ("close", ip)
        self.orig_at_set: list[tuple[str, dict | None]] = []  # (узел, содержимое orig-файла в момент set_*)
        self.handle_ip: dict[int, str] = {}
        self.handles_used: list[int] = []
        self.closed: list[int] = []

    # --- устройства ---
    def enum_devices(self):
        self.calls.append(("enum_devices",))
        return list(self.devices)

    def open(self, entry):
        self.calls.append(("open", entry.ip))
        h = 1000 + len(self.handle_ip)
        self.handle_ip[h] = entry.ip
        return h

    def close(self, h):
        self.calls.append(("close", self.handle_ip[h]))
        self.closed.append(h)

    # --- чтение ---
    def _node(self, h, node, kind, verb):
        self.handles_used.append(h)
        ip = self.handle_ip[h]  # KeyError = вызов с чужим/закрытым handle
        if node not in self.state[ip]:
            raise RuntimeError(f"нет узла {node}")
        have = self.state[ip][node][0]
        if have != kind:
            raise TypeError(f"{verb}: узел {node} имеет вид {have}, а не {kind}")
        return ip

    def _get(self, kind, h, node):
        self.calls.append((f"get_{kind}", node))
        ip = self._node(h, node, kind, f"get_{kind}")
        if node in self.fail_get:
            raise RuntimeError("node unreadable")
        if node in self.fail_get_once:
            self.fail_get_once.discard(node)
            raise RuntimeError("node unreadable")
        return self.state[ip][node][1]

    def get_int(self, h, node):
        v = self._get("int", h, node)
        return {"cur": v, "min": 0, "max": 10000, "inc": 1}

    def get_float(self, h, node):
        v = self._get("float", h, node)
        return {"cur": v, "min": 0.0, "max": 1e6}

    def get_enum(self, h, node):
        v = self._get("enum", h, node)
        return {"cur": v, "supported": [0, 1, 7]}

    def get_bool(self, h, node):
        return self._get("bool", h, node)

    # --- запись ---
    def _snapshot_orig(self, node):
        text = self.orig_path.read_text(encoding="utf-8") if self.orig_path.exists() else None
        self.orig_at_set.append((node, json.loads(text) if text else None))

    def _set(self, method, kind, h, node, value, stored=None):
        self.calls.append((method, node, value))
        self._snapshot_orig(node)
        ip = self._node(h, node, kind, method)
        if node in self.fail_set:
            raise RuntimeError("node is locked")
        self.state[ip][node] = (kind, value if stored is None else stored)

    def set_int(self, h, node, value):
        self._set("set_int", "int", h, node, value)

    def set_float(self, h, node, value):
        self._set("set_float", "float", h, node, value)

    def set_enum(self, h, node, value):
        self._set("set_enum", "enum", h, node, value)

    def set_enum_str(self, h, node, value):
        self._set("set_enum_str", "enum", h, node, value, stored=ENUM_NAMES[value])

    def set_bool(self, h, node, value):
        self._set("set_bool", "bool", h, node, value)

    # --- удобства для проверок ---
    def value(self, node, ip=IP):
        return self.state[ip][node][1]

    def setter_calls(self):
        return [c for c in self.calls if c[0].startswith("set_")]

    def count(self, name):
        return sum(1 for c in self.calls if c[0] == name)


def run(argv, api, orig):
    """Код выхода: возвращённый ``int`` или код ``SystemExit`` (строка/None -> 1/0)."""
    try:
        rc = cam_cfg.main(argv, api=api, orig_path=orig)
    except SystemExit as exc:
        code = exc.code
        return 0 if code is None else code if isinstance(code, int) else 1
    return rc


def read_orig(orig):
    return json.loads(orig.read_text(encoding="utf-8"))


LEGACY = {"TriggerMode": 0, "TriggerSource": 0, "TriggerSelfTriggerPeriod": 300}


def write_legacy(orig, data=None):
    orig.write_text(json.dumps({IP: dict(data or LEGACY)}, indent=2), encoding="utf-8")


@pytest.fixture
def orig(tmp_path):
    return tmp_path / "cam_orig.json"


@pytest.fixture
def api(orig):
    return FakeApi(orig)


# ============================================================ A1: исходное сохраняется ДО записи


def test_set_writes_orig_file_before_calling_setter(api, orig):
    rc = run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)

    assert rc == 0
    node, on_disk = api.orig_at_set[0]
    assert node == "TriggerSelfTriggerPeriod"
    assert on_disk is not None, "в момент set_int orig-файла ещё нет"
    assert on_disk[IP]["TriggerSelfTriggerPeriod"] == {"value": 300, "type": "int"}


def test_set_saves_each_original_before_its_own_write(api, orig):
    run(["set", IP, "ExposureTime:float=2000.0", "TriggerSelfTriggerPeriod:int=500"], api, orig)

    assert [n for n, _ in api.orig_at_set] == ["ExposureTime", "TriggerSelfTriggerPeriod"]
    at_first = api.orig_at_set[0][1][IP]
    at_second = api.orig_at_set[1][1][IP]
    assert at_first["ExposureTime"] == {"value": 1000.0, "type": "float"}
    # к моменту второй записи оба исходных уже на диске, первый — до-записное, не 2000.0
    assert at_second["ExposureTime"] == {"value": 1000.0, "type": "float"}
    assert at_second["TriggerSelfTriggerPeriod"] == {"value": 300, "type": "int"}


def test_set_writes_new_value_to_device(api, orig):
    run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)

    assert api.value("TriggerSelfTriggerPeriod") == 500


# ============================================================ A2: первое исходное не перезаписывается


def test_second_set_of_same_node_keeps_first_original(api, orig):
    run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)
    run(["set", IP, "TriggerSelfTriggerPeriod:int=700"], api, orig)

    assert api.value("TriggerSelfTriggerPeriod") == 700
    assert read_orig(orig)[IP]["TriggerSelfTriggerPeriod"] == {"value": 300, "type": "int"}


def test_revert_after_two_sets_restores_first_original(api, orig):
    run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)
    run(["set", IP, "TriggerSelfTriggerPeriod:int=700"], api, orig)
    api.calls.clear()

    run(["revert", IP], api, orig)

    assert api.setter_calls() == [("set_int", "TriggerSelfTriggerPeriod", 300)]
    assert api.value("TriggerSelfTriggerPeriod") == 300


def test_originals_are_per_ip(api, orig):
    api.state[OTHER_IP]["TriggerSelfTriggerPeriod"] = ("int", 999)
    run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)
    run(["set", OTHER_IP, "TriggerSelfTriggerPeriod:int=600"], api, orig)

    saved = read_orig(orig)
    assert saved[IP]["TriggerSelfTriggerPeriod"] == {"value": 300, "type": "int"}
    assert saved[OTHER_IP]["TriggerSelfTriggerPeriod"] == {"value": 999, "type": "int"}


def test_set_opens_requested_ip_not_neighbour(api, orig):
    run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)

    assert [c for c in api.calls if c[0] == "open"] == [("open", IP)]
    assert api.value("TriggerSelfTriggerPeriod", OTHER_IP) == 300


# ============================================================ A3: откат в обратном порядке


def test_revert_goes_in_reverse_order_of_saving(api, orig):
    run(
        ["set", IP, "ExposureTime:float=2000.0", "TriggerSelfTriggerPeriod:int=500", "TriggerSource:enum=SelfTrigger"],
        api,
        orig,
    )
    api.calls.clear()

    run(["revert", IP], api, orig)

    assert api.setter_calls() == [
        ("set_enum", "TriggerSource", 0),
        ("set_int", "TriggerSelfTriggerPeriod", 300),
        ("set_float", "ExposureTime", 1000.0),
    ]


def test_revert_restores_device_state_for_all_four_types(api, orig):
    run(
        [
            "set",
            IP,
            "ExposureTime:float=2000.0",
            "TriggerSelfTriggerPeriod:int=500",
            "TriggerSource:enum=SelfTrigger",
            "LightEnable:bool=true",
        ],
        api,
        orig,
    )
    assert api.value("LightEnable") is True
    api.calls.clear()

    run(["revert", IP], api, orig)

    assert api.state[IP] == DEFAULT_NODES
    last = api.setter_calls()[0]  # LightEnable сохранён последним -> возвращается первым
    assert last[:2] == ("set_bool", "LightEnable")
    assert last[2] is False


def test_revert_prints_returned_lines(api, orig, capsys):
    run(["set", IP, "TriggerSource:enum=SelfTrigger"], api, orig)
    capsys.readouterr()

    run(["revert", IP], api, orig)

    assert "возвращён TriggerSource = 0" in capsys.readouterr().out.splitlines()


def test_revert_continues_after_refused_node_and_reports_it(api, orig, capsys):
    run(["set", IP, "ExposureTime:float=2000.0", "TriggerSource:enum=SelfTrigger"], api, orig)
    capsys.readouterr()
    api.fail_set.add("TriggerSource")

    run(["revert", IP], api, orig)

    out = capsys.readouterr().out.splitlines()
    assert any(line.startswith("НЕ ВОЗВРАЩЁН TriggerSource") for line in out)
    assert api.value("ExposureTime") == 1000.0  # следующий узел всё же возвращён


# ============================================================ A4: отказ setter


def _refusal_run(api, orig):
    api.fail_set.add("TriggerSelfTriggerPeriod")
    return run(
        ["set", IP, "ExposureTime:float=2000.0", "TriggerSelfTriggerPeriod:int=500", "TriggerSource:enum=SelfTrigger"],
        api,
        orig,
    )


def test_refusal_returns_one(api, orig):
    assert _refusal_run(api, orig) == 1


def test_refusal_never_writes_later_node(api, orig):
    _refusal_run(api, orig)

    assert not [c for c in api.setter_calls() if c[1] == "TriggerSource"]
    assert api.value("TriggerSource") == 0


def test_refusal_keeps_originals_of_written_and_refused_nodes(api, orig):
    _refusal_run(api, orig)

    saved = read_orig(orig)[IP]
    assert saved["ExposureTime"] == {"value": 1000.0, "type": "float"}
    assert saved["TriggerSelfTriggerPeriod"] == {"value": 300, "type": "int"}


def test_refusal_closes_device_exactly_once(api, orig):
    _refusal_run(api, orig)

    assert api.count("close") == 1


def test_refusal_leaves_earlier_written_node_and_prints_refusal(api, orig, capsys):
    _refusal_run(api, orig)

    assert api.value("ExposureTime") == 2000.0  # автоотката нет: это делает revert
    out = capsys.readouterr().out.splitlines()
    refused = [line for line in out if line.startswith("SET TriggerSelfTriggerPeriod:")]
    assert len(refused) == 1
    assert " ОТКАЗ " in refused[0] and "node is locked" in refused[0]
    assert refused[0].startswith("SET TriggerSelfTriggerPeriod: было=300 записано=500 ОТКАЗ ")
    assert refused[0].endswith("прочитано=300")


# ============================================================ A5: узел не читается до записи


def test_unreadable_node_saved_with_null_value_and_err(api, orig):
    api.fail_get_once.add("TriggerSelfTriggerPeriod")

    rc = run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)

    assert rc == 0
    entry = read_orig(orig)[IP]["TriggerSelfTriggerPeriod"]
    assert entry["value"] is None
    assert entry["type"] == "int"
    assert "node unreadable" in entry["err"]
    assert api.value("TriggerSelfTriggerPeriod") == 500  # запись всё же состоялась


def test_unreadable_node_orig_saved_before_write(api, orig):
    api.fail_get_once.add("TriggerSelfTriggerPeriod")

    run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)

    on_disk = api.orig_at_set[0][1]
    assert on_disk is not None and on_disk[IP]["TriggerSelfTriggerPeriod"]["value"] is None


def test_revert_skips_null_entry_without_setter_call(api, orig, capsys):
    api.fail_get_once.add("TriggerSelfTriggerPeriod")
    run(["set", IP, "ExposureTime:float=2000.0", "TriggerSelfTriggerPeriod:int=500"], api, orig)
    capsys.readouterr()
    api.calls.clear()

    run(["revert", IP], api, orig)

    out = capsys.readouterr().out.splitlines()
    assert any(line.startswith("SKIP TriggerSelfTriggerPeriod") for line in out)
    assert api.setter_calls() == [("set_float", "ExposureTime", 1000.0)]
    assert api.value("TriggerSelfTriggerPeriod") == 500  # не тронут


# ============================================================ A6: старый формат orig-файла


def test_legacy_revert_order_and_setter_types(api, orig):
    write_legacy(orig)
    api.state[IP]["TriggerMode"] = ("enum", 1)
    api.state[IP]["TriggerSource"] = ("enum", 7)
    api.state[IP]["TriggerSelfTriggerPeriod"] = ("int", 20)

    run(["revert", IP], api, orig)

    assert api.setter_calls() == [
        ("set_int", "TriggerSelfTriggerPeriod", 300),
        ("set_enum", "TriggerSource", 0),
        ("set_enum", "TriggerMode", 0),
    ]
    assert api.state[IP] == DEFAULT_NODES


def test_legacy_revert_prints_returned_lines(api, orig, capsys):
    write_legacy(orig)

    run(["revert", IP], api, orig)

    out = capsys.readouterr().out.splitlines()
    assert "возвращён TriggerSelfTriggerPeriod = 300" in out
    assert "возвращён TriggerMode = 0" in out


def test_set_does_not_overwrite_legacy_original(api, orig):
    write_legacy(orig)
    api.state[IP]["TriggerMode"] = ("enum", 1)  # как после прошлого запуска

    run(["set", IP, "TriggerMode:enum=1"], api, orig)
    api.calls.clear()
    run(["revert", IP], api, orig)

    assert ("set_enum", "TriggerMode", 0) in api.setter_calls()
    assert api.value("TriggerMode") == 0


def test_new_node_after_legacy_entries_reverts_first(api, orig):
    write_legacy(orig)

    run(["set", IP, "ExposureTime:float=2000.0"], api, orig)
    api.calls.clear()
    run(["revert", IP], api, orig)

    assert [c[1] for c in api.setter_calls()] == [
        "ExposureTime",
        "TriggerSelfTriggerPeriod",
        "TriggerSource",
        "TriggerMode",
    ]


# ============================================================ A7: get только читает


def test_get_makes_no_setter_calls_and_returns_zero(api, orig):
    rc = run(["get", IP, "TriggerSelfTriggerPeriod:int", "TriggerSource:enum", "ExposureTime:float"], api, orig)

    assert rc == 0
    assert api.setter_calls() == []


def test_get_prints_value_lines(api, orig, capsys):
    run(["get", IP, "TriggerSelfTriggerPeriod:int", "TriggerSource:enum", "LightEnable:bool"], api, orig)

    out = capsys.readouterr().out.splitlines()
    assert "GET TriggerSelfTriggerPeriod = 300" in out
    assert "GET TriggerSource = 0" in out
    bool_line = [line for line in out if line.startswith("GET LightEnable = ")]
    assert len(bool_line) == 1 and "ERR" not in bool_line[0]


def test_get_prints_err_for_raising_getter_and_continues(api, orig, capsys):
    api.fail_get.add("ExposureTime")

    rc = run(["get", IP, "ExposureTime:float", "TriggerSelfTriggerPeriod:int"], api, orig)

    out = capsys.readouterr().out.splitlines()
    err_lines = [line for line in out if line.startswith("GET ExposureTime = ERR ")]
    assert len(err_lines) == 1 and "node unreadable" in err_lines[0]
    assert "GET TriggerSelfTriggerPeriod = 300" in out
    assert rc == 0
    assert api.setter_calls() == []


# ============================================================ A8: вид setter по TYPE и VALUE


def test_enum_by_name_uses_set_enum_str(api, orig):
    run(["set", IP, "TriggerSource:enum=SelfTrigger"], api, orig)

    assert api.setter_calls() == [("set_enum_str", "TriggerSource", "SelfTrigger")]
    assert api.value("TriggerSource") == 7


def test_enum_by_integer_uses_set_enum_with_int(api, orig):
    run(["set", IP, "TriggerMode:enum=1"], api, orig)

    calls = api.setter_calls()
    assert calls == [("set_enum", "TriggerMode", 1)]
    assert type(calls[0][2]) is int
    assert api.value("TriggerMode") == 1


def test_int_uses_set_int_with_int(api, orig):
    run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)

    calls = api.setter_calls()
    assert calls == [("set_int", "TriggerSelfTriggerPeriod", 500)]
    assert type(calls[0][2]) is int


def test_float_uses_set_float_with_float(api, orig):
    run(["set", IP, "ExposureTime:float=2500.5"], api, orig)

    calls = api.setter_calls()
    assert calls == [("set_float", "ExposureTime", 2500.5)]
    assert type(calls[0][2]) is float


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1", True), ("0", False), ("true", True), ("false", False), ("TRUE", True), ("False", False)],
)
def test_bool_value_forms(api, orig, text, expected):
    api.state[IP]["LightEnable"] = ("bool", not expected)

    run(["set", IP, f"LightEnable:bool={text}"], api, orig)

    calls = api.setter_calls()
    assert [c[:2] for c in calls] == [("set_bool", "LightEnable")]
    assert calls[0][2] is expected
    assert api.value("LightEnable") is expected


def test_set_reads_node_with_getter_of_its_type(api, orig):
    run(["set", IP, "ExposureTime:float=2000.0", "LightEnable:bool=1"], api, orig)

    reads = [c for c in api.calls if c[0].startswith("get_")]
    assert ("get_float", "ExposureTime") in reads
    assert ("get_bool", "LightEnable") in reads


# ============================================================ A9: файл заканчивается переводом строки


def test_orig_file_ends_with_newline(api, orig):
    run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)

    text = orig.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text)[IP]["TriggerSelfTriggerPeriod"]["value"] == 300


# ============================================================ A10: неизвестный TYPE


def test_unknown_type_exits_nonzero_before_opening_device(api, orig):
    rc = run(["set", IP, "TriggerSelfTriggerPeriod:string=500"], api, orig)

    assert rc != 0
    assert api.count("open") == 0
    assert api.setter_calls() == []


def test_unknown_type_after_valid_node_writes_nothing(api, orig):
    rc = run(["set", IP, "TriggerSelfTriggerPeriod:int=500", "ExposureTime:double=2.0"], api, orig)

    assert rc != 0
    assert api.count("open") == 0
    assert api.setter_calls() == []
    assert api.value("TriggerSelfTriggerPeriod") == 300
    assert not orig.exists()


def test_unknown_type_in_get_exits_nonzero_before_opening_device(api, orig):
    rc = run(["get", IP, "TriggerSelfTriggerPeriod:string"], api, orig)

    assert rc != 0
    assert api.count("open") == 0


# ============================================================ дескриптор и вывод


@pytest.mark.parametrize(
    ("argv", "refuse"),
    [
        (["set", IP, "TriggerSelfTriggerPeriod:int=500"], None),
        (["get", IP, "TriggerSource:enum"], None),
        (["revert", IP], None),
        (["set", IP, "TriggerSelfTriggerPeriod:int=500"], "TriggerSelfTriggerPeriod"),
    ],
    ids=["set", "get", "revert", "set-refused"],
)
def test_device_handle_closed_exactly_once(api, orig, argv, refuse):
    write_legacy(orig)
    if refuse:
        api.fail_set.add(refuse)

    run(argv, api, orig)

    assert api.count("open") == 1
    assert api.count("close") == 1
    assert api.closed == list(api.handle_ip)  # закрыт именно тот handle, что открыт


def test_every_node_call_uses_the_opened_handle(api, orig):
    run(["set", IP, "ExposureTime:float=2000.0", "TriggerSource:enum=SelfTrigger"], api, orig)
    run(["revert", IP], api, orig)

    assert set(api.handles_used) <= set(api.handle_ip)
    assert api.handles_used  # вызовы были


def test_set_prints_ok_line_with_before_written_read(api, orig, capsys):
    run(["set", IP, "TriggerSelfTriggerPeriod:int=500"], api, orig)

    out = capsys.readouterr().out.splitlines()
    assert "SET TriggerSelfTriggerPeriod: было=300 записано=500 OK прочитано=500" in out


def test_set_prints_one_line_per_node_in_argument_order(api, orig, capsys):
    run(["set", IP, "ExposureTime:float=2000.0", "TriggerMode:enum=1"], api, orig)

    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("SET ")]
    assert [line.split(":")[0] for line in lines] == ["SET ExposureTime", "SET TriggerMode"]
    assert all(" OK " in line for line in lines)


# ============================================================ существующие команды не меняются


def test_show_reads_only_and_prints_state(api, orig, capsys):
    rc = run(["show", IP], api, orig)

    out = capsys.readouterr().out
    assert rc == 0
    assert api.setter_calls() == []
    assert f"открыт {IP} ID3013" in out
    for name in ("TriggerMode", "TriggerSource", "TriggerSelfTriggerPeriod"):
        assert name in out
    assert '"cur": 300' in out
    assert api.count("close") == 1


def test_period_command_sets_int_and_revert_restores(api, orig):
    run(["period", IP, "500"], api, orig)

    assert api.setter_calls() == [("set_int", "TriggerSelfTriggerPeriod", 500)]
    assert api.value("TriggerSelfTriggerPeriod") == 500

    run(["revert", IP], api, orig)
    assert api.value("TriggerSelfTriggerPeriod") == 300


def test_selftrigger_sets_mode_and_source_and_revert_restores(api, orig):
    rc = run(["selftrigger", IP], api, orig)

    assert rc == 0
    assert api.value("TriggerMode") == 1
    assert api.value("TriggerSource") == 7
    assert ("set_enum_str", "TriggerSource", "SelfTrigger") in api.setter_calls()

    run(["revert", IP], api, orig)
    assert api.state[IP] == DEFAULT_NODES


def test_selftrigger_failure_rolls_back_already_written_mode(api, orig):
    api.fail_set.add("TriggerSource")

    try:
        rc = run(["selftrigger", IP], api, orig)
    except Exception:  # noqa: BLE001 — сегодняшнее поведение: исключение пробрасывается
        rc = "raised"

    assert rc != 0
    assert api.value("TriggerMode") == 0  # TriggerMode, уже записанный в On, возвращён
    assert api.count("close") == 1
