"""RED-приёмка кодогена `Services/robot_comm/codegen.py` (Task T1.1, redакция 2).

Независимый tester, слепой к реализации: worktree на коммите GATE-0 (до кодогена).
`codegen.py`, `core/protocol_v2.py`, `core/params_v2.py` ещё не существуют. Контракт —
ТОЛЬКО API, продиктованное ведущим в брифе (DESIGN), не выведено самим тестировщиком:

    generate(root) -> {Path: str}      — ровно core/protocol_v2.py + core/params_v2.py
    check(root) -> list[Path]          — что на диске разошлось с generate(root)
    lua_block(root) -> str             — таблицы REG/OP/ERR/PDEF/KIND/ACT между маркерами
    yaml_sha8(root) -> str             — первые 8 hex sha256(bytes(delta_v2.yaml))
    CLI: python -m Services.robot_comm.codegen [--check]

    protocol_v2: REG, REG_COUNT, OP, OP_SPEC, ERR, ERR_TEXT, REASON, CONSTANTS,
                 KIND, ACT, STOP_LEVEL
    params_v2:   PARAMS, PARAM_ID, DICT_FINGERPRINT, to_eng, to_raw, RobotParamsV2

Ожидаемые значения — литералы, переписанные руками из `delta_v2.yaml`
(`plans/robot-protocol-v2/tasks.md` T1.1: YAML — единственный источник контракта),
НЕ читаются обратно из сгенерированного модуля.

Импорты `codegen`/`protocol_v2`/`params_v2` — ТОЛЬКО внутри тел тестов, не на уровне
модуля: сбор (collection) должен пройти успешно, каждый тест падает с ImportError
индивидуально (см. приёмку в брифе). Единственный допустимый skip — `test_lua_block_runs_in_lua`
(`pytest.importorskip("lupa")`).
"""

from __future__ import annotations

import hashlib
import struct
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# Services/robot_comm/tests/test_codegen_v2.py -> tests(0) / robot_comm(1) / Services(2) / root(3)
_REPO_ROOT = Path(__file__).resolve().parents[3]
_YAML_PATH = _REPO_ROOT / "Services" / "robot_comm" / "protocols" / "delta_v2.yaml"
_YAML_DOC = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
_PARAMS_YAML: dict[str, dict] = _YAML_DOC["params"]


def _field_name(param_name: str) -> str:
    """P_SPD_DEFAULT -> spd_default (правило DESIGN: без префикса P_, lower-case)."""
    assert param_name.startswith("P_"), param_name
    return param_name[len("P_") :].lower()


_PARAM_CASES = [
    pytest.param(name, meta, _field_name(name), id=name)
    for name, meta in sorted(_PARAMS_YAML.items(), key=lambda kv: kv[1]["id"])
]


