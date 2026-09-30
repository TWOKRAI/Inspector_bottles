"""Слепые RED-тесты сборщика прошивки Services/robot_comm/build_fw.py (robot-protocol-v2, T1.3).

Написаны по контракту из брифа, без просмотра реализации (её ещё нет).
Модуль build_fw импортируется ВНУТРИ тестов (_bf()), а не на уровне файла:
пока модуля нет, каждый тест падает своим ModuleNotFoundError, а не одной
ошибкой сбора.

Ожидаемые значения — литералы. Единственное «вычисленное» число (FW_BUILD = 0x0C53)
получено ВНЕ кода под тестом независимой побитовой реализацией CRC16/MODBUS
(проверена по эталону «123456789» -> 0x4B37): сырой CRC источников ниже = 0x8C53,
т.е. бит 15 выставлен (маска 0x7FFF наблюдаема) и старший ниббл после маски нулевой
(дополнение до 4 цифр наблюдаемо).
"""

from __future__ import annotations

import importlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from Services.robot_comm import codegen

SRC = "robot/v2/src"
ART = "robot/v2/main_v2.lua"

# Тело «сгенерированного» блока: многострочный, без трейлинг-перевода строки и без 0x-хексов.
GEN_BLOCK = "-- BEGIN GEN\nREG = {A = 1}\n-- END GEN"

# Базовый набор источников. Конкатенация сырых байтов этого набора == строка, чей CRC
# посчитан офлайн: b"-- header\nFW_BUILD = @@FW_BUILD@@\n-- @@GENERATED@@\nx = 200\n".
HEADER = b"-- header\nFW_BUILD = @@FW_BUILD@@\n"
GENERATED = b"-- @@GENERATED@@\n"
BODY = b"x = 200\n"
DEFAULT = {"00_header.lua": HEADER, "10_generated.lua": GENERATED, "20_body.lua": BODY}
FW_BUILD_DEFAULT = 0x0C53  # (0x8C53 & 0x7FFF)


def _bf():
    return importlib.import_module("Services.robot_comm.build_fw")


def make_root(base: Path, files: dict[str, bytes], crlf: bool = False) -> Path:
    """Корень-пустышка: <base>/robot/v2/src/<файлы>. Пишем write_bytes (на машине autocrlf=true)."""
    src = base / SRC
    src.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (src / name).write_bytes(data.replace(b"\n", b"\r\n") if crlf else data)
    return base


def _nonblank(text: str) -> list[str]:
    return [ln.rstrip() for ln in text.split("\n") if ln.strip()]


@pytest.fixture
def gen_calls(monkeypatch):
    """Подмена codegen.lua_block (настоящему нужен delta_v2.yaml под root); пишет аргументы вызовов."""
    calls: list = []

    def fake(root):
        calls.append(root)
        return GEN_BLOCK

    monkeypatch.setattr(codegen, "lua_block", fake)
    return calls


@pytest.fixture
def no_luacheck(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)


def test_order_and_separators(tmp_path, gen_calls):
    bf = _bf()
    # Создаём в перемешанном порядке; «мусор» с неподходящими именами не должен попасть в сборку.
    files = {
        "25_c.lua": b"c = 3\n",
        "20_b.lua": b"b = 2\n",
        "00_header.lua": HEADER,
        "notes.lua": b"DECOY_notes\n",
        "5_short.lua": b"DECOY_short\n",
        "x9_bad.lua": b"DECOY_x9\n",
        "30_skip.txt": b"DECOY_txt\n",
        "20_a.lua": b"a = 1\n",
        "10_generated.lua": b"-- gen begin\n-- @@GENERATED@@\n-- gen end\n",
    }
    root = make_root(tmp_path, files)
    out = re.sub(r"0x[0-9A-F]{4}\b", "0xXXXX", bf.build(root))
    assert _nonblank(out) == [
        "-- ===== 00_header.lua =====",
        "-- header",
        "FW_BUILD = 0xXXXX",
        "-- ===== 10_generated.lua =====",
        "-- gen begin",
        "-- BEGIN GEN",
        "REG = {A = 1}",
        "-- END GEN",
        "-- gen end",
        "-- ===== 20_a.lua =====",
        "a = 1",
        "-- ===== 20_b.lua =====",
        "b = 2",
        "-- ===== 25_c.lua =====",
        "c = 3",
    ]


