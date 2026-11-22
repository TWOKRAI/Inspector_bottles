"""Приёмка R2d2-A: ``params`` записи рецепта доходят до драйвера (сквозной путь, без фейков драйвера).

Путь под проверкой: ``config["recipe_devices"]`` -> настоящий ``DeviceHubPlugin.start()`` -> ``DeviceManager.upsert``
-> ``DeviceEntry.params`` -> настоящий драйвер (``robot`` / ``delta_v2`` и ``vfd`` / ``gd20_bridge``). Подменён только
``ctx`` (``make_ctx`` из ``conftest``: фейковый менеджер воркеров, ``MagicMock`` вместо ``state_proxy``) — драйверы,
менеджер, реестр и протоколы настоящие. Порт робота — свободный, ничего не слушает: connect падает настоящим отказом.

Ожидаемые значения — литералы из рецепта и умолчания драйвера (3); из кода под тестом они не вычисляются.
Причина, по которой тест краснеет при потере ключа: ``max_reconnect_attempts`` у драйвера не равен значению из
``params`` рецепта (литерал 0 против умолчания 3), а не отсутствие атрибута у фейка.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Services.device_hub.errors import DeviceHubError
from Services.robot_comm.tests.e2e_rig_v2 import bounded, free_port

from .conftest import make_ctx

_DEADLINE_S = 20.0
_TICKS = 5


# ------------------------------------------------------------------ #
# Сборка
# ------------------------------------------------------------------ #


def _recipe_devices(port: int, params: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Записи ``devices:`` рецепта: робот v2 по tcp и ПЧ на его мосту; ``params=None`` — без ключа ``params``."""
    robot: dict[str, Any] = {
        "id": "robot_main",
        "name": "Робот",
        "kind": "robot",
        "protocol": "delta_v2",
        "transport": {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": 2},
    }
    vfd: dict[str, Any] = {
        "id": "vfd_belt",
        "name": "ПЧ ленты",
        "kind": "vfd",
        "protocol": "gd20_bridge",
        "transport": {"type": "bridge", "bridge": "robot_main"},
    }
    if params is not None:
        robot["params"] = dict(params)
        vfd["params"] = dict(params)
    return [robot, vfd]


def _started_plugin(tmp_path: Path, params: dict[str, Any] | None) -> DeviceHubPlugin:
    """Настоящий ``configure`` + ``start`` с ``recipe_devices``; ``shutdown`` — в автофикстуре ``conftest``."""
    registry_file = tmp_path / "devices.yaml"
    config: dict[str, Any] = {
        "registry_path": str(registry_file),
        "recipe_devices": _recipe_devices(free_port(), params),
    }
    ctx = make_ctx(config, tmp_registry=registry_file)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin


def _robot_driver(plugin: DeviceHubPlugin) -> Any:
    """Драйвер робота: его создаёт настоящий ``connect`` на закрытом порту (``False``, драйвер остаётся в менеджере)."""
    manager = plugin._manager
    connected = bounded(lambda: manager.connect("robot_main"), _DEADLINE_S)
    assert connected is False, "порт никто не слушает: connect обязан вернуть False"
    driver = manager.get_driver("robot_main")
    assert driver is not None
    return driver


def _vfd_driver(plugin: DeviceHubPlugin) -> Any:
    """Драйвер ПЧ: ``connect`` создаёт его до проверки носителя; носитель не подключён -> ``DeviceHubError``."""
    manager = plugin._manager
    with pytest.raises(DeviceHubError):
        bounded(lambda: manager.connect("vfd_belt"), _DEADLINE_S)
    driver = manager.get_driver("vfd_belt")
    assert driver is not None
    return driver


# ------------------------------------------------------------------ #
# params -> драйвер
# ------------------------------------------------------------------ #


@pytest.fixture
def plugin_limit_zero(tmp_path: Path) -> DeviceHubPlugin:
    """Рецепт с ``params: {max_reconnect_attempts: 0}`` у обоих устройств."""
    return _started_plugin(tmp_path, {"max_reconnect_attempts": 0})


@pytest.fixture
def plugin_default(tmp_path: Path) -> DeviceHubPlugin:
    """Контроль: те же записи без ключа ``params``."""
    return _started_plugin(tmp_path, None)


@pytest.mark.timeout(60)
def test_robot_driver_gets_limit_zero_from_recipe_params(plugin_limit_zero: DeviceHubPlugin) -> None:
    """``params.max_reconnect_attempts: 0`` записи робота доходит до драйвера робота."""
    assert _robot_driver(plugin_limit_zero).max_reconnect_attempts == 0


@pytest.mark.timeout(60)
def test_vfd_driver_gets_limit_zero_from_recipe_params(plugin_limit_zero: DeviceHubPlugin) -> None:
    """``params.max_reconnect_attempts: 0`` записи ПЧ доходит до драйвера ПЧ."""
    assert _vfd_driver(plugin_limit_zero).max_reconnect_attempts == 0


@pytest.mark.timeout(60)
def test_robot_driver_without_params_keeps_default_three(plugin_default: DeviceHubPlugin) -> None:
    """Контроль: без ключа ``params`` у драйвера робота умолчание 3."""
    assert _robot_driver(plugin_default).max_reconnect_attempts == 3


@pytest.mark.timeout(60)
def test_vfd_driver_without_params_keeps_default_three(plugin_default: DeviceHubPlugin) -> None:
    """Контроль: без ключа ``params`` у драйвера ПЧ умолчание 3."""
    assert _vfd_driver(plugin_default).max_reconnect_attempts == 3


# ------------------------------------------------------------------ #
# Поведение лимита на закрытом порту робота
# ------------------------------------------------------------------ #


def _tick_after_failed_connect(plugin: DeviceHubPlugin, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Неудачный connect, желание подключения как у supervisor, ``_TICKS`` тиков драйвера под дедлайном.

    Затвор переподключения (``RECONNECT_THROTTLE_S``, 2,0 с, SPI.g / ADR-DH-012 п.7) снят на классе драйвера: иначе
    5 подряд идущих тиков делают одну попытку, и «не сдался» было бы верно по любому лимиту. Попытки при этом
    настоящие: каждая — отказ в соединении с закрытым портом.
    """
    driver = _robot_driver(plugin)
    monkeypatch.setattr(type(driver), "RECONNECT_THROTTLE_S", 0.0)
    driver.desired_connected = True  # то же, что supervisor ставит после connect (plugin._conn_loop)

    def ticks() -> None:
        for _ in range(_TICKS):
            driver.tick()

    bounded(ticks, _DEADLINE_S)
    return driver


@pytest.mark.timeout(60)
def test_limit_zero_never_gives_up_on_closed_port(
    plugin_limit_zero: DeviceHubPlugin, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Лимит 0 из рецепта: после 5 тиков на закрытом порту драйвер не «сдался» (``reconnect_exhausted`` False)."""
    driver = _tick_after_failed_connect(plugin_limit_zero, monkeypatch)
    assert driver.reconnect_exhausted is False


@pytest.mark.timeout(60)
def test_limit_zero_keeps_desired_connected_on_closed_port(
    plugin_limit_zero: DeviceHubPlugin, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Лимит 0 из рецепта: после 5 тиков желание подключения остаётся True."""
    driver = _tick_after_failed_connect(plugin_limit_zero, monkeypatch)
    assert driver.desired_connected is True


@pytest.mark.timeout(60)
def test_default_limit_gives_up_on_closed_port(
    plugin_default: DeviceHubPlugin, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Контроль (умолчание 3): после 5 тиков на закрытом порту ``reconnect_exhausted`` True."""
    driver = _tick_after_failed_connect(plugin_default, monkeypatch)
    assert driver.reconnect_exhausted is True


@pytest.mark.timeout(60)
def test_default_limit_drops_desired_connected_on_closed_port(
    plugin_default: DeviceHubPlugin, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Контроль (умолчание 3): после «сдался» желание подключения сброшено в False."""
    driver = _tick_after_failed_connect(plugin_default, monkeypatch)
    assert driver.desired_connected is False
