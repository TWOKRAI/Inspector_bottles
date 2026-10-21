"""Вывод join по ``Port.join`` + громкая ошибка C-17 + предупреждение deprecated (plans/topology-port-join.md, C16.1).

Слепые приёмочные тесты (написаны до реализации): A2, A7, A8. Ожидаемые значения — литералы плана.

Модель (из плана):
- вход участвует в join, если ``Port.effective_join`` (``join``, иначе ``not optional``);
- join у процесса выводится при >= 2 разных процессах-источниках в join-входы;
- ``metadata.{collector|inspector}.mode == "join"`` при невыведенном join -> ошибка ``check()`` (C-17),
  результат одинаков до и после ``infer_missing_collectors()``;
- непустой ``metadata.collector``/``metadata.inspector`` -> ровно одно предупреждение на процесс за вызов ``infer``.

Фейковые плагины создаются фабрикой ВНУТРИ тела теста: до реализации ``Port(join=...)`` молча
отбрасывает неизвестный kwarg, поэтому тесты падают на утверждении, а не при сборе.
Реестр плагинов — снимок/восстановление, как в ``process_module/tests/test_blueprint_wire_collector.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.adapters.std_facade import StdLoggerFacade
from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

# Литерал плана (A2): ожидаемый collector при двух join-источниках.
_JOIN_SKELETON = {"mode": "join", "inputs": ["frame", "overlay"], "primary": "frame"}

# Значение, которого не должно быть ни в тексте ошибки C-17, ни в тексте предупреждения.
_SECRET_TIMEOUT = 0.7345


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Снимок/восстановление глобального PluginRegistry (не ``clear()``-в-пустоту)."""
    snapshot = PluginRegistry.snapshot()
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()
    PluginRegistry.restore(snapshot)


# ---------------------------------------------------------------------------
# Фабрика фейковых плагинов (внутри теста, не на уровне модуля)
# ---------------------------------------------------------------------------

# вариант overlay-входа получателя -> kwargs порта
_OVERLAY_VARIANTS: dict[str, dict[str, Any]] = {
    "opt_join": {"optional": True, "join": True},  # как overlay_draw.overlay после правки
    "opt_default": {"optional": True},  # как все нынешние optional-входы (join=None)
    "req_nojoin": {"join": False},  # обязательный вход, явно вне join
    "req_default": {},  # обязательный вход, join=None
}


def _register_fakes() -> None:
    """Зарегистрировать источники ``src_frame``/``src_overlay`` и получателей ``joiner_<вариант>``."""

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
    ]
    for variant, overlay_kwargs in _OVERLAY_VARIANTS.items():
        classes.append(
            _plugin_class(
                f"_Joiner_{variant}",
                f"joiner_{variant}",
                [
                    Port(name="frame", dtype="image/bgr", shape="(H, W, 3)"),
                    Port(name="overlay", dtype="dict", shape="-", **overlay_kwargs),
                ],
                [],
            )
        )
    for cls in classes:
        PluginRegistry.register(name=cls.name, plugin_class=cls, category=cls.category)


def _plugin(name: str) -> dict:
    return {"plugin_name": name, "plugin_class": ""}


def _joiner_process(proc_name: str, variant: str, **extra: Any) -> dict:
    return {"process_name": proc_name, "plugins": [_plugin(f"joiner_{variant}")], **extra}


def _wires_to(proc_name: str, variant: str, *, with_overlay_wire: bool = True) -> list[dict]:
    """Провода S1.frame -> P.frame и (опц.) S2.overlay -> P.overlay (тег = имя source-порта)."""
    wires = [{"source": "s1.src_frame.frame", "target": f"{proc_name}.joiner_{variant}.frame"}]
    if with_overlay_wire:
        wires.append({"source": "s2.src_overlay.overlay", "target": f"{proc_name}.joiner_{variant}.overlay"})
    return wires


def _blueprint(procs: list[dict], wires: list[dict]) -> SystemBlueprint:
    base = [
        {"process_name": "s1", "plugins": [_plugin("src_frame")]},
        {"process_name": "s2", "plugins": [_plugin("src_overlay")]},
    ]
    return SystemBlueprint.model_validate({"name": "join_by_port", "processes": base + procs, "wires": wires})


