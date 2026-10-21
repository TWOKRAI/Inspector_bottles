"""Рецепты и join по ``Port.join`` (plans/topology-port-join.md, C16.1): A4, A5, A9, A10.

Слепые приёмочные тесты (написаны до реализации). Ожидаемые значения — литералы плана;
значения «до» сняты на main ``aad763838`` внешним скриптом сборки на стадии 0 и сюда
переписаны как литералы (не получены прогоном этой ветки).

Сборка — тот же вход, что в ``test_build_characterization.py``:
``SystemBuilder.from_manifest(app, recipe).build()`` -> ``launcher._processes``.

Исключён по имени: ``robot_demo`` — на main не собирается (SystemExit 1, C-18, полоса Р2),
это не C-16. ``modbus_demo`` удалён (C-18, владелец 2026-10-21; замена — ``color_inspect``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import yaml

# backend/tests/<file> → parents[3] == корень проекта (Inspector_bottles).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RECIPES_DIR = PROJECT_ROOT / "multiprocess_prototype" / "recipes"

# На main не собираются (SystemExit 1) — не относятся к C-16.
NOT_BUILDABLE_ON_MAIN = {"robot_demo"}

ALL_RECIPES = sorted(p.stem for p in RECIPES_DIR.glob("*.yaml"))
BUILDABLE_RECIPES = [r for r in ALL_RECIPES if r not in NOT_BUILDABLE_ON_MAIN]

# J из плана: collector join-узла с frame + overlay и таймаутом 0.25.
J = {"inputs": ["frame", "overlay"], "mode": "join", "primary": "frame", "timeout_sec": 0.25}
STITCHER = {"inputs": ["frame", "region"], "mode": "join", "primary": "frame"}

# A4 «до» (main aad763838): непустые collector'ы; у остальных процессов — {}.
COLLECTORS_BEFORE: dict[str, dict[str, dict]] = {
    "dataset_circle_capture": {"crop": J},
    "hikvision_letter_robot": {"recog": J},
    "letter_angle_inspect": {"crop": J},
    "letter_robot_sim": {"recog": J},
    "line_filter_inspect": {"draw": J},
    "region_pipeline": {"stitcher": STITCHER},
}

# A4 «после»: то же, плюс draw = J в четырёх рецептах.
COLLECTORS_AFTER: dict[str, dict[str, dict]] = {
    **COLLECTORS_BEFORE,
    "dataset_circle_capture": {"crop": J, "draw": J},
    "hikvision_letter_robot": {"recog": J, "draw": J},
    "letter_angle_inspect": {"crop": J, "draw": J},
    "letter_robot_sim": {"recog": J, "draw": J},
}


@lru_cache(maxsize=None)
def _built_collectors(recipe: str) -> dict[str, Any]:
    """Собрать рецепт и вернуть ``{process_name: config['collector']}``."""
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    app = load_manifest(PROJECT_ROOT / "multiprocess_prototype" / "app.yaml")
    launcher = SystemBuilder.from_manifest(app, recipe).build()
    return {name: proc["config"]["collector"] for name, proc in launcher._processes}


# ---------------------------------------------------------------------------
# A4. Обратная совместимость: collector'ы всех собираемых рецептов
# ---------------------------------------------------------------------------


def test_a4_recipe_set_reaches_the_known_recipes() -> None:
    """Страж «ноль наблюдений»: параметризация не пуста и видит каждый рецепт таблицы A4."""
    assert len(BUILDABLE_RECIPES) > 0
    assert set(COLLECTORS_AFTER) <= set(BUILDABLE_RECIPES), set(COLLECTORS_AFTER) - set(BUILDABLE_RECIPES)
    assert not (NOT_BUILDABLE_ON_MAIN & set(BUILDABLE_RECIPES))


@pytest.mark.parametrize("recipe", BUILDABLE_RECIPES)
def test_a4_untouched_processes_keep_their_collector(recipe: str) -> None:
    """A4 «до»: процессы вне списка изменений (не ``draw`` четырёх рецептов) сохраняют collector «до»."""
    collectors = _built_collectors(recipe)
    assert collectors, f"{recipe}: сборка вернула ноль процессов"
    changed = set(COLLECTORS_AFTER.get(recipe, {})) - set(COLLECTORS_BEFORE.get(recipe, {}))
    for proc, collector in collectors.items():
        if proc in changed:
            continue
        assert collector == COLLECTORS_BEFORE.get(recipe, {}).get(proc, {}), f"{recipe}.{proc}"


@pytest.mark.parametrize("recipe", BUILDABLE_RECIPES)
def test_a4_after_exact_nonempty_collectors(recipe: str) -> None:
    """A4 «после»: набор непустых collector'ов рецепта в точности равен таблице (``draw`` = J в четырёх рецептах)."""
    nonempty = {proc: c for proc, c in _built_collectors(recipe).items() if c}
    assert nonempty == COLLECTORS_AFTER.get(recipe, {})


# ---------------------------------------------------------------------------
# A5. hikvision_letter_robot
# ---------------------------------------------------------------------------


