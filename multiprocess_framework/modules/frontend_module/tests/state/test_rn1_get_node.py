"""RN1 — слепые RED-тесты: ``TelemetryViewModel.get_node(path, default=None)``.

Контракт по брифу ``plans/2026-10-27_system-run-state/tasks/RN1.md`` (DESIGN 3, ЛИТЕРАЛЫ ``get_node``):
``get_node`` читает УЗЕЛ из листьев; ``get(path, default)`` остаётся листовым (не меняется).
Настоящая ``TelemetryViewModel`` без подмен, питается через ``on_state_delta``.
"""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.state.telemetry_view_model import TelemetryViewModel


def _delta(path: str, value: object, deleted: bool = False) -> dict:
    return {"data_type": "state_delta", "path": path, "value": value, "deleted": deleted}


def test_get_node_returns_nested_dict_get_stays_leaf(qtbot) -> None:
    """Свойство: при узле ``a.n`` = ``{"x": 3}``: ``get_node("a.n")`` -> ``{"x": 3}``,
    ``get("a.n")`` -> ``None`` (лист-контракт НЕ меняется), ``get("a.n.x")`` -> ``3``.

    Убивает мутантов: (а) ``get_node`` = ``return self._model.get(...)`` (вернёт ``None``);
    (б) ``get`` научили собирать узел (``get("a.n")`` перестанет быть ``None``).
    """
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("a.n", {"x": 3}))
    assert vm.get_node("a.n") == {"x": 3}
    assert vm.get("a.n") is None
    assert vm.get("a.n.x") == 3


def test_get_node_two_level_nested(qtbot) -> None:
    """Свойство: вложенность сохраняется (``{"p": {"q": 1}, "r": 2}``).

    Убивает мутанта: ``get_node`` отдаёт плоский срез снимка без сборки.
    """
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("a.n", {"p": {"q": 1}, "r": 2}))
    assert vm.get_node("a.n") == {"p": {"q": 1}, "r": 2}


def test_get_node_missing_returns_default(qtbot) -> None:
    """Свойство: отсутствующий путь -> ``default`` (``7``), без default -> ``None``.

    Убивает мутанта: ``default`` игнорируется / возвращается ``(False, None)`` кортежем.
    """
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("a.n", {"x": 3}))
    assert vm.get_node("a.zz", default=7) == 7
    assert vm.get_node("a.zz") is None


def test_get_node_found_none_leaf_is_not_default(qtbot) -> None:
    """Свойство: лист ``a.n.x`` со значением ``None`` найден -> ``None``, НЕ default.

    Убивает мутанта: ``value if value is not None else default`` вместо ``value if found else default``.
    """
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("a.n.x", None))
    assert vm.snapshot("a") == {"a.n.x": None}  # предпосылка: лист с None записан
    assert vm.get_node("a.n.x", default=7) is None


def test_get_node_empty_path_returns_default(qtbot) -> None:
    """Свойство: пустой путь — не «весь снимок»: ``get_node("", default=7)`` -> ``7``.

    Убивает мутанта: ``get_node`` на пустом пути отдаёт собранный корень.
    """
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("a.n", {"x": 3}))
    assert vm.get_node("", default=7) == 7
