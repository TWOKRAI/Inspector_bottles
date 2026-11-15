"""Приёмка (слепая): корень репозитория для относительного registry_path и предупреждение о прежнем месте.

Контракт из критериев B1..B9:
- без INSPECTOR_DATA_DIR относительный путь реестра считается от корня репозитория (а не от его родителя);
- если реестр по прежнему месту (родитель корня) есть, а по новому нет — configure пишет ровно одно
  предупреждение через ``ctx.log_warning`` и ничего не трогает на диске;
- сбой проверки прежнего места не роняет configure.

ctx — мок (make_ctx): смотрим ``ctx.log_warning.call_args_list``, не caplog. Корень репозитория в тестах — литерал
``Path(plugin.__file__).resolve().parents[3]``. В настоящий <репо>/data/ тесты не пишут и настоящие devices.yaml
не читают: везде, где зовётся configure, ``_PROJECT_ROOT`` подменяется на каталог внутри tmp_path.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import Plugins.hub.device_hub.plugin as plugin_mod
from Plugins.hub.device_hub.plugin import DeviceHubPlugin, _resolve_registry_path

from .conftest import make_ctx

_LEGACY_YAML = "version: 1\ndevices: []\n"
_LEGACY_MTIME_NS = 1_000_000_000_000_000_000  # 2001-09-09, заведомо не «сейчас»


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каждый тест — без INSPECTOR_DATA_DIR."""
    monkeypatch.delenv("INSPECTOR_DATA_DIR", raising=False)


def _repo_root() -> Path:
    """Корень репозитория — литерал: plugin.py лежит в <корень>/Plugins/hub/device_hub/."""
    return Path(plugin_mod.__file__).resolve().parents[3]


def _warnings(ctx: MagicMock) -> list[str]:
    """Тексты всех вызовов ctx.log_warning (позиционный первый аргумент)."""
    return [str(c.args[0]) if c.args else str(c.kwargs) for c in ctx.log_warning.call_args_list]


def _setup_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    """Подменить _PROJECT_ROOT на <tmp>/repo; вернуть (repo, новый реестр, прежний реестр)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(plugin_mod, "_PROJECT_ROOT", repo)
    return repo, repo / "data" / "devices.yaml", tmp_path / "data" / "devices.yaml"


def _make_legacy_file(legacy: Path) -> None:
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(_LEGACY_YAML, encoding="utf-8")
    os.utime(legacy, ns=(_LEGACY_MTIME_NS, _LEGACY_MTIME_NS))


def _configure(raw_path: str) -> tuple[DeviceHubPlugin, MagicMock]:
    ctx = make_ctx({"registry_path": raw_path})
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    return plugin, ctx


# ------------------------------------------------------------------ #
# B1-B4: резолв пути
# ------------------------------------------------------------------ #


def test_b1_relative_path_resolves_to_repo_root() -> None:
    """B1: без env относительный путь — ровно <корень репозитория>/data/devices.yaml."""
    assert _resolve_registry_path("data/devices.yaml") == _repo_root() / "data" / "devices.yaml"


def test_b2_relative_path_is_inside_repo_root() -> None:
    """B2: результат лежит внутри корня репозитория, а не выше него."""
    assert _resolve_registry_path("data/devices.yaml").is_relative_to(_repo_root())


def test_b3_env_data_dir_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B3: INSPECTOR_DATA_DIR=<tmp>/data -> <tmp>/data/devices.yaml."""
    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path / "data"))
    assert _resolve_registry_path("data/devices.yaml") == tmp_path / "data" / "devices.yaml"


def test_b4_absolute_path_returned_as_is(tmp_path: Path) -> None:
    """B4: абсолютный путь возвращается как есть."""
    raw = tmp_path / "somewhere" / "devices.yaml"
    assert _resolve_registry_path(str(raw)) == raw


# ------------------------------------------------------------------ #
# B5-B6: предупреждение о прежнем месте
# ------------------------------------------------------------------ #


def test_b5_legacy_registry_file_gives_one_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B5: прежний файл есть, нового нет -> ровно одно предупреждение с обоими путями и словом «вручную»."""
    _repo, new_reg, legacy = _setup_roots(monkeypatch, tmp_path)
    _make_legacy_file(legacy)
    assert not new_reg.exists()

    _plugin, ctx = _configure("data/devices.yaml")

    warns = _warnings(ctx)
    assert len(warns) == 1, warns
    assert str(new_reg) in warns[0]
    assert str(legacy) in warns[0]
    assert "вручную" in warns[0]


def test_b5_legacy_file_untouched_and_new_not_created(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B5: configure не трогает прежний файл (содержимое, mtime) и не создаёт новый реестр."""
    _repo, new_reg, legacy = _setup_roots(monkeypatch, tmp_path)
    _make_legacy_file(legacy)

    _configure("data/devices.yaml")

    assert legacy.read_text(encoding="utf-8") == "version: 1\ndevices: []\n"
    assert legacy.stat().st_mtime_ns == _LEGACY_MTIME_NS
    assert not new_reg.exists()


