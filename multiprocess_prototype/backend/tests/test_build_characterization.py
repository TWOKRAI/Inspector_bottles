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
  - слово оператора (``target_word`` плагина word_layout) нормализуется в ``""``: это
    состояние, а не свойство рецепта, и после Save из пульта оно лежит в файле рецепта
    (В5/Task 6.1c); ключ ``target_field: "target_word"`` — другой ключ, его не трогаем;
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

    Ф7 финальное ревью фазы G: у rooted-путей дополнительно канонизируются
    разделители (``\\`` → ``/``). Значения вроде ``log_directory`` производны от
    env ``INSPECTOR_LOG_DIR`` (process-global ``setdefault`` в launch + соседние
    тесты одного pytest-процесса) — стиль разделителей зависел от порядка запуска
    и окружения, и golden молча краснел (обнаружено: тест был red на main с merge
    G.3/G.4, каталог backend/tests вне framework-раннера). Путь тот же — Windows
    принимает оба разделителя; канон — ``/``.
    """
    root = str(PROJECT_ROOT)
    if isinstance(obj, str):
        s = obj.replace(root, ROOT_PLACEHOLDER)
        if ROOT_PLACEHOLDER in s:
            s = s.replace("\\", "/")
        return s
    if isinstance(obj, dict):
        return {k: _normalize_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_paths(v) for v in obj]
    return obj


def _normalize_operator_state(obj: Any) -> Any:
    """Слово оператора → ``""`` рекурсивно (В5/Task 6.1c).

    У каждого dict с ключом ``target_word`` и строковым значением значение заменяется на
    пустую строку; не-строки (``None``, числа) и одноимённое СЛОВО в ``target_field``
    (значение, не ключ) не трогаются. Иначе реальный Save слова из пульта в рецепт краснил
    бы golden, а «осознанная» перегенерация замораживала бы слово оператора.
    """
    if isinstance(obj, dict):
        return {
            k: "" if k == "target_word" and isinstance(v, str) else _normalize_operator_state(v) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_normalize_operator_state(v) for v in obj]
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
    return _normalize_operator_state(_normalize_paths(stable))


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


def test_operator_word_normalized() -> None:
    """Нормализатор: ``target_word``-строка → ``""``, остальное (включая ``target_field``) не тронуто."""
    src = {
        "proc_dicts": {
            "layout": {"config": {"target_word": "МИР", "target_field": "target_word"}},
            "list": [{"target_word": "КОТ"}, [{"target_word": "ДОМ"}]],
            "none": {"target_word": None},
            "num": {"target_word": 5},
        }
    }
    assert _normalize_operator_state(src) == {
        "proc_dicts": {
            "layout": {"config": {"target_word": "", "target_field": "target_word"}},
            "list": [{"target_word": ""}, [{"target_word": ""}]],
            "none": {"target_word": None},
            "num": {"target_word": 5},
        }
    }
    # исходный объект не мутирован
    assert src["proc_dicts"]["layout"]["config"]["target_word"] == "МИР"


def test_operator_word_in_recipe_does_not_change_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Реальная сборка β со словом «МИР» в layout/word_layout даёт тот же срез, что golden.

    Рецепт в репозитории не правится: загрузчик сырого рецепта подменён обёрткой, которая после
    чтения подставляет слово в плагин word_layout. Страж «ноль наблюдений»: слово действительно
    дошло до сборки (иначе тест прошёл бы вхолостую).
    """
    from multiprocess_prototype.backend import launch

    original = launch._load_raw_dict
    injected: list[str] = []

    def _find_word_layout(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("plugin_name") == "word_layout" and isinstance(node.get("config"), dict):
                node["config"]["target_word"] = "МИР"
                injected.append("МИР")
            for v in node.values():
                _find_word_layout(v)
        elif isinstance(node, list):
            for v in node:
                _find_word_layout(v)

    def _load_with_word(path: Path) -> Any:
        raw = original(path)
        _find_word_layout(raw)
        return raw

    monkeypatch.setattr(launch, "_load_raw_dict", _load_with_word)
    actual = _canonical_build("hikvision_letter_robot")

    assert injected, "слово не подставлено: в загруженном рецепте нет плагина word_layout"
    expected = json.loads(_golden_path("hikvision_letter_robot").read_text(encoding="utf-8"))
    assert actual == expected
