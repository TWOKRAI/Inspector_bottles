"""Кодоген протокола Delta v2: `delta_v2.yaml` -> Python-модули + Lua-блок (Task T1.1).

`Services/robot_comm/protocols/delta_v2.yaml` — единственный источник контракта
(plans/robot-protocol-v2/tasks.md, T1.1). Из него порождаются:

    core/protocol_v2.py — REG/OP/ERR/REASON/CONSTANTS и т.п. (без импортов)
    core/params_v2.py   — PARAMS, PARAM_ID, DICT_FINGERPRINT, to_eng/to_raw, RobotParamsV2
    lua_block(root)     — таблицы REG/OP/ERR/PDEF/KIND/ACT/C/RSN/STOP между маркерами

Регенерация детерминирована: тот же YAML -> байт-в-байт тот же текст (без временных
меток, без порядка set/словарей рантайма — только literal-рендер, без `repr()`/`pprint`
целиком, по одному элементу на строку).

CLI: `python -m Services.robot_comm.codegen [--check]`.
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

import yaml

_YAML_REL = Path("Services/robot_comm/protocols/delta_v2.yaml")
_PROTOCOL_REL = Path("Services/robot_comm/core/protocol_v2.py")
_PARAMS_REL = Path("Services/robot_comm/core/params_v2.py")

# Разбит на две строки: однострочный вариант (132 символа) валит E501 (line-length=120).
_HEADER_TMPL = (
    "# СГЕНЕРИРОВАНО из Services/robot_comm/protocols/delta_v2.yaml ({sha8})\n"
    "# не править руками; python -m Services.robot_comm.codegen"
)

# Константы из secttion `constants:`, которые логически являются адресами —
# рендерятся в hex (0x%04X), как и в исходном YAML. Остальные (SC_STRIDE, SC_CAP,
# WRITE_CHUNK, READ_MAX, W_MIN, W_MAX) — обычные десятичные числа.
_HEX_CONSTANT_KEYS = frozenset(
    {
        "PROTO_VER",
        "CMD_BASE",
        "RES_BASE",
        "SAFETY_BASE",
        "TLM_BASE",
        "SC_BASE",
        "PMIR_BASE",
        "PMIR_FALLBACK_BASE",
        "VFD_BASE",
        "PMIR_MAGIC_VALUE",
    }
)


# ─────────────────────────── общий literal-рендерер (Python) ───────────────────────────


class _Hex:
    """Маркер «отрендерить этот int как 0x%0{width}X», а не десятичным литералом."""

    __slots__ = ("value", "width")

    def __init__(self, value: int, width: int) -> None:
        self.value = value
        self.width = width


def _render_scalar(value: object) -> str:
    if isinstance(value, _Hex):
        return f"0x{value.value:0{value.width}X}"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return repr(value)
    raise TypeError(f"codegen: не умею рендерить литерал {value!r}")


def _render(value: object, indent: int) -> str:
    """Рекурсивный literal-рендер: dict/list/tuple — по одному элементу на строку."""
    pad = "    " * indent
    pad_in = "    " * (indent + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = ["{"]
        for key, item in value.items():
            key_str = _render_scalar(key) if isinstance(key, str) else str(key)
            lines.append(f"{pad_in}{key_str}: {_render(item, indent + 1)},")
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    if isinstance(value, tuple):
        if not value:
            return "()"
        lines = ["("]
        for item in value:
            lines.append(f"{pad_in}{_render(item, indent + 1)},")
        lines.append(f"{pad})")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = ["["]
        for item in value:
            lines.append(f"{pad_in}{_render(item, indent + 1)},")
        lines.append(f"{pad}]")
        return "\n".join(lines)
    return _render_scalar(value)


def _assign(name: str, value: object) -> str:
    return f"{name} = {_render(value, 0)}"


def _module_text(header: str, sections: list[str]) -> str:
    parts = [header]
    for section in sections:
        parts.append("")
        parts.append(section)
    parts.append("")
    return "\n".join(parts)


# ─────────────────────────── общий literal-рендерер (Lua) ───────────────────────────


def _lua_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _lua_scalar(value: object) -> str:
    if isinstance(value, _Hex):
        return f"0x{value.value:0{value.width}X}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _lua_string(value)
    raise TypeError(f"codegen: не умею рендерить Lua-литерал {value!r}")


def _lua_render(value: object, indent: int) -> str:
    pad = "  " * indent
    pad_in = "  " * (indent + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = ["{"]
        for key, item in value.items():
            key_str = str(key) if isinstance(key, str) else f"[{key}]"
            lines.append(f"{pad_in}{key_str} = {_lua_render(item, indent + 1)},")
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    if isinstance(value, (list, tuple)):
        if not value:
            return "{}"
        lines = ["{"]
        for item in value:
            lines.append(f"{pad_in}{_lua_render(item, indent + 1)},")
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    return _lua_scalar(value)


def _lua_assign(name: str, value: object) -> str:
    return f"{name} = {_lua_render(value, 0)}"


# ─────────────────────────── CRC16/MODBUS (DICT_FINGERPRINT) ───────────────────────────


def crc16_modbus(data: bytes) -> int:
    """CRC16/MODBUS: poly 0xA001 (reflected), init 0xFFFF."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _dict_fingerprint(params_yaml: dict) -> int:
    """CRC16/MODBUS по id/min/max/default (u16 LE) всех параметров, сорт. по id, свёрнутый до 15 бит.

    15 бит — чтобы отпечаток записывался из Lua как слово W (±32767, RL 12-2) без знакового перехода.
    Значение вне 16 бит — ошибка словаря, а не повод молча обрезать: иначе смена такого предела не меняла бы отпечаток.
    """
    words = bytearray()
    for name, meta in sorted(params_yaml.items(), key=lambda kv: kv[1]["id"]):
        for value in (meta["id"], meta["min"], meta["max"], meta["default"]):
            if not -32768 <= value <= 0xFFFF:
                raise ValueError(f"{name}: значение {value} не помещается в 16 бит — нужен широкий параметр")
            words += struct.pack("<H", value & 0xFFFF)
    return crc16_modbus(bytes(words)) & 0x7FFF


