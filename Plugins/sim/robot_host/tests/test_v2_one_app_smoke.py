# -*- coding: utf-8 -*-
"""Слепая приёмка T2.4 (RED до кода): смоук «одно приложение».

Два блюпринта собираются публичным входом фреймворка ``build_app`` (валидатор блюпринта внутри
сборки, образец — ``apps/line_sim/tests/test_f1_task12_wiring.py``):

  A. штатный ``apps/line_sim/pipeline.yaml`` с подставленным ``protocol: v2`` у ``SimRobotHostPlugin``;
  B. он же с добавочным ПУСТЫМ процессом-хозяином (``process_name: host``, без плагинов).

Ожидание: ``BlueprintError`` нет; плагины те же классы; процессы ``camera`` и ``mjpeg`` остаются
раздельными. YAML читается из репозитория и правится в памяти; файлы манифеста для сборки пишутся
в ``tmp_path`` (``discovery.plugin_paths`` — абсолютный путь), файлы репозитория не меняются.
"""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.app_module import build_app
from multiprocess_framework.modules.app_module.builder import BlueprintError


_REPO_ROOT = Path(__file__).resolve().parents[4]
_APP_DIR = _REPO_ROOT / "apps" / "line_sim"
_ROBOT_CLASS = "Plugins.sim.robot_host.plugin.SimRobotHostPlugin"
_GENERIC = "multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess"


def _write_app(tmp_path: Path, name: str, pipeline: dict) -> Path:
    """Манифест + pipeline + system в ``tmp_path/name``; скан плагинов — абсолютным путём."""
    out = tmp_path / name
    out.mkdir()
    app = yaml.safe_load((_APP_DIR / "app.yaml").read_text(encoding="utf-8"))
    app["discovery"]["plugin_paths"] = [str(_REPO_ROOT / "Plugins" / "sim")]
    (out / "app.yaml").write_text(yaml.safe_dump(app, allow_unicode=True), encoding="utf-8")
    (out / "pipeline.yaml").write_text(yaml.safe_dump(pipeline, allow_unicode=True), encoding="utf-8")
    (out / "system.yaml").write_text((_APP_DIR / "system.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return out / "app.yaml"


def _processes(app_yaml: Path) -> dict:
    """Собрать приложение (валидатор блюпринта) и отдать конфиг процессов."""
    return build_app(app_yaml)._get_processes_config()  # noqa: SLF001 — как в test_f1_task12_wiring


def _plugin_classes(processes: dict) -> dict[str, list[tuple[str, str | None]]]:
    return {
        proc_name: [(p.get("plugin_name"), p.get("plugin_class")) for p in proc["config"]["plugins"]]
        for proc_name, proc in processes.items()
    }


def test_same_plugins_one_app(tmp_path) -> None:
    """Блюпринты A (``protocol: v2``) и B (+ пустой ``host``) собираются без ``BlueprintError``; у B те
    же плагины, что у A, плюс пустой ``host``; ``camera`` и ``mjpeg`` остаются разными процессами; ключ
    ``protocol: v2`` дошёл до плагина хоста в обоих блюпринтах.

    НЕ доказывает: что приложение ЗАПУСКАЕТСЯ (только сборка и валидатор; живой запуск — у лида);
    что плагин реально читает ``protocol`` (это test_v2_host); что пустой процесс переживёт запуск."""
    base = yaml.safe_load((_APP_DIR / "pipeline.yaml").read_text(encoding="utf-8"))
    disk_before = (_APP_DIR / "pipeline.yaml").read_bytes()

    pipeline_a = copy.deepcopy(base)
    robot_cfgs = [
        plugin
        for proc in pipeline_a["processes"]
        for plugin in proc.get("plugins", [])
        if plugin.get("plugin_class") == _ROBOT_CLASS
    ]
    assert len(robot_cfgs) == 1, "в штатном pipeline.yaml ожидался ровно один SimRobotHostPlugin"
    robot_cfgs[0]["protocol"] = "v2"

    pipeline_b = copy.deepcopy(pipeline_a)
    pipeline_b["processes"].append(
        {"process_name": "host", "process_class": _GENERIC, "priority": "normal", "plugins": []}
    )

    try:
        proc_a = _processes(_write_app(tmp_path, "a", pipeline_a))
        proc_b = _processes(_write_app(tmp_path, "b", pipeline_b))
    except BlueprintError as exc:
        pytest.fail(f"валидатор блюпринта отверг сборку: {exc}")

    classes_a, classes_b = _plugin_classes(proc_a), _plugin_classes(proc_b)
    assert classes_b == {**classes_a, "host": []}, f"плагины B разошлись с A: {classes_b} vs {classes_a}"
    assert "camera" in proc_a and "mjpeg" in proc_a and "camera" in proc_b and "mjpeg" in proc_b
    assert [n for n, _c in classes_b["camera"]] == ["scene_source"], classes_b["camera"]
    assert [n for n, _c in classes_b["mjpeg"]] == ["mjpeg_sink"], classes_b["mjpeg"]

    for label, procs in (("A", proc_a), ("B", proc_b)):
        robot = next(p for p in procs["robot"]["config"]["plugins"] if p.get("plugin_class") == _ROBOT_CLASS)
        assert robot.get("protocol") == "v2", f"блюпринт {label}: protocol не дошёл до плагина: {robot!r}"

    assert (_APP_DIR / "pipeline.yaml").read_bytes() == disk_before, "pipeline.yaml на диске изменился"
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "apps/line_sim"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    assert status.strip() == "", f"файлы apps/line_sim изменены: {status!r}"
