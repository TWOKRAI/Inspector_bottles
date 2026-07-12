"""SystemBuilder / AppSpec / assemble_proc_dicts — generic сборка (Ф5.11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_framework.modules.app_module import (
    AppSpec,
    SystemBuilder,
    assemble_proc_dicts,
    build_app,
)

_GENERIC_PROCESS = "multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess"

# .../app_module/tests/<file> → parents[4] = корень репо (для examples/minimal_app).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MINIMAL_APP_YAML = _REPO_ROOT / "examples" / "minimal_app" / "app.yaml"


def _minimal_blueprint() -> dict:
    return {
        "name": "minimal",
        "processes": [
            {
                "process_name": "ticker",
                "process_class": _GENERIC_PROCESS,
                "plugins": [
                    {
                        "plugin_class": "examples.minimal_app.plugins.tick_source.plugin.TickSourcePlugin",
                        "plugin_name": "tick_source",
                        "category": "utility",
                    }
                ],
            }
        ],
        "wires": [],
    }


def test_appspec_is_frozen() -> None:
    spec = AppSpec(manifest_path=Path("/x/app.yaml"))
    with pytest.raises(Exception):
        spec.manifest_path = Path("/y")  # type: ignore[misc]


def test_assemble_proc_dicts_generic() -> None:
    # Плагин должен быть в singleton (check() резолвит порты) — импорт регистрирует.
    import examples.minimal_app.plugins.tick_source.plugin  # noqa: F401

    proc_dicts = assemble_proc_dicts(_minimal_blueprint())
    assert "ticker" in proc_dicts
    pd = proc_dicts["ticker"]
    # merge_with_defaults(DEFAULT_PROCESS_SCHEMA) гарантирует ключи
    assert "class" in pd and "queues" in pd and "managers" in pd


def test_assemble_proc_dicts_invalid_raises() -> None:
    from multiprocess_framework.modules.app_module import BlueprintError

    bad = {
        "processes": [{"process_name": "a", "process_class": _GENERIC_PROCESS, "plugins": []}],
        # wire от несуществующего источника — check() обязан вернуть ошибку
        "wires": [{"source": "ghost", "source_port": "out", "target": "a", "target_port": "in"}],
    }
    with pytest.raises(BlueprintError):
        assemble_proc_dicts(bad)


def test_factory_mode_delegates_to_launcher_factory(tmp_path: Path) -> None:
    """AppSpec.launcher_factory приоритетен: SystemBuilder оборачивает готовый launcher."""
    (tmp_path / "pipeline.yaml").write_text("processes: []\n", encoding="utf-8")
    manifest = tmp_path / "app.yaml"
    manifest.write_text("name: FactoryApp\npipeline: pipeline.yaml\n", encoding="utf-8")

    class _FakeLauncher:
        _processes = [("p1", {}), ("p2", {})]

    seen: dict = {}

    def factory(m, override):
        seen["name"] = m.name
        seen["override"] = override
        return _FakeLauncher()

    spec = AppSpec(manifest_path=manifest, pipeline_override="recipeX", launcher_factory=factory)
    launcher = SystemBuilder(spec).build()
    assert isinstance(launcher, _FakeLauncher)
    assert seen == {"name": "FactoryApp", "override": "recipeX"}


def test_generic_build_produces_launcher() -> None:
    """build_app на manifest'е minimal_app даёт launcher с процессом ticker (без запуска)."""
    launcher = build_app(_MINIMAL_APP_YAML)
    names = [n for n, _ in launcher._processes]
    assert names == ["ticker"]
    assert launcher._orchestrator_class_path is None  # базовый ProcessManagerProcess