def _field_name(param_name: str) -> str:
    """P_SPD_DEFAULT -> spd_default (без префикса P_, lower-case)."""
    return param_name[len("P_") :].lower()


# ─────────────────────────── чтение YAML и извлечение структур ───────────────────────────


def _yaml_path(root: Path) -> Path:
    return root / _YAML_REL


def _load_yaml(root: Path) -> dict:
    return yaml.safe_load(_yaml_path(root).read_text(encoding="utf-8"))


def yaml_sha8(root: Path) -> str:
    """Первые 8 hex sha256(bytes(delta_v2.yaml)), переводы строк приведены к LF (checkout на Windows)."""
    data = _yaml_path(root).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()[:8]


def _extract(doc: dict) -> dict:
    """Вытащить из YAML-документа плоские структуры, общие для всех трёх выходов."""
    reg: dict[str, int] = {}
    reg_count: dict[str, int] = {}
    for name, meta in doc["registers"].items():
        upper = name.upper()
        reg[upper] = meta["address"]
        if meta["type"] == "block":
            reg_count[upper] = meta["count"]

    op: dict[str, int] = {}
    op_spec: dict[str, dict] = {}
    for name, meta in doc["opcodes"].items():
        op[name] = meta["code"]
        op_spec[name] = {
            "argc": meta["argc"],
            "busy": meta["busy"],
            "args": [{"name": arg["name"], "type": arg["type"]} for arg in meta["args"]],
            "result": meta["result"],
        }

    err: dict[str, int] = {}
    err_text: dict[int, str] = {}
    err_kind: dict[int, str] = {}
    for name, meta in doc["errno"].items():
        err[name] = meta["code"]
        err_text[meta["code"]] = meta["text"]
        err_kind[meta["code"]] = meta["kind"]

    reason: dict[str, int] = {}
    reason_text: dict[int, str] = {}
    for name, meta in doc["reasons"].items():
        reason[name] = meta["code"]
        reason_text[meta["code"]] = meta["text"]

    constants: dict[str, int] = {}
    gate1_constants: tuple[str, ...] = ()
    for key, value in doc["constants"].items():
        if key == "gate1_constants":
            gate1_constants = tuple(value)
        else:
            constants[key] = value

    kind = dict(doc["scenario"]["kinds"])
    act = dict(doc["scenario"]["actions"])
    sc_record = tuple(doc["scenario"]["record"])
    stop_level = dict(doc["stop_levels"])

    params: dict[int, dict] = {}
    param_id: dict[str, int] = {}
    for name, meta in sorted(doc["params"].items(), key=lambda kv: kv[1]["id"]):
        param_id[name] = meta["id"]
        params[meta["id"]] = {
            "name": name,
            "label": meta["label"],
            "unit": meta["unit"],
            "scale": meta["scale"],
            "signed": bool(meta["signed"]),
            "min": meta["min"],
            "max": meta["max"],
            "default": meta["default"],
            "group": meta["group"],
            "apply": meta["apply"],
            "info": meta["info"],
            "gate1": bool(meta.get("gate1", False)),
        }

    groups = {group_id: dict(meta) for group_id, meta in doc["groups"].items()}

    return {
        "reg": reg,
        "reg_count": reg_count,
        "op": op,
        "op_spec": op_spec,
        "err": err,
        "err_text": err_text,
        "err_kind": err_kind,
        "reason": reason,
        "reason_text": reason_text,
        "constants": constants,
        "gate1_constants": gate1_constants,
        "kind": kind,
        "act": act,
        "stop_level": stop_level,
        "sc_record": sc_record,
        "params": params,
        "param_id": param_id,
        "groups": groups,
        "dict_fingerprint": _dict_fingerprint(doc["params"]),
    }


