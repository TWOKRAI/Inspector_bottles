"""Авторские hazard-тесты сборщика прошивки build_fw (robot-protocol-v2, T1.3, итерация 2).

Слепые тесты tester'а лежат в test_build_fw.py; здесь — места, которые видит только автор:
что именно проверяет luacheck, BOM, остатки токенов, регистр glob, границы regex 80_mirror,
не-UTF-8 источник. Каждый негативный тест проверяет подстроку сообщения, а не только тип ошибки.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from Services.robot_comm import build_fw, codegen

SRC = "robot/v2/src"
ART = "robot/v2/main_v2.lua"

DEFAULT = {
    "00_header.lua": b"-- header\nFW_BUILD = @@FW_BUILD@@\n",
    "10_generated.lua": b"-- @@GENERATED@@\n",
    "20_body.lua": b"x = 200\n",
}


def make_root(base: Path, files: dict[str, bytes]) -> Path:
    src = base / SRC
    src.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (src / name).write_bytes(data)
    return base


@pytest.fixture(autouse=True)
def _fake_lua_block(monkeypatch):
    monkeypatch.setattr(codegen, "lua_block", lambda root: "-- GEN\nREG = {A = 1}")


def _fake_luacheck(monkeypatch):
    """Подмена luacheck: пишет argv и «существовал ли артефакт в момент вызова»."""
    runs: list[tuple[list, bool]] = []

    def fake_run(cmd, *a, **k):
        runs.append((list(cmd), Path(cmd[-1]).exists()))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "C:/fake/luacheck.exe")
    monkeypatch.setattr(subprocess, "run", fake_run)
    return runs


def test_luacheck_runs_on_built_artifact_after_write(tmp_path, monkeypatch):
    """luacheck: конфиг из robot/v2, последним аргументом собранный артефакт, к моменту вызова он уже записан."""
    root = make_root(tmp_path, DEFAULT)
    runs = _fake_luacheck(monkeypatch)
    assert build_fw.main(["--root", str(root)]) == 0
    ((cmd, existed),) = runs
    assert existed is True, "luacheck вызван до записи артефакта"
    assert Path(cmd[-1]) == root / ART
    assert cmd[1] == "--config" and Path(cmd[2]) == root / "robot/v2/.luacheckrc"
    runs.clear()
    assert build_fw.main(["--check", "--root", str(root)]) == 0
    ((cmd, existed),) = runs
    assert existed is True and Path(cmd[-1]) == root / ART
    assert cmd[1] == "--config" and Path(cmd[2]) == root / "robot/v2/.luacheckrc"


def test_check_stale_artifact_skips_luacheck(tmp_path, monkeypatch):
    """--check по устаревшему артефакту: rc=1, luacheck не зовётся."""
    root = make_root(tmp_path, DEFAULT)
    runs = _fake_luacheck(monkeypatch)
    assert build_fw.main(["--root", str(root)]) == 0
    runs.clear()
    (root / SRC / "20_body.lua").write_bytes(b"x = 201\n")
    assert build_fw.main(["--check", "--root", str(root)]) == 1
    assert runs == []


def test_bom_in_source_is_build_error(tmp_path):
    root = make_root(tmp_path, {**DEFAULT, "20_body.lua": b"\xef\xbb\xbfx = 1\n"})
    with pytest.raises(build_fw.BuildError, match=r"20_body.*BOM"):
        build_fw.build(root)


def test_fw_build_token_outside_header_is_error(tmp_path):
    root = make_root(tmp_path, {**DEFAULT, "20_body.lua": b"v = @@FW_BUILD@@\n"})
    with pytest.raises(build_fw.BuildError, match="@@"):
        build_fw.build(root)


def test_generated_line_twice_is_error(tmp_path):
    root = make_root(tmp_path, {**DEFAULT, "10_generated.lua": b"-- @@GENERATED@@\n-- @@GENERATED@@\n"})
    with pytest.raises(build_fw.BuildError, match="10_generated.*GENERATED"):
        build_fw.build(root)


def test_uppercase_extension_not_picked_up(tmp_path):
    """Регистр имени учитывается одинаково на win32 и Linux: 20_UP.LUA в сборку не входит."""
    root = make_root(tmp_path, {**DEFAULT, "20_UP.LUA": b"UPPER_MARK = 1\n"})
    assert "UPPER_MARK" not in build_fw.build(root)


def test_mirror_wait_with_space_is_error(tmp_path):
    root = make_root(tmp_path, {**DEFAULT, "80_mirror.lua": b"local a = 1\nWAIT (3)\n"})
    with pytest.raises(build_fw.BuildError, match=r"80_mirror.*строка 2.*WAIT"):
        build_fw.build(root)


def test_non_utf8_source_is_error(tmp_path):
    root = make_root(tmp_path, {**DEFAULT, "20_body.lua": "-- комментарий\n".encode("cp1251")})
    with pytest.raises(build_fw.BuildError, match=r"20_body.*UTF-8"):
        build_fw.build(root)
