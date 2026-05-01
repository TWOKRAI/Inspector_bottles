"""TopologyManager — универсальный менеджер динамической топологии процессов.

Композиционный компонент для ProcessManagerProcess.
Работает с dict'ами (Dict at Boundary) — конкретные схемы (SourceTopology и т.п.)
определяются в приложении и передаются через callback'и.

Основные операции:
  apply(topology_dict)  — применить новую топологию (diff → execute commands)
  get()                 — получить текущую topology как dict
  diff(topology_dict)   — dry-run: вычислить diff без применения

TopologyManager НЕ знает про конкретные типы процессов (камеры, процессоры).
Он оперирует абстрактными «командами»: process.create, process.stop, register_update.
Функции diff и конвертации предоставляются приложением.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# Тип callback'ов
DiffFn = Callable[[Optional[Dict], Dict], Dict]
"""(current_topology_dict, desired_topology_dict) -> diff_dict"""

CommandsFn = Callable[[Dict, Dict], List[Dict]]
"""(diff_dict, desired_topology_dict) -> [command_dict, ...]"""


class TopologyManager:
    """Менеджер динамической топологии процессов.

    Не наследуется от BaseManager — лёгкий компонент без lifecycle.
    Получает callback'и для операций от ProcessManagerProcess.

    Args:
        create_process_fn: (process_name, class_path, config, priority) -> dict
        stop_process_fn: (process_name) -> bool
        allocate_shm_fn: (process_name, memory_names, coll) -> None
        diff_fn: вычислить diff между двумя topology dict'ами
        commands_fn: сгенерировать команды из diff
    """

    def __init__(
        self,
        *,
        create_process_fn: Callable[..., Any],
        stop_process_fn: Callable[[str], bool],
        allocate_shm_fn: Callable[[str, dict, int], None] | None = None,
        diff_fn: DiffFn | None = None,
        commands_fn: CommandsFn | None = None,
        logger: Any = None,
    ) -> None:
        self._create_process = create_process_fn
        self._stop_process = stop_process_fn
        self._allocate_shm = allocate_shm_fn
        self._diff_fn = diff_fn
        self._commands_fn = commands_fn
        self._current_topology: dict | None = None
        self._log = logger

    @property
    def current_topology(self) -> dict | None:
        return self._current_topology

    def configure(
        self,
        *,
        diff_fn: DiffFn | None = None,
        commands_fn: CommandsFn | None = None,
    ) -> None:
        """Настроить callback'и (может вызываться после создания)."""
        if diff_fn is not None:
            self._diff_fn = diff_fn
        if commands_fn is not None:
            self._commands_fn = commands_fn

    # -------------------------------------------------------------------------
    # Публичный API
    # -------------------------------------------------------------------------

    def apply(self, topology_dict: dict) -> dict:
        """Применить новую топологию. Возвращает результат."""
        if self._diff_fn is None or self._commands_fn is None:
            return {"success": False, "error": "diff_fn/commands_fn not configured"}

        try:
            diff = self._diff_fn(self._current_topology, topology_dict)

            has_changes = diff.get("has_changes", True)
            if not has_changes:
                return {"success": True, "applied": 0, "message": "No changes"}

            commands = self._commands_fn(diff, topology_dict)
            results = []

            for cmd in commands:
                result = self._execute_command(cmd)
                results.append(result)

            self._current_topology = topology_dict

            if self._log is not None:
                self._log._log_info(f"Topology applied: {len(commands)} commands")
            return {
                "success": True,
                "applied": len(commands),
                "diff": diff,
                "results": results,
            }
        except Exception as e:
            if self._log is not None:
                self._log._log_error(f"Topology apply error: {e}")
            return {"success": False, "error": str(e)}

    def get(self) -> dict:
        """Получить текущую topology."""
        return {"success": True, "topology": self._current_topology}

    def diff(self, topology_dict: dict) -> dict:
        """Dry-run: вычислить diff без применения."""
        if self._diff_fn is None or self._commands_fn is None:
            return {"success": False, "error": "diff_fn/commands_fn not configured"}

        try:
            diff = self._diff_fn(self._current_topology, topology_dict)
            commands = self._commands_fn(diff, topology_dict)
            return {
                "success": True,
                "has_changes": diff.get("has_changes", bool(commands)),
                "diff": diff,
                "commands_count": len(commands),
                "commands": [
                    {"cmd": c.get("cmd", ""), "process_name": c.get("process_name", "")}
                    for c in commands
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Исполнение команд
    # -------------------------------------------------------------------------

    def _execute_command(self, cmd: dict) -> dict:
        """Выполнить одну команду."""
        cmd_type = cmd.get("cmd", "")
        process_name = cmd.get("process_name", "")

        try:
            if cmd_type == "process.stop":
                success = self._stop_process(process_name)
                return {"cmd": cmd_type, "process_name": process_name, "success": success}

            elif cmd_type == "process.create":
                proc_dict = cmd.get("proc_dict", {})
                memory = proc_dict.get("memory")

                # SHM allocation
                if memory and self._allocate_shm:
                    try:
                        mem_names = {k: v for k, v in memory.items() if k != "coll"}
                        coll = memory.get("coll", 2)
                        if mem_names:
                            self._allocate_shm(process_name, mem_names, coll)
                            if self._log is not None:
                                self._log._log_info(f"SHM allocated for {process_name}: {list(mem_names.keys())} (coll={coll})")
                    except Exception as e:
                        if self._log is not None:
                            self._log._log_warning(f"SHM allocation failed for {process_name}: {e}")

                result = self._create_process(
                    process_name=process_name,
                    class_path=proc_dict.get("class", ""),
                    config=proc_dict.get("config"),
                    priority=proc_dict.get("priority", "normal"),
                )
                return {"cmd": cmd_type, "process_name": process_name, "result": result}

            elif cmd_type == "register_update":
                return {
                    "cmd": cmd_type,
                    "process_name": process_name,
                    "success": True,
                    "note": "dispatched via RegistersManager",
                }

            else:
                return {"cmd": cmd_type, "success": False, "error": f"Unknown: {cmd_type}"}

        except Exception as e:
            if self._log is not None:
                self._log._log_error(f"Topology command error: {cmd}: {e}")
            return {
                "cmd": cmd_type,
                "process_name": process_name,
                "success": False,
                "error": str(e),
            }
