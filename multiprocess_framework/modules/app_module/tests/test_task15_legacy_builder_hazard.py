"""Авторский hazard-тест Task 1.5 (line-sim): совместимость builder'а приложения до 1.5.

Опасность, которую видит только автор: ``SystemBuilder`` зовёт ``spec.proc_dicts_builder``
с kwarg'ами. Передай он ``telemetry_section`` безусловно — любой builder, написанный до 1.5
с явной сигнатурой, упал бы ``TypeError`` даже в приложении БЕЗ телеметрии. Поэтому kwarg
уходит только когда секция задана; этот тест пинит именно это.
"""

from __future__ import annotations

from pathlib import Path

import examples.minimal_app.plugins.tick_source.plugin  # noqa: F401 — регистрирует плагин для check()

from multiprocess_framework.modules.app_module import AppSpec, SystemBuilder, assemble_proc_dicts

_GENERIC_PROCESS = "multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess"
_TICK_PLUGIN = "examples.minimal_app.plugins.tick_source.plugin.TickSourcePlugin"


def _legacy_builder(blueprint, *, observability_section=None, log_dir=None, app_config_path="", recipe_path=""):
    """Сигнатура ``ProcDictsBuilder`` до Task 1.5 — без ``telemetry_section``."""
    return assemble_proc_dicts(
        blueprint,
        observability_section=observability_section,
        log_dir=log_dir,
        app_config_path=app_config_path,
        recipe_path=recipe_path,
    )


def test_legacy_builder_builds_app_without_telemetry(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text(
        "name: p\nprocesses:\n"
        "  - process_name: ticker\n"
        f"    process_class: {_GENERIC_PROCESS}\n"
        "    plugins:\n"
        f"      - plugin_class: {_TICK_PLUGIN}\n"
        "        plugin_name: tick_source_legacy\n"
        "        category: utility\n"
        "wires: []\n",
        encoding="utf-8",
    )
    (tmp_path / "system.yaml").write_text("observability:\n  errors:\n    enabled: true\n", encoding="utf-8")
    manifest = tmp_path / "app.yaml"
    manifest.write_text("name: Legacy\npipeline: pipeline.yaml\nsystem: system.yaml\n", encoding="utf-8")

    launcher = SystemBuilder(AppSpec(manifest_path=manifest, proc_dicts_builder=_legacy_builder)).build()

    cfg = dict(launcher._processes)["ticker"]["config"]
    assert "telemetry" not in cfg


# --------------------------------------------------------------------------- #
# Правки по ревью 1.5 (итерация 1): свойства переноса, не покрытые спекой      #
# --------------------------------------------------------------------------- #


def _blueprint_one(telemetry=None) -> dict:
    entry = {
        "process_name": "ticker",
        "process_class": _GENERIC_PROCESS,
        "plugins": [{"plugin_class": _TICK_PLUGIN, "plugin_name": "tick_source_rv", "category": "utility"}],
    }
    if telemetry is not None:
        entry["telemetry"] = telemetry
    return {"name": "rv", "processes": [entry], "wires": []}


def test_per_process_only_builds_section() -> None:
    """Только per-process override, глобальной секции нет → гейт у процесса всё равно есть."""
    cfg = assemble_proc_dicts(_blueprint_one({"metrics": {"fps": {"enabled": True}}}))["ticker"]["config"]
    assert cfg["telemetry"] == {"publish": {"metrics": {"fps": {"enabled": True}}}}


def test_explicit_empty_per_process_override_is_kept() -> None:
    """Явный ``{}`` per-process — «включить с дефолтами»: и секция, и сырой override на месте."""
    cfg = assemble_proc_dicts(_blueprint_one({}))["ticker"]["config"]
    assert cfg["telemetry"] == {"publish": {}}
    assert cfg["telemetry_override"] == {}


import pytest  # noqa: E402


@pytest.mark.parametrize("publish_yaml", ["\n    default_interval_sec: -1", " fast"])
def test_invalid_telemetry_section_fails_build(tmp_path: Path, publish_yaml: str) -> None:
    """Невалидная секция роняет сборку, а не выключает гейт молча (паритет с прототипом)."""
    import pydantic

    (tmp_path / "pipeline.yaml").write_text(
        "name: p\nprocesses:\n"
        "  - process_name: ticker\n"
        f"    process_class: {_GENERIC_PROCESS}\n"
        "    plugins:\n"
        f"      - plugin_class: {_TICK_PLUGIN}\n"
        "        plugin_name: tick_source_bad\n"
        "        category: utility\n"
        "wires: []\n",
        encoding="utf-8",
    )
    (tmp_path / "system.yaml").write_text(f"telemetry:\n  publish:{publish_yaml}\n", encoding="utf-8")
    manifest = tmp_path / "app.yaml"
    manifest.write_text("name: Bad\npipeline: pipeline.yaml\nsystem: system.yaml\n", encoding="utf-8")

    with pytest.raises(pydantic.ValidationError):
        SystemBuilder(AppSpec(manifest_path=manifest)).build()
