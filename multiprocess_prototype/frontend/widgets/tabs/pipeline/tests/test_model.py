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
    """Тесты display-привязок в PipelineModel (G.4.2b: display = binding, не wire).

    Привязка = {node_id: <source endpoint>, display_id: <канал>}. Ключ — пара
    (node_id, display_id): один выход → N каналов (fan-out), один канал → N выходов
    (fan-in). Display-узлов и display-wire'ов в модели больше нет.
    """

    def test_add_display_creates_binding(self) -> None:
        """add_display создаёт привязку source→канал в topology['displays']."""
        model = PipelineModel()
        old, new = model.add_display("cam.capture.frame", "main_output")
        assert old["displays"] == []
        assert len(new["displays"]) == 1
        entry = new["displays"][0]
        assert entry["node_id"] == "cam.capture.frame"
        assert entry["display_id"] == "main_output"
        assert entry["display_name"] == ""

    def test_add_display_with_name(self) -> None:
        """add_display сохраняет display_name."""
        model = PipelineModel()
        _, new = model.add_display("cam.capture.frame", "main", display_name="Главный экран")
        assert new["displays"][0]["display_name"] == "Главный экран"

    def test_add_display_duplicate_pair_raises(self) -> None:
        """Дубликат пары (node_id, display_id) вызывает ValueError."""
        model = PipelineModel()
        model.add_display("cam.capture.frame", "main")
        with pytest.raises(ValueError, match="уже существует"):
            model.add_display("cam.capture.frame", "main")

    def test_add_display_fan_out_allowed(self) -> None:
        """Один выход может быть привязан к двум каналам (fan-out)."""
        model = PipelineModel()
        model.add_display("cam.capture.frame", "main")
        model.add_display("cam.capture.frame", "preview")  # тот же source, другой канал
        assert len(model.get_displays()) == 2

    def test_add_display_fan_in_allowed(self) -> None:
        """Два разных выхода могут ссылаться на один канал (fan-in)."""
        model = PipelineModel()
        model.add_display("cam.capture.frame", "main_output")
        model.add_display("proc.mask.out", "main_output")  # тот же канал, другой source
        displays = model.get_displays()
        assert len(displays) == 2

    def test_get_displays_returns_copy(self) -> None:
        """get_displays возвращает deep copy — мутация не влияет на модель."""
        model = PipelineModel()
        model.add_display("cam.capture.frame", "main")
        displays = model.get_displays()
        displays[0]["node_id"] = "HACKED"
        assert model.get_displays()[0]["node_id"] == "cam.capture.frame"

    def test_get_edges_excludes_display_bindings(self) -> None:
        """get_edges_as_tuples содержит только process→process wire'ы."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        model.add_display("A.plugin.frame", "main")
        model.add_wire("A.out.0", "B.in.0")

        edges = model.get_edges_as_tuples()
        # Только процессный wire; привязки дисплея в wires не попадают
        assert len(edges) == 1
        assert edges[0] == ("A", "B")

    def test_validate_catches_binding_to_missing_process(self) -> None:
        """validate() ловит display-привязку к несуществующему процессу-источнику."""
        topo = {
            "processes": [{"process_name": "A", "plugins": []}],
            "wires": [],
            "displays": [{"node_id": "ghost.plugin.frame", "display_id": "main"}],
        }
        model = PipelineModel(topo)
        errors = model.validate()
        assert any("несуществующий процесс" in e for e in errors)

    def test_validate_no_error_for_valid_binding(self) -> None:
        """validate() не сообщает об ошибках для привязки с валидным источником."""
        model = PipelineModel()
        model.add_process("cam")
        model.add_process("proc")
        model.add_wire("cam.out.0", "proc.in.0")
        model.add_display("proc.plugin.frame", "main")
        errors = model.validate()
        assert not any("display" in e.lower() for e in errors)
