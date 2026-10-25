"""Неприменённая metadata.collector/inspector -> ошибка check() (plans/topology-port-join.md, C28.1).

Слепые приёмочные тесты (написаны до реализации): M1-M13. M0 - у developer (существующий тест, правка ожидания).
Ожидаемые значения - литералы плана (подстроки текста ошибки, ``join-источников: N``, значения collector).

Каждый случай зовёт ``SystemBlueprint.check()`` дважды - до и после ``infer_missing_collectors()`` - и сравнивает
списки, отфильтрованные по подстроке ``(deprecated, ключи:`` (так ошибка C-28 отличается от C-17, C-22 и от
несвязанных ошибок «Вход ... не подключен»). Результат C-28 не должен зависеть от ``infer`` (боевая сборка зовёт
``infer`` перед ``check()``).

Фикстуры - как в ``test_modeless_collector_check.py``: свои фейковые плагины, снимок/восстановление PluginRegistry.
Реестр подменяется только тестами с фейками (фикстура ``fakes``); M10 собирает реальные рецепты на реальном реестре.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

# Подстрока, по которой отбираются ошибки C-28 (из плана: DESIGN 3, «Acceptance»).
_C28 = "(deprecated, ключи:"
# Преамбула ошибки C-22 (collector без mode при невыведенном join).
_C22 = " без mode (ключи:"
# Подстроки ошибки C-17 (metadata.<key>.mode=join при невыведенном join).
_C17_INSPECTOR = "metadata.inspector.mode=join"

# tests/<file> -> parents[4] == корень проекта (Inspector_bottles): tests, process_manager_module, modules,
# multiprocess_framework, <корень>.
PROJECT_ROOT = Path(__file__).resolve().parents[4]
RECIPES_DIR = PROJECT_ROOT / "multiprocess_prototype" / "recipes"
APP_YAML = PROJECT_ROOT / "multiprocess_prototype" / "app.yaml"

# Литерал плана (M10): число рецептов репозитория.
_RECIPE_COUNT = 22
ALL_RECIPES = sorted(p.stem for p in RECIPES_DIR.glob("*.yaml"))


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


@pytest.fixture
def fakes():
    """Снимок реестра -> чистый реестр с фейками -> восстановление. Только для тестов с фейковыми плагинами."""
    snapshot = PluginRegistry.snapshot()
    PluginRegistry.clear()
    _register_fakes()
    yield
    PluginRegistry.clear()
    PluginRegistry.restore(snapshot)


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
    return SystemBlueprint.model_validate({"name": "unapplied_metadata", "processes": base + procs, "wires": wires})


def _proc(bp: SystemBlueprint, name: str):
    return next(p for p in bp.processes if p.process_name == name)


def _only(errors: list[str], marker: str) -> list[str]:
    return [e for e in errors if marker in e]


def _before_after_all(bp: SystemBlueprint) -> tuple[list[str], list[str]]:
    """Полный ``check()`` без infer, затем infer и ``check()`` снова. Списки НЕ фильтруются."""
    before = bp.check()
    bp.infer_missing_collectors()
    after = bp.check()
    return before, after


def _before_after(bp: SystemBlueprint) -> tuple[list[str], list[str]]:
    """``check()`` до/после infer; оба списка - только ошибки C-28 (по подстроке). Списки обязаны быть равны."""
    before_all, after_all = _before_after_all(bp)
    before, after = _only(before_all, _C28), _only(after_all, _C28)
    assert before == after, f"C-28 зависит от infer: до={before!r}, после={after!r}"
    return before, after


# ---------------------------------------------------------------------------
# M1-M2. один join-источник: секция не применится -> ошибка
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_m1_one_join_source_metadata_inspector_is_one_error() -> None:
    bp = _blueprint(
        [_joiner_process("P", metadata={"inspector": {"timeout_sec": 0.25}})],
        [_frame_wire("P")],
    )

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    text = before[0]
    assert "'P'" in text
    assert "metadata.inspector" in text
    assert "timeout_sec" in text
    assert "join-источников: 1" in text
    assert "collector: {timeout_sec: …}" in text
    assert "0.25" not in text  # значения секции в текст не попадают


@pytest.mark.usefixtures("fakes")
def test_m2_one_join_source_metadata_collector_is_one_error_naming_collector() -> None:
    bp = _blueprint(
        [_joiner_process("P", metadata={"collector": {"timeout_sec": 0.25}})],
        [_frame_wire("P")],
    )

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    text = before[0]
    assert "'P'" in text
    assert "metadata.collector" in text
    assert "metadata.inspector" not in text
    assert "join-источников: 1" in text
    assert "0.25" not in text


# ---------------------------------------------------------------------------
# M3. два join-источника: секция применяется, ошибки нет
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_m3_two_join_sources_metadata_is_applied_no_error() -> None:
    bp = _blueprint(
        [_joiner_process("P", metadata={"inspector": {"timeout_sec": 0.25}})],
        [_frame_wire("P"), _overlay_wire("P")],
    )

    before, after = _before_after(bp)

    assert before == [] and after == []
    assert _proc(bp, "P").collector["timeout_sec"] == 0.25


# ---------------------------------------------------------------------------
# M4. два источника, но typed collector с mode=fanin: секция не применится
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_m4_two_sources_typed_fanin_collector_makes_metadata_unapplied() -> None:
    bp = _blueprint(
        [
            _joiner_process(
                "P",
                collector={"mode": "fanin"},
                metadata={"inspector": {"timeout_sec": 0.25}},
            )
        ],
        [_frame_wire("P"), _overlay_wire("P")],
    )

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    assert "'P'" in before[0]
    assert "mode=fanin" in before[0]


# ---------------------------------------------------------------------------
# M5. C-17 и C-28 не дублируют друг друга: по процессу с ошибкой C-17 C-28 молчит
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_m5_c17_error_suppresses_c28_for_the_same_process() -> None:
    bp = _blueprint(
        [
            _joiner_process(
                "P",
                metadata={"inspector": {"mode": "join", "inputs": ["frame"], "primary": "frame"}},
            )
        ],
        [_frame_wire("P")],
    )

    before_all, after_all = _before_after_all(bp)

    for errors in (before_all, after_all):
        assert len(_only(errors, _C17_INSPECTOR)) >= 1, errors
        assert _only(errors, _C28) == []


# ---------------------------------------------------------------------------
# M6. C-22 и C-28 одновременно: обе ошибки остаются, по одной
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_m6_c22_and_c28_both_reported_once() -> None:
    bp = _blueprint(
        [
            _joiner_process(
                "P",
                collector={"timeout_sec": 1},
                metadata={"inspector": {"timeout_sec": 0.25}},
            )
        ],
        [_frame_wire("P")],
    )

    before_all, after_all = _before_after_all(bp)

    for errors in (before_all, after_all):
        assert len(_only(errors, _C22)) == 1, errors
        assert len(_only(errors, _C28)) == 1, errors
    assert _only(before_all, _C28) == _only(after_all, _C28)
    assert _only(before_all, _C22) == _only(after_all, _C22)


# ---------------------------------------------------------------------------
# M7. ноль источников
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_m7_zero_join_sources_metadata_collector_is_one_error() -> None:
    bp = _blueprint(
        [_joiner_process("P", metadata={"collector": {"timeout_sec": 0.25}})],
        [],
    )

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    assert "'P'" in before[0]
    assert "join-источников: 0" in before[0]


# ---------------------------------------------------------------------------
# M8. пустая секция / пустая metadata - ошибки нет
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
@pytest.mark.parametrize("metadata", [{"inspector": {}}, {}], ids=["empty_inspector", "empty_metadata"])
@pytest.mark.parametrize("with_overlay", [False, True], ids=["one_source", "two_sources"])
def test_m8_empty_section_or_empty_metadata_has_no_c28_error(metadata: dict, with_overlay: bool) -> None:
    wires = [_frame_wire("P")] + ([_overlay_wire("P")] if with_overlay else [])
    bp = _blueprint([_joiner_process("P", metadata=metadata)], wires)

    before, after = _before_after(bp)

    assert before == [] and after == []


# ---------------------------------------------------------------------------
# M9. три процесса: ошибка только у A
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_m9_only_process_with_unapplied_section_is_reported() -> None:
    bp = _blueprint(
        [
            _joiner_process("A", metadata={"inspector": {"timeout_sec": 0.25}}),
            _joiner_process("B"),
            _joiner_process("C", metadata={"source_target_fps": 25}),
        ],
        [_frame_wire("A"), _frame_wire("B"), _frame_wire("C")],
    )

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    assert "'A'" in before[0]
    assert "'B'" not in before[0]
    assert "'C'" not in before[0]


# ---------------------------------------------------------------------------
# M10. боевые рецепты: 0 процессов с metadata.collector/inspector, сборка не бросает (реальный реестр)
# ---------------------------------------------------------------------------


def _recipe_processes(recipe: str) -> list[dict]:
    data = yaml.safe_load((RECIPES_DIR / f"{recipe}.yaml").read_text(encoding="utf-8"))
    return list(data["blueprint"]["processes"])


def _offenders(recipe: str) -> list[str]:
    """Процессы рецепта с непустой ``metadata.collector`` или ``metadata.inspector``."""
    result: list[str] = []
    for proc in _recipe_processes(recipe):
        metadata = proc.get("metadata") or {}
        if metadata.get("collector") or metadata.get("inspector"):
            result.append(f"{recipe}:{proc.get('process_name')}")
    return result


def test_m10_recipe_set_is_the_known_22() -> None:
    """Страж «ноль наблюдений»: рецептов ровно 22 и в них есть процессы."""
    assert len(ALL_RECIPES) == _RECIPE_COUNT, ALL_RECIPES
    assert "robot_demo" in ALL_RECIPES
    assert sum(len(_recipe_processes(r)) for r in ALL_RECIPES) > 0


def test_m10_no_recipe_process_has_legacy_metadata_section() -> None:
    offenders = [o for r in ALL_RECIPES for o in _offenders(r)]

    assert offenders == []


@pytest.mark.parametrize("recipe", ALL_RECIPES)
def test_m10_recipe_builds_without_raising(recipe: str) -> None:
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    app = load_manifest(APP_YAML)
    launcher = SystemBuilder.from_manifest(app, recipe).build()

    assert len(launcher._processes) > 0


# ---------------------------------------------------------------------------
# M11. C-17 по inspector подавляет C-28 и для collector-секции того же процесса
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_m11_c17_on_inspector_suppresses_c28_by_process_name() -> None:
    bp = _blueprint(
        [
            _joiner_process(
                "P",
                metadata={"collector": {"timeout_sec": 0.25}, "inspector": {"mode": "join"}},
            )
        ],
        [_frame_wire("P")],
    )

    before_all, after_all = _before_after_all(bp)

    for errors in (before_all, after_all):
        assert len(_only(errors, _C17_INSPECTOR)) >= 1, errors
        assert _only(errors, _C28) == []


# ---------------------------------------------------------------------------
# M12. не-dict metadata.collector не прячет metadata.inspector от infer
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_m12_non_dict_collector_does_not_hide_inspector_section() -> None:
    bp = _blueprint(
        [_joiner_process("P", metadata={"collector": 5, "inspector": {"timeout_sec": 0.25}})],
        [_frame_wire("P"), _overlay_wire("P")],
    )

    before_all, after_all = _before_after_all(bp)

    assert _only(before_all, _C28) == []
    assert _only(after_all, _C28) == []
    assert _proc(bp, "P").collector["timeout_sec"] == 0.25


# ---------------------------------------------------------------------------
# M13. решение (б): {mode: fanin} без других ключей - тоже ошибка
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_m13_bare_fanin_section_is_an_error_with_one_source() -> None:
    bp = _blueprint(
        [_joiner_process("P", metadata={"inspector": {"mode": "fanin"}})],
        [_frame_wire("P")],
    )

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    text = before[0]
    assert "metadata.inspector (deprecated, ключи: mode)" in text
    assert "collector: {mode: …}" in text


# ---------------------------------------------------------------------------
# Дополнительно (шаблон текста, DESIGN 3): ключи отсортированы и перечислены через ', ' и в подсказке
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fakes")
def test_extra_keys_are_sorted_in_preamble_and_hint() -> None:
    bp = _blueprint(
        [_joiner_process("P", metadata={"collector": {"timeout_sec": 0.25, "inputs_hint": 1}})],
        [_frame_wire("P")],
    )

    before, after = _before_after(bp)

    assert len(before) == 1 and len(after) == 1
    text = before[0]
    assert "(deprecated, ключи: inputs_hint, timeout_sec)" in text
    assert "{inputs_hint: …, timeout_sec: …}" in text
