# multiprocess_prototype_v3/tests/support/harness.py
"""Обёртка над SystemLauncher для интеграционных тестов v3."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union


def ensure_inspector_paths() -> None:
    root = Path(__file__).resolve().parents[3]
    modules = root / "multiprocess_framework" / "modules"
    for p in (root, modules):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


class SystemTestHarness:
    """Старт/stop SystemLauncher в фоне + доступ к SharedResourcesManager."""

    def __init__(self, stop_timeout: float = 10.0) -> None:
        ensure_inspector_paths()
        from multiprocess_framework.modules.process_manager_module import SystemLauncher

        self._stop_timeout = stop_timeout
        self._launcher = SystemLauncher(stop_timeout=stop_timeout)
        self._thread: Optional[threading.Thread] = None

    def add_process(self, name: str, proc_dict: dict) -> None:
        self._launcher.add_process(name, proc_dict)

    def add_from_schema(self, *configs: Any) -> None:
        from multiprocess_framework.modules.data_schema_module import process

        for cfg in configs:
            name, proc_dict = process(cfg)
            self.add_process(name, proc_dict)

    def start_background(self, ready_wait_s: float = 3.0) -> None:
        """launch_orchestrator в daemon-треде (без блокирующего wait)."""
        self._thread = threading.Thread(target=self._launcher.start, daemon=True)
        self._thread.start()
        time.sleep(ready_wait_s)

    def stop(self) -> None:
        self._launcher.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._stop_timeout + 3.0)

    def shared_resources(self) -> Any:
        spawner = getattr(self._launcher, "_spawner", None)
        if not spawner:
            return None
        return spawner.get_shared_resources()

    def send_system_command(
        self,
        process_name: str,
        command: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        sr = self.shared_resources()
        if not sr:
            raise RuntimeError("Shared resources not available")
        pd = sr.get_process_data(process_name)
        if not pd:
            raise RuntimeError(f"No process data for {process_name}")
        q = pd.get_queue("system")
        if not q:
            raise RuntimeError(f"No system queue for {process_name}")
        msg: Dict[str, Any] = {"command": command}
        if data is not None:
            msg["data"] = data
        q.put(msg)


def wait_for_probe_file(
    path: Union[str, Path],
    min_value: int,
    timeout: float,
    poll: float = 0.05,
) -> int:
    """Ждать, пока число в probe-файле consumer не станет >= min_value."""
    p = Path(path)
    deadline = time.monotonic() + timeout
    last = 0
    while time.monotonic() < deadline:
        if p.exists():
            try:
                last = int(p.read_text(encoding="utf-8").strip() or "0")
            except ValueError:
                last = 0
            if last >= min_value:
                return last
        time.sleep(poll)
    raise AssertionError(f"probe {path}: last={last}, expected>={min_value}")


def wait_for_log_substring(
    log_file: Path,
    substring: str,
    timeout: float,
    poll: float = 0.1,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log_file.exists():
            try:
                text = log_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            if substring in text:
                return
        time.sleep(poll)
    raise AssertionError(f"substring not found in {log_file}: {substring!r}")
