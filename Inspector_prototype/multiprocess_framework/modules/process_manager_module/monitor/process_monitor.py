"""Мониторинг состояний процессов. Реестр: get_all_process_data() → ProcessData."""
import time
from typing import Any, Dict, Optional
from multiprocessing import Event
from ...worker_module import ThreadConfig, ThreadPriority


_CUSTOM_EXCLUDE_KEYS = frozenset({
    "stop_event", "pause_event", "error_manager",
})


def _state_snapshot_from_process_data(process_data: Any) -> Optional[Dict[str, Any]]:
    if not process_data:
        return None
    status = getattr(process_data, "status", None)
    status_str = status.value if status is not None and hasattr(status, "value") else (
        str(status) if status is not None else "unknown"
    )
    meta = getattr(process_data, "metadata", None) or {}
    cust = getattr(process_data, "custom", None) or {}
    safe_custom = {
        k: v for k, v in (dict(cust) if isinstance(cust, dict) else {}).items()
        if k not in _CUSTOM_EXCLUDE_KEYS
    }
    return {
        "status": status_str,
        "metadata": dict(meta) if isinstance(meta, dict) else {},
        "custom": safe_custom,
    }


class ProcessMonitor:
    def __init__(self, process_manager_process, poll_interval: float = 0.5):
        self.process = process_manager_process
        self.poll_interval = poll_interval
        self.previous_states: Dict[str, Dict[str, Any]] = {}
        self._monitoring = False

    def start(self):
        if self._monitoring:
            self.process._log_warning("Monitor already running")
            return
        self.process._log_info("Starting process state monitor")
        self.process.worker_manager.create_worker(
            "state_monitor",
            self._monitoring_loop,
            ThreadConfig(priority=ThreadPriority.NORMAL),
            auto_start=True,
        )
        self._monitoring = True

    def stop(self):
        if not self._monitoring:
            return
        self.process._log_info("Stopping process state monitor")
        self._monitoring = False

    def _monitoring_loop(self, stop_event: Event, pause_event: Event):
        self.process._log_info("Process monitor loop started")
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            try:
                if not self.process.shared_resources:
                    time.sleep(self.poll_interval)
                    continue
                reg = self.process.shared_resources.process_state_registry
                if not reg:
                    time.sleep(self.poll_interval)
                    continue
                all_processes = reg.get_all_process_data()
                all_states: Dict[str, Dict[str, Any]] = {}
                for name, pd in all_processes.items():
                    snap = _state_snapshot_from_process_data(pd)
                    if snap is not None:
                        all_states[name] = snap
                for pname, cur in all_states.items():
                    prev = self.previous_states.get(pname)
                    if prev != cur:
                        self._handle_state_change(pname, prev, cur)
                        self.previous_states[pname] = cur.copy()
                cur_names = set(all_states.keys())
                for pname in set(self.previous_states.keys()) - cur_names:
                    self.process._log_info(f"Process removed: {pname}")
                    self.previous_states.pop(pname, None)
                self._check_heartbeats()
                time.sleep(self.poll_interval)
            except Exception as e:
                self.process._log_error(f"Error in monitoring loop: {e}")
                time.sleep(self.poll_interval)
        self.process._log_info("Process monitor loop stopped")

    def _check_heartbeats(self) -> None:
        """Liveness: неживой OS-процесс без актуального state → stopped/crashed."""
        if not hasattr(self.process, "_process_registry"):
            return
        for proc in self.process._process_registry.os_processes:
            if proc.is_alive():
                continue
            exitcode = proc.exitcode
            prev = self.previous_states.get(proc.name)
            prev_status = (prev or {}).get("status", "unknown")
            if prev_status in ("stopped", "error", "crashed"):
                continue
            new_status = "stopped" if exitcode == 0 else "crashed"
            if new_status == "crashed":
                self.process._log_warning(
                    f"Process '{proc.name}' crashed (exitcode={exitcode})"
                )
            snap = {
                "status": new_status,
                "exitcode": exitcode,
                "metadata": {},
                "custom": {},
            }
            self._handle_state_change(proc.name, prev, snap)
            self.previous_states[proc.name] = snap.copy()
            if self.process.shared_resources:
                try:
                    psr = self.process.shared_resources.process_state_registry
                    if psr is not None and hasattr(psr, "update_state"):
                        psr.update_state(proc.name, status=new_status)
                except Exception:
                    pass

    def _handle_state_change(
        self,
        process_name: str,
        previous_state: Optional[Dict[str, Any]],
        current_state: Dict[str, Any],
    ):
        cur_s = current_state.get("status", "unknown")
        prev_s = previous_state.get("status", "unknown") if previous_state else None
        if prev_s != cur_s:
            self.process._log_info(
                f"Process '{process_name}' status changed: {prev_s} -> {cur_s}"
            )
            self._broadcast_status_change(process_name, prev_s, cur_s, current_state)

    def _broadcast_status_change(
        self,
        process_name: str,
        old_status: Optional[str],
        new_status: str,
        current_state: Dict[str, Any],
    ):
        try:
            if not self.process.router_manager:
                return
            msg = {
                "type": "system",
                "subtype": "process_status_changed",
                "sender": self.process.name,
                "process_name": process_name,
                "old_status": old_status,
                "new_status": new_status,
                "state": current_state,
                "timestamp": time.time(),
            }
            sent = self.process.communication.broadcast(msg, exclude_self=True)
            if sent > 0:
                self.process._log_debug(
                    f"Broadcasted status change for '{process_name}' to {sent} processes"
                )
            else:
                self.process._log_warning(
                    f"No processes received status change for '{process_name}'"
                )
        except Exception as e:
            self.process._log_error(f"Failed to broadcast status change: {e}")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "monitoring": self._monitoring,
            "tracked_processes": len(self.previous_states),
            "poll_interval": self.poll_interval,
            "crashed_processes": [
                n
                for n, st in self.previous_states.items()
                if st.get("status") == "crashed"
            ],
        }
