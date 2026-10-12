"""Тесты лида T3.6 — свойства ленивых ``__init__``, которые не стережёт слепая приёмка (ревью T3.6 р.1).

Purpose: ``ROBOT_AVAILABLE`` без pymodbus, кэш имени в пространстве модуля, точный текст ``AttributeError``,
``__dir__`` без загрузки клиента, ленивый ``RobotCommService``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import Services.robot_comm as root_pkg
import Services.robot_comm.core as core_pkg

_ROOT = Path(__file__).resolve().parents[3]


def _run(code: str) -> object:
    """Выполнить код в чистом процессе (conftest уже загрузил клиента в этот) и вернуть его JSON-вывод."""
    env = dict(os.environ, PYTHONPATH=str(_ROOT), PYTHONUTF8="1")
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=_ROOT, env=env, capture_output=True, text=True, timeout=60, check=True
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_robot_available_follows_modbus_without_pymodbus() -> None:
    """Без pymodbus ``ROBOT_AVAILABLE`` — тот же ``False``, что ``Services.modbus.MODBUS_AVAILABLE``.

    Не доказывает поведение в настоящем venv без pymodbus: отсутствие имитируется ``sys.modules['pymodbus'] = None``.
    """
    got = _run(
        "import json, sys; sys.modules['pymodbus'] = None\n"
        "import Services.robot_comm as rc, Services.modbus as mb\n"
        "print(json.dumps([rc.ROBOT_AVAILABLE is mb.MODBUS_AVAILABLE, rc.ROBOT_AVAILABLE]))"
    )
    assert got == [True, False]


@pytest.mark.parametrize(
    ("pkg", "name"), [(root_pkg, "RobotConfig"), (core_pkg, "RobotClientV2")], ids=["root", "core"]
)
def test_lazy_name_is_cached_in_module_dict(pkg, name: str) -> None:
    """После первого обращения имя лежит в ``vars(pkg)`` — второй доступ идёт мимо ``__getattr__``.

    Не доказывает потокобезопасность первого обращения.
    """
    getattr(pkg, name)
    assert name in vars(pkg)


@pytest.mark.parametrize(
    ("pkg", "text"),
    [
        (root_pkg, "module 'Services.robot_comm' has no attribute 'NoSuchName_T36'"),
        (core_pkg, "module 'Services.robot_comm.core' has no attribute 'NoSuchName_T36'"),
    ],
    ids=["root", "core"],
)
def test_unknown_name_error_text_is_exact(pkg, text: str) -> None:
    """Текст ``AttributeError`` — стандартный текст модуля. Не доказывает ничего о подмодулях пакета."""
    with pytest.raises(AttributeError) as info:
        getattr(pkg, "NoSuchName_T36")
    assert str(info.value) == text


def test_dir_lists_all_without_loading_client() -> None:
    """``dir()`` обоих пакетов содержит все имена ``__all__`` и не грузит ``core.client``.

    Не доказывает порядок имён в ``dir()``.
    """
    got = _run(
        "import json, sys\n"
        "import Services.robot_comm as rc, Services.robot_comm.core as c\n"
        "d1, d2 = dir(rc), dir(c)\n"
        "print(json.dumps([set(rc.__all__) <= set(d1), set(c.__all__) <= set(d2),\n"
        "                  'Services.robot_comm.core.client' in sys.modules]))"
    )
    assert got == [True, True, False]


def test_robot_comm_service_is_direct_object() -> None:
    """``RobotCommService`` корня — тот же класс, что в ``service.py``. Не доказывает, что сервис работает."""
    from Services.robot_comm.service import RobotCommService

    assert root_pkg.RobotCommService is RobotCommService


__all__: list[str] = []
