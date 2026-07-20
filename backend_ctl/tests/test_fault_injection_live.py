# -*- coding: utf-8 -*-
"""Live-тест Ф3.7 fault-injection (acceptance): смерть source → авто-рестарт → жив снова.

Доказывает механизм супервизии Ф3.6 на живой системе:
  1. boot рецепта, где у source-процесса ``camera_0`` включена per-process
     RestartPolicy(enabled=True, max_retries=3, window_sec=60) — глобальная
     политика при этом остаётся выключенной (дефолт);
  2. baseline: ``camera_0`` жив, ``introspect.status`` отдаёт pid_1, status running;
  3. ``harness.kill_child("camera_0")`` — настоящий SIGKILL (crash, exitcode != 0),
     НЕ graceful process.stop (иначе авто-рестарт не триггерится);
  4. монитор ловит смерть по ``is_alive()`` за ≤ poll 0.5с (не ждёт heartbeat_timeout
     15с), планирует рестарт после backoff 2с, диспатчит IPC ``process.restart`` в PM;
  5. **процесс снова жив с НОВЫМ pid** (pid_2 != pid_1) и status running — прямое
     доказательство «смерть → авто-рестарт», а не выживание старого процесса.

Дедлайн ожидания рестарта ~25с (poll 0.5 + backoff 2 + ready + refresh с запасом).

Собственный порт 8783 (изоляция от общих фикстур и занятых 8766/8767/8778/8779 —
ловушка «двух бэкендов»: общий PID-реестр/SHM конфликтуют между системами).
BackendHarness грузит топологию ФАЙЛОМ (temp-рецепт), app.yaml не трогается.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest
import yaml

from backend_ctl.harness import BackendHarness

_SOURCE = "camera_0"  # source-плагин capture; non-protected → авто-рестарт применим
_PORT = 8783


def _status_pid(drv, name: str) -> tuple[int | None, str | None]:
    """(pid, status) из introspect.status процесса; (None, None) при недоступности."""
    try:
        res = drv.introspect_status(name, timeout=5.0)
    except Exception:  # noqa: BLE001 — процесс может быть мёртв/пересоздаётся
        return None, None
    node = res
    for _ in range(4):
        if isinstance(node, dict) and "pid" in node:
            return node.get("pid"), node.get("status")
        node = node.get("result") if isinstance(node, dict) else None
    return None, None


def _make_recipe_with_restart_policy() -> Path:
    """Temp-рецепт region_pipeline с per-process RestartPolicy(enabled) на camera_0.

    Глобальная политика PM НЕ трогается (остаётся выключенной) — доказываем, что
    именно per-process флаг включает авто-рестарт source-процесса.
    """
    from multiprocess_prototype.backend.launch import load_topology_dict
    from multiprocess_prototype.main import DEFAULT_BLUEPRINT

    bp = load_topology_dict(DEFAULT_BLUEPRINT)
    for proc in bp.get("processes", []):
        if isinstance(proc, dict) and proc.get("process_name") == _SOURCE:
            proc["restart_policy"] = {"enabled": True, "max_retries": 3, "window_sec": 60}
            break
    else:
        raise AssertionError(f"источник '{_SOURCE}' не найден в {DEFAULT_BLUEPRINT}")

    tmp = Path(tempfile.gettempdir()) / f"fault_injection_recipe_{_PORT}.yaml"
    tmp.write_text(yaml.safe_dump(bp, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return tmp


@pytest.fixture(scope="module")
def fault_backend():
    """Свой headless-бэкенд с per-process restart_policy на camera_0."""
    recipe = _make_recipe_with_restart_policy()
    harness = BackendHarness(recipe=recipe, port=_PORT)
    drv = harness.start()
    try:
        yield harness, drv
    finally:
        harness.stop()
        recipe.unlink(missing_ok=True)


@pytest.mark.harness_smoke
def test_source_death_triggers_auto_restart(fault_backend) -> None:
    """SIGKILL source → монитор авто-рестартит → процесс жив снова с новым pid."""
    harness, drv = fault_backend

    # Baseline: source жив, известен pid_1.
    pid_1, status_1 = _status_pid(drv, _SOURCE)
    assert isinstance(pid_1, int) and pid_1 > 0, f"baseline pid '{_SOURCE}' не получен: {pid_1}/{status_1}"

    # Fault: настоящий SIGKILL (crash), а не graceful stop.
    killed_pid = harness.kill_child(_SOURCE)
    assert killed_pid == pid_1, f"убит не тот pid: {killed_pid} != {pid_1}"

    # Дождаться авто-рестарта: source снова жив с НОВЫМ pid (poll 0.5 + backoff 2 + ready).
    deadline = time.time() + 25.0
    pid_2, status_2 = None, None
    while time.time() < deadline:
        pid_2, status_2 = _status_pid(drv, _SOURCE)
        if isinstance(pid_2, int) and pid_2 > 0 and pid_2 != pid_1:
            break
        time.sleep(1.0)

    assert isinstance(pid_2, int) and pid_2 > 0, (
        f"source '{_SOURCE}' не воскрес после SIGKILL за 25с (авто-рестарт не сработал): pid={pid_2}, status={status_2}"
    )
    assert pid_2 != pid_1, (
        f"pid не изменился ({pid_1}) — процесс не был пересоздан монитором (смерть → авто-рестарт не доказана)"
    )
