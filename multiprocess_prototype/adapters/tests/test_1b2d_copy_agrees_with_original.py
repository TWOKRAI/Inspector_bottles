# -*- coding: utf-8 -*-
"""RED-приёмка Task 1b.2d: копия регистра из ``RegistersManager.from_catalog`` принимает/отвергает
(и нормализует) РОВНО как оригинальный register-класс.

Независимый тестер, без реализации. Оракул — поведение: на одном и том же значении
оригинал (``from_registry(PluginRegistry)``) и копия (``from_catalog(payload)``) выносят один
и тот же вердикт (принято/отклонено) и хранят одно и то же значение. Присваивание — тем же
путём, что у GUI-слоя: ``RegistersManager.set_field_value`` (проверка FieldMeta + ``setattr`` с
``validate_assignment``). Механизм переноса правил (ключи FieldMeta, словарь правил) НЕ
предполагается — виден только результат через ``from_catalog``.

Ожидаемые значения — литералы (дефолты, нормализованные строки); ни одно не считается вызовом
тестируемого кода. Литералы сверены на ОРИГИНАЛЕ тестом
``test_pinned_literals_hold_on_original`` (зелёный сегодня) — если литерал неверен, падает он,
а не «разрыв копии».

Допущения тестера (помечены, см. отчёт):
- «отклонено» = ``set_field_value`` вернул ``(False, _)``; текст ошибки НЕ сравнивается;
- после отклонения ПОЛЕВОЙ проверкой (тип/элемент контейнера/значение поля) хранимое значение
  равно значению ДО присваивания — проверено на оригинале (``test_container_original_...``);
- РЕШЕНИЕ ВЛАДЕЛЬЦА (2026-10-02, заменило мою прежнюю трактовку): отвергнутое значение НЕ остаётся
  в регистре — ни на оригинале, ни на копии, ни на бэкенде; отказ = ничего не записано. Это
  касается и межполевых правил (``model_validator``): раньше на оригинале измерено
  ``max_export_batch_size <- 4096`` -> отклонено, но хранится 4096 (pydantic ставит значение,
  потом зовёт after-валидатор, без отката). Теперь такие случаи ожидают прежний литерал
  (6 / 5 / 512 / 2048) на ОБЕИХ сторонах и на этом дереве красные и на оригинале; оракул AC3
  сравнивает хранимое ВСЕГДА, а не только при принятии;
- ``blur`` (``register_classes == []``) не проверяется вовсе.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.app_module import discover as app_discover
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
from multiprocess_framework.modules.registers_module.core.field_info import extract_fields
from multiprocess_framework.modules.registers_module.core.manager import RegistersManager


# ---------------------------------------------------------------------------
# Харнесс (тот же паттерн, что в test_catalog_registers_editing_acceptance.py)
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    # tests/ -> adapters -> multiprocess_prototype -> repo root
    return Path(__file__).resolve().parents[3]


def _local_entries() -> list[Any]:
    """discover(Plugins/) в ЭТОМ процессе -> PluginEntry-ы (идемпотентно)."""
    app_discover(plugin_paths=[str(_repo_root() / "Plugins")], service_paths=[])
    return PluginRegistry.list()


def _build_catalog_payload(entries: list[Any]) -> dict[str, Any]:
    """``catalog.plugins``-payload через РЕАЛЬНЫЙ ``FieldInfo.to_dict()`` (принятый кодек 1b.2a)."""
    plugins: list[dict[str, Any]] = []
    for e in entries:
        register: dict[str, Any] | None = None
        if e.register_classes:
            fields = [fi.to_dict() for fi in extract_fields(e.name, e.register_classes[0], e.category)]
            register = {"fields": fields}
        plugins.append({"name": e.name, "category": e.category, "register": register})
    return {"success": True, "rev": "0" * 64, "plugins": plugins, "failed_imports": {}}


def _fresh_pair() -> tuple[RegistersManager, RegistersManager]:
    """(оригинал, копия) — СВЕЖИЕ менеджеры на каждый вызов: принятые присваивания не текут между тестами."""
    entries = _local_entries()
    assert entries, "discover(Plugins/) не нашёл ни одного плагина — фикстура сломана"
    original = RegistersManager.from_registry(PluginRegistry)
    copy_rm = RegistersManager.from_catalog(_build_catalog_payload(entries))
    return original, copy_rm


def _assign(rm: RegistersManager, plugin: str, field: str, value: Any) -> tuple[bool, Any]:
    """(принято?, хранимое значение после) — присваивание путём ``set_field_value``."""
    ok, _err = rm.set_field_value(plugin, field, copy.deepcopy(value))
    reg = rm.get_register(plugin)
    assert reg is not None, f"у менеджера нет регистра {plugin!r} — копия не построена"
    return bool(ok), copy.deepcopy(getattr(reg, field))


def _check_case(plugin: str, field: str, value: Any, expect_ok: bool, expect_stored: Any) -> list[str]:
    """Прогнать один случай на оригинале и копии; вернуть список расхождений с литералом (пуст = ок)."""
    original, copy_rm = _fresh_pair()
    problems: list[str] = []
    for label, rm in (("оригинал", original), ("копия", copy_rm)):
        ok, stored = _assign(rm, plugin, field, value)
        if ok is not expect_ok or stored != expect_stored:
            problems.append(
                f"{label}: {plugin}.{field} <- {value!r}: принято={ok!r} хранится={stored!r}; "
                f"ожидалось принято={expect_ok!r} хранится={expect_stored!r}"
            )
    return problems


# ---------------------------------------------------------------------------
# AC1 — типы элементов контейнеров (10 полей в 7 регистрах)
# ---------------------------------------------------------------------------

_MODBUS_PAYLOAD_DEFAULT = [
    {"source": "width"},
    {"source": "height"},
    {"source": "frame_id"},
    {"source": "detections", "reduce": "count"},
    {"source": "detections", "reduce": "sum", "field": "area", "dtype": "u32"},
    {"source": "detections", "reduce": "max", "field": "area", "dtype": "u32"},
]
_OVERLAY_COLOR_TABLE_DEFAULT = [
    {"type": "line", "color": [0, 255, 0], "thickness": 4},
    {"type": "dashed", "color": [0, 255, 0], "thickness": 3},
    {"type": "point", "color": [255, 0, 255], "radius": 8},
]

# (plugin, field, значение с НЕВЕРНЫМ элементом, дефолт-литерал, валидное значение той же формы)
CONTAINER_CASES: list[tuple[str, str, Any, Any, Any]] = [
    ("blob_detector", "contour_color_bgr", ["x"], [0, 255, 0], [1, 2, 3]),
    ("chain_executor", "steps", [1], [], [{"op": "x"}]),
    ("modbus_sink", "payload", [1], _MODBUS_PAYLOAD_DEFAULT, [{"source": "width"}]),
    (
        "overlay_draw",
        "color_table",
        [1],
        _OVERLAY_COLOR_TABLE_DEFAULT,
        [{"type": "line", "color": [1, 2, 3], "thickness": 2}],
    ),
    ("otel_export", "headers", {"a": 1}, {}, {"Authorization": "${OTEL_TOKEN}"}),
    ("center_crop", "pad_color_bgr", ["x"], [0, 0, 0], [1, 2, 3]),
    ("circle_detector", "circle_color_bgr", ["x"], [0, 255, 0], [1, 2, 3]),
    ("circle_draw", "color_bgr", ["x"], [0, 255, 0], [1, 2, 3]),
    ("overlay_draw", "default_line_color", ["x"], [0, 255, 255], [1, 2, 3]),
    ("overlay_draw", "default_point_color", ["x"], [0, 0, 255], [1, 2, 3]),
]
_CONTAINER_IDS = [f"{p}.{f}" for p, f, *_ in CONTAINER_CASES]


@pytest.mark.parametrize(("plugin", "field", "wrong", "default", "_valid"), CONTAINER_CASES, ids=_CONTAINER_IDS)
def test_container_element_types_rejected_like_original(
    plugin: str, field: str, wrong: Any, default: Any, _valid: Any
) -> None:
    """Post: значение с неверным элементом контейнера отклонено ОБЕИМИ сторонами, хранимое не тронуто.

    Измерено до запуска (ревью 1b.2b): копия принимает — кодек вырождает ``list[int]`` и т.п.
    в голый ``list``. Красный на «копия».
    """
    problems = _check_case(plugin, field, wrong, expect_ok=False, expect_stored=default)
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize(("plugin", "field", "wrong", "default", "_valid"), CONTAINER_CASES, ids=_CONTAINER_IDS)
def test_container_original_rejects_wrong_element_anchor(
    plugin: str, field: str, wrong: Any, default: Any, _valid: Any
) -> None:
    """Якорь: ОРИГИНАЛ действительно отвергает неверный элемент и хранит дефолт-литерал (зелёный сегодня)."""
    original, _ = _fresh_pair()
    ok, stored = _assign(original, plugin, field, wrong)
    assert (ok, stored) == (False, default), (
        f"оригинал {plugin}.{field} <- {wrong!r}: принято={ok!r}, хранится={stored!r}"
    )


@pytest.mark.parametrize(("plugin", "field", "_wrong", "_default", "valid"), CONTAINER_CASES, ids=_CONTAINER_IDS)
def test_container_valid_value_accepted_by_both(
    plugin: str, field: str, _wrong: Any, _default: Any, valid: Any
) -> None:
    """Положительный контроль: ВАЛИДНОЕ значение той же формы принято обеими и сохранено как есть."""
    problems = _check_case(plugin, field, valid, expect_ok=True, expect_stored=valid)
    assert not problems, "; ".join(problems)


# ---------------------------------------------------------------------------
# AC2 — python-валидаторы воспроизведены
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "expect_ok", "expect_stored"),
    [
        # дефолты: dedup_radius=5, hysteresis_margin=6. Правило: hysteresis_margin >= dedup_radius.
        ("hysteresis_margin", 4, False, 6),  # 4 < 5 — нарушение
        ("dedup_radius", 7, False, 5),  # 7 > 6 — нарушение с другой стороны правила
        ("hysteresis_margin", 5, True, 5),  # граница: 5 == 5 — разрешено
        ("dedup_radius", 6, True, 6),  # граница: 6 == 6 — разрешено
    ],
    ids=["margin_below_radius", "radius_above_margin", "boundary_margin_eq_radius", "boundary_radius_eq_margin"],
)
def test_line_filter_cross_field_rule(field: str, value: int, expect_ok: bool, expect_stored: int) -> None:
    """Post: межполевое правило line_filter (``hysteresis_margin >= dedup_radius``) на копии == оригинал."""
    problems = _check_case("line_filter", field, value, expect_ok, expect_stored)
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize("value", ["   ", ""], ids=["blank_spaces", "empty"])
def test_otel_endpoint_blank_rejected(value: str) -> None:
    """Post: пустой/пробельный endpoint отклонён обеими сторонами; хранится дефолт регистра плагина ``""``."""
    problems = _check_case("otel_export", "endpoint", value, expect_ok=False, expect_stored="")
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize("value", ["http://127.0.0.1:4318", "localhost:4318"], ids=["no_signal_path", "no_scheme"])
def test_otel_endpoint_without_signal_path_rejected(value: str) -> None:
    """Post: адрес без пути сигнала (и без схемы) отклонён обеими; хранится дефолт ``""``."""
    problems = _check_case("otel_export", "endpoint", value, expect_ok=False, expect_stored="")
    assert not problems, "; ".join(problems)


def test_otel_endpoint_whitespace_normalized_identically() -> None:
    """Post: endpoint с пробелами по краям ПРИНЯТ обеими и хранится обрезанным — одинаково."""
    problems = _check_case(
        "otel_export",
        "endpoint",
        "  http://127.0.0.1:4318/v1/logs  ",
        expect_ok=True,
        expect_stored="http://127.0.0.1:4318/v1/logs",
    )
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize(
    ("value", "expect_ok", "expect_stored"),
    [
        ({"Authorization": "Bearer abc"}, False, {}),  # литерал вместо ${ENV}
        (
            {"Authorization": "${OTEL_TOKEN}"},
            True,
            {"Authorization": "${OTEL_TOKEN}"},
        ),  # контроль: валидная подстановка
        ({"Authorization": "${OTEL_TOKEN} tail"}, False, {}),  # подстановка «не целиком»
    ],
    ids=["literal_rejected", "env_placeholder_accepted", "placeholder_with_tail_rejected"],
)
def test_otel_headers_only_env_placeholders(
    value: dict[str, str], expect_ok: bool, expect_stored: dict[str, str]
) -> None:
    """Post: значение заголовка — только ``${ENV_VAR}`` целиком; иначе отказ обеих сторон."""
    problems = _check_case("otel_export", "headers", value, expect_ok, expect_stored)
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize(
    ("value", "expect_ok", "expect_stored"),
    [
        ("bogus", False, "INFO"),  # неизвестный — отказ, хранится дефолт
        ("warn", True, "WARNING"),  # алиас раскрывается (нормализация)
        ("debug", True, "DEBUG"),  # регистр нормализуется
    ],
    ids=["unknown_rejected", "alias_warn_normalized", "lowercase_normalized"],
)
def test_otel_unknown_level_rejected(value: str, expect_ok: bool, expect_stored: str) -> None:
    """Post: уровень вне шкалы отклонён; алиасы/регистр нормализуются одинаково на обеих сторонах."""
    problems = _check_case("otel_export", "level", value, expect_ok, expect_stored)
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize(
    ("field", "value", "expect_ok", "expect_stored"),
    [
        # дефолты: max_queue_size=2048, max_export_batch_size=512. Правило: batch <= queue.
        ("max_export_batch_size", 4096, False, 512),  # batch > queue
        ("max_queue_size", 100, False, 2048),  # queue < batch — нарушение с другой стороны
        ("max_export_batch_size", 2048, True, 2048),  # граница: batch == queue — разрешено
        ("max_queue_size", 512, True, 512),  # граница: queue == batch — разрешено
    ],
    ids=["batch_above_queue", "queue_below_batch", "boundary_batch_eq_queue", "boundary_queue_eq_batch"],
)
def test_otel_batch_must_fit_queue(field: str, value: int, expect_ok: bool, expect_stored: int) -> None:
    """Post: ``max_export_batch_size <= max_queue_size`` — на копии то же, что на оригинале."""
    problems = _check_case("otel_export", field, value, expect_ok, expect_stored)
    assert not problems, "; ".join(problems)


def test_pinned_literals_hold_on_original() -> None:
    """Якорь AC2: ВСЕ литералы AC2 выше выполняются на ОРИГИНАЛЕ (зелёный сегодня).

    Красен на этом дереве по 4 межполевым случаям (оригинал оставляет отвергнутое значение) —
    решение владельца 2026-10-02: так быть не должно. Остальные строки таблицы зелёные; если
    красна строка вне этих 4 — неверен литерал тестера, а не копия. Таблица продублирована
    намеренно (литералы, а не ссылка на параметры выше).
    """
    table: list[tuple[str, str, Any, bool, Any]] = [
        ("line_filter", "hysteresis_margin", 4, False, 6),
        ("line_filter", "dedup_radius", 7, False, 5),
        ("line_filter", "hysteresis_margin", 5, True, 5),
        ("line_filter", "dedup_radius", 6, True, 6),
        ("otel_export", "endpoint", "   ", False, ""),
        ("otel_export", "endpoint", "", False, ""),
        ("otel_export", "endpoint", "http://127.0.0.1:4318", False, ""),
        ("otel_export", "endpoint", "localhost:4318", False, ""),
        ("otel_export", "endpoint", "  http://127.0.0.1:4318/v1/logs  ", True, "http://127.0.0.1:4318/v1/logs"),
        ("otel_export", "headers", {"Authorization": "Bearer abc"}, False, {}),
        ("otel_export", "headers", {"Authorization": "${OTEL_TOKEN}"}, True, {"Authorization": "${OTEL_TOKEN}"}),
        ("otel_export", "headers", {"Authorization": "${OTEL_TOKEN} tail"}, False, {}),
        ("otel_export", "level", "bogus", False, "INFO"),
        ("otel_export", "level", "warn", True, "WARNING"),
        ("otel_export", "level", "debug", True, "DEBUG"),
        ("otel_export", "max_export_batch_size", 4096, False, 512),
        ("otel_export", "max_queue_size", 100, False, 2048),
        ("otel_export", "max_export_batch_size", 2048, True, 2048),
        ("otel_export", "max_queue_size", 512, True, 512),
    ]
    wrong: list[str] = []
    for plugin, field, value, expect_ok, expect_stored in table:
        original, _ = _fresh_pair()
        ok, stored = _assign(original, plugin, field, value)
        if ok is not expect_ok or stored != expect_stored:
            wrong.append(
                f"{plugin}.{field} <- {value!r}: принято={ok!r} хранится={stored!r}, "
                f"ожидалось ({expect_ok!r}, {expect_stored!r})"
            )
    assert not wrong, "; ".join(wrong)


# ---------------------------------------------------------------------------
# AC3 — оракул по ВСЕМ register-классам каталога Plugins/
# ---------------------------------------------------------------------------

# Фиксированный набор проб: пустые/граничные значения, неверные типы, контейнеры с неверными
# элементами, строки уровня/адреса, малые целые для межполевых границ. Каждая проба пробуется
# на КАЖДОМ поле каждого регистра — вердикт и хранимое значение копии обязаны совпасть с оригиналом.
PROBES: list[Any] = [
    None, "", "   ", "x", "__not_a_choice__", "bogus", "warn", "DEBUG",
    "http://127.0.0.1:4318", "  http://127.0.0.1:4318/v1/logs  ", "${X}",
    0, 1, 2, 3, 4, 5, 6, 7, 100, 101, 512, 2048, 4096, -1, 10**9, -(10**9),
    1.5, True, False,
    [], [1, 2, 3], ["x"], [1, "x"], [[]], [{}], [{"a": 1}], [1],
    {}, {"a": 1}, {"a": "b"}, {"Authorization": "${TOKEN}"}, {"Authorization": "Bearer abc"},
]  # fmt: skip

# Регистры, у которых на момент написания (2026-10-02, дерево addadf7de) копия расходится с
# оригиналом, — ПРОГНОЗ тестера по AC1/AC2 (10 полей в 7 регистрах + line_filter + otel_export).
# Литерал: закрытие разрыва делает ``test_oracle_...all_registers`` зелёным, а
# ``test_oracle_no_divergence_outside_known_list`` защищает от НОВЫХ разрывов вне списка.
KNOWN_DIVERGENT_REGISTERS: frozenset[str] = frozenset(
    {
        "blob_detector",
        "chain_executor",
        "modbus_sink",
        "overlay_draw",
        "otel_export",
        "center_crop",
        "circle_detector",
        "circle_draw",
        "line_filter",
    }
)


def _all_divergences() -> tuple[int, list[tuple[str, str, Any, Any, Any]]]:
    """(число сравнённых регистров, [(plugin, field, проба, (verdict,stored) оригинала, (verdict,stored) копии)])."""
    entries = _local_entries()
    original, copy_rm = _fresh_pair()
    divergences: list[tuple[str, str, Any, Any, Any]] = []
    compared = 0
    for e in entries:
        if not e.register_classes:
            continue  # blur и т.п.: регистра нет — вне контракта
        compared += 1
        name = e.name
        orig_reg, copy_reg = original.get_register(name), copy_rm.get_register(name)
        assert orig_reg is not None and copy_reg is not None, f"у {name!r} нет регистра на одной из сторон"
        fields = extract_fields(name, e.register_classes[0], e.category)
        for fi in fields:
            field = fi.field_name
            saved_o, saved_c = copy.deepcopy(orig_reg.__dict__[field]), copy.deepcopy(copy_reg.__dict__[field])
            probes = list(PROBES)
            if fi.meta is not None:
                for edge in (fi.meta.min, fi.meta.max):
                    if edge is not None:
                        probes += [edge - 1, edge, edge + 1]
            for probe in probes:
                o = _assign(original, name, field, probe)
                c = _assign(copy_rm, name, field, probe)
                if o != c:
                    divergences.append((name, field, probe, o, c))
                # вернуть исходное состояние напрямую (в обход валидации), чтобы разрыв не копился
                orig_reg.__dict__[field] = copy.deepcopy(saved_o)
                copy_reg.__dict__[field] = copy.deepcopy(saved_c)
    return compared, divergences


def test_oracle_copy_agrees_with_original_for_all_registers() -> None:
    """Post: на фиксированном наборе проб вердикт и хранимое значение копии == оригинала, для ВСЕХ registers."""
    compared, divergences = _all_divergences()
    assert compared >= 43, f"сравнено только {compared} register-классов (измерено 43 на 2026-10-02) — обход ослеп"
    registers = sorted({d[0] for d in divergences})
    sample = [(p, f, repr(v), o, c) for p, f, v, o, c in divergences[:6]]
    assert not divergences, (
        f"{len(divergences)} расхождений копия/оригинал в {len(registers)} регистрах {registers}; первые: {sample}"
    )


def test_oracle_no_divergence_outside_known_list() -> None:
    """Защита: расхождения возможны ТОЛЬКО в регистрах литерального списка ``KNOWN_DIVERGENT_REGISTERS``.

    Зелёный и сегодня, и после закрытия разрыва (список просто опустеет по факту); красный —
    если появился НОВЫЙ класс расхождений вне списка (прогноз тестера неполон или регрессия).
    """
    _compared, divergences = _all_divergences()
    unexpected = sorted({d[0] for d in divergences} - KNOWN_DIVERGENT_REGISTERS)
    assert not unexpected, f"расхождения вне известного списка: {unexpected}"


# ---------------------------------------------------------------------------
# (г) Текст отказа не содержит отвергнутого значения (секреты не утекают в ошибку)
# ---------------------------------------------------------------------------


def _error_text(rm: RegistersManager, plugin: str, field: str, value: Any) -> tuple[bool, str]:
    ok, err = rm.set_field_value(plugin, field, copy.deepcopy(value))
    return bool(ok), str(err)


_LEAK_CASES = [
    ("headers", {"Authorization": "literal-secret-123"}, "literal-secret-123"),
    ("endpoint", "UNIQUE-MARKER-endpoint-7f3a9c", "UNIQUE-MARKER-endpoint-7f3a9c"),
]


@pytest.mark.parametrize(("field", "value", "marker"), _LEAK_CASES, ids=["headers_literal", "endpoint_marker"])
def test_copy_rejection_is_refusal_without_echoing_the_value(field: str, value: Any, marker: str) -> None:
    """Post: копия ОТВЕРГАЕТ значение и строка-маркер значения не попадает в текст ошибки.

    Два условия в одном тесте намеренно: без первого «нет маркера в тексте» тривиально
    выполнено у принявшей копии (``None`` -> ``"None"``).
    """
    _, copy_rm = _fresh_pair()
    ok, text = _error_text(copy_rm, "otel_export", field, value)
    assert ok is False, f"копия приняла {field}={value!r} (текст: {text!r})"
    assert marker not in text, f"маркер отвергнутого значения попал в текст ошибки копии: {text!r}"


@pytest.mark.parametrize(("field", "value", "marker"), _LEAK_CASES[:1], ids=["headers_literal"])
def test_original_rejection_does_not_echo_the_value_anchor(field: str, value: Any, marker: str) -> None:
    """Якорь (зелёный сегодня): ОРИГИНАЛ отвергает ``headers`` и не печатает значение (``hide_input_in_errors``).

    ТОЛЬКО headers. Для ``endpoint`` якоря НЕТ намеренно: измерено, что у ОРИГИНАЛА валидатор
    ``_endpoint_carries_signal_path`` сам вставляет значение в текст ошибки (``endpoint {value!r} неполон``),
    поэтому ``hide_input_in_errors`` его не спасает — ожидание «оригинал не печатает endpoint» было
    моей неверной моделью. Копия по (г) всё равно обязана не печатать маркер; если реализация
    воспроизведёт текст валидатора, тест на копии останется красным — решение за лидом.
    """
    original, _ = _fresh_pair()
    ok, text = _error_text(original, "otel_export", field, value)
    assert ok is False, f"оригинал принял {field}={value!r}"
    assert marker not in text, f"оригинал печатает значение в ошибке: {text!r}"