# ─────────────────────────── protocol_v2.py ───────────────────────────


def _render_protocol_module(doc: dict, sha8: str) -> str:
    ex = _extract(doc)

    reg = {name: _Hex(addr, 4) for name, addr in ex["reg"].items()}
    op = {name: _Hex(code, 2) for name, code in ex["op"].items()}
    constants = {
        key: (_Hex(value, 4) if key in _HEX_CONSTANT_KEYS else value) for key, value in ex["constants"].items()
    }

    sections = [
        _assign("REG", reg),
        _assign("REG_COUNT", ex["reg_count"]),
        _assign("OP", op),
        _assign("OP_SPEC", ex["op_spec"]),
        _assign("ERR", ex["err"]),
        _assign("ERR_TEXT", ex["err_text"]),
        _assign("ERR_KIND", ex["err_kind"]),
        _assign("REASON", ex["reason"]),
        _assign("REASON_TEXT", ex["reason_text"]),
        _assign("CONSTANTS", constants),
        _assign("GATE1_CONSTANTS", ex["gate1_constants"]),
        _assign("KIND", ex["kind"]),
        _assign("ACT", ex["act"]),
        _assign("STOP_LEVEL", ex["stop_level"]),
        _assign("SC_RECORD", ex["sc_record"]),
    ]
    header = _HEADER_TMPL.format(sha8=sha8)
    return _module_text(header, sections)


# ─────────────────────────── params_v2.py ───────────────────────────


def _render_params_class(doc: dict) -> str:
    lines = [
        "class RobotParamsV2(SchemaBase):",
        '    """Параметры робота Delta v2 — по одному полю на запись словаря (params.md §11.3)."""',
        "",
    ]
    for name, meta in sorted(doc["params"].items(), key=lambda kv: kv[1]["id"]):
        field = _field_name(name)
        scale = meta["scale"]
        is_int = scale == 1
        py_type = "int" if is_int else "float"
        if is_int:
            default_v: float = meta["default"]
            ge_v: float = meta["min"]
            le_v: float = meta["max"]
        else:
            default_v = meta["default"] / scale
            ge_v = meta["min"] / scale
            le_v = meta["max"] / scale
        group_name = doc["groups"][meta["group"]]["name"]

        lines.append(f"    {field}: Annotated[")
        lines.append(f"        {py_type},")
        # Границы держит FieldMeta: SchemaBase проверяет min/max сам — вторая копия в Field(ge, le) могла бы разойтись
        lines.append(f"        Field(default={_render_scalar(default_v)}),")
        lines.append("        FieldMeta(")
        lines.append(f"            {_render_scalar(meta['label'])},")
        lines.append(f"            unit={_render_scalar(meta['unit'])},")
        lines.append(f"            min={_render_scalar(ge_v)},")
        lines.append(f"            max={_render_scalar(le_v)},")
        lines.append(f"            info={_render_scalar(meta['info'])},")
        lines.append(f"            ui_group={_render_scalar(group_name)},")
        lines.append(f"            ui_order={meta['id']},")
        if scale != 1:
            lines.append("            round_k=1,")
        lines.append("        ),")
        lines.append("    ]")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _render_params_module(doc: dict, sha8: str) -> str:
    ex = _extract(doc)

    imports = "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import math",
            "",
            "from typing import Annotated",
            "",
            "from pydantic import Field",
            "",
            "from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase",
        ]
    )

    to_eng = (
        "def to_eng(name: str, raw: float) -> float:\n"
        '    """Сырое значение параметра -> инженерные единицы (raw / scale)."""\n'
        '    return raw / PARAMS[PARAM_ID[name]]["scale"]'
    )
    to_raw = (
        "def to_raw(name: str, eng: float) -> int:\n"
        '    """Инженерные единицы -> сырое значение (округление до ближайшего от нуля)."""\n'
        '    scale = PARAMS[PARAM_ID[name]]["scale"]\n'
        "    x = eng * scale\n"
        "    magnitude = int(math.floor(abs(x) + 0.5))\n"
        "    return -magnitude if x < 0 else magnitude"
    )

    sections = [
        imports,
        _assign("PARAMS", ex["params"]),
        _assign("PARAM_ID", ex["param_id"]),
        _assign("GROUPS", ex["groups"]),
        f"DICT_FINGERPRINT = {ex['dict_fingerprint']}",
        to_eng,
        to_raw,
        _render_params_class(doc),
    ]
    header = _HEADER_TMPL.format(sha8=sha8)
    return _module_text(header, sections)


