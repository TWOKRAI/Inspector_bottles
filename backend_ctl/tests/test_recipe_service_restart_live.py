"""Live-плечо автора Task 1b.1: ``recipe.activate`` переживает рестарт бэкенда.

Что может сломаться именно в этом механизме (почему тест устроен так):

* ``persist_active`` пишет не тот файл — боевой ``app.yaml`` вместо манифеста, из
  которого поднят хаб. Ловится сверкой sha256 боевого файла до/после и значением
  ``pipeline:`` во временном манифесте.
* ``persist_active`` пишет значение, которое boot не резолвит (абсолютный путь в
  чужой каталог, путь от cwd). Ловится вторым подъёмом: он обязан собрать X.
* Активация применила топологию, но манифест не записан (порядок apply → persist
  перепутан или persist проглочен) — после рестарта поднялся бы прежний рецепт.

Ответ живой команды приходит в конверте: полезная нагрузка обработчика лежит в
``result`` (``RouterManager.reply_to_request``), ``success`` конверта выводится из неё.
Свой порт 8889 (диапазон 8880-8899 Task 1b.1).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend_ctl.harness import BackendHarness
from backend_ctl.tests.test_recipe_service_live import BOOT_RECIPE, manifest_launcher, write_temp_manifest

_PORT = 8889
_TARGET = "g1_perf_probe"  # синтетический источник + счётчик: без железа, отличим от BOOT_RECIPE
_TARGET_PROCESS = "synthetic_source"  # процесс, которого нет в BOOT_RECIPE


def _payload(reply: Any) -> dict:
    assert isinstance(reply, dict), reply
    result = reply.get("result")
    assert isinstance(result, dict), f"нет result в конверте: {reply}"
    return result


def _process_names(drv) -> set[str]:
    reply = drv.send_command("ProcessManager", "supervision.status", {}, timeout=8.0)
    node: Any = reply
    for _ in range(4):
        if isinstance(node, dict) and "processes" in node:
            break
        node = node.get("result") if isinstance(node, dict) else None
    assert isinstance(node, dict), f"supervision.status без processes: {reply}"
    procs = node["processes"]
    return set(procs) if isinstance(procs, dict) else {p.get("name") for p in procs}


@pytest.mark.harness_smoke
def test_activate_survives_backend_restart(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    real_manifest = repo_root / "multiprocess_prototype" / "app.yaml"
    real_sha = hashlib.sha256(real_manifest.read_bytes()).hexdigest()

    shutil.copytree(repo_root / "multiprocess_prototype" / "recipes", tmp_path / "recipes")
    manifest = write_temp_manifest(real_manifest, tmp_path)

    harness = BackendHarness(port=_PORT, launcher_factory=lambda: manifest_launcher(manifest))
    drv = harness.start()
    try:
        listed = _payload(drv.send_command("ProcessManager", "recipe.list", {}, timeout=8.0))
        assert listed["active"] == BOOT_RECIPE, listed
        assert _TARGET_PROCESS not in _process_names(drv)

        reply = drv.send_command("ProcessManager", "recipe.activate", {"name": _TARGET}, timeout=60.0)
        activated = _payload(reply)
        assert activated.get("success") is True, activated
        assert activated["apply"].get("success") is True, activated
        assert _TARGET_PROCESS in _process_names(drv)
    finally:
        harness.stop()

    assert yaml.safe_load(manifest.read_text(encoding="utf-8"))["pipeline"] == f"recipes/{_TARGET}.yaml"
    assert hashlib.sha256(real_manifest.read_bytes()).hexdigest() == real_sha, "боевой app.yaml изменён"

    harness = BackendHarness(port=_PORT, launcher_factory=lambda: manifest_launcher(manifest))
    drv = harness.start()
    try:
        listed = _payload(drv.send_command("ProcessManager", "recipe.list", {}, timeout=8.0))
        assert listed["active"] == _TARGET, listed
        assert _TARGET_PROCESS in _process_names(drv), "после рестарта поднят не активированный рецепт"
    finally:
        harness.stop()
