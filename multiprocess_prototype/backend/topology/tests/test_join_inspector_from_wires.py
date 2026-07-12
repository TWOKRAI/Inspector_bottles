"""Ф4.7: join/inspector из wires — эквивалентность прежнему hoist-результату.

Заменяет удалённый ``test_inspector_hoist.py`` (тестировал снятый костыль
``_hoist_inspector_from_metadata``). До Ф4.7 корректность join двух живых узлов
(``recog``/``draw`` в ``hikvision_letter_robot.yaml``) зависела от того, что
``launch.py::unwrap_recipe`` поднимал ``inspector`` из ``metadata`` в прямой ключ ДО
``SystemBlueprint.model_validate`` (иначе ``extra="ignore"`` молча роняет ``metadata``
целиком). Теперь mode/inputs/primary выводятся структурно из ``wires`` в
``BlueprintAssembler.assemble()`` (``SystemBlueprint.infer_missing_inspectors()``) — вне
зависимости от того, куда GUI-save положил ``inspector``. Тонкая настройка
(``timeout_sec``) при этом сохраняется — ``metadata`` больше не молча теряется, стала
typed-полем ``ProcessConfig.metadata``.

Оба живых рецепта (``phone_sketch``/``hikvision_letter_robot``, G1) собираются через
полный boot-путь (``SystemBuilder.from_manifest(...).build()`` — тот же путь, что и
характеризационный снапшот 5.1, который обязан остаться зелёным без изменений).
"""

from __future__ import annotations

from pathlib import Path

# backend/topology/tests/<file> → parents[4] == корень проекта (Inspector_bottles).
PROJECT_ROOT = Path(__file__).resolve().parents[4]

# Прежний hoist-результат (metadata.inspector, дословно из hikvision_letter_robot.yaml
# до Ф4.7) — эталон, с которым сверяем вывод из wires.
_EXPECTED_JOIN = {
    "mode": "join",
    "inputs": ["frame", "overlay"],
    "primary": "frame",
    "timeout_sec": 0.25,
}


def _build_proc_configs(recipe: str) -> dict[str, dict]:
    """Собрать launcher рецепта и вернуть ``{process_name: config_dict}``."""
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    app = load_manifest(PROJECT_ROOT / "multiprocess_prototype" / "app.yaml")
    launcher = SystemBuilder.from_manifest(app, recipe).build()
    return {name: proc["config"] for name, proc in launcher._processes}


class TestHikvisionJoinNodes:
    """recog/draw — оба живых join-узла, inspector раньше жил под metadata."""

    def test_recog_inspector_equals_former_hoist_result(self) -> None:
        configs = _build_proc_configs("hikvision_letter_robot")
        assert configs["recog"]["inspector"] == _EXPECTED_JOIN

    def test_draw_inspector_equals_former_hoist_result(self) -> None:
        configs = _build_proc_configs("hikvision_letter_robot")
        assert configs["draw"]["inspector"] == _EXPECTED_JOIN

    def test_join_not_degraded_to_fanin(self) -> None:
        """Acceptance Ф4.7: join не деградирует в fanin ни на одном из живых узлов."""
        configs = _build_proc_configs("hikvision_letter_robot")
        for name in ("recog", "draw"):
            assert configs[name]["inspector"]["mode"] == "join", (
                f"{name}: join деградировал в {configs[name]['inspector']!r}"
            )

    def test_non_join_nodes_stay_fanin(self) -> None:
        """layout получает 2 источника (recog+phone), но входы optional — остаётся fanin.

        Regression guard на ложный positive в другую сторону: структурный вывод из
        wires не должен НАВЯЗЫВАТЬ join там, где раньше (с hoist) его не было.
        """
        configs = _build_proc_configs("hikvision_letter_robot")
        assert configs["layout"]["inspector"] == {}
        assert configs["vision"]["inspector"] == {}
        assert configs["line"]["inspector"] == {}


class TestPhoneSketchNoJoinNodes:
    """phone_sketch не содержит ни одной inspector-декларации — join нигде не нужен."""

    def test_all_processes_stay_fanin(self) -> None:
        configs = _build_proc_configs("phone_sketch")
        for name, cfg in configs.items():
            assert cfg["inspector"] == {}, f"{name}: неожиданный inspector {cfg['inspector']!r}"
