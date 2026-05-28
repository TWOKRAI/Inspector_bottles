# -*- coding: utf-8 -*-
"""Тесты валидации wire через PluginCatalog Protocol + are_ports_compatible.

Task F.5: wire-валидация переведена с raw _registry bridge на PluginCatalog
Protocol (resolve -> PluginSpec.ports -> PortSpec -> Port -> are_ports_compatible).

Сценарии:
- test_compatible_image_image_wire_ok: image/bgr -> image/bgr -> wire OK
- test_incompatible_image_tensor_wire_blocked: image/bgr -> tensor/float32 -> блокируется
- test_wildcard_image_compatible: image/bgr -> image/* -> wire OK
- test_display_target_accepts_image_bgr: wire к display.* с image/bgr выходом -> OK
- test_display_target_rejects_tensor: wire к display.* с tensor/float32 выходом -> блокируется
- test_no_plugins_skips_validation: пустой каталог -> graceful, wire OK
- test_unknown_plugin_skips_validation: catalog.resolve() -> None -> warning + wire OK

Запуск:
    python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_wire_validation.py -v
"""

from __future__ import annotations

from unittest.mock import patch

from multiprocess_prototype.domain.protocols.plugin_catalog import (
    PluginSpec,
    PortSpec,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import (
    PipelinePresenter,
)

from ._helpers import make_pipeline_services, make_pipeline_services_with_orchestrator


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_plugin_spec(
    name: str,
    inputs: list[PortSpec] | None = None,
    outputs: list[PortSpec] | None = None,
) -> PluginSpec:
    """Создать PluginSpec с заданными портами."""
    ports = tuple(inputs or []) + tuple(outputs or [])
    return PluginSpec(
        name=name,
        category="processing",
        ports=ports,
    )


def _make_presenter_with_processes(
    plugin_specs: dict[str, PluginSpec] | None = None,
) -> PipelinePresenter:
    """Создать PipelinePresenter с двумя процессами в topology.

    G.4.2: используем реальный orchestrator, процессы создаются в topology
    (а не через модель напрямую) — domain dispatch требует, чтобы процессы
    были видны в topology_repo для ConnectWire-валидации.
    """
    services = make_pipeline_services_with_orchestrator(
        topology={
            "processes": [
                {"process_name": "proc_a", "plugins": [{"plugin_name": "plugin_a"}]},
                {"process_name": "proc_b", "plugins": [{"plugin_name": "plugin_b"}]},
            ],
            "wires": [],
        },
        plugin_specs=plugin_specs,
    )
    presenter = PipelinePresenter(services)
    presenter.load_topology_from_config()

    return presenter


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestWireValidationCompatible:
    """Тесты совместимых wire-соединений."""

    def test_compatible_image_image_wire_ok(self):
        """image/bgr -> image/bgr: wire добавляется в модель."""
        port_out = PortSpec(name="frame", dtype="image/bgr", direction="output", shape="(H, W, 3)")
        port_in = PortSpec(name="frame", dtype="image/bgr", direction="input", shape="(H, W, 3)")

        specs = {
            "plugin_a": _make_plugin_spec("plugin_a", outputs=[port_out]),
            "plugin_b": _make_plugin_spec("plugin_b", inputs=[port_in]),
        }

        presenter = _make_presenter_with_processes(plugin_specs=specs)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "proc_b.plugin_b.frame")

        assert result is True
        mock_warn.assert_not_called()

        # Wire должен быть в модели
        topo = presenter.model.to_topology_dict()
        wires = topo.get("wires", [])
        assert len(wires) == 1
        assert wires[0]["source"] == "proc_a.plugin_a.frame"
        assert wires[0]["target"] == "proc_b.plugin_b.frame"

    def test_wildcard_image_compatible(self):
        """image/bgr -> image/*: wildcard совместим, wire добавляется."""
        port_out = PortSpec(name="out", dtype="image/bgr", direction="output")
        port_in = PortSpec(name="in", dtype="image/*", direction="input")

        specs = {
            "plugin_a": _make_plugin_spec("plugin_a", outputs=[port_out]),
            "plugin_b": _make_plugin_spec("plugin_b", inputs=[port_in]),
        }

        presenter = _make_presenter_with_processes(plugin_specs=specs)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.out", "proc_b.plugin_b.in")

        assert result is True
        mock_warn.assert_not_called()


class TestWireValidationIncompatible:
    """Тесты несовместимых wire-соединений."""

    def test_incompatible_image_tensor_wire_blocked(self):
        """image/bgr -> tensor/float32: wire блокируется, QMessageBox.warning показывается."""
        port_out = PortSpec(name="frame", dtype="image/bgr", direction="output", shape="(H, W, 3)")
        port_in = PortSpec(name="tensor", dtype="tensor/float32", direction="input", shape="(N, 4)")

        specs = {
            "plugin_a": _make_plugin_spec("plugin_a", outputs=[port_out]),
            "plugin_b": _make_plugin_spec("plugin_b", inputs=[port_in]),
        }

        presenter = _make_presenter_with_processes(plugin_specs=specs)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "proc_b.plugin_b.tensor")

        assert result is False
        mock_warn.assert_called_once()

        # Wire НЕ должен быть в модели
        topo = presenter.model.to_topology_dict()
        wires = topo.get("wires", [])
        assert len(wires) == 0

    def test_incompatible_wire_message_contains_dtypes(self):
        """Сообщение об ошибке содержит типы несовместимых портов."""
        port_out = PortSpec(name="data", dtype="dict", direction="output")
        port_in = PortSpec(name="frame", dtype="image/bgr", direction="input")

        specs = {
            "plugin_a": _make_plugin_spec("plugin_a", outputs=[port_out]),
            "plugin_b": _make_plugin_spec("plugin_b", inputs=[port_in]),
        }

        presenter = _make_presenter_with_processes(plugin_specs=specs)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            presenter.add_wire("proc_a.plugin_a.data", "proc_b.plugin_b.frame")

        call_args = mock_warn.call_args
        message_text = call_args[0][2]
        assert "dict" in message_text
        assert "image/bgr" in message_text


