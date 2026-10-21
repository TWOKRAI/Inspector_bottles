"""``collector`` без ``mode`` при невыведенном join -> ошибка ``check()`` (plans/topology-port-join.md, C22.1).

Слепые приёмочные тесты (написаны до реализации): B1-B8, B10, B11. B0 и B9 - у лида (существующие наборы).
Ожидаемые значения - литералы плана (подстроки текста ошибки, ``join-источников: N``, словарь collector).

Каждый случай зовёт ``SystemBlueprint.check()`` дважды - до и после ``infer_missing_collectors()`` - и сравнивает
списки, отфильтрованные по точной преамбуле `` без mode (ключи:`` (текст C-17 тоже содержит «без mode»,
поэтому фильтр по одному «без mode» не годится; real check() ещё даёт несвязанную ошибку «Вход ... не подключен»).
Фикстуры - как в ``test_infer_join_by_port.py``: свои фейковые плагины, снимок/восстановление PluginRegistry.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

# Точная преамбула ошибки C-22 (из плана): отличает её от C-17 и от «Вход ... не подключен».
_PREAMBLE = " без mode (ключи:"

# Литерал плана (B3): collector после infer при двух join-источниках с тонкой настройкой.
_B3_COLLECTOR = {"mode": "join", "inputs": ["frame", "overlay"], "primary": "frame", "timeout_sec": 0.25}


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Снимок/восстановление глобального PluginRegistry."""
    snapshot = PluginRegistry.snapshot()
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()
    PluginRegistry.restore(snapshot)


# ---------------------------------------------------------------------------
# Фабрика фейковых плагинов и сборка схемы
# ---------------------------------------------------------------------------


def _register_fakes() -> None:
    """Источники ``src_frame``/``src_overlay`` и ``joiner``: ``frame`` обязательный, ``overlay`` optional+join."""

    def _plugin_class(cls_name: str, plugin_name: str, inputs: list[Port], outputs: list[Port]) -> type:
        return type(
            cls_name,
            (ProcessModulePlugin,),
            {
                "name": plugin_name,
                "category": "processing",
                "inputs": inputs,
                "outputs": outputs,
                "configure": lambda self, ctx: None,
                "start": lambda self, ctx: None,
            },
        )

    classes = [
        _plugin_class("_SrcFrame", "src_frame", [], [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]),
        _plugin_class("_SrcOverlay", "src_overlay", [], [Port(name="overlay", dtype="dict", shape="-")]),
        _plugin_class(
            "_Joiner",
            "joiner",
            [
                Port(name="frame", dtype="image/bgr", shape="(H, W, 3)"),
                Port(name="overlay", dtype="dict", shape="-", optional=True, join=True),
            ],
            [],
        ),
    ]
    for cls in classes:
        PluginRegistry.register(name=cls.name, plugin_class=cls, category=cls.category)


def _plugin(name: str) -> dict:
    return {"plugin_name": name, "plugin_class": ""}


def _joiner_process(proc_name: str, **extra: Any) -> dict:
    return {"process_name": proc_name, "plugins": [_plugin("joiner")], **extra}


def _frame_wire(proc_name: str) -> dict:
    """Провод S1.frame -> <proc>.frame: один join-источник (обязательный вход)."""
    return {"source": "s1.src_frame.frame", "target": f"{proc_name}.joiner.frame"}


def _overlay_wire(proc_name: str) -> dict:
    """Провод S2.overlay -> <proc>.overlay: второй join-источник."""
    return {"source": "s2.src_overlay.overlay", "target": f"{proc_name}.joiner.overlay"}


def _blueprint(procs: list[dict], wires: list[dict]) -> SystemBlueprint:
    base = [
        {"process_name": "s1", "plugins": [_plugin("src_frame")]},
        {"process_name": "s2", "plugins": [_plugin("src_overlay")]},
    ]
    return SystemBlueprint.model_validate({"name": "modeless_collector", "processes": base + procs, "wires": wires})


def _proc(bp: SystemBlueprint, name: str):
    return next(p for p in bp.processes if p.process_name == name)


def _c22(errors: list[str]) -> list[str]:
    return [e for e in errors if _PREAMBLE in e]


def _before_after(bp: SystemBlueprint) -> tuple[list[str], list[str]]:
    """check() без infer, затем infer и check() снова; оба списка - только ошибки C-22 (по точной преамбуле).

    Результат C-22 не должен зависеть от infer: списки равны (проверяется здесь же).
    """
    before = _c22(bp.check())
    bp.infer_missing_collectors()
    after = _c22(bp.check())
    assert before == after, f"C-22 зависит от infer: до={before!r}, после={after!r}"
    return before, after


# ---------------------------------------------------------------------------
# B1. typed collector без mode, один join-источник
# ---------------------------------------------------------------------------


def test_b1_typed_modeless_collector_with_one_join_source_is_one_error() -> None:
    _register_fakes()
    bp = _blueprint([_joiner_process("P", collector={"timeout_sec": 0.25})], [_frame_wire("P")])

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    text = before[0]
    assert "'P'" in text
    assert "collector без mode" in text
    assert "timeout_sec" in text
    assert "join-источников: 1" in text
    assert "mode: fanin" in text
    assert "0.25" not in text  # значения секции в текст не попадают


# ---------------------------------------------------------------------------
# B2. секция в extras под ключом collector (a) и inspector (b)
# ---------------------------------------------------------------------------


