"""Тесты PipelineModel — SSOT-модель topology."""

from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.widgets.tabs.pipeline.model import (
    PipelineModel,
)


class TestPipelineModelAddProcess:
    """Тесты добавления процессов."""

    def test_add_process(self) -> None:
        """Добавление процесса возвращает (old, new)."""
        model = PipelineModel()
        old, new = model.add_process("camera", plugin_name="HikvisionPlugin")
        assert old["processes"] == []
        assert len(new["processes"]) == 1
        assert new["processes"][0]["process_name"] == "camera"
        assert new["processes"][0]["plugins"][0]["plugin_name"] == "HikvisionPlugin"

    def test_add_process_with_config(self) -> None:
        """Добавление процесса с конфигом."""
        model = PipelineModel()
        _, new = model.add_process("proc", config={"fps": 30})
        assert new["processes"][0]["config"] == {"fps": 30}


class TestPipelineModelRemoveProcess:
    """Тесты удаления процессов."""

    def test_remove_process_cascades_wires(self) -> None:
        """Удаление процесса каскадно удаляет wire'ы."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        model.add_process("C")
        model.add_wire("A.out.0", "B.in.0")
        model.add_wire("B.out.0", "C.in.0")

        old, new = model.remove_process("B")
        # B и все его wire'ы удалены
        assert "B" not in [p["process_name"] for p in new["processes"]]
        assert len(new["wires"]) == 0

    def test_remove_keeps_unrelated_wires(self) -> None:
        """Удаление процесса не затрагивает несвязанные wire'ы."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        model.add_process("C")
        model.add_wire("A.out.0", "B.in.0")

        model.remove_process("C")
        wires = model.get_wires()
        assert len(wires) == 1


class TestPipelineModelWires:
    """Тесты wire'ов."""

    def test_add_wire(self) -> None:
        """Wire добавляется и возвращает (old, new)."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        old, new = model.add_wire("A.out.0", "B.in.0")
        assert len(old["wires"]) == 0
        assert len(new["wires"]) == 1
        assert new["wires"][0]["source"] == "A.out.0"
        assert new["wires"][0]["target"] == "B.in.0"

    def test_add_wire_cycle_rejected(self) -> None:
        """Цикл отклоняется с ValueError."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        model.add_process("C")
        model.add_wire("A.out.0", "B.in.0")
        model.add_wire("B.out.0", "C.in.0")
        with pytest.raises(ValueError, match="цикл"):
            model.add_wire("C.out.0", "A.in.0")

    def test_add_wire_self_loop_rejected(self) -> None:
        """Self-loop отклоняется с ValueError."""
        model = PipelineModel()
        model.add_process("A")
        with pytest.raises(ValueError, match="Self-loop"):
            model.add_wire("A.out.0", "A.in.0")

    def test_add_wire_duplicate_rejected(self) -> None:
        """Дубликат wire'а отклоняется."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        model.add_wire("A.out.0", "B.in.0")
        with pytest.raises(ValueError, match="уже существует"):
            model.add_wire("A.out.0", "B.in.0")

    def test_remove_wire(self) -> None:
        """Удаление wire'а."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        model.add_wire("A.out.0", "B.in.0")
        _, new = model.remove_wire("A.out.0", "B.in.0")
        assert len(new["wires"]) == 0


class TestPipelineModelRoundTrip:
    """Тесты сериализации."""

    def test_round_trip(self) -> None:
        """from_topology_dict / to_topology_dict без потерь."""
        topo = {
            "processes": [
                {"process_name": "A", "plugins": [{"plugin_name": "P1"}]},
                {"process_name": "B", "plugins": []},
            ],
            "wires": [{"source": "A.out.0", "target": "B.in.0"}],
        }
        model = PipelineModel()
        model.from_topology_dict(topo)
        result = model.to_topology_dict()
        assert result == topo

    def test_immutability(self) -> None:
        """Мутация оригинального dict не влияет на модель."""
        topo = {"processes": [{"process_name": "A", "plugins": []}], "wires": []}
        model = PipelineModel()
        model.from_topology_dict(topo)
        topo["processes"].append({"process_name": "HACK", "plugins": []})
        assert len(model.get_process_names()) == 1