def _crc16_modbus(data: bytes) -> int:
    """CRC16/MODBUS (poly 0xA001 reflected, init 0xFFFF) — независимый оракул для
    DICT_FINGERPRINT, написан заново в тесте, не переиспользует код кодогена."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _expected_dict_fingerprint() -> int:
    """CRC16/MODBUS по id/min/max/default (u16 LE) всех параметров, сорт. по id."""
    words = bytearray()
    for _name, meta in sorted(_PARAMS_YAML.items(), key=lambda kv: kv[1]["id"]):
        words += struct.pack("<H", meta["id"] & 0xFFFF)
        words += struct.pack("<H", meta["min"] & 0xFFFF)
        words += struct.pack("<H", meta["max"] & 0xFFFF)
        words += struct.pack("<H", meta["default"] & 0xFFFF)
    return _crc16_modbus(bytes(words))


# ─────────────────────────── codegen.generate / check ───────────────────────────


def test_generate_is_deterministic():
    from Services.robot_comm import codegen

    out1 = codegen.generate(_REPO_ROOT)
    out2 = codegen.generate(_REPO_ROOT)

    expected_paths = {
        _REPO_ROOT / "Services" / "robot_comm" / "core" / "protocol_v2.py",
        _REPO_ROOT / "Services" / "robot_comm" / "core" / "params_v2.py",
    }
    assert set(out1) == expected_paths
    assert out1 == out2  # тот же вход -> байт-в-байт тот же текст (детерминизм)

    sha8 = codegen.yaml_sha8(_REPO_ROOT)
    assert len(sha8) == 8
    for text in out1.values():
        header = text[:300]
        assert "СГЕНЕРИРОВАНО" in header
        assert sha8 in header


def test_check_clean_and_stale(tmp_path):
    from Services.robot_comm import codegen

    proto_dir = tmp_path / "Services" / "robot_comm" / "protocols"
    proto_dir.mkdir(parents=True)
    yaml_copy = proto_dir / "delta_v2.yaml"
    yaml_copy.write_bytes(_YAML_PATH.read_bytes())

    outputs = codegen.generate(tmp_path)
    assert len(outputs) == 2

    # ничего не записано на диск -> оба выхода "отсутствуют" = отличаются (missing считается)
    assert set(codegen.check(tmp_path)) == set(outputs)

    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    assert codegen.check(tmp_path) == []

    # правим один сгенерированный файл руками -> только он "протух"
    edited_path = sorted(outputs)[0]
    original_text = outputs[edited_path]
    edited_path.write_text(original_text + "\n# правка руками\n", encoding="utf-8")
    assert codegen.check(tmp_path) == [edited_path]

    edited_path.write_text(original_text, encoding="utf-8")
    assert codegen.check(tmp_path) == []

    # правим сам YAML (default одного параметра) -> sha8 в шапке меняется у ОБОИХ
    # файлов -> оба "протухли", хотя PMIR/REG-часть протокола не менялась
    doc = yaml.safe_load(yaml_copy.read_text(encoding="utf-8"))
    doc["params"]["P_SPD_DEFAULT"]["default"] = 81
    yaml_copy.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")

    assert set(codegen.check(tmp_path)) == set(outputs)


# ─────────────────────────── protocol_v2: литералы из delta_v2.yaml ───────────────────────────


def test_protocol_values():
    from Services.robot_comm.core import protocol_v2

    assert protocol_v2.REG["CMD_FLAG"] == 0x1000
    assert protocol_v2.REG["SC_BUF"] == 0x1400
    assert protocol_v2.REG_COUNT["SC_BUF"] == 330

    assert protocol_v2.OP["PARAM_SET"] == 0x50
    assert protocol_v2.OP_SPEC["PARAM_SET"]["argc"] == 2
    assert protocol_v2.OP_SPEC["PARAM_SET"]["busy"] == "by_class"
    assert protocol_v2.OP_SPEC["PARAM_SET"]["result"] == "instant"

    assert protocol_v2.OP_SPEC["PTP_MOVE"]["argc"] == 6
    assert protocol_v2.OP_SPEC["PTP_MOVE"]["busy"] == "deny"
    assert protocol_v2.OP_SPEC["PTP_MOVE"]["result"] == "done_seq"
    assert protocol_v2.OP_SPEC["PTP_MOVE"]["args"][0] == {"name": "x", "type": "s16"}

    assert protocol_v2.ERR["E_BUSY"] == 4
    assert protocol_v2.ERR_TEXT[4] == "Робот занят другой командой"

    assert protocol_v2.REASON["R_DEAD_ZONE"] == 5

    assert protocol_v2.CONSTANTS["SC_CAP"] == 55
    assert protocol_v2.CONSTANTS["PROTO_VER"] == 0x0200

    assert protocol_v2.KIND["LINE_PASS"] == 1
    assert protocol_v2.ACT["DELAY_MS"] == 3
    assert protocol_v2.STOP_LEVEL["HALT"] == 3


# ─────────────────────────── params_v2 / RobotParamsV2 ───────────────────────────


@pytest.mark.parametrize("name,meta,field_name", _PARAM_CASES)
def test_params_model_accepts_every_default(name, meta, field_name):
    from Services.robot_comm.core.params_v2 import RobotParamsV2

    model = RobotParamsV2()
    expected_eng = meta["default"] / meta["scale"]
    assert getattr(model, field_name) == pytest.approx(expected_eng)


@pytest.mark.parametrize("name,meta,field_name", _PARAM_CASES)
def test_params_model_rejects_out_of_range(name, meta, field_name):
    import pydantic

    from Services.robot_comm.core.params_v2 import RobotParamsV2

    scale = meta["scale"]
    eng_min = meta["min"] / scale
    eng_max = meta["max"] / scale

    # границы — приняты (это НЕ "за диапазоном")
    RobotParamsV2(**{field_name: eng_min})
    RobotParamsV2(**{field_name: eng_max})

    with pytest.raises(pydantic.ValidationError):
        RobotParamsV2(**{field_name: (meta["min"] - 1) / scale})
    with pytest.raises(pydantic.ValidationError):
        RobotParamsV2(**{field_name: (meta["max"] + 1) / scale})


@pytest.mark.parametrize("name,meta,field_name", _PARAM_CASES)
def test_scale_round_trip_at_bounds(name, meta, field_name):
    from Services.robot_comm.core.params_v2 import to_eng, to_raw

    for raw in (meta["min"], meta["max"], meta["default"]):
        eng = to_eng(name, raw)
        assert to_raw(name, eng) == raw


def test_dict_fingerprint_matches_independent_crc():
    from Services.robot_comm.core.params_v2 import DICT_FINGERPRINT

    assert DICT_FINGERPRINT == _expected_dict_fingerprint()


# ─────────────────────────── lua_block ───────────────────────────


def test_lua_block_markers_and_sha():
    from Services.robot_comm import codegen

    text = codegen.lua_block(_REPO_ROOT)
    sha8 = hashlib.sha256(_YAML_PATH.read_bytes()).hexdigest()[:8]

    assert codegen.yaml_sha8(_REPO_ROOT) == sha8
    assert text.startswith(f"-- ===== BEGIN GENERATED (delta_v2.yaml {sha8}) =====")
    assert text.rstrip().endswith("-- ===== END GENERATED =====")

    # Lua 5.1 И 5.4 одновременно: без goto, без //, без битовых операторов
    assert "goto " not in text
    assert "//" not in text


def test_lua_block_runs_in_lua():
    lupa = pytest.importorskip("lupa")

    from Services.robot_comm import codegen
    from Services.robot_comm.core.params_v2 import DICT_FINGERPRINT

    text = codegen.lua_block(_REPO_ROOT)
    runtime = lupa.LuaRuntime()
    runtime.execute(text)
    g = runtime.globals()

    assert g["REG"]["CMD_FLAG"] == 0x1000
    assert g["OP"]["PARAM_SET"]["code"] == 0x50
    assert g["OP"]["PARAM_SET"]["argc"] == 2
    assert g["ERR"]["E_BUSY"] == 4
    assert g["PDEF"][96]["name"] == "P_WDG_TIMEOUT_MS"
    assert g["PDEF"][96]["def"] == 3000
    assert g["PDEF"][96]["min"] == 0
    assert g["PDEF"][96]["max"] == 60000
    assert g["PDEF"][96]["apply"] == "live"
    assert g["C"]["SC_CAP"] == 55
    assert g["C"]["PMIR_DICT"] == DICT_FINGERPRINT
    assert g["KIND"]["LINE_PASS"] == 1
    assert g["ACT"]["DELAY_MS"] == 3
    assert g["RSN"]["R_DEAD_ZONE"] == 5
    assert g["STOP"]["HALT"] == 3


# ─────────────────────────── CLI ───────────────────────────


def test_cli_check_exit_code(tmp_path):
    # Закоммиченное дерево проверяется как есть — без предварительной генерации, иначе проверка пуста
    import os

    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    common = dict(capture_output=True, text=True, timeout=60, env=env)
    fresh = subprocess.run([sys.executable, "-m", "Services.robot_comm.codegen", "--check"], cwd=_REPO_ROOT, **common)
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr

    # Дерево только с YAML (генератов нет) — устарело, код выхода 1
    yaml_copy = tmp_path / "Services" / "robot_comm" / "protocols" / "delta_v2.yaml"
    yaml_copy.parent.mkdir(parents=True)
    yaml_copy.write_bytes(_YAML_PATH.read_bytes())
    stale = subprocess.run([sys.executable, "-m", "Services.robot_comm.codegen", "--check"], cwd=tmp_path, **common)
    assert stale.returncode == 1, stale.stdout + stale.stderr
