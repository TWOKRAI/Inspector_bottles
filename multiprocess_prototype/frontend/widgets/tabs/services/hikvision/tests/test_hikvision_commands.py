"""Тесты вкладки services/hikvision на команды плагина `hikvision` на ядре `camera_device` (Task 4.4).

Мост команд и отправитель — спаи: тест проверяет, ЧТО ушло в плагин (литералы из ACCEPTANCE), а не как
presenter это строит. Ответ неизвестной команды ядра: `{"status": "error", "reason": "No handler for key '<имя>'"}`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from PySide6.QtWidgets import QLabel

from multiprocess_prototype.frontend.widgets.tabs.services.hikvision.controller import (
    HikvisionWidgetController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.hikvision.presenter import (
    HikvisionSettingsPresenter,
)
from multiprocess_prototype.frontend.widgets.tabs.services.hikvision.widget import (
    HikvisionSettingsWidget,
)


class SpyBridge:
    """TopologyBridge-спай: пишет `on_action_command(plugin, command, args)`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def on_action_command(self, plugin_name: str, command_name: str, args: dict | None = None) -> bool:
        self.calls.append((plugin_name, command_name, args))
        return True


class SpySender:
    """CommandSender-спай: `send_command` (fire-and-forget) и `request_command` (round-trip с заданным ответом)."""

    def __init__(self, reply: dict | None = None) -> None:
        self.sent: list[tuple[str, str, dict]] = []
        self.requests: list[tuple[str, str, dict]] = []
        self.reply = reply if reply is not None else {}

    def send_command(self, target_process: str, command: str, args: dict | None = None) -> None:
        self.sent.append((target_process, command, args))

    def request_command(self, target_process: str, command: str, args: dict | None = None) -> dict:
        self.requests.append((target_process, command, args))
        return self.reply


class SyncRunner:
    """RequestRunner без потока: результат сразу в колбэк."""

    def submit(self, fn: Any, on_result: Any) -> None:
        on_result(fn())


class FakeTopology:
    """Топология с одним процессом `camera`, где живёт плагин `hikvision`."""

    def load(self) -> Any:
        data = {"processes": [{"process_name": "camera", "plugins": [{"plugin_name": "hikvision"}]}]}
        return SimpleNamespace(to_dict=lambda: data)


def _build(qapp: Any, reply: dict | None = None):
    bridge = SpyBridge()
    sender = SpySender(reply)
    presenter = HikvisionSettingsPresenter(
        bridge=bridge, topology=FakeTopology(), command_sender=sender, request_runner=SyncRunner()
    )
    widget = HikvisionSettingsWidget()
    controller = HikvisionWidgetController(widget, presenter)
    return widget, controller, bridge, sender


def _status_text(widget: HikvisionSettingsWidget) -> str:
    return widget.findChild(QLabel, "hikvision_status").text()


def test_open_and_close_buttons_send_core_commands(qapp) -> None:
    """«Открыть» -> take_device без аргументов, «Закрыть» -> release_device."""
    widget, _controller, bridge, _sender = _build(qapp)
    widget._btn_open.click()
    widget._btn_close.click()
    assert bridge.calls == [("hikvision", "take_device", {}), ("hikvision", "release_device", {})]


def _register_updates(sender: SpySender) -> list[tuple[str, str, dict]]:
    return [call for call in sender.sent if call[1] == "register_update"]


def test_apply_sends_register_update_per_field(qapp) -> None:
    """«Применить» с fps=30, экспозицией 900 -> три register_update в процесс камеры."""
    widget, _controller, bridge, sender = _build(qapp)
    widget._edit_fps.setText("30")
    widget._edit_exposure.setText("900")
    widget._btn_apply.click()
    assert (
        "camera",
        "register_update",
        {"register": "hikvision", "field": "exposure_time", "value": 900.0},
    ) in sender.sent
    assert [args["field"] for _proc, _cmd, args in _register_updates(sender)] == [
        "frame_rate",
        "exposure_time",
        "gain",
    ]
    assert bridge.calls == []


def test_apply_with_empty_fps_skips_frame_rate_and_says_so(qapp) -> None:
    """fps=0 (пустое поле) не отправляется: min register'а 1.0. Остальные уходят, статус называет пропуск."""
    widget, _controller, _bridge, sender = _build(qapp)
    widget._edit_fps.setText("0")
    widget._edit_exposure.setText("900")
    widget._edit_gain.setText("0")
    widget._btn_apply.click()
    assert [args for _proc, _cmd, args in _register_updates(sender)] == [
        {"register": "hikvision", "field": "exposure_time", "value": 900.0},
        {"register": "hikvision", "field": "gain", "value": 0.0},
    ]
    assert "fps пуст: не отправлен" in _status_text(widget)


def test_find_devices_asks_plugin_list_devices(qapp) -> None:
    """Перечисление приборов -> list_devices у плагина hikvision; приборы `{kind, value, name}` попадают в список."""
    reply = {"success": True, "devices": [{"kind": "serial", "value": "SN1", "name": "DS-MV 1"}]}
    widget, _controller, _bridge, sender = _build(qapp, reply)
    widget._btn_enum.click()
    assert sender.requests == [("camera", "list_devices", {})]
    assert widget._combo_devices.count() == 1
    assert "DS-MV 1" in widget._combo_devices.itemText(0)


def test_read_params_shows_node_error(qapp) -> None:
    """Ответ read_params с params и param_errors: значения в полях, текст ошибки узла виден."""
    reply = {
        "success": True,
        "params": {"exposure_time": 900.0, "gain": 1.5, "frame_rate": 25.0},
        "param_errors": {"gain": "узел Gain: значение вне диапазона"},
    }
    widget, _controller, _bridge, sender = _build(qapp, reply)
    widget._btn_get.click()
    assert sender.requests == [("camera", "read_params", {})]
    assert widget._edit_exposure.text() == "900.00"
    assert "узел Gain: значение вне диапазона" in _status_text(widget)


def test_unknown_command_reply_is_shown(qapp) -> None:
    """Ядро отвечает на неизвестную команду `{"status": "error", "reason": ...}` — причина видна, не «успех»."""
    reply = {"status": "error", "reason": "No handler for key 'list_devices'"}
    widget, _controller, _bridge, _sender = _build(qapp, reply)
    widget._btn_enum.click()
    assert "No handler for key 'list_devices'" in _status_text(widget)
    assert widget._combo_devices.count() == 0


def test_every_sent_command_is_a_plugin_command(qapp) -> None:
    """Страховка: каждое имя команды, которое шлёт presenter, есть в `HikvisionCameraPlugin.commands`."""
    from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin

    widget, _controller, bridge, sender = _build(qapp, {"success": True, "devices": [], "params": {}})
    for button in (widget._btn_enum, widget._btn_open, widget._btn_close, widget._btn_get):
        button.click()
    names = {cmd for _plugin, cmd, _args in bridge.calls} | {cmd for _proc, cmd, _args in sender.requests}
    assert names == {"list_devices", "take_device", "release_device", "read_params"}
    assert names <= set(HikvisionCameraPlugin.commands)
