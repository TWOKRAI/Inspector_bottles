"""П3 (Task 2.8a) — слепые RED-тесты: ``TelemetryReadModel`` хранит листья.

Публичный API не меняется, меняется смысл: dict-дельта ЗАМЕНЯЕТ поддерево пути,
история переписанных листьев сохраняется, опрос-снимок видит листья dict-дельты.
Настоящий ``TelemetryReadModel`` без подмен.
"""

from __future__ import annotations

from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel


def test_merge_node_dict_then_leaf_keeps_fresh_leaf():
    """Узел-dict поверх свежих листьев не откатывает более новый лист ``x_mm``."""
    m = TelemetryReadModel()
    m.ingest("devices.state.robot_main.status.telemetry.x_mm", 10.0)
    m.ingest("devices.state.robot_main.status.telemetry.y_mm", 20.0)
    m.ingest("devices.state.robot_main.status", {"telemetry": {"x_mm": 10.0, "y_mm": 20.0}})
    m.ingest("devices.state.robot_main.status.telemetry.x_mm", 55.0)

    assert m.snapshot("devices.state.robot_main") == {
        "devices.state.robot_main.status.telemetry.x_mm": 55.0,
        "devices.state.robot_main.status.telemetry.y_mm": 20.0,
    }


def test_dict_delta_replaces_subtree():
    m = TelemetryReadModel()
    m.ingest("a.n", {"x": 1, "y": 2})
    m.ingest("a.n", {"x": 3})
    assert m.snapshot("a") == {"a.n.x": 3}


def test_dict_delta_keeps_history_of_rewritten_leaf():
    """Лист, переписанный dict-дельтой, остаётся в истории с новой отметкой времени."""
    T = [1.0]
    m = TelemetryReadModel(tracked_suffixes=("x_mm",), clock=lambda: T[0])
    m.ingest("r.status.telemetry.x_mm", 10.0)
    T[0] = 2.0
    m.ingest("r.status", {"telemetry": {"x_mm": 30.0}})

    assert m.history("r.status.telemetry.x_mm") == [(1.0, 10.0), (2.0, 30.0)]


def test_poll_guard_sees_dict_delta_leaves():
    """Ответ опроса, запрошенный ДО dict-дельты, не затирает её лист."""
    m = TelemetryReadModel()
    seq = m.write_seq
    m.ingest("a.n", {"x": 1})

    assert m.ingest_poll_snapshot({"a.n.x": 0}, requested_at_seq=seq) == []
    assert m.get("a.n.x") == 1


def test_prime_flattens_dict():
    m = TelemetryReadModel(initial_cache={"a.n": {"x": 1}})
    assert m.snapshot("a") == {"a.n.x": 1}


def test_empty_dict_clears_subtree():
    m = TelemetryReadModel()
    m.ingest("a.n.x", 1)
    m.ingest("a.n", {})
    assert m.snapshot("a") == {}


def test_h6_delete_of_absent_path_does_not_fail_and_bumps_write_seq_once():
    """H6 (контроль, зелёный на базе): удаление несуществующего пути не падает, ``write_seq`` +1."""
    m = TelemetryReadModel()
    before = m.write_seq
    m.ingest("x.y", 1, deleted=True)
    assert m.write_seq == before + 1
