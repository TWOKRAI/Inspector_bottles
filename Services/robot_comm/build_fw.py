"""Сборщик прошивки робота: robot/v2/src/NN_*.lua -> robot/v2/main_v2.lua (robot-protocol-v2, T1.3).

Контракт:
- Источники: ``<root>/robot/v2/src/[0-9][0-9]_*.lua``, по возрастанию имени. Нет каталога или
  файлов -> ``BuildError``. Обязательны ``00_header.lua`` и ``10_generated.lua``.
- Читаются байты, ``\r\n`` -> ``\n``, декодирование utf-8.
- ``FW_BUILD`` = ``codegen.crc16_modbus(склейка нормализованных сырых байт) & 0x7FFF``,
  считается ДО подстановок (вывод ``lua_block`` на него не влияет).
- Вывод: для каждого файла ``-- ===== <имя> =====`` + его текст (с ``\n`` в конце).
  В ``10_generated.lua`` строка ровно ``-- @@GENERATED@@`` заменяется на ``codegen.lua_block(root)``;
  в ``00_header.lua`` токен ``@@FW_BUILD@@`` -> ``0xXXXX``.
- ``80_mirror.lua`` (если есть): в коде (часть строки до ``--``) запрещены ``while``, ``WAIT(``,
  ``DELAY(`` — ошибка с именем файла, номером строки и словом. Регистр важен.
- Артефакт пишется байтами (LF, без CR): на машине autocrlf=true ``write_text`` дал бы CRLF.

CLI: ``python -m Services.robot_comm.build_fw [--check] [--root PATH]``. Сначала luacheck
(нет в PATH -> предупреждение в stderr, не провал), затем сборка либо ``--check`` (без записи).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess  # nosec B404 — запуск luacheck по фиксированному списку аргументов
import sys
from pathlib import Path

from Services.robot_comm import codegen

SRC_REL = Path("robot/v2/src")
ARTIFACT_REL = Path("robot/v2/main_v2.lua")

_HEADER = "00_header.lua"
_GENERATED = "10_generated.lua"
_MIRROR = "80_mirror.lua"
_GEN_LINE = "-- @@GENERATED@@"
_FW_TOKEN = "@@FW_BUILD@@"  # nosec B105 — токен-подстановка, не пароль
_MIRROR_FORBIDDEN = (r"\bwhile\b", r"WAIT\(", r"DELAY\(")


class BuildError(Exception):
    """Ошибка сборки прошивки (нет источников, заглушки, запрещённый код в 80_mirror)."""


def _sources(root: Path) -> dict[str, bytes]:
    """Имя -> сырые байты источников по возрастанию имени."""
    src_dir = Path(root) / SRC_REL
    if not src_dir.is_dir():
        raise BuildError(f"нет каталога источников: {src_dir}")
    paths = sorted(src_dir.glob("[0-9][0-9]_*.lua"), key=lambda p: p.name)
    if not paths:
        raise BuildError(f"в {src_dir} нет файлов NN_*.lua")
    return {p.name: p.read_bytes().replace(b"\r\n", b"\n") for p in paths}


def _fw_build_of(raw: dict[str, bytes]) -> int:
    return codegen.crc16_modbus(b"".join(raw.values())) & 0x7FFF


def fw_build(root: Path) -> int:
    """FW_BUILD: CRC16/MODBUS нормализованных источников, маска 0x7FFF."""
    return _fw_build_of(_sources(root))


def _check_mirror(text: str) -> None:
    for lineno, line in enumerate(text.split("\n"), start=1):
        code = line.split("--", 1)[0]
        for pattern in _MIRROR_FORBIDDEN:
            hit = re.search(pattern, code)
            if hit:
                raise BuildError(f"80_mirror, строка {lineno}: запрещено {hit.group(0)!r} в зеркале")


def build(root: Path) -> str:
    """Текст main_v2.lua. На диск ничего не пишет."""
    raw = _sources(root)
    for required in (_HEADER, _GENERATED):
        if required not in raw:
            raise BuildError(f"нет обязательного файла {required}")
    fw = _fw_build_of(raw)

    parts: list[str] = []
    for name, data in raw.items():
        text = data.decode("utf-8")
        if name == _MIRROR:
            _check_mirror(text)
        if name == _HEADER:
            if _FW_TOKEN not in text:
                raise BuildError(f"{name}: нет токена {_FW_TOKEN}")
            text = text.replace(_FW_TOKEN, f"0x{fw:04X}")
        elif name == _GENERATED:
            lines = text.split("\n")
            if _GEN_LINE not in lines:
                raise BuildError(f"{name}: нет строки-заглушки {_GEN_LINE}")
            block = codegen.lua_block(root).rstrip("\n")
            text = "\n".join(block if ln == _GEN_LINE else ln for ln in lines)
        if not text.endswith("\n"):
            text += "\n"
        parts.append(f"-- ===== {name} =====\n{text}")
    return "".join(parts)


def check(root: Path) -> list[str]:
    """Проблемы свежести артефакта (пусто = свежий). BuildError пробрасывается."""
    expected = build(root).encode("utf-8")
    artifact = Path(root) / ARTIFACT_REL
    if not artifact.exists():
        return [f"артефакт отсутствует: {artifact}"]
    if artifact.read_bytes() != expected:
        return [f"артефакт устарел: {artifact} (пересоберите: python -m Services.robot_comm.build_fw)"]
    return []


def _luacheck(src_dir: Path) -> bool:
    """False, если luacheck запущен и нашёл проблемы. Нет luacheck -> предупреждение, True."""
    exe = shutil.which("luacheck")
    if exe is None:
        print("предупреждение: luacheck не найден в PATH, статпроверка Lua пропущена", file=sys.stderr)
        return True
    if subprocess.run([exe, str(src_dir)]).returncode != 0:  # nosec B603 — exe из shutil.which, без shell
        print("luacheck: найдены проблемы", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_fw", description="Сборка robot/v2/main_v2.lua из robot/v2/src")
    parser.add_argument("--check", action="store_true", help="не писать, проверить свежесть артефакта")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2], help="корень репозитория")
    args = parser.parse_args(argv)
    root: Path = args.root

    if not _luacheck(root / SRC_REL):
        return 1
    try:
        if args.check:
            problems = check(root)
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1 if problems else 0
        (root / ARTIFACT_REL).write_bytes(build(root).encode("utf-8"))
    except BuildError as exc:
        print(f"ошибка сборки: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