def test_generated_placeholder_replaced(tmp_path, gen_calls):
    bf = _bf()
    root = make_root(tmp_path, {**DEFAULT, "10_generated.lua": b"-- gen begin\n-- @@GENERATED@@\n-- gen end\n"})
    out = bf.build(root)
    assert GEN_BLOCK in out, "блок из codegen.lua_block должен войти в вывод целиком и подряд"
    assert out.count(GEN_BLOCK) == 1
    assert "@@GENERATED@@" not in out, "строка-заглушка должна быть заменена, а не оставлена"
    assert "@@FW_BUILD@@" not in out
    nb = _nonblank(out)
    i = nb.index("-- BEGIN GEN")
    assert nb[i - 1] == "-- gen begin" and nb[i + 3] == "-- gen end", "блок стоит ровно на месте строки-заглушки"
    assert gen_calls, "build обязан звать codegen.lua_block через атрибут модуля"
    assert {Path(c) for c in gen_calls} == {root}, "lua_block получает root"


def test_fw_build_literal_and_hand_value(tmp_path, gen_calls, monkeypatch):
    bf = _bf()
    root = make_root(tmp_path, DEFAULT)
    assert bf.fw_build(root) == 0x0C53
    assert "FW_BUILD = 0x0C53" in bf.build(root).split("\n"), "формат 0x%04X: верхний регистр, 4 цифры, маска 0x7FFF"
    # CRC берётся ДО подстановок: другой вывод lua_block FW_BUILD не меняет.
    codegen.lua_block = lambda r: "-- OTHER\nREG = {B = 2}"  # откатывается monkeypatch-ем gen_calls
    assert bf.fw_build(root) == 0x0C53
    assert "FW_BUILD = 0x0C53" in bf.build(root).split("\n")
    # Один изменённый байт источника меняет FW_BUILD.
    (root / SRC / "20_body.lua").write_bytes(b"x = 201\n")
    assert bf.fw_build(root) != 0x0C53


def test_deterministic_and_crlf_same_build(tmp_path, gen_calls):
    bf = _bf()
    lf = make_root(tmp_path / "lf", DEFAULT)
    crlf = make_root(tmp_path / "crlf", DEFAULT, crlf=True)
    assert (crlf / SRC / "20_body.lua").read_bytes() == b"x = 200\r\n", "фикстура: CRLF действительно записан"
    out_lf = bf.build(lf)
    assert bf.build(lf) == out_lf, "повторная сборка тех же входов идентична"
    out_crlf = bf.build(crlf)
    assert out_crlf == out_lf, "CRLF-источники дают тот же вывод, что и LF"
    assert bf.fw_build(crlf) == bf.fw_build(lf) == 0x0C53, "CRC считается по нормализованным (LF) байтам"
    assert "\r" not in out_crlf
    assert str(lf) not in out_lf and str(crlf) not in out_crlf, "в выводе нет путей"


def test_mirror_forbidden_code_vs_comment(tmp_path, gen_calls, capsys):
    bf = _bf()
    forbidden = {
        "delay": (b"local x = 1\nDELAY(5)\n", "DELAY"),
        "wait": (b"WAIT(3)\n", "WAIT"),
        "while": (b"while true do end\n", "while"),
        "code_before_comment": (b"DELAY(5) -- why\n", "DELAY"),
    }
    for name, (mirror, word) in forbidden.items():
        root = make_root(tmp_path / name, {**DEFAULT, "80_mirror.lua": mirror})
        with pytest.raises(bf.BuildError) as ei:
            bf.build(root)
        msg = str(ei.value)
        assert "80_mirror" in msg and word in msg, f"{name}: сообщение без файла или слова: {msg!r}"

    allowed = {
        "clean": b"local y = 2\n",
        "delay_in_comment": b"-- DELAY(5) is forbidden here\nlocal y = 2\n",
        "wait_after_dashes": b"local x = 1 -- WAIT( no\n",
        "while_in_comment": b"-- while loops banned\nlocal y = 2\n",
    }
    for name, mirror in allowed.items():
        root = make_root(tmp_path / name, {**DEFAULT, "80_mirror.lua": mirror})
        bf.build(root)  # не должно бросать: контроль, что фикстура сама по себе собирается

    # Правило только для 80_mirror: те же слова в другом файле, либо без 80_mirror — не ошибка.
    other = make_root(tmp_path / "other_file", {**DEFAULT, "20_body.lua": b"DELAY(1)\nwhile x do end\nWAIT(2)\n"})
    bf.build(other)

    # CLI: ошибка сборки -> stderr + код 1, артефакт не создан.
    bad = make_root(tmp_path / "cli", {**DEFAULT, "80_mirror.lua": b"DELAY(5)\n"})
    assert bf.main(["--root", str(bad)]) == 1
    assert "DELAY" in capsys.readouterr().err
    assert not (bad / ART).exists()


