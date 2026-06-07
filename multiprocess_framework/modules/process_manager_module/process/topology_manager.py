"""TopologyManager — универсальный менеджер динамической топологии процессов.

Композиционный компонент для ProcessManagerProcess.
Работает с dict'ами (Dict at Boundary) — конкретные схемы (SourceTopology и т.п.)
определяются в приложении и передаются через callback'и (сиды).

Наследуется от ``BaseManager + ObservableMixin`` — единый паттерн для всех
компонентов системы (решение владельца 2026-06-07). Observability (логи,
метрики, ошибки) инъецируется через конструктор; если менеджеры не переданы —
вызовы тихо no-op (гарантия ObservableMixin).

Основные операции:
  apply(topology_dict)  — применить новую топологию (diff → execute commands)
  get()                 — получить текущую topology как dict
  diff(topology_dict)   — dry-run: вычислить diff без применения

6 типов команд:
  process.stop_all   — остановить несколько процессов ПАРАЛЛЕЛЬНО (bulk)
  process.stop       — остановить один процесс (halt, back-compat)
  process.cleanup    — снять с реестра + освободить SHM + удалить конфиг (free)
  process.provision  — зарегистрировать очереди + аллоцировать SHM (provision)
  process.create     — создать экземпляр БЕЗ старта (instantiate)
  process.start      — запустить процесс (run)

TopologyManager НЕ знает про конкретные типы процессов (камеры, процессоры).
Он оперирует абстрактными командами через сиды. Функции diff, генерации команд
и каждого сида предоставляются приложением/PM.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from ...base_manager import BaseManager, ObservableMixin

# Тип callback'ов
DiffFn = Callable[[Optional[Dict], Dict], Dict]
"""(current_topology_dict, desired_topology_dict) -> diff_dict"""

CommandsFn = Callable[[Dict, Dict], List[Dict]]
"""(diff_dict, desired_topology_dict) -> [command_dict, ...]"""


class TopologyManager(BaseManager, ObservableMixin):
    """Менеджер динамической топологии процессов.

    Наследуется от BaseManager + ObservableMixin (паттерн как ProcessModule).
    Получает callback'и (сиды) для операций от ProcessManagerProcess.

    Args:
        create_process_fn: (name, proc_dict) -> bool — создать экземпляр БЕЗ старта.
        stop_process_fn: (name) -> bool — остановить процесс.
        stop_all_process_fn: (names: list[str]) -> bool — остановить несколько
            процессов ПАРАЛЛЕЛЬНО (bulk). Паритет stop_many дороги B: один
            общий таймаут на все, а не N×timeout последовательно.
        cleanup_process_fn: (name) -> bool — снять с реестра + освободить SHM + конфиг.
        provision_process_fn: (name, proc_dict) -> bool — очереди + SHM.
        start_process_fn: (name) -> bool — запустить процесс.
        allocate_shm_fn: DEPRECATED — SHM теперь в provision. Сохранён для back-compat.
        diff_fn: вычислить diff между двумя topology dict'ами.
        commands_fn: сгенерировать команды из diff.
        manager_name: имя менеджера (дефолт "topology").
        logger: менеджер логирования (ObservableMixin).
        error: менеджер ошибок (ObservableMixin).
        stats: менеджер статистики (ObservableMixin).
    """

    def __init__(
        self,
        *,
        create_process_fn: Callable[..., Any] | None = None,
        stop_process_fn: Callable[[str], bool] | None = None,
        stop_all_process_fn: Callable[[list[str]], bool] | None = None,
        cleanup_process_fn: Callable[[str], bool] | None = None,
        provision_process_fn: Callable[..., bool] | None = None,
        start_process_fn: Callable[[str], bool] | None = None,
        allocate_shm_fn: Callable[[str, dict, int], None] | None = None,
        diff_fn: DiffFn | None = None,
        commands_fn: CommandsFn | None = None,
        manager_name: str = "topology",
        logger: Any = None,
        error: Any = None,
        stats: Any = None,
    ) -> None:
        BaseManager.__init__(self, manager_name)
        ObservableMixin.__init__(
            self,
            managers={"logger": logger, "error": error, "stats": stats},
        )
        self._create_process = create_process_fn
        self._stop_process = stop_process_fn
        self._stop_all_process = stop_all_process_fn
        self._cleanup_process = cleanup_process_fn
        self._provision_process = provision_process_fn
        self._start_process = start_process_fn
        self._allocate_shm = allocate_shm_fn  # deprecated, back-compat
        self._diff_fn = diff_fn
        self._commands_fn = commands_fn
        self._current_topology: dict | None = None

    # -------------------------------------------------------------------------
    # Lifecycle (BaseManager контракт)
    # -------------------------------------------------------------------------

    def initialize(self) -> bool:
        """Инициализация — тривиальная (менеджер конфигурируется через сиды)."""
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        """Завершение — сбросить состояние."""
        self._current_topology = None
        self.is_initialized = False
        return True

    # -------------------------------------------------------------------------
    # Конфигурация сидов
    # -------------------------------------------------------------------------

    @property
    def current_topology(self) -> dict | None:
        return self._current_topology

    def configure(
        self,
        *,
        diff_fn: DiffFn | None = None,
        commands_fn: CommandsFn | None = None,
        create_process_fn: Callable[..., Any] | None = None,
        stop_process_fn: Callable[[str], bool] | None = None,
        stop_all_process_fn: Callable[[list[str]], bool] | None = None,
        cleanup_process_fn: Callable[[str], bool] | None = None,
        provision_process_fn: Callable[..., bool] | None = None,
        start_process_fn: Callable[[str], bool] | None = None,
    ) -> None:
        """Настроить callback'и (может вызываться после создания)."""
        if diff_fn is not None:
            self._diff_fn = diff_fn
        if commands_fn is not None:
            self._commands_fn = commands_fn
        if create_process_fn is not None:
            self._create_process = create_process_fn
        if stop_process_fn is not None:
            self._stop_process = stop_process_fn
        if stop_all_process_fn is not None:
            self._stop_all_process = stop_all_process_fn
        if cleanup_process_fn is not None:
            self._cleanup_process = cleanup_process_fn
        if provision_process_fn is not None:
            self._provision_process = provision_process_fn
        if start_process_fn is not None:
            self._start_process = start_process_fn

    # -------------------------------------------------------------------------
    # Публичный API
    # -------------------------------------------------------------------------

    def apply(self, topology_dict: dict) -> dict:
        """Применить новую топологию. Возвращает результат.

        При полном успехе коммитит ``_current_topology = topology_dict``.
        При ЛЮБОМ неуспехе (exception в сиде ИЛИ soft-fail ``success: False``)
        НЕ коммитит — ``_current_topology`` остаётся прежней.

        Returns:
            dict с ключами ``success``, ``applied``, ``diff``, ``results``.
            При неуспехе — ``success: False``, ``failed_at``, ``results``.
        """
        if self._diff_fn is None or self._commands_fn is None:
            return {"success": False, "error": "diff_fn/commands_fn not configured"}

        t_start = time.perf_counter()

        try:
            diff = self._diff_fn(self._current_topology, topology_dict)

            has_changes = diff.get("has_changes", True)
            if not has_changes:
                return {"success": True, "applied": 0, "message": "No changes"}

            commands = self._commands_fn(diff, topology_dict)
            self._log_info(
                f"Топология: применение {len(commands)} команд (текущая={'есть' if self._current_topology else 'нет'})"
            )

            results: list[dict] = []
            for idx, cmd in enumerate(commands):
                result = self._execute_command(cmd)
                results.append(result)

                # Проверить soft-fail: сид вернул success=False без exception
                if not result.get("success", True):
                    elapsed_ms = (time.perf_counter() - t_start) * 1000
                    self._log_error(
                        f"Топология: команда #{idx} ({cmd.get('cmd', '?')}) завершилась неуспешно: {result}"
                    )
                    self._record_timing("topology.apply_ms", elapsed_ms)
                    return {
                        "success": False,
                        "results": results,
                        "failed_at": idx,
                    }

            # Все команды успешны — коммитим топологию
            self._current_topology = topology_dict

            elapsed_ms = (time.perf_counter() - t_start) * 1000
            self._log_info(f"Топология применена: {len(commands)} команд за {elapsed_ms:.1f}ms")
            self._record_metric("topology.commands", len(commands))
            self._record_timing("topology.apply_ms", elapsed_ms)

            return {
                "success": True,
                "applied": len(commands),
                "diff": diff,
                "results": results,
            }
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            self._log_error(f"Топология: ошибка apply: {e}")
            self._track_error(e, {"phase": "topology.apply"})
            self._record_timing("topology.apply_ms", elapsed_ms)
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
                    {
                        "cmd": c.get("cmd", ""),
                        "process_name": c.get("process_name", ""),
                    }
                    for c in commands
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Исполнение команд — 5 типов + back-compat register_update
    # -------------------------------------------------------------------------

    def _execute_command(self, cmd: dict) -> dict:
        """Выполнить одну команду. Возвращает ``{cmd, ..., success}``.

        Поддерживает 6 типов:
        - ``process.stop_all`` → ``stop_all_process_fn(names)`` — bulk-параллельная
          остановка (паритет stop_many дороги B: один общий таймаут, а не N×timeout).
        - ``process.stop`` → ``stop_process_fn(name)`` — single (back-compat).
        - ``process.cleanup`` → ``cleanup_process_fn(name)``
        - ``process.provision`` → ``provision_process_fn(name, proc_dict)``
        - ``process.create`` → ``create_process_fn(name, proc_dict)``
        - ``process.start`` → ``start_process_fn(name)``

        Back-compat:
        - ``register_update`` → ``success: True`` (не падает).
        """
        cmd_type = cmd.get("cmd", "")
        process_name = cmd.get("process_name", "")

        try:
            if cmd_type == "process.stop_all":
                if self._stop_all_process is None:
                    return {
                        "cmd": cmd_type,
                        "success": False,
                        "error": "stop_all_process_fn not configured",
                    }
                names = cmd.get("process_names", [])
                success = self._stop_all_process(names)
                return {
                    "cmd": cmd_type,
                    "process_names": names,
                    "success": bool(success),
                }

            elif cmd_type == "process.stop":
                if self._stop_process is None:
                    return {
                        "cmd": cmd_type,
                        "process_name": process_name,
                        "success": False,
                        "error": "stop_process_fn not configured",
                    }
                success = self._stop_process(process_name)
                return {
                    "cmd": cmd_type,
                    "process_name": process_name,
                    "success": bool(success),
                }

            elif cmd_type == "process.cleanup":
                if self._cleanup_process is None:
                    return {
                        "cmd": cmd_type,
                        "process_name": process_name,
                        "success": False,
                        "error": "cleanup_process_fn not configured",
                    }
                success = self._cleanup_process(process_name)
                return {
                    "cmd": cmd_type,
                    "process_name": process_name,
                    "success": bool(success),
                }

            elif cmd_type == "process.provision":
                if self._provision_process is None:
                    return {
                        "cmd": cmd_type,
                        "process_name": process_name,
                        "success": False,
                        "error": "provision_process_fn not configured",
                    }
                proc_dict = cmd.get("proc_dict", {})
                success = self._provision_process(process_name, proc_dict)
                return {
                    "cmd": cmd_type,
                    "process_name": process_name,
                    "success": bool(success),
                }

            elif cmd_type == "process.create":
                if self._create_process is None:
                    return {
                        "cmd": cmd_type,
                        "process_name": process_name,
                        "success": False,
                        "error": "create_process_fn not configured",
                    }
                proc_dict = cmd.get("proc_dict", {})
                success = self._create_process(process_name, proc_dict)
                return {
                    "cmd": cmd_type,
                    "process_name": process_name,
                    "success": bool(success),
                }

            elif cmd_type == "process.start":
                if self._start_process is None:
                    return {
                        "cmd": cmd_type,
                        "process_name": process_name,
                        "success": False,
                        "error": "start_process_fn not configured",
                    }
                success = self._start_process(process_name)
                return {
                    "cmd": cmd_type,
                    "process_name": process_name,
                    "success": bool(success),
                }

            elif cmd_type == "register_update":
                # Back-compat: старая команда, не падаем
                return {
                    "cmd": cmd_type,
                    "process_name": process_name,
                    "success": True,
                    "note": "dispatched via RegistersManager",
                }

            else:
                return {
                    "cmd": cmd_type,
                    "success": False,
                    "error": f"Unknown: {cmd_type}",
                }

        except Exception as e:
            self._log_error(f"Топология: ошибка команды {cmd}: {e}")
            self._track_error(e, {"phase": "execute_command", "cmd": cmd_type})
            return {
                "cmd": cmd_type,
                "process_name": process_name,
                "success": False,
                "error": str(e),
            }