def test_a5_hikvision_letter_robot_draw_collector_is_join() -> None:
    assert _built_collectors("hikvision_letter_robot")["draw"] == J


def test_a5_hikvision_letter_robot_recog_collector_is_join() -> None:
    assert _built_collectors("hikvision_letter_robot")["recog"] == J


# ---------------------------------------------------------------------------
# A9. Рецепты не содержат deprecated-форм и ручных mode/inputs/primary
# ---------------------------------------------------------------------------

_STRUCTURAL_COLLECTOR_KEYS = ("mode", "inputs", "primary")


def _iter_processes(node: Any):
    """Все dict'ы-процессы рецепта (есть ключ ``process_name``), на любой глубине."""
    if isinstance(node, dict):
        if "process_name" in node:
            yield node
        for value in node.values():
            yield from _iter_processes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_processes(value)


def _violations(proc: dict) -> list[str]:
    """Нарушения A9 одного процесса: deprecated-места и ручные структурные ключи collector."""
    found: list[str] = []
    if "inspector" in proc:
        found.append("inspector")
    metadata = proc.get("metadata")
    if isinstance(metadata, dict):
        for key in ("inspector", "collector"):
            if key in metadata:
                found.append(f"metadata.{key}")
    collector = proc.get("collector")
    if isinstance(collector, dict):
        found.extend(f"collector.{k}" for k in _STRUCTURAL_COLLECTOR_KEYS if k in collector)
    return found


def test_a9_scanner_detects_every_forbidden_form() -> None:
    """Парная достижимость к A9: сканер ловит каждую запрещённую форму на синтетическом процессе."""
    assert _violations({"process_name": "x", "inspector": {"timeout_sec": 0.25}}) == ["inspector"]
    assert _violations({"process_name": "x", "metadata": {"inspector": {}}}) == ["metadata.inspector"]
    assert _violations({"process_name": "x", "metadata": {"collector": {}}}) == ["metadata.collector"]
    assert _violations({"process_name": "x", "collector": {"mode": "join", "inputs": [], "primary": "frame"}}) == [
        "collector.mode",
        "collector.inputs",
        "collector.primary",
    ]
    assert _violations({"process_name": "x", "collector": {"timeout_sec": 0.25}, "metadata": {}}) == []


@pytest.mark.parametrize("recipe", ALL_RECIPES)
def test_a9_recipe_has_no_deprecated_or_manual_join_forms(recipe: str) -> None:
    """A9: нет process-level ``inspector``, ``metadata.inspector|collector``, ``mode|inputs|primary`` в collector."""
    doc = yaml.safe_load((RECIPES_DIR / f"{recipe}.yaml").read_text(encoding="utf-8"))
    processes = list(_iter_processes(doc))
    assert processes, f"{recipe}: сканер не нашёл ни одного процесса"
    bad = {p["process_name"]: v for p in processes if (v := _violations(p))}
    assert bad == {}


# Процессы, где рецепт задаёт тонкую настройку таймаута без mode (DESIGN 6 плана).
_RECIPE_TIMEOUT_PROCESSES = {
    "hikvision_letter_robot": ["draw", "recog"],
    "letter_robot_sim": ["draw", "recog"],
    "letter_angle_inspect": ["draw", "crop"],
    "dataset_circle_capture": ["draw", "crop"],
    "line_filter_inspect": ["draw"],
}


@pytest.mark.parametrize(
    ("recipe", "proc_name"),
    [(r, p) for r, ps in _RECIPE_TIMEOUT_PROCESSES.items() for p in ps],
)
def test_a9_migrated_processes_declare_timeout_only_collector(recipe: str, proc_name: str) -> None:
    """Парная проверка к A9 (отсутствие запрещённого != наличие нового): ``collector: {timeout_sec: 0.25}``."""
    doc = yaml.safe_load((RECIPES_DIR / f"{recipe}.yaml").read_text(encoding="utf-8"))
    proc = next(p for p in _iter_processes(doc) if p["process_name"] == proc_name)
    assert proc.get("collector") == {"timeout_sec": 0.25}


# ---------------------------------------------------------------------------
# A10. qr-рецепты: неподключённый overlay — не ошибка
# ---------------------------------------------------------------------------

_QR_DRAW_PROCESSES = {
    "qr_reader_sdk_demo": ["draw"],
    "qr_reader_sdk_dual_demo": ["draw_1", "draw_2"],
    "qr_reader_sdk_dual_selftrigger": ["draw_1", "draw_2"],
}


@pytest.mark.parametrize("recipe", list(_QR_DRAW_PROCESSES))
def test_a10_qr_recipe_builds_and_draw_stays_without_join(recipe: str) -> None:
    """A10: рецепт собирается (сборка включает ``check()``), процесс с ``overlay_draw`` есть, join у него не выведен."""
    collectors = _built_collectors(recipe)  # SystemExit/BlueprintInvalid при ошибке check() -> тест падает
    for proc_name in _QR_DRAW_PROCESSES[recipe]:
        assert proc_name in collectors, f"{recipe}: нет процесса {proc_name!r}: {sorted(collectors)}"
        assert collectors[proc_name] == {}, f"{recipe}.{proc_name}"