def _proc(bp: SystemBlueprint, name: str):
    return next(p for p in bp.processes if p.process_name == name)


# ---------------------------------------------------------------------------
# A2. Вывод join по Port.join
# ---------------------------------------------------------------------------


def test_a2_optional_input_with_join_true_makes_join_with_required_input() -> None:
    """A2: frame (обязательный) от S1 + overlay (optional=True, join=True) от S2 -> join из двух входов."""
    _register_fakes()
    bp = _blueprint([_joiner_process("p", "opt_join")], _wires_to("p", "opt_join"))
    bp.infer_missing_collectors()

    assert _proc(bp, "p").collector == _JOIN_SKELETON
    assert bp.check() == []


def test_a2_without_s2_wire_no_join_and_check_clean() -> None:
    """A2: без провода S2 — ``check() == []`` (optional не обязателен) и ``collector == {}``."""
    _register_fakes()
    bp = _blueprint([_joiner_process("p", "opt_join")], _wires_to("p", "opt_join", with_overlay_wire=False))
    bp.infer_missing_collectors()

    assert _proc(bp, "p").collector == {}
    assert bp.check() == []


def test_a2_required_input_with_join_false_does_not_join() -> None:
    """A2: обязательный вход с ``join=False`` от S2 — join не выводится (подключён, но вне join)."""
    _register_fakes()
    bp = _blueprint([_joiner_process("p", "req_nojoin")], _wires_to("p", "req_nojoin"))
    bp.infer_missing_collectors()

    assert _proc(bp, "p").collector == {}
    assert bp.check() == []  # оба входа подключены: ошибки нет, просто нет join


def test_a2_optional_input_with_default_join_does_not_join() -> None:
    """Совместимость: optional-вход с ``join=None`` (все нынешние плагины) по-прежнему не участвует в join."""
    _register_fakes()
    bp = _blueprint([_joiner_process("p", "opt_default")], _wires_to("p", "opt_default"))
    bp.infer_missing_collectors()

    assert _proc(bp, "p").collector == {}
    assert bp.check() == []


def test_a2_required_input_with_default_join_still_joins() -> None:
    """Совместимость: обязательные входы с ``join=None`` от двух источников -> join, как до правки."""
    _register_fakes()
    bp = _blueprint([_joiner_process("p", "req_default")], _wires_to("p", "req_default"))
    bp.infer_missing_collectors()

    assert _proc(bp, "p").collector == _JOIN_SKELETON


# ---------------------------------------------------------------------------
# A7. C-17: metadata.mode=join при невыведенном join -> громкая ошибка check()
# ---------------------------------------------------------------------------

_METADATA_KEYS = ["collector", "inspector"]


def _c17_blueprint(case: str, key: str) -> SystemBlueprint:
    """Blueprint процесса ``layout`` с ``metadata.<key>.mode == "join"``.

    case:
      - ``one_source``: один join-источник (overlay — optional, join=None) -> join не выводится;
      - ``two_sources``: два join-источника (overlay: optional, join=True) -> join выводится;
      - ``explicit_fanin``: два join-источника, но явный ``collector: {mode: fanin}``.
    """
    metadata = {key: {"mode": "join", "timeout_sec": _SECRET_TIMEOUT}}
    if case == "one_source":
        variant, extra = "opt_default", {}
    elif case == "two_sources":
        variant, extra = "opt_join", {}
    elif case == "explicit_fanin":
        variant, extra = "opt_join", {"collector": {"mode": "fanin"}}
    else:  # pragma: no cover - ошибка самого теста
        raise AssertionError(case)
    _register_fakes()
    return _blueprint([_joiner_process("layout", variant, metadata=metadata, **extra)], _wires_to("layout", variant))


def _check_without_and_after_infer(case: str, key: str) -> tuple[list[str], list[str], dict]:
    """``check()`` без ``infer`` и после него + collector процесса ``layout`` после ``infer``."""
    without_infer = _c17_blueprint(case, key).check()
    PluginRegistry.clear()  # свежий реестр для второго blueprint (register бросает на повторное имя)
    bp = _c17_blueprint(case, key)
    bp.infer_missing_collectors()
    return without_infer, bp.check(), dict(_proc(bp, "layout").collector)