class TestPipelineModelValidate:
    """Тесты валидации."""

    def test_validate_valid_topology(self) -> None:
        """Валидная topology — нет ошибок (кроме orphan'ов если нет wire'ов)."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        model.add_wire("A.out.0", "B.in.0")
        errors = model.validate()
        assert len(errors) == 0

    def test_validate_duplicate_names(self) -> None:
        """Дубликаты имён процессов."""
        topo = {
            "processes": [
                {"process_name": "A", "plugins": []},
                {"process_name": "A", "plugins": []},
            ],
            "wires": [],
        }
        model = PipelineModel(topo)
        errors = model.validate()
        assert any("Дублирующееся" in e for e in errors)

    def test_validate_orphan_process(self) -> None:
        """Изолированный процесс — предупреждение."""
        model = PipelineModel()
        model.add_process("lonely")
        errors = model.validate()
        assert any("Изолированный" in e for e in errors)

    def test_validate_wire_to_missing_process(self) -> None:
        """Wire ссылается на несуществующий процесс."""
        topo = {
            "processes": [{"process_name": "A", "plugins": []}],
            "wires": [{"source": "A.out.0", "target": "MISSING.in.0"}],
        }
        model = PipelineModel(topo)
        errors = model.validate()
        assert any("несуществующий" in e for e in errors)


class TestPipelineModelDisplays:
    """Тесты display-узлов в PipelineModel."""

    def test_add_display_creates_entry(self) -> None:
        """add_display создаёт запись в topology['displays']."""
        model = PipelineModel()
        old, new = model.add_display("disp1", "main_output")
        assert old["displays"] == []
        assert len(new["displays"]) == 1
        entry = new["displays"][0]
        assert entry["node_id"] == "disp1"
        assert entry["display_id"] == "main_output"
        assert entry["display_name"] == ""

    def test_add_display_with_name(self) -> None:
        """add_display сохраняет display_name."""
        model = PipelineModel()
        _, new = model.add_display("disp1", "main", display_name="Главный экран")
        assert new["displays"][0]["display_name"] == "Главный экран"

    def test_add_display_duplicate_raises(self) -> None:
        """Дубликат node_id вызывает ValueError."""
        model = PipelineModel()
        model.add_display("disp1", "main")
        with pytest.raises(ValueError, match="уже существует"):
            model.add_display("disp1", "other")

    def test_add_display_same_display_id_allowed(self) -> None:
        """Два разных node_id могут ссылаться на один display_id."""
        model = PipelineModel()
        model.add_display("disp1", "main_output")
        model.add_display("disp2", "main_output")  # тот же display_id — разрешено
        displays = model.get_displays()
        assert len(displays) == 2

    def test_remove_display_cascades_wires(self) -> None:
        """remove_display каскадно удаляет wire'ы к этому display."""
        model = PipelineModel()
        model.add_process("cam")
        model.add_display("disp1", "main")
        model.add_wire("cam.plugin.frame", "display.disp1.frame")
        assert len(model.get_wires()) == 1

        _, new = model.remove_display("disp1")
        assert new["displays"] == []
        assert new["wires"] == []

    def test_remove_display_keeps_other_wires(self) -> None:
        """remove_display не трогает wire'ы к другим display-узлам."""
        model = PipelineModel()
        model.add_process("cam")
        model.add_display("disp1", "main")
        model.add_display("disp2", "preview")
        model.add_wire("cam.plugin.frame", "display.disp1.frame")
        model.add_wire("cam.plugin.frame", "display.disp2.frame")

        model.remove_display("disp1")
        wires = model.get_wires()
        assert len(wires) == 1
        assert wires[0]["target"] == "display.disp2.frame"

    def test_remove_nonexistent_display_no_raise(self) -> None:
        """remove_display несуществующего узла не вызывает исключения."""
        model = PipelineModel()
        model.add_process("cam")
        old, new = model.remove_display("ghost")
        # Нет изменений — topology одинаковый
        assert old["displays"] == new["displays"]

    def test_add_wire_to_display_works(self) -> None:
        """Wire process→display добавляется без cycle-ошибки."""
        model = PipelineModel()
        model.add_process("cam")
        model.add_display("disp1", "main")
        old, new = model.add_wire("cam.plugin.frame", "display.disp1.frame")
        assert len(new["wires"]) == 1
        assert new["wires"][0]["source"] == "cam.plugin.frame"
        assert new["wires"][0]["target"] == "display.disp1.frame"

    def test_add_wire_to_nonexistent_display_raises(self) -> None:
        """Wire к несуществующему display вызывает ValueError."""
        model = PipelineModel()
        model.add_process("cam")
        with pytest.raises(ValueError, match="не найден"):
            model.add_wire("cam.plugin.frame", "display.ghost.frame")

    def test_get_displays_returns_copy(self) -> None:
        """get_displays возвращает deep copy — мутация не влияет на модель."""
        model = PipelineModel()
        model.add_display("disp1", "main")
        displays = model.get_displays()
        displays[0]["node_id"] = "HACKED"
        assert model.get_displays()[0]["node_id"] == "disp1"

    def test_get_edges_excludes_displays(self) -> None:
        """get_edges_as_tuples не включает wire'ы к display-узлам."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        model.add_display("disp1", "main")
        model.add_wire("A.out.0", "B.in.0")
        model.add_wire("B.plugin.frame", "display.disp1.frame")

        edges = model.get_edges_as_tuples()
        # Только процессный wire, display-wire исключён
        assert len(edges) == 1
        assert edges[0] == ("A", "B")

    def test_validate_catches_wire_to_missing_display(self) -> None:
        """validate() ловит wire, ссылающийся на несуществующий display."""
        topo = {
            "processes": [{"process_name": "A", "plugins": []}],
            "wires": [{"source": "A.out.0", "target": "display.ghost.frame"}],
            "displays": [],
        }
        model = PipelineModel(topo)
        errors = model.validate()
        assert any("несуществующий display" in e for e in errors)

    def test_validate_catches_orphan_display(self) -> None:
        """validate() находит изолированный display (без источников)."""
        model = PipelineModel()
        model.add_display("disp1", "main")
        errors = model.validate()
        assert any("Изолированный display" in e for e in errors)

    def test_validate_no_error_for_connected_display(self) -> None:
        """validate() не сообщает об ошибках для display с wire-источником."""
        model = PipelineModel()
        model.add_process("cam")
        model.add_process("proc")
        model.add_display("disp1", "main")
        model.add_wire("cam.out.0", "proc.in.0")
        model.add_wire("proc.plugin.frame", "display.disp1.frame")
        errors = model.validate()
        # Нет orphan-display и нет wire к несуществующему display
        assert not any("display" in e.lower() for e in errors)
