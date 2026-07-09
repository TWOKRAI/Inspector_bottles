"""Характеризационный тест ``SystemBuilder.build()`` — прекондиция carve E (Task 5.1).

Фиксирует ТЕКУЩЕЕ поведение сборки как golden-снапшот::

    blueprint dict (рецепт ⊕ фундамент)  →  N процессов + orchestrator_config

Смысл (стратегия strangler-fig, app-template-idea.md §5): перед выносом шва
``SystemLauncher(...)+add_process`` во framework (Task 5.2, E3) нужен сетчатый
тест, который ловит ЛЮБОЙ дрейф результата сборки. E3 обязан оставить снапшот
бит-в-бит прежним (acceptance 5.2: «5.1 зелёный без изменений»).

Что снапшотится (детерминированный, машинно-независимый срез launcher'а):
  - имена процессов в порядке добавления + их количество;
  - ``proc_dict`` каждого процесса (class/config/managers/queues/workers/...);
  - ``orchestrator_class_path`` (в E3 станет DI-параметром — снапшот зафиксирует
    прежнее значение);
  - ``orchestrator_config`` целиком (initial_state, throttle_rules, backend_ctl,
    sys_config, observability_config_path, replace_debounce_s).

Устойчивость снапшота:
  - абсолютный путь корня проекта нормализуется в ``<ROOT>`` (иначе снапшот привязан
    к машине);
  - ``build()`` НЕ спавнит процессы — только конструирует ``SystemLauncher`` (dict-
    сборка + assembly + filesystem-discover), поэтому «железные» рецепты (phone /
    hikvision) собираются headless без камеры [[hardware-recipes-no-headless-boot]];
  - счётчик discover'а плагинов кэшируется между вызовами в одном процессе (56→0),
    но в снапшот НЕ течёт (``initial_state.plugins == {catalog: [], paths: []}``) —
    поэтому тест не зависит от порядка сборки рецептов.

Обновить golden осознанно (после одобренной смены поведения)::

    UPDATE_BUILD_SNAPSHOTS=1 python -m pytest \
        multiprocess_prototype/backend/tests/test_build_characterization.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

# backend/tests/<file> → parents[3] == корень проекта (Inspector_bottles).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"
ROOT_PLACEHOLDER = "<ROOT>"

# «Два живых рецепта» (директива владельца, G1): их сборку нельзя ломать при carve.
RECIPES = ["phone_sketch", "hikvision_letter_robot"]


def _normalize_paths(obj: Any) -> Any:
    """Заменить абсолютный путь корня проекта на ``<ROOT>`` рекурсивно.

    Делает снапшот машинно-независимым, сохраняя относительную структуру путей.
    """
    root = str(PROJECT_ROOT)
    if isinstance(obj, str):
        return obj.replace(root, ROOT_PLACEHOLDER)
    if isinstance(obj, dict):
        return {k: _normalize_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_paths(v) for v in obj]
    return obj


def _canonical_build(recipe: str) -> dict[str, Any]:
    """Собрать launcher рецепта и извлечь детерминированный канонический срез.

    Прогон через ``json.dumps(default=str)`` → ``loads`` канонизирует не-JSON
    значения (Path, float) к стабильному виду до нормализации путей.
    """
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    app = load_manifest(PROJECT_ROOT / "multiprocess_prototype" / "app.yaml")
    launcher = SystemBuilder.from_manifest(app, recipe).build()

    payload = {
        "process_names": [name for name, _ in launcher._processes],
        "process_count": len(launcher._processes),
        "proc_dicts": {name: proc for name, proc in launcher._processes},
        "orchestrator_class_path": launcher._orchestrator_class_path,
        "stop_timeout": launcher._stop_timeout,
        "orchestrator_config": launcher._orchestrator_config,
    }
    # default=str → стабильная сериализация Path/float; loads → снова dict для diff.
    stable = json.loads(json.dumps(payload, default=str, sort_keys=True))
    return _normalize_paths(stable)


def _golden_path(recipe: str) -> Path:
    return SNAPSHOT_DIR / f"{recipe}.build.json"


def _dump_golden(recipe: str, data: dict[str, Any]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    _golden_path(recipe).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("recipe", RECIPES)
def test_build_matches_snapshot(recipe: str) -> None:
    """build() рецепта даёт бит-в-бит прежний срез (процессы + orchestrator_config)."""
    actual = _canonical_build(recipe)

    if os.environ.get("UPDATE_BUILD_SNAPSHOTS"):
        _dump_golden(recipe, actual)
        pytest.skip(f"golden обновлён: {_golden_path(recipe).name}")

    golden_path = _golden_path(recipe)
    assert golden_path.exists(), (
        f"нет golden-снапшота {golden_path}; сгенерировать: "
        f"UPDATE_BUILD_SNAPSHOTS=1 python -m pytest {Path(__file__).name}"
    )
    expected = json.loads(golden_path.read_text(encoding="utf-8"))

    # Явные инварианты — читаемое сообщение до глубокого diff всего среза.
    assert actual["process_names"] == expected["process_names"]
    assert actual["process_count"] == expected["process_count"]
    assert actual["orchestrator_class_path"] == expected["orchestrator_class_path"]
    # Полный снапшот: ловит ЛЮБОЙ дрейф proc_dict / orchestrator_config.
    assert actual == expected