def test_missing_generated_or_placeholder_errors(tmp_path, gen_calls, capsys):
    bf = _bf()
    bf.build(make_root(tmp_path / "control", DEFAULT))  # контроль: базовый набор собирается

    with pytest.raises(bf.BuildError):
        bf.build(make_root(tmp_path / "no_nn", {"notes.lua": b"x\n", "5_short.lua": b"y\n"}))

    no_header = {k: v for k, v in DEFAULT.items() if k != "00_header.lua"}
    with pytest.raises(bf.BuildError, match="00_header"):
        bf.build(make_root(tmp_path / "no_header", no_header))

    no_gen = {k: v for k, v in DEFAULT.items() if k != "10_generated.lua"}
    with pytest.raises(bf.BuildError, match="10_generated"):
        bf.build(make_root(tmp_path / "no_gen", no_gen))

    with pytest.raises(bf.BuildError, match="GENERATED|10_generated"):
        bf.build(make_root(tmp_path / "no_placeholder", {**DEFAULT, "10_generated.lua": b"-- nothing here\n"}))

    with pytest.raises(bf.BuildError, match="FW_BUILD|00_header"):
        bf.build(make_root(tmp_path / "no_token", {**DEFAULT, "00_header.lua": b"-- header\n"}))

    # CLI: тот же отказ -> код 1, сообщение в stderr, артефакт не создан.
    cli = make_root(tmp_path / "cli", no_gen)
    assert bf.main(["--root", str(cli)]) == 1
    assert "10_generated" in capsys.readouterr().err
    assert not (cli / ART).exists()


def test_check_zero_then_edit_one(tmp_path, gen_calls, no_luacheck):
    bf = _bf()
    root = make_root(tmp_path, DEFAULT)
    art = root / ART
    check = ["--check", "--root", str(root)]

    assert bf.main(check) == 1, "артефакта нет -> не свежий"
    assert not art.exists(), "--check ничего не пишет"

    assert bf.main(["--root", str(root)]) == 0
    written = art.read_bytes()
    assert written == bf.build(root).encode("ascii"), "артефакт == build(root) побайтно"
    assert b"\r" not in written, "артефакт с LF-окончаниями"
    assert bf.main(check) == 0
    assert bf.check(root) == []

    # Правка одного источника -> артефакт устарел; --check не чинит его молча.
    (root / SRC / "20_body.lua").write_bytes(BODY + b"y = 2\n")
    assert bf.main(check) == 1
    assert art.read_bytes() == written

    assert bf.main(["--root", str(root)]) == 0
    assert bf.main(check) == 0

    # Правка одного байта самого артефакта -> тоже устарел.
    fresh = art.read_bytes()
    assert b"x = 200" in fresh
    art.write_bytes(fresh.replace(b"x = 200", b"x = 201"))
    assert bf.main(check) == 1

    # Тот же текст, но с CRLF — не «равен побайтно».
    art.write_bytes(fresh.replace(b"\n", b"\r\n"))
    assert bf.main(check) == 1

    art.write_bytes(fresh)
    assert bf.main(check) == 0


def test_luacheck_absent_warns_present_failing_fails(tmp_path, gen_calls, monkeypatch, capsys):
    bf = _bf()
    root = make_root(tmp_path, DEFAULT)
    check = ["--check", "--root", str(root)]
    runs: list = []

    def fake_run(cmd, *a, rc=0, **k):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, rc)

    monkeypatch.setattr(subprocess, "run", lambda cmd, *a, **k: fake_run(cmd, *a, **k))
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    assert bf.main(["--root", str(root)]) == 0  # свежий артефакт
    capsys.readouterr()

    # luacheck отсутствует: предупреждение в stderr, но не провал; subprocess не зовётся.
    assert bf.main(check) == 0
    err = capsys.readouterr().err
    assert "luacheck" in err.lower(), "отсутствие luacheck должно быть видно в stderr"
    assert not any("luacheck" in " ".join(map(str, c)).lower() for c in runs)

    # luacheck есть и возвращает 0: успех, и он реально запущен.
    found = lambda name, *a, **k: "C:/fake/luacheck.exe" if str(name).startswith("luacheck") else None  # noqa: E731
    monkeypatch.setattr(shutil, "which", found)
    monkeypatch.setattr(subprocess, "run", lambda cmd, *a, **k: fake_run(cmd, *a, rc=0, **k))
    assert bf.main(check) == 0
    assert any("luacheck" in " ".join(map(str, c)).lower() for c in runs), "luacheck обязан быть запущен"

    # luacheck есть и возвращает не 0: код 1.
    monkeypatch.setattr(subprocess, "run", lambda cmd, *a, **k: fake_run(cmd, *a, rc=1, **k))
    assert bf.main(check) == 1


def test_repo_artifact_fresh(capsys, no_luacheck):
    bf = _bf()
    repo = Path(__file__).resolve().parents[3]
    rc = bf.main(["--check", "--root", str(repo)])
    assert rc == 0, f"robot/v2/main_v2.lua устарел или отсутствует: {capsys.readouterr().err}"