@pytest.mark.parametrize("key", _METADATA_KEYS)
def test_a7_one_join_source_with_metadata_mode_join_is_an_error(key: str) -> None:
    """A7: metadata.<key>.mode=join у процесса с одним join-источником -> ровно одна ошибка с именем процесса."""
    without_infer, after_infer, collector_after = _check_without_and_after_infer("one_source", key)

    for errors in (without_infer, after_infer):
        assert len(errors) == 1, errors
        assert "'layout'" in errors[0]
        assert f"metadata.{key}.mode=join" in errors[0]
        assert str(_SECRET_TIMEOUT) not in errors[0]  # значения metadata в тексте нет
    assert without_infer == after_infer


@pytest.mark.parametrize("key", _METADATA_KEYS)
def test_a7_two_join_sources_with_metadata_mode_join_is_not_an_error(key: str) -> None:
    """A7: тот же blueprint с двумя join-источниками -> ошибки нет (до и после infer, списки равны)."""
    without_infer, after_infer, collector_after = _check_without_and_after_infer("two_sources", key)

    assert collector_after["mode"] == "join"  # достижимость: join действительно применён, поэтому ошибки нет
    assert without_infer == []
    assert after_infer == []


@pytest.mark.parametrize("key", _METADATA_KEYS)
def test_a7_explicit_fanin_collector_with_metadata_mode_join_is_an_error(key: str) -> None:
    """A7: явный ``collector: {mode: fanin}`` при metadata mode=join -> ошибка (до и после infer, списки равны)."""
    without_infer, after_infer, collector_after = _check_without_and_after_infer("explicit_fanin", key)

    for errors in (without_infer, after_infer):
        assert len(errors) == 1, errors
        assert "'layout'" in errors[0]
        assert f"metadata.{key}.mode=join" in errors[0]
        assert str(_SECRET_TIMEOUT) not in errors[0]
    assert without_infer == after_infer


@pytest.mark.parametrize("key", _METADATA_KEYS)
def test_a7_metadata_without_mode_join_is_not_an_error(key: str) -> None:
    """Граница C-17: ошибку даёт только ``mode == "join"``; mode-less тонкая настройка и ``mode: fanin`` — нет.

    Парная проверка достижимости к ошибочным кейсам A7: та же топология с одним join-источником.
    """
    for metadata in ({key: {"timeout_sec": _SECRET_TIMEOUT}}, {key: {"mode": "fanin"}}):
        PluginRegistry.clear()
        _register_fakes()
        bp = _blueprint(
            [_joiner_process("layout", "opt_default", metadata=metadata)], _wires_to("layout", "opt_default")
        )
        assert bp.check() == []
        bp.infer_missing_collectors()
        assert bp.check() == []


# ---------------------------------------------------------------------------
# A8. Предупреждение deprecated (metadata.collector / metadata.inspector)
# ---------------------------------------------------------------------------


