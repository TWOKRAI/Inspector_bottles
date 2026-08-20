# -*- coding: utf-8 -*-
"""Тесты секции управления телеметрией (telemetry-publish-control Ф4.1).

Конструкторный инвариант: контролы строятся ПО ШАБЛОНУ из списка метрик, не хардкодом.
Плюс: on_change отдаёт ровно изменённую ось; `capped_by_throttle` (Task 1.4) виден в UI;
read-model питает читаемый статус; presenter строит корректный merge/target-конверт.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_framework.modules.process_module.heartbeat.telemetry import gated_metrics
from multiprocess_framework.modules.frontend_module.state import TelemetryViewModel
from multiprocess_prototype.frontend.widgets.tabs.processes._panels import SingleProcessPanel
from multiprocess_prototype.frontend.widgets.tabs.processes._telemetry_controls import (
    TelemetryControlsSection,
)
from multiprocess_prototype.frontend.widgets.tabs.processes.presenter import ProcessesPresenter

from ._helpers import make_processes_services


def _presenter(command_sender=None) -> ProcessesPresenter:
    return ProcessesPresenter(make_processes_services(), command_sender=command_sender)


def _delta(path: str, value: object) -> dict:
    return {"data_type": "state_delta", "path": path, "value": value, "deleted": False}


# ------------------------------------------------------------------ #
#  1. Шаблонная генерация строк по списку метрик (главный инвариант)  #
# ------------------------------------------------------------------ #


class TestTemplateGeneration:
    def test_builds_one_row_per_metric(self, qtbot) -> None:
        section = TelemetryControlsSection("cam", ["fps", "latency_ms", "shm"])
        qtbot.addWidget(section)
        assert set(section._rows) == {"fps", "latency_ms", "shm"}

    def test_arbitrary_metric_list_drives_rows(self, qtbot) -> None:
        """Список метрик — единственный источник строк: новый ключ → новая строка."""
        section = TelemetryControlsSection("cam", ["a", "b", "c", "d"])
        qtbot.addWidget(section)
        assert len(section._rows) == 4
        assert set(section._rows) == {"a", "b", "c", "d"}

    def test_gated_metrics_all_present(self, qtbot) -> None:
        section = TelemetryControlsSection("cam", list(gated_metrics()))
        qtbot.addWidget(section)
        assert set(section._rows) == set(gated_metrics())

    def test_label_falls_back_to_key(self, qtbot) -> None:
        section = TelemetryControlsSection("cam", ["fps"], labels={"fps": "Кадры/с"})
        qtbot.addWidget(section)
        # Метка задана → её текст; неизвестная метрика взяла бы сам ключ.
        section2 = TelemetryControlsSection("cam", ["unknown_metric"])
        qtbot.addWidget(section2)
        assert section2._rows["unknown_metric"].metric == "unknown_metric"

    def test_default_interval_applied(self, qtbot) -> None:
        section = TelemetryControlsSection("cam", ["fps", "shm"], defaults={"fps": 0.5, "shm": 3.0})
        qtbot.addWidget(section)
        assert section._rows["fps"].interval.value() == 0.5
        assert section._rows["shm"].interval.value() == 3.0


# ------------------------------------------------------------------ #
#  2. on_change: отдаёт ровно изменённую ось                          #
# ------------------------------------------------------------------ #


class TestOnChange:
    def test_toggle_emits_enabled_only(self, qtbot) -> None:
        calls: list = []
        section = TelemetryControlsSection("cam", ["fps"], on_change=lambda m, e, i: calls.append((m, e, i)))
        qtbot.addWidget(section)
        section._rows["fps"].enable.setChecked(False)  # был True → toggled
        assert calls == [("fps", False, None)]

    def test_interval_emits_interval_only(self, qtbot) -> None:
        calls: list = []
        section = TelemetryControlsSection("cam", ["fps"], on_change=lambda m, e, i: calls.append((m, e, i)))
        qtbot.addWidget(section)
        row = section._rows["fps"]
        row.interval.setValue(0.2)
        row.interval.editingFinished.emit()  # коммит по завершению ввода
        assert calls == [("fps", None, 0.2)]

    def test_disable_greys_interval(self, qtbot) -> None:
        section = TelemetryControlsSection("cam", ["fps"], on_change=lambda *a: None)
        qtbot.addWidget(section)
        section._rows["fps"].enable.setChecked(False)
        assert section._rows["fps"].interval.isEnabled() is False

    def test_update_readouts_does_not_emit(self, qtbot) -> None:
        """Программное обновление статуса НЕ порождает команду записи (suppress-гвард)."""
        calls: list = []
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.cam.state.fps", 21.0))
        section = TelemetryControlsSection("cam", ["fps"], on_change=lambda *a: calls.append(a))
        qtbot.addWidget(section)
        section.update_readouts(vm)
        assert calls == []


# ------------------------------------------------------------------ #
#  3. Read-model питает читаемый статус                               #
# ------------------------------------------------------------------ #


class TestReadModel:
    def test_readout_reflects_state_value(self, qtbot) -> None:
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.cam.state.fps", 21.0))
        section = TelemetryControlsSection("cam", ["fps", "latency_ms"])
        qtbot.addWidget(section)
        section.update_readouts(vm)
        assert section._rows["fps"].readout.text() == "21.0"
        assert section._rows["latency_ms"].readout.text() == "—"  # нет значения

    def test_none_vm_is_noop(self, qtbot) -> None:
        section = TelemetryControlsSection("cam", ["fps"])
        qtbot.addWidget(section)
        section.update_readouts(None)  # не падает
        assert section._rows["fps"].readout.text() == "—"


# ------------------------------------------------------------------ #
#  4. capped_by_throttle (Task 1.4) виден пользователю                #
# ------------------------------------------------------------------ #


class TestCapsSurfaced:
    def test_caps_result_shows_warning(self, qtbot) -> None:
        section = TelemetryControlsSection("cam", ["fps"])
        qtbot.addWidget(section)
        result = {
            "publish": {"capped_by_throttle": {"fps": {"publisher_interval_sec": 0.1, "throttle_interval_sec": 2.0}}}
        }
        section.show_result("fps", result)
        row = section._rows["fps"]
        assert "2.0" in row.readout.text()
        assert "троттл" in row.readout.text()
        assert row.readout.property("capped") is True

    def test_caps_result_nested_in_result_envelope(self, qtbot) -> None:
        """Ответ, завёрнутый в result (как _leaf_result) — caps всё равно найден."""
        section = TelemetryControlsSection("cam", ["fps"])
        qtbot.addWidget(section)
        result = {
            "success": True,
            "result": {"publish": {"capped_by_throttle": {"fps": {"throttle_interval_sec": 5.0}}}},
        }
        section.show_result("fps", result)
        assert "5.0" in section._rows["fps"].readout.text()

    def test_success_without_caps_clears_warning(self, qtbot) -> None:
        section = TelemetryControlsSection("cam", ["fps"])
        qtbot.addWidget(section)
        section.show_result("fps", {"publish": {"capped_by_throttle": {"fps": {"throttle_interval_sec": 2.0}}}})
        section.show_result("fps", {"publish": {"reached": 1}})  # успех без caps
        assert section._rows["fps"].readout.property("capped") is False

    def test_readout_not_overwritten_by_vm_while_capped(self, qtbot) -> None:
        """Пока висит caps-предупреждение, живое значение из read-model его не затирает."""
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.cam.state.fps", 21.0))
        section = TelemetryControlsSection("cam", ["fps"])
        qtbot.addWidget(section)
        section.show_result("fps", {"publish": {"capped_by_throttle": {"fps": {"throttle_interval_sec": 2.0}}}})
        section.update_readouts(vm)
        assert "троттл" in section._rows["fps"].readout.text()


# ------------------------------------------------------------------ #
#  5. Presenter: конверт + отправка через bridge                     #
# ------------------------------------------------------------------ #


class TestPresenterCommand:
    def test_command_enabled_and_interval(self) -> None:
        cmd = ProcessesPresenter.telemetry_command("cam", "fps", enabled=False, interval_sec=0.5)
        assert cmd == {
            "cmd": "telemetry.broadcast",
            "publish": {"metrics": {"fps": {"enabled": False, "interval_sec": 0.5}}},
            "telemetry_mode": "merge",
            "target": "cam",
        }

    def test_command_interval_only_omits_enabled(self) -> None:
        cmd = ProcessesPresenter.telemetry_command("cam", "fps", interval_sec=0.5)
        assert cmd["publish"]["metrics"]["fps"] == {"interval_sec": 0.5}

    def test_command_enabled_only_omits_interval(self) -> None:
        cmd = ProcessesPresenter.telemetry_command("cam", "fps", enabled=True)
        assert cmd["publish"]["metrics"]["fps"] == {"enabled": True}

    def test_apply_sends_via_request_bridge(self) -> None:
        sender = MagicMock()
        sender.request_system_command.return_value = {"success": True, "publish": {"reached": 1}}
        presenter = _presenter(command_sender=sender)
        res = presenter.apply_telemetry_metric("cam", "fps", interval_sec=0.5)
        assert res == {"success": True, "publish": {"reached": 1}}
        sent = sender.request_system_command.call_args[0][0]
        assert sent["cmd"] == "telemetry.broadcast"
        assert sent["target"] == "cam"
        assert sent["telemetry_mode"] == "merge"

    def test_apply_without_command_sender_is_error(self) -> None:
        presenter = _presenter(command_sender=None)
        res = presenter.apply_telemetry_metric("cam", "fps", enabled=True)
        assert res["success"] is False


# ------------------------------------------------------------------ #
#  6. Интеграция панели: секция собрана и подключена                  #
# ------------------------------------------------------------------ #


class TestPanelIntegration:
    def test_single_panel_builds_telemetry_section(self, qtbot) -> None:
        vm = TelemetryViewModel()
        panel = SingleProcessPanel(_presenter(), MagicMock(name="bindings"), "camera_0", telemetry=vm)
        qtbot.addWidget(panel)
        assert hasattr(panel, "_telemetry_controls")
        assert set(panel._telemetry_controls._rows) == set(gated_metrics())


# ------------------------------------------------------------------ #
#  6. Второй адрес метрики: поддерево писателя (Ф1 «порта наблюдений»)#
# ------------------------------------------------------------------ #


class TestPluginSubtreeReadout:
    """У метрики ДВА адреса, и строка обязана понимать оба.

    Опасное здесь — не «нашлось значение», а ЧЬЁ оно. Арбитраж имён снят Ф1:
    два писателя с одноимённым листом законны, и строка «17» перестала быть
    ответом на вопрос. Поэтому проверяется текст с именем писателя, а не факт
    непустоты. Второе опасное — приоритет: плоский агрегат фреймворка не должен
    подменяться плагинным листом того же имени и наоборот.
    """

    def test_plugin_leaf_is_shown_with_its_writer(self, qtbot) -> None:
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.cam.state.plugins.capture.drops", 17))
        section = TelemetryControlsSection("cam", ["drops"])
        qtbot.addWidget(section)
        section.update_readouts(vm)
        assert section._rows["drops"].readout.text() == "capture: 17"

    def test_two_writers_are_both_visible(self, qtbot) -> None:
        """Оба писателя в строке, оба со своим литералом — иначе один молча исчезнет."""
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.cam.state.plugins.capture.drops", 17))
        vm.on_state_delta(_delta("processes.cam.state.plugins.mask.drops", 4))
        section = TelemetryControlsSection("cam", ["drops"])
        qtbot.addWidget(section)
        section.update_readouts(vm)
        assert section._rows["drops"].readout.text() == "capture: 17, mask: 4"

    def test_flat_aggregate_still_wins_and_shows_no_writer(self, qtbot) -> None:
        """Регресс-якорь: `fps` — агрегат фреймворка, он плоский и без писателя."""
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.cam.state.fps", 21.0))
        section = TelemetryControlsSection("cam", ["fps"])
        qtbot.addWidget(section)
        section.update_readouts(vm)
        assert section._rows["fps"].readout.text() == "21.0"

    def test_a_neighbour_process_subtree_does_not_leak_in(self, qtbot) -> None:
        """Граница — точка-разделитель: `cam2` не протекает в строку `cam`."""
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.cam2.state.plugins.capture.drops", 99))
        section = TelemetryControlsSection("cam", ["drops"])
        qtbot.addWidget(section)
        section.update_readouts(vm)
        assert section._rows["drops"].readout.text() == "—"

    def test_deeper_node_under_a_writer_is_not_a_process_level_readout(self, qtbot) -> None:
        """Писатель — РОВНО один сегмент: `plugins.<w>.workers.<x>.drops` сюда не идёт.

        Иначе строка каталога показала бы per-worker величину под именем
        process-level метрики — подмена величины, а не мелочь отображения.
        """
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.cam.state.plugins.capture.workers.w1.drops", 5))
        section = TelemetryControlsSection("cam", ["drops"])
        qtbot.addWidget(section)
        section.update_readouts(vm)
        assert section._rows["drops"].readout.text() == "—"

    def test_none_leaf_reads_as_no_value(self, qtbot) -> None:
        """Снятое показание рисуется прочерком, а не строкой «capture: None»."""
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.cam.state.plugins.capture.drops", None))
        section = TelemetryControlsSection("cam", ["drops"])
        qtbot.addWidget(section)
        section.update_readouts(vm)
        assert section._rows["drops"].readout.text() == "—"

    def test_caps_warning_is_not_overwritten_by_a_plugin_leaf(self, qtbot) -> None:
        """Приоритет потолка сохраняется и для второго адреса (у первого он уже был)."""
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta("processes.cam.state.plugins.capture.drops", 17))
        section = TelemetryControlsSection("cam", ["drops"])
        qtbot.addWidget(section)
        section.show_result("drops", {"publish": {"capped_by_throttle": {"drops": {"throttle_interval_sec": 2.0}}}})
        section.update_readouts(vm)
        assert "троттл" in section._rows["drops"].readout.text()

    def test_model_without_snapshot_degrades_to_a_dash(self, qtbot) -> None:
        """Урезанный дубль read-model не роняет панель."""

        class _NoSnapshot:
            def get(self, path, default=None):
                return None

        section = TelemetryControlsSection("cam", ["drops"])
        qtbot.addWidget(section)
        section.update_readouts(_NoSnapshot())
        assert section._rows["drops"].readout.text() == "—"