def test_b2a_extras_collector_modeless_with_one_join_source_is_one_error() -> None:
    _register_fakes()
    bp = _blueprint([_joiner_process("P", extras={"collector": {"timeout_sec": 0.25}})], [_frame_wire("P")])

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    assert "'P'" in before[0]
    assert "collector без mode" in before[0]
    assert "join-источников: 1" in before[0]


def test_b2b_extras_inspector_modeless_with_one_join_source_is_one_error_naming_inspector() -> None:
    _register_fakes()
    bp = _blueprint([_joiner_process("P", extras={"inspector": {"timeout_sec": 0.25}})], [_frame_wire("P")])

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    assert "'P'" in before[0]
    assert "inspector без mode" in before[0]
    assert "join-источников: 1" in before[0]


# ---------------------------------------------------------------------------
# B3. два join-источника: тонкая настройка применяется, ошибок нет
# ---------------------------------------------------------------------------


def test_b3_two_join_sources_modeless_collector_is_thin_tuning_no_error() -> None:
    _register_fakes()
    bp = _blueprint(
        [_joiner_process("P", collector={"timeout_sec": 0.25})],
        [_frame_wire("P"), _overlay_wire("P")],
    )

    before, after = _before_after(bp)

    assert before == [] and after == []
    assert _proc(bp, "P").collector == _B3_COLLECTOR


# ---------------------------------------------------------------------------
# B4. один источник, mode задан явно - ошибки нет
# ---------------------------------------------------------------------------


def test_b4_one_source_explicit_fanin_has_no_error() -> None:
    _register_fakes()
    bp = _blueprint([_joiner_process("P", collector={"mode": "fanin", "timeout_sec": 0.25})], [_frame_wire("P")])

    before, after = _before_after(bp)

    assert before == [] and after == []


def test_b4_one_source_explicit_join_has_no_c22_error() -> None:
    _register_fakes()
    bp = _blueprint(
        [_joiner_process("P", collector={"mode": "join", "inputs": ["frame"], "primary": "frame"})],
        [_frame_wire("P")],
    )

    before, after = _before_after(bp)

    assert before == [] and after == []


# ---------------------------------------------------------------------------
# B5. один источник, секции нет / пустая - ошибки нет
# ---------------------------------------------------------------------------


def test_b5_one_source_without_collector_has_no_error() -> None:
    _register_fakes()
    bp = _blueprint([_joiner_process("P")], [_frame_wire("P")])

    before, after = _before_after(bp)

    assert before == [] and after == []


def test_b5_one_source_empty_collector_has_no_error() -> None:
    _register_fakes()
    bp = _blueprint([_joiner_process("P", collector={})], [_frame_wire("P")])

    before, after = _before_after(bp)

    assert before == [] and after == []


# ---------------------------------------------------------------------------
# B6. ноль источников
# ---------------------------------------------------------------------------


def test_b6_zero_join_sources_modeless_collector_is_one_error() -> None:
    _register_fakes()
    bp = _blueprint([_joiner_process("P", collector={"timeout_sec": 0.25})], [])

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    assert "'P'" in before[0]
    assert "join-источников: 0" in before[0]


# ---------------------------------------------------------------------------
# B7. mode: None и mode: "" - как mode-less
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("empty_mode", [None, ""], ids=["mode_none", "mode_empty_string"])
def test_b7_falsy_mode_is_treated_as_modeless(empty_mode: Any) -> None:
    _register_fakes()
    bp = _blueprint(
        [_joiner_process("P", collector={"mode": empty_mode, "timeout_sec": 1})],
        [_frame_wire("P")],
    )

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    assert "'P'" in before[0]
    assert "join-источников: 1" in before[0]


# ---------------------------------------------------------------------------
# B8. три процесса: ошибка только у A
# ---------------------------------------------------------------------------


def test_b8_only_modeless_process_is_reported() -> None:
    _register_fakes()
    bp = _blueprint(
        [
            _joiner_process("A", collector={"timeout_sec": 0.25}),
            _joiner_process("B", collector={"mode": "fanin", "timeout_sec": 0.25}),
            _joiner_process("C"),
        ],
        [_frame_wire("A"), _frame_wire("B"), _frame_wire("C")],
    )

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    assert "'A'" in before[0]
    assert "'B'" not in before[0]
    assert "'C'" not in before[0]


# ---------------------------------------------------------------------------
# B10. C-17 и C-22 одновременно: обе ошибки остаются, по одной
# ---------------------------------------------------------------------------


def test_b10_c17_and_c22_both_reported_once_before_and_after_infer() -> None:
    _register_fakes()
    bp = _blueprint(
        [_joiner_process("P", collector={"timeout_sec": 0.25}, metadata={"collector": {"mode": "join"}})],
        [_frame_wire("P")],
    )

    before_all = bp.check()
    bp.infer_missing_collectors()
    after_all = bp.check()

    for errors in (before_all, after_all):
        assert len([e for e in errors if "metadata.collector.mode=join" in e]) == 1
        assert len([e for e in errors if _PREAMBLE in e]) == 1
    assert _c22(before_all) == _c22(after_all)


# ---------------------------------------------------------------------------
# B11. нестроковые ключи секции не ломают check()
# ---------------------------------------------------------------------------


def test_b11_non_string_section_keys_do_not_raise_and_are_listed_sorted() -> None:
    _register_fakes()
    bp = _blueprint([_joiner_process("P", extras={"collector": {1: "a", "x": 2}})], [_frame_wire("P")])

    before, after = _before_after(bp)  # check() не бросает ни до, ни после infer

    assert len(before) == 1 and len(after) == 1
    assert "ключи: 1, x" in before[0]