@pytest.fixture
def warning_log(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Перехват ``StdLoggerFacade.warning`` (патч класса: ``__slots__``) — как в test_blueprint_extras."""
    msgs: list[str] = []

    def _capture(self, msg, *args, **kwargs):
        text = str(msg)
        if args:
            try:
                text = text % args
            except (TypeError, ValueError):
                text = f"{text} {args}"
        msgs.append(text)

    monkeypatch.setattr(StdLoggerFacade, "warning", _capture)
    return msgs


def _two_draw_blueprint(metadata_a: dict | None) -> SystemBlueprint:
    """Два join-процесса ``draw_a``/``draw_b`` на одних источниках; ``metadata`` — только у ``draw_a``."""
    _register_fakes()
    proc_a_extra = {"metadata": metadata_a} if metadata_a is not None else {}
    return _blueprint(
        [_joiner_process("draw_a", "req_default", **proc_a_extra), _joiner_process("draw_b", "req_default")],
        _wires_to("draw_a", "req_default") + _wires_to("draw_b", "req_default"),
    )


@pytest.mark.parametrize("key", _METADATA_KEYS)
def test_a8_metadata_on_one_of_two_processes_gives_exactly_one_warning(key: str, warning_log: list[str]) -> None:
    """A8: два процесса, ``metadata`` только у ``draw_a`` -> ровно 1 запись: его имя, штатный ключ, без значений."""
    bp = _two_draw_blueprint({key: {"timeout_sec": _SECRET_TIMEOUT}})
    bp.infer_missing_collectors()

    assert len(warning_log) == 1, warning_log
    assert "draw_a" in warning_log[0]
    assert "draw_b" not in warning_log[0]
    assert "collector" in warning_log[0]  # называет штатный ключ
    assert str(_SECRET_TIMEOUT) not in warning_log[0]  # значение metadata в текст не попадает


def test_a8_timeout_from_metadata_is_mixed_into_inferred_collector() -> None:
    """A8: ``timeout_sec`` из metadata подмешан поверх выведенного скелета (у соседа без metadata его нет)."""
    bp = _two_draw_blueprint({"inspector": {"timeout_sec": 0.25}})
    bp.infer_missing_collectors()

    assert _proc(bp, "draw_a").collector == {**_JOIN_SKELETON, "timeout_sec": 0.25}
    assert _proc(bp, "draw_b").collector == _JOIN_SKELETON


def test_a8_no_metadata_no_warning_but_inference_ran(warning_log: list[str]) -> None:
    """A8: без ``metadata`` — 0 записей. Парная достижимость: вывод join прошёл по тем же процессам."""
    bp = _two_draw_blueprint(None)
    bp.infer_missing_collectors()

    assert _proc(bp, "draw_a").collector == _JOIN_SKELETON  # infer реально отработал
    assert _proc(bp, "draw_b").collector == _JOIN_SKELETON
    assert warning_log == []


def test_a8_empty_metadata_section_does_not_warn(warning_log: list[str]) -> None:
    """Пустая секция (``metadata.inspector == {}``) — не «непустой dict» -> предупреждения нет."""
    bp = _two_draw_blueprint({"inspector": {}})
    bp.infer_missing_collectors()

    assert _proc(bp, "draw_a").collector == _JOIN_SKELETON  # достижимость: процесс обработан
    assert warning_log == []


def test_a8_both_metadata_keys_on_one_process_warn_once(warning_log: list[str]) -> None:
    """Один раз на процесс: ``metadata.collector`` И ``metadata.inspector`` вместе -> всё равно 1 запись."""
    bp = _two_draw_blueprint({"collector": {"timeout_sec": 0.25}, "inspector": {"timeout_sec": 0.25}})
    bp.infer_missing_collectors()

    assert len(warning_log) == 1, warning_log
    assert "draw_a" in warning_log[0]


def test_a8_warns_even_when_join_is_not_inferred(warning_log: list[str]) -> None:
    """Предупреждение стоит ДО порога ``< 2``: один join-источник (join не выведен) — запись есть."""
    _register_fakes()
    bp = _blueprint(
        [_joiner_process("layout", "opt_default", metadata={"inspector": {"timeout_sec": 0.25}})],
        _wires_to("layout", "opt_default"),
    )
    bp.infer_missing_collectors()

    assert _proc(bp, "layout").collector == {}  # join не выведен
    assert len(warning_log) == 1, warning_log
    assert "layout" in warning_log[0]


def test_a8_warns_even_with_explicit_mode_escape_hatch(warning_log: list[str]) -> None:
    """Предупреждение стоит ДО escape-hatch: явный ``collector: {mode: fanin}`` не глушит запись."""
    _register_fakes()
    bp = _blueprint(
        [
            _joiner_process(
                "layout",
                "req_default",
                metadata={"inspector": {"timeout_sec": 0.25}},
                collector={"mode": "fanin"},
            )
        ],
        _wires_to("layout", "req_default"),
    )
    bp.infer_missing_collectors()

    assert _proc(bp, "layout").collector == {"mode": "fanin"}  # escape-hatch сработал
    assert len(warning_log) == 1, warning_log


def test_a8_check_does_not_warn(warning_log: list[str]) -> None:
    """``check()`` не предупреждает. Парная достижимость: ``infer`` на том же blueprint пишет 1 запись."""
    bp = _two_draw_blueprint({"inspector": {"timeout_sec": 0.25}})
    bp.check()
    assert warning_log == []

    bp.infer_missing_collectors()
    assert len(warning_log) == 1, warning_log