def test_b6_legacy_robot_dir_only_gives_one_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B6: на прежнем месте только каталог data/robot (файла реестра нет) -> одно предупреждение."""
    _repo, new_reg, legacy = _setup_roots(monkeypatch, tmp_path)
    (tmp_path / "data" / "robot").mkdir(parents=True)
    assert not legacy.exists()

    _plugin, ctx = _configure("data/devices.yaml")

    warns = _warnings(ctx)
    assert len(warns) == 1, warns
    assert str(new_reg) in warns[0]
    assert str(legacy) in warns[0]
    assert "вручную" in warns[0]


# ------------------------------------------------------------------ #
# B7: когда предупреждения нет
# ------------------------------------------------------------------ #


def test_b7_new_registry_exists_no_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B7: новый реестр уже есть (прежний тоже) -> предупреждений нет."""
    _repo, new_reg, legacy = _setup_roots(monkeypatch, tmp_path)
    _make_legacy_file(legacy)
    new_reg.parent.mkdir(parents=True)
    new_reg.write_text(_LEGACY_YAML, encoding="utf-8")

    _plugin, ctx = _configure("data/devices.yaml")

    assert _warnings(ctx) == []


def test_b7_env_data_dir_set_no_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B7: задан INSPECTOR_DATA_DIR -> предупреждений нет (прежнее место существует, нового нет)."""
    _repo, _new_reg, legacy = _setup_roots(monkeypatch, tmp_path)
    _make_legacy_file(legacy)
    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path / "envroot" / "data"))

    _plugin, ctx = _configure("data/devices.yaml")

    assert _warnings(ctx) == []


def test_b7_absolute_registry_path_no_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B7: абсолютный registry_path -> предупреждений нет (прежнее место существует)."""
    _repo, _new_reg, legacy = _setup_roots(monkeypatch, tmp_path)
    _make_legacy_file(legacy)

    _plugin, ctx = _configure(str(tmp_path / "abs" / "devices.yaml"))

    assert _warnings(ctx) == []


def test_b7_no_legacy_place_no_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B7: прежнего места нет вовсе -> предупреждений нет."""
    _repo, _new_reg, legacy = _setup_roots(monkeypatch, tmp_path)
    assert not legacy.parent.exists()

    _plugin, ctx = _configure("data/devices.yaml")

    assert _warnings(ctx) == []


# ------------------------------------------------------------------ #
# B8: второй configure после того, как первый создал реестр
# ------------------------------------------------------------------ #


def test_b8_second_configure_after_registry_created_no_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B8: первый плагин создал реестр (сохранил устройство), shutdown; второй configure -> предупреждений нет."""
    _repo, new_reg, legacy = _setup_roots(monkeypatch, tmp_path)
    _make_legacy_file(legacy)

    plugin1, ctx1 = _configure("data/devices.yaml")
    result = plugin1.cmd_device_upsert(
        {
            "id": "dev_b8",
            "name": "B8",
            "kind": "robot",
            "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
        }
    )
    assert result.get("status") == "ok", result
    plugin1.shutdown(ctx1)
    assert new_reg.exists(), "предусловие B8: первый плагин должен был создать реестр"

    _plugin2, ctx2 = _configure("data/devices.yaml")

    assert _warnings(ctx2) == []


# ------------------------------------------------------------------ #
# B9: сбой проверки прежнего места не роняет configure
# ------------------------------------------------------------------ #


def _block_legacy_place(monkeypatch: pytest.MonkeyPatch, legacy_dir: Path) -> list[str]:
    """OSError на любое обращение к ``legacy_dir`` и всему под ним; остальные пути — как обычно.

    Патчатся пути чтения ФС (os.* и Path.*) избирательно по аргументу. Возвращает список сработавших обращений.
    """
    prefix = str(legacy_dir)
    hits: list[str] = []

    def is_legacy(p: Any) -> bool:
        try:
            s = os.fsdecode(os.fspath(p))
        except TypeError:
            return False  # дескриптор (int) и прочее — не путь прежнего места
        s = os.path.abspath(s)
        return s == prefix or s.startswith(prefix + os.sep)

    def wrap_os(name: str) -> None:
        real = getattr(os, name)

        def inner(p: Any = ".", *a: Any, **k: Any) -> Any:
            if is_legacy(p):
                hits.append(f"os.{name}")
                raise OSError(5, f"simulated I/O error on {name}")
            return real(p, *a, **k)

        monkeypatch.setattr(os, name, inner)

    def wrap_path(name: str) -> None:
        real: Callable[..., Any] = getattr(Path, name)

        def inner(self: Path, *a: Any, **k: Any) -> Any:
            if is_legacy(self):
                hits.append(f"Path.{name}")
                raise OSError(5, f"simulated I/O error on {name}")
            return real(self, *a, **k)

        monkeypatch.setattr(Path, name, inner)

    for n in ("stat", "lstat", "scandir", "listdir", "access"):
        wrap_os(n)
    for n in ("stat", "lstat", "exists", "is_file", "is_dir", "iterdir", "glob", "rglob", "open", "read_text"):
        wrap_path(n)
    return hits


def test_b9_legacy_check_oserror_does_not_break_configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B9: OSError при проверке прежнего места (только его) не роняет configure — плагин доходит до READY."""
    _repo, new_reg, legacy = _setup_roots(monkeypatch, tmp_path)
    _make_legacy_file(legacy)
    (tmp_path / "data" / "robot").mkdir()
    _block_legacy_place(monkeypatch, tmp_path / "data")

    plugin, ctx = _configure("data/devices.yaml")  # не должен бросить

    assert plugin._manager.is_initialized
    assert new_reg.parent.is_dir()