# ─────────────────────────── публичный API ───────────────────────────


def generate(root: Path) -> dict[Path, str]:
    """YAML -> {путь: текст} ровно для core/protocol_v2.py и core/params_v2.py. Ничего не пишет на диск."""
    doc = _load_yaml(root)
    sha8 = yaml_sha8(root)
    return {
        root / _PROTOCOL_REL: _render_protocol_module(doc, sha8),
        root / _PARAMS_REL: _render_params_module(doc, sha8),
    }


def check(root: Path) -> list[Path]:
    """Пути сгенерированных файлов, чей текст на диске разошёлся с generate(root) (отсутствие = разошёлся)."""
    stale = []
    for path, text in generate(root).items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            stale.append(path)
    return sorted(stale)


def lua_block(root: Path) -> str:
    """Таблицы REG/OP/ERR/PDEF/KIND/ACT/C/RSN/STOP между маркерами BEGIN/END GENERATED."""
    doc = _load_yaml(root)
    sha8 = yaml_sha8(root)
    ex = _extract(doc)

    reg = {name: _Hex(addr, 4) for name, addr in ex["reg"].items()}
    op = {
        name: {
            "code": _Hex(code, 2),
            "argc": doc["opcodes"][name]["argc"],
            "busy": doc["opcodes"][name]["busy"],
        }
        for name, code in ex["op"].items()
    }
    pdef: dict[int, dict] = {}
    for name, meta in sorted(doc["params"].items(), key=lambda kv: kv[1]["id"]):
        pdef[meta["id"]] = {
            "name": name,
            "min": meta["min"],
            "max": meta["max"],
            "def": meta["default"],
            "apply": meta["apply"],
            "signed": bool(meta["signed"]),
        }
    constants = {
        key: (_Hex(value, 4) if key in _HEX_CONSTANT_KEYS else value) for key, value in ex["constants"].items()
    }
    constants["PMIR_DICT"] = ex["dict_fingerprint"]

    lines = [f"-- ===== BEGIN GENERATED (delta_v2.yaml {sha8}) ====="]
    for name, value in (
        ("REG", reg),
        ("OP", op),
        ("ERR", ex["err"]),
        ("PDEF", pdef),
        ("KIND", ex["kind"]),
        ("ACT", ex["act"]),
        ("C", constants),
        ("RSN", ex["reason"]),
        ("STOP", ex["stop_level"]),
    ):
        lines.append("")
        lines.append(_lua_assign(name, value))
    lines.append("")
    lines.append("-- ===== END GENERATED =====")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path.cwd()
    if not _yaml_path(root).is_file():
        print(f"нет {_YAML_REL} — запускайте из корня репозитория", file=sys.stderr)
        return 2
    if "--check" in args:
        stale = check(root)
        for path in stale:
            print(path)
        return 1 if stale else 0
    for path, text in generate(root).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
