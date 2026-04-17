"""RobotSimulatorProcess — rejection robot simulator."""

import datetime
import time

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ThreadConfig, ExecutionMode


class RobotSimulatorProcess(ProcessModule):
    """Robot simulator. Logs rejections to file."""

    def _init_system_threads(self):
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._action_count = 0

    def _init_application_threads(self):
        self._log_info("RobotSimulatorProcess initializing...")
        self._log_file = self.get_config("log_file", "./robot_actions.log")
        self._reject_delay = self.get_config("reject_delay", 0.5)
        self.command_manager.register_command("reject_item", self._cmd_reject)
        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker("robot_worker", self._robot_worker, config, auto_start=True)
        self._log_info(f"RobotSimulatorProcess ready: log_file={self._log_file}")

    def _cmd_reject(self, data):
        frame_id = data.get("frame_id", 0)
        for defect in data.get("defects", []):
            self._action_count += 1
            center = defect.get("center", [0, 0])
            area = defect.get("area", 0)
            self._log_info(f"REJECT #{self._action_count}: frame={frame_id}, pos=({center[0]}, {center[1]}), area={area}")
            ts = datetime.datetime.now().isoformat()
            try:
                with open(self._log_file, "a") as f:
                    f.write(f"{ts} | frame={frame_id} | x={center[0]} y={center[1]} | area={area}\n")
            except Exception as e:
                self._log_error(f"Failed to write robot log: {e}")
        if self._reject_delay > 0:
            time.sleep(self._reject_delay)
        return {"status": "ok", "action_id": self._action_count}

    def _robot_worker(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            msgs = self.receive(timeout=0.1, channel_types=['system'])
            for msg in msgs:
                msg_dict = msg if isinstance(msg, dict) else (msg.to_dict() if hasattr(msg, "to_dict") else None)
                if msg_dict and msg_dict.get("command") and self.command_manager:
                    try:
                        self.command_manager.handle_command(msg_dict)
                    except Exception as e:
                        self._log_error(f"Command '{msg_dict.get('command')}' failed: {e}")
            time.sleep(0.02)

    def shutdown(self) -> bool:
        self._log_info(f"RobotSimulatorProcess shutting down. Total actions: {self._action_count}")
        self.is_initialized = False
        return super().shutdown()
