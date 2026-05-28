# -*- coding: utf-8 -*-
"""Тесты валидации wire через PluginRegistry.are_ports_compatible.
Task E.1: мигрировано на AppServices. Wire-валидация использует bridge _registry.

Сценарии:
- test_compatible_image_image_wire_ok: image/bgr → image/bgr → wire OK
- test_incompatible_image_tensor_wire_blocked: image/bgr → tensor/float32 → блокируется
- test_wildcard_image_compatible: image/bgr → image/* → wire OK
- test_display_target_accepts_image_bgr: wire к display.* с image/bgr выходом → OK
- test_display_target_rejects_tensor: wire к display.* с tensor/float32 выходом → блокируется
- test_no_registry_skips_validation: registry=None → graceful, wire OK
- test_unknown_plugin_skips_validation: registry.get() → None → warning + wire OK

Запуск:
    python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_wire_validation.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import (
    PipelinePresenter,
)

from ._helpers import make_pipeline_services


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_plugin_entry(name: str, inputs: list[Port], outputs: list[Port]) -> MagicMock:
    """Создать mock PluginEntry с заданными портами."""
    entry = MagicMock()
    entry.name = name
    entry.inputs = inputs
    entry.outputs = outputs
    return entry


def _make_registry(plugins: dict[str, MagicMock]) -> MagicMock:
    """Создать mock PluginRegistry.

    Args:
        plugins: словарь {plugin_name: mock_entry}
    """
    registry = MagicMock()
    registry.get.side_effect = lambda name: plugins.get(name)
    return registry


def _make_presenter_with_processes(registry=None) -> PipelinePresenter:
    """Создать PipelinePresenter с двумя процессами в модели."""
    services = make_pipeline_services(
        topology={"processes": [], "wires": []},
        plugin_registry=registry,
    )
    presenter = PipelinePresenter(services)

    # Добавить процессы напрямую в модель для тестов
    presenter._model.add_process("proc_a", "plugin_a", "processing")
    presenter._model.add_process("proc_b", "plugin_b", "processing")

    return presenter


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestWireValidationCompatible:
    """Тесты совместимых wire-соединений."""

    def test_compatible_image_image_wire_ok(self):
        """image/bgr → image/bgr: wire добавляется в модель."""
        port_out = Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")
        port_in = Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")

        entry_a = _make_plugin_entry("plugin_a", inputs=[], outputs=[port_out])
        entry_b = _make_plugin_entry("plugin_b", inputs=[port_in], outputs=[])
        registry = _make_registry({"plugin_a": entry_a, "plugin_b": entry_b})

        presenter = _make_presenter_with_processes(registry=registry)

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
        """image/bgr → image/*: wildcard совместим, wire добавляется."""
        port_out = Port(name="out", dtype="image/bgr", shape="")
        port_in = Port(name="in", dtype="image/*", shape="")

        entry_a = _make_plugin_entry("plugin_a", inputs=[], outputs=[port_out])
        entry_b = _make_plugin_entry("plugin_b", inputs=[port_in], outputs=[])
        registry = _make_registry({"plugin_a": entry_a, "plugin_b": entry_b})

        presenter = _make_presenter_with_processes(registry=registry)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.out", "proc_b.plugin_b.in")

        assert result is True
        mock_warn.assert_not_called()


class TestWireValidationIncompatible:
    """Тесты несовместимых wire-соединений."""

    def test_incompatible_image_tensor_wire_blocked(self):
        """image/bgr → tensor/float32: wire блокируется, QMessageBox.warning показывается."""
        port_out = Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")
        port_in = Port(name="tensor", dtype="tensor/float32", shape="(N, 4)")

        entry_a = _make_plugin_entry("plugin_a", inputs=[], outputs=[port_out])
        entry_b = _make_plugin_entry("plugin_b", inputs=[port_in], outputs=[])
        registry = _make_registry({"plugin_a": entry_a, "plugin_b": entry_b})

        presenter = _make_presenter_with_processes(registry=registry)

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
        port_out = Port(name="data", dtype="dict", shape="")
        port_in = Port(name="frame", dtype="image/bgr", shape="")

        entry_a = _make_plugin_entry("plugin_a", inputs=[], outputs=[port_out])
        entry_b = _make_plugin_entry("plugin_b", inputs=[port_in], outputs=[])
        registry = _make_registry({"plugin_a": entry_a, "plugin_b": entry_b})

        presenter = _make_presenter_with_processes(registry=registry)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            presenter.add_wire("proc_a.plugin_a.data", "proc_b.plugin_b.frame")

        call_args = mock_warn.call_args
        message_text = call_args[0][2]
        assert "dict" in message_text
        assert "image/bgr" in message_text


class TestWireValidationDisplay:
    """Тесты валидации wire к display-узлам."""

    def test_display_target_accepts_image_bgr(self):
        """Wire к display.* с image/bgr выходом → OK (wildcard image/*)."""
        port_out = Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")

        entry_a = _make_plugin_entry("plugin_a", inputs=[], outputs=[port_out])
        registry = _make_registry({"plugin_a": entry_a})

        services = make_pipeline_services(
            topology={"processes": [], "wires": []},
            plugin_registry=registry,
        )
        presenter = PipelinePresenter(services)
        presenter._model.add_process("proc_a", "plugin_a", "processing")
        presenter._model.add_display("disp1", "main_output", "Главный экран")

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "display.disp1.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_display_target_accepts_image_gray(self):
        """Wire к display.* с image/gray выходом → OK (wildcard image/*)."""
        port_out = Port(name="mask", dtype="image/gray", shape="(H, W)")

        entry_a = _make_plugin_entry("plugin_a", inputs=[], outputs=[port_out])
        registry = _make_registry({"plugin_a": entry_a})

        services = make_pipeline_services(
            topology={"processes": [], "wires": []},
            plugin_registry=registry,
        )
        presenter = PipelinePresenter(services)
        presenter._model.add_process("proc_a", "plugin_a", "processing")
        presenter._model.add_display("disp1", "mask_output", "Маска")

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.mask", "display.disp1.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_display_target_rejects_tensor(self):
        """Wire к display.* с tensor/float32 выходом → блокируется (не image-тип)."""
        port_out = Port(name="out", dtype="tensor/float32", shape="(N, 4)")

        entry_a = _make_plugin_entry("plugin_a", inputs=[], outputs=[port_out])
        registry = _make_registry({"plugin_a": entry_a})

        services = make_pipeline_services(
            topology={"processes": [], "wires": []},
            plugin_registry=registry,
        )
        presenter = PipelinePresenter(services)
        presenter._model.add_process("proc_a", "plugin_a", "processing")
        presenter._model.add_display("disp1", "main_output", "")

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.out", "display.disp1.frame")

        assert result is False
        mock_warn.assert_called_once()

    def test_display_target_rejects_dict(self):
        """Wire к display.* с dict выходом → блокируется."""
        port_out = Port(name="stats", dtype="dict", shape="")

        entry_a = _make_plugin_entry("plugin_a", inputs=[], outputs=[port_out])
        registry = _make_registry({"plugin_a": entry_a})

        services = make_pipeline_services(
            topology={"processes": [], "wires": []},
            plugin_registry=registry,
        )
        presenter = PipelinePresenter(services)
        presenter._model.add_process("proc_a", "plugin_a", "processing")
        presenter._model.add_display("disp1", "main_output", "")

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.stats", "display.disp1.frame")

        assert result is False
        mock_warn.assert_called_once()


class TestWireValidationGracefulDegradation:
    """Тесты graceful degradation — wire не блокируется при недоступном registry."""

    def test_no_registry_skips_validation(self):
        """services.plugins без _registry: валидация пропускается, wire создаётся."""
        presenter = _make_presenter_with_processes(registry=None)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "proc_b.plugin_b.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_unknown_source_plugin_skips_validation(self):
        """registry.get(src_plugin) → None: лог warning + wire добавляется (legacy compat)."""
        port_in = Port(name="frame", dtype="image/bgr", shape="")
        entry_b = _make_plugin_entry("plugin_b", inputs=[port_in], outputs=[])
        registry = _make_registry({"plugin_b": entry_b})

        presenter = _make_presenter_with_processes(registry=registry)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "proc_b.plugin_b.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_unknown_target_plugin_skips_validation(self):
        """registry.get(tgt_plugin) → None: лог warning + wire добавляется (legacy compat)."""
        port_out = Port(name="frame", dtype="image/bgr", shape="")
        entry_a = _make_plugin_entry("plugin_a", inputs=[], outputs=[port_out])
        registry = _make_registry({"plugin_a": entry_a})

        presenter = _make_presenter_with_processes(registry=registry)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "proc_b.plugin_b.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_unknown_source_port_skips_validation(self):
        """Порт 'frame' не найден в outputs плагина: пропуск, wire добавляется."""
        port_wrong = Port(name="out", dtype="image/bgr", shape="")
        entry_a = _make_plugin_entry("plugin_a", inputs=[], outputs=[port_wrong])
        port_in = Port(name="frame", dtype="image/bgr", shape="")
        entry_b = _make_plugin_entry("plugin_b", inputs=[port_in], outputs=[])
        registry = _make_registry({"plugin_a": entry_a, "plugin_b": entry_b})

        presenter = _make_presenter_with_processes(registry=registry)

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            result = presenter.add_wire("proc_a.plugin_a.frame", "proc_b.plugin_b.frame")

        assert result is True
        mock_warn.assert_not_called()

    def test_malformed_source_endpoint_skips_validation(self):
        """Некорректный source endpoint (без точек): пропуск, wire попытается добавиться."""
        port_in = Port(name="frame", dtype="image/bgr", shape="")
        entry_b = _make_plugin_entry("plugin_b", inputs=[port_in], outputs=[])
        registry = _make_registry({"plugin_b": entry_b})

        presenter = _make_presenter_with_processes(registry=registry)

        with patch("PySide6.QtWidgets.QMessageBox.warning"):
            presenter.add_wire("invalid", "proc_b.plugin_b.frame")