class TestWireValidationDisplay:
    """Тесты валидации wire к display-узлам."""

    def test_display_target_accepts_image_bgr(self):
        """Wire к display.* с image/bgr выходом -> OK (wildcard image/*)."""
        port_out = PortSpec(name="frame", dtype="image/bgr", direction="output", shape="(H, W, 3)")

        specs = {
            "plugin_a": _make_plugin_spec("plugin_a", outputs=[port_out]),
        }

        services = make_pipeline_services(
            topology={"processes": [], "wires": []},
            plugin_specs=specs,
        )
        presenter = PipelinePresenter(services)
        presenter._model.add_process("proc_a", "plugin_a", "processing")
        presenter._model.add_display("disp1", "main_output", "Главный экран")

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "display.disp1.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_display_target_accepts_image_gray(self):
        """Wire к display.* с image/gray выходом -> OK (wildcard image/*)."""
        port_out = PortSpec(name="mask", dtype="image/gray", direction="output", shape="(H, W)")

        specs = {
            "plugin_a": _make_plugin_spec("plugin_a", outputs=[port_out]),
        }

        services = make_pipeline_services(
            topology={"processes": [], "wires": []},
            plugin_specs=specs,
        )
        presenter = PipelinePresenter(services)
        presenter._model.add_process("proc_a", "plugin_a", "processing")
        presenter._model.add_display("disp1", "mask_output", "Маска")

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.mask", "display.disp1.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_display_target_rejects_tensor(self):
        """Wire к display.* с tensor/float32 выходом -> блокируется (не image-тип)."""
        port_out = PortSpec(name="out", dtype="tensor/float32", direction="output", shape="(N, 4)")

        specs = {
            "plugin_a": _make_plugin_spec("plugin_a", outputs=[port_out]),
        }

        services = make_pipeline_services(
            topology={"processes": [], "wires": []},
            plugin_specs=specs,
        )
        presenter = PipelinePresenter(services)
        presenter._model.add_process("proc_a", "plugin_a", "processing")
        presenter._model.add_display("disp1", "main_output", "")

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.out", "display.disp1.frame")

        assert result is False
        mock_warn.assert_called_once()

    def test_display_target_rejects_dict(self):
        """Wire к display.* с dict выходом -> блокируется."""
        port_out = PortSpec(name="stats", dtype="dict", direction="output")

        specs = {
            "plugin_a": _make_plugin_spec("plugin_a", outputs=[port_out]),
        }

        services = make_pipeline_services(
            topology={"processes": [], "wires": []},
            plugin_specs=specs,
        )
        presenter = PipelinePresenter(services)
        presenter._model.add_process("proc_a", "plugin_a", "processing")
        presenter._model.add_display("disp1", "main_output", "")

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.stats", "display.disp1.frame")

        assert result is False
        mock_warn.assert_called_once()


class TestWireValidationGracefulDegradation:
    """Тесты graceful degradation -- wire не блокируется при пустом каталоге."""

    def test_no_plugins_skips_validation(self):
        """Пустой FakePluginCatalog: валидация пропускается, wire создаётся."""
        presenter = _make_presenter_with_processes(plugin_specs=None)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "proc_b.plugin_b.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_unknown_source_plugin_skips_validation(self):
        """catalog.resolve(src_plugin) -> None: лог warning + wire добавляется (legacy compat)."""
        port_in = PortSpec(name="frame", dtype="image/bgr", direction="input")

        specs = {
            "plugin_b": _make_plugin_spec("plugin_b", inputs=[port_in]),
        }

        presenter = _make_presenter_with_processes(plugin_specs=specs)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "proc_b.plugin_b.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_unknown_target_plugin_skips_validation(self):
        """catalog.resolve(tgt_plugin) -> None: лог warning + wire добавляется (legacy compat)."""
        port_out = PortSpec(name="frame", dtype="image/bgr", direction="output")

        specs = {
            "plugin_a": _make_plugin_spec("plugin_a", outputs=[port_out]),
        }

        presenter = _make_presenter_with_processes(plugin_specs=specs)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "proc_b.plugin_b.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_unknown_source_port_skips_validation(self):
        """Порт 'frame' не найден в outputs плагина: пропуск, wire добавляется."""
        # plugin_a имеет output 'out' (не 'frame')
        port_wrong = PortSpec(name="out", dtype="image/bgr", direction="output")
        port_in = PortSpec(name="frame", dtype="image/bgr", direction="input")

        specs = {
            "plugin_a": _make_plugin_spec("plugin_a", outputs=[port_wrong]),
            "plugin_b": _make_plugin_spec("plugin_b", inputs=[port_in]),
        }

        presenter = _make_presenter_with_processes(plugin_specs=specs)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "proc_b.plugin_b.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_malformed_source_endpoint_skips_validation(self):
        """Некорректный source endpoint (без точек): пропуск, wire попытается добавиться."""
        port_in = PortSpec(name="frame", dtype="image/bgr", direction="input")

        specs = {
            "plugin_b": _make_plugin_spec("plugin_b", inputs=[port_in]),
        }

        presenter = _make_presenter_with_processes(plugin_specs=specs)

        with patch("PySide6.QtWidgets.QMessageBox.warning"):
            presenter.add_wire("invalid", "proc_b.plugin_b.frame")
