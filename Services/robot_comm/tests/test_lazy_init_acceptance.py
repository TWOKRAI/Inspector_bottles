"""Слепые приёмочные тесты ленивых ``__init__`` пакетов ``robot_comm`` и ``robot_comm.core`` (T3.6).

Purpose:
    Закрепить три свойства, которые реализация обязана дать (или сохранить):

    1. ``import Services.robot_comm.programs`` и ``import Services.robot_comm.core.protocol_v2``
       не тянут ``pymodbus``, ``Services.modbus`` и ``Services.robot_comm.core.client``
       (для ``protocol_v2`` — ещё и ``core.client_v2``). Проверка — только в ОТДЕЛЬНОМ процессе
       (``subprocess``): процесс pytest не годится, ``tests/conftest.py`` уже загрузил клиента.
    2. Имена ``__all__`` корня и ``core`` — те же объекты (``is``), что прямой импорт из
       модуля-источника; множества ``__all__`` равны литералам ниже.
    3. Неизвестное имя даёт ``AttributeError`` с этим именем в тексте; ``hasattr`` — ``False``;
       ``from <пакет> import *`` отдаёт все имена ``__all__``.

    Ожидания — литералы из задания T3.6, не результат чтения ``__init__.py``.
    Тесты не читали реализацию ленивых ``__init__`` (её ещё нет). До кода красные: оба теста
    «не загружено»; остальные — зелёные сторожа поведения, которое жадный код уже даёт.

Что файл НЕ покрывает намеренно: время импорта (не меряется), ``RobotCommService``,
``params_v2``, ``multiprocess_framework``, потокобезопасность первого обращения к ленивому
имени, поведение ``dir(pkg)`` и ``__getattr__`` на модульном уровне подпакетов.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Корень репозитория (или worktree): tests -> robot_comm -> Services -> корень.
_ROOT = Path(__file__).resolve().parents[3]

_ROOT_PKG = "Services.robot_comm"
_CORE_PKG = "Services.robot_comm.core"

# Таблица корня: имя -> (модуль-источник, атрибут в нём). 13 имён.
_ROOT_TABLE: dict[str, tuple[str, str]] = {
    "RobotClient": ("Services.robot_comm.core.client", "RobotClient"),
    "RobotConfig": ("Services.robot_comm.core.config", "RobotConfig"),
    "RobotPosition": ("Services.robot_comm.core.datatypes", "RobotPosition"),
    "Telemetry": ("Services.robot_comm.core.datatypes", "Telemetry"),
    "JobEcho": ("Services.robot_comm.core.datatypes", "JobEcho"),
    "DrawPoint": ("Services.robot_comm.core.datatypes", "DrawPoint"),
    "RobotClientProtocol": ("Services.robot_comm.interfaces", "RobotClientProtocol"),
    "DeviceTransport": ("Services.robot_comm.interfaces", "DeviceTransport"),
    "RobotCommError": ("Services.robot_comm.errors", "RobotCommError"),
    "RobotJobError": ("Services.robot_comm.errors", "RobotJobError"),
    "RobotNotConnectedError": ("Services.robot_comm.errors", "RobotNotConnectedError"),
    "build_register_map": ("Services.robot_comm.core.registers", "build_register_map"),
    "ROBOT_AVAILABLE": ("Services.modbus", "MODBUS_AVAILABLE"),
}
_ROOT_ALL = {
    "RobotClient",
    "RobotConfig",
    "RobotPosition",
    "Telemetry",
    "JobEcho",
    "DrawPoint",
    "RobotClientProtocol",
    "DeviceTransport",
    "RobotCommError",
    "RobotJobError",
    "RobotNotConnectedError",
    "build_register_map",
    "ROBOT_AVAILABLE",
}

# Таблица core: имя -> (модуль-источник, атрибут в нём). 9 имён.
_CORE_TABLE: dict[str, tuple[str, str]] = {
    "RobotClient": ("Services.robot_comm.core.client", "RobotClient"),
    "RobotClientV2": ("Services.robot_comm.core.client_v2", "RobotClientV2"),
    "ClientV2Config": ("Services.robot_comm.core.client_v2", "ClientV2Config"),
    "RobotConfig": ("Services.robot_comm.core.config", "RobotConfig"),
    "RobotPosition": ("Services.robot_comm.core.datatypes", "RobotPosition"),
    "Telemetry": ("Services.robot_comm.core.datatypes", "Telemetry"),
    "JobEcho": ("Services.robot_comm.core.datatypes", "JobEcho"),
    "DrawPoint": ("Services.robot_comm.core.datatypes", "DrawPoint"),
    "build_register_map": ("Services.robot_comm.core.registers", "build_register_map"),
}
_CORE_ALL = {
    "RobotClient",
    "RobotClientV2",
    "ClientV2Config",
    "RobotConfig",
    "RobotPosition",
    "Telemetry",
    "JobEcho",
    "DrawPoint",
    "build_register_map",
}

_UNKNOWN_NAME = "NoSuchName_T36"


def _run_child(code: str) -> str:
    """Выполнить ``code`` в чистом процессе Python и вернуть последнюю строку stdout.

    ``cwd`` и ``PYTHONPATH`` заданы явно: иначе подпроцесс импортирует пакет из основного дерева.
    """
    env = {**os.environ, "PYTHONPATH": str(_ROOT), "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"подпроцесс упал (код {proc.returncode}):\n{proc.stderr}"
    lines = proc.stdout.strip().splitlines()
    assert lines, f"подпроцесс ничего не напечатал; stderr:\n{proc.stderr}"
    return lines[-1]


def _loaded_after_import(import_statement: str) -> list[str]:
    """Имена модулей в ``sys.modules`` дочернего процесса после ``import_statement``."""
    code = f"import json, sys\n{import_statement}\nprint(json.dumps(sorted(sys.modules)))\n"
    return json.loads(_run_child(code))


def _hits(loaded: list[str], name: str) -> list[str]:
    """Ключи ``sys.modules``, равные ``name`` или начинающиеся с ``name + '.'``."""
    return [key for key in loaded if key == name or key.startswith(name + ".")]


@pytest.mark.parametrize(
    "forbidden",
    ["pymodbus", "Services.modbus", "Services.robot_comm.core.client"],
)
def test_programs_import_does_not_load(forbidden: str) -> None:
    """``import Services.robot_comm.programs`` не загружает ``forbidden`` (ни его подмодули).

    Не доказывает: что ``programs`` вообще работоспособен после импорта (это тесты
    ``test_programs_*``); что не грузится ``core.client_v2`` (отдельный модуль, тут не проверяется).
    """
    loaded = _loaded_after_import("import Services.robot_comm.programs")
    assert _hits(loaded, forbidden) == []


@pytest.mark.parametrize(
    "forbidden",
    [
        "pymodbus",
        "Services.modbus",
        "Services.robot_comm.core.client",
        "Services.robot_comm.core.client_v2",
    ],
)
def test_core_leaf_import_does_not_load(forbidden: str) -> None:
    """``import Services.robot_comm.core.protocol_v2`` не загружает ``forbidden``.

    Имя ``core.client`` проверяется точно: ``core.client_v2`` не начинается с ``core.client.``
    и ловится только собственным параметром. Не доказывает: что ``protocol_v2`` корректен по
    содержанию (это ``test_protocol_v2_yaml``).
    """
    loaded = _loaded_after_import("import Services.robot_comm.core.protocol_v2")
    assert _hits(loaded, forbidden) == []


def test_subprocess_sees_eager_import() -> None:
    """Достижимость: ``import Services.robot_comm.core.client`` в том же подпроцессе грузит ``pymodbus``.

    Без этой пары тесты «не загружено» были бы зелёными пусто (подпроцесс не видел бы импортов).
    Не доказывает: что сам ``pymodbus`` нужен клиенту по контракту — только что при загрузке
    клиента он оказывается в ``sys.modules``.
    """
    loaded = _loaded_after_import("import Services.robot_comm.core.client")
    assert _hits(loaded, "pymodbus") != []


def test_root_all_is_the_literal_set() -> None:
    """``set(Services.robot_comm.__all__)`` равно 13 именам из задания.

    Не доказывает: порядок имён и отсутствие дублей в списке; что каждое имя разрешается
    (это ``test_root_names_are_direct_objects``).
    """
    pkg = importlib.import_module(_ROOT_PKG)
    assert set(pkg.__all__) == _ROOT_ALL


@pytest.mark.parametrize("name", sorted(_ROOT_TABLE))
def test_root_names_are_direct_objects(name: str) -> None:
    """Имя корня ``Services.robot_comm`` — тот же объект, что прямой импорт из модуля-источника.

    Проверка тождества (``is``), а не равенства. Не доказывает: что имя не загружено заранее
    (ленивость — тесты ``..._does_not_load``); что в чистом процессе первое обращение к имени
    работает (в процессе pytest модули уже загружены ``conftest``).
    """
    module_name, attr = _ROOT_TABLE[name]
    pkg = importlib.import_module(_ROOT_PKG)
    source = getattr(importlib.import_module(module_name), attr)
    assert getattr(pkg, name) is source


def test_core_all_is_the_literal_set() -> None:
    """``set(Services.robot_comm.core.__all__)`` равно 9 именам из задания.

    Не доказывает: порядок и дубли; что имена разрешаются (это
    ``test_core_names_are_direct_objects``).
    """
    pkg = importlib.import_module(_CORE_PKG)
    assert set(pkg.__all__) == _CORE_ALL


@pytest.mark.parametrize("name", sorted(_CORE_TABLE))
def test_core_names_are_direct_objects(name: str) -> None:
    """Имя ``Services.robot_comm.core`` — тот же объект, что прямой импорт из модуля-источника.

    Не доказывает: ленивость загрузки и поведение в чистом процессе (см. примечание к
    ``test_root_names_are_direct_objects``).
    """
    module_name, attr = _CORE_TABLE[name]
    pkg = importlib.import_module(_CORE_PKG)
    source = getattr(importlib.import_module(module_name), attr)
    assert getattr(pkg, name) is source


@pytest.mark.parametrize("pkg_name", [_ROOT_PKG, _CORE_PKG])
def test_unknown_name_raises_attribute_error(pkg_name: str) -> None:
    """Неизвестное имя: ``AttributeError`` с именем в тексте, ``hasattr`` даёт ``False``.

    Не доказывает: точный формат сообщения (проверяется только вхождение имени); что
    ``AttributeError`` не маскирует внутреннюю ошибку импорта известного имени.
    """
    pkg = importlib.import_module(pkg_name)
    with pytest.raises(AttributeError, match=_UNKNOWN_NAME):
        getattr(pkg, _UNKNOWN_NAME)
    assert hasattr(pkg, _UNKNOWN_NAME) is False


@pytest.mark.parametrize(
    ("pkg_name", "expected"),
    [(_ROOT_PKG, _ROOT_ALL), (_CORE_PKG, _CORE_ALL)],
    ids=["root", "core"],
)
def test_star_import_gives_all_names(pkg_name: str, expected: set[str]) -> None:
    """``from <пакет> import *`` в чистом процессе кладёт в пространство имён ровно имена ``__all__``.

    Не доказывает: что имена в пространстве имён — те же объекты (это тесты ``..._direct_objects``);
    поведение ``import *`` из подмодулей.
    """
    code = (
        "import json\n"
        "ns = {}\n"
        f"exec('from {pkg_name} import *', ns)\n"
        "print(json.dumps(sorted(k for k in ns if k != '__builtins__')))\n"
    )
    names = json.loads(_run_child(code))
    assert set(names) == expected


__all__: list[str] = []
