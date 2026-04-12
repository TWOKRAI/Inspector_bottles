"""
SystemCommandHandler — базовые системные команды God Mode.

Предоставляет: help, status, ps, stats.
Не зависит от registers_module.
Все методы работают без crash при отсутствии менеджеров.
"""
import os
from typing import Any, Dict, List, Optional


class SystemCommandHandler:
    """Обработчик системных консольных команд.

    Используется в God Mode для диагностики состояния процесса.
    Все методы возвращают str — готовый текст для вывода в консоль.

    Args:
        process_info: Объект или dict с полями name/pid/managers.
                      Может быть None — методы вернут fallback-текст.
    """

    # Описания встроенных команд этого обработчика
    _BUILTIN_DESCRIPTIONS: Dict[str, str] = {
        "help":   "Show available commands and descriptions",
        "status": "Show current process state (name, pid, managers)",
        "ps":     "List child processes (if process_manager available)",
        "stats":  "Show aggregated metrics (if stats_manager available)",
    }

    def __init__(self, process_info: Optional[Any] = None) -> None:
        self._process_info = process_info

    # =========================================================================
    # help
    # =========================================================================

    def help(self, command_registry: Optional[Dict[str, str]] = None) -> str:
        """Вывести список доступных команд с описаниями.

        Args:
            command_registry: dict {command_name: description}.
                              Если передан — показывает все команды из него.
                              Иначе — показывает только встроенные команды.

        Returns:
            Отформатированная строка со списком команд.
        """
        lines: List[str] = ["Available commands:"]
        lines.append("-" * 40)

        if command_registry:
            # Показываем все команды из реестра; встроенные тоже должны там быть
            for name in sorted(command_registry):
                description = command_registry[name] or ""
                lines.append(f"  {name:<20} {description}")
        else:
            # Fallback: только встроенные
            for name, description in sorted(self._BUILTIN_DESCRIPTIONS.items()):
                lines.append(f"  {name:<20} {description}")

        lines.append("-" * 40)
        lines.append(f"Total: {len(command_registry) if command_registry else len(self._BUILTIN_DESCRIPTIONS)} command(s)")
        return "\n".join(lines)

    # =========================================================================
    # status
    # =========================================================================

    def status(self, process: Optional[Any] = None) -> str:
        """Вывести состояние текущего процесса.

        Использует переданный `process` (приоритет) или self._process_info.
        Поддерживает объекты с атрибутами и dict.

        Args:
            process: Объект или dict с полями name/pid/managers.

        Returns:
            Отформатированная строка со статусом процесса.
        """
        target = process or self._process_info

        lines: List[str] = ["Process status:"]
        lines.append("-" * 40)

        if target is None:
            lines.append("  name:     unknown")
            lines.append(f"  pid:      {os.getpid()}")
            lines.append("  managers: (no process info)")
        else:
            name = _get_attr(target, "name", "unknown")
            pid = _get_attr(target, "pid", None) or os.getpid()
            managers = _get_attr(target, "managers", None)

            lines.append(f"  name:     {name}")
            lines.append(f"  pid:      {pid}")

            if managers is not None:
                if isinstance(managers, dict):
                    mgr_names = sorted(managers.keys())
                elif hasattr(managers, "keys"):
                    mgr_names = sorted(managers.keys())
                elif isinstance(managers, (list, tuple)):
                    mgr_names = sorted(str(m) for m in managers)
                else:
                    mgr_names = [str(managers)]
                lines.append(f"  managers: {', '.join(mgr_names) if mgr_names else '(none)'}")
            else:
                # Попробуем найти менеджеры как атрибуты объекта
                known_managers = [
                    "logger_manager", "command_manager", "router_manager",
                    "stats_manager", "console_manager", "error_manager",
                ]
                found = [m for m in known_managers if getattr(target, m, None) is not None]
                if found:
                    lines.append(f"  managers: {', '.join(found)}")
                else:
                    lines.append("  managers: (unknown)")

        lines.append("-" * 40)
        return "\n".join(lines)

    # =========================================================================
    # ps
    # =========================================================================

    def ps(self, process_manager: Optional[Any] = None) -> str:
        """Вывести список дочерних процессов.

        Args:
            process_manager: Объект с методом get_processes() / list_processes()
                             или атрибутом processes. Если None — сообщение
                             «not available».

        Returns:
            Отформатированная строка со списком процессов.
        """
        if process_manager is None:
            return "ps: not available (no process_manager)"

        processes = _extract_processes(process_manager)

        if processes is None:
            return "ps: not available (process_manager has no process list)"

        lines: List[str] = ["Child processes:"]
        lines.append("-" * 40)

        if not processes:
            lines.append("  (no child processes)")
        else:
            for i, proc in enumerate(processes, start=1):
                if isinstance(proc, dict):
                    name = proc.get("name", f"process-{i}")
                    pid = proc.get("pid", "?")
                    state = proc.get("state", proc.get("status", "?"))
                    lines.append(f"  [{i}] {name:<24} pid={pid}  state={state}")
                elif hasattr(proc, "name"):
                    name = getattr(proc, "name", f"process-{i}")
                    pid = getattr(proc, "pid", "?")
                    state = getattr(proc, "state", getattr(proc, "status", "?"))
                    lines.append(f"  [{i}] {name:<24} pid={pid}  state={state}")
                else:
                    lines.append(f"  [{i}] {proc}")

        lines.append("-" * 40)
        lines.append(f"Total: {len(processes)} process(es)")
        return "\n".join(lines)

    # =========================================================================
    # stats
    # =========================================================================

    def stats(self, stats_manager: Optional[Any] = None) -> str:
        """Вывести агрегированную статистику.

        Args:
            stats_manager: Объект с методом get_all_metrics() и/или get_stats().
                           Если None — «no stats available».

        Returns:
            Отформатированная строка с метриками.
        """
        if stats_manager is None:
            return "stats: no stats available (no stats_manager)"

        lines: List[str] = ["Statistics:"]
        lines.append("-" * 40)

        # Попробуем get_all_metrics()
        metrics: Optional[Dict[str, Any]] = None
        if hasattr(stats_manager, "get_all_metrics"):
            try:
                metrics = stats_manager.get_all_metrics()
            except Exception:
                metrics = None

        if metrics is not None:
            if not metrics:
                lines.append("  (no metrics recorded)")
            else:
                for key, record in sorted(metrics.items()):
                    if isinstance(record, dict):
                        mtype = record.get("type", record.get("metric_type", "?"))
                        value = _format_metric_value(record)
                        lines.append(f"  {key:<30} [{mtype}] {value}")
                    else:
                        lines.append(f"  {key:<30} {record}")
        else:
            # Fallback: get_stats()
            if hasattr(stats_manager, "get_stats"):
                try:
                    stat_dict = stats_manager.get_stats()
                    if isinstance(stat_dict, dict):
                        for k, v in sorted(stat_dict.items()):
                            lines.append(f"  {k:<30} {v}")
                    else:
                        lines.append(f"  {stat_dict}")
                except Exception as exc:
                    lines.append(f"  (error reading stats: {exc})")
            else:
                lines.append("  (stats_manager has no get_all_metrics or get_stats)")

        lines.append("-" * 40)
        return "\n".join(lines)


# =============================================================================
# Вспомогательные функции
# =============================================================================

def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    """Получить значение из dict или атрибута объекта."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_processes(process_manager: Any) -> Optional[List[Any]]:
    """Извлечь список процессов из process_manager любым доступным способом."""
    # get_processes() — предпочтительный метод
    if hasattr(process_manager, "get_processes"):
        try:
            result = process_manager.get_processes()
            if isinstance(result, (list, tuple)):
                return list(result)
            if isinstance(result, dict):
                return list(result.values())
        except Exception:
            pass

    # list_processes()
    if hasattr(process_manager, "list_processes"):
        try:
            result = process_manager.list_processes()
            if isinstance(result, (list, tuple)):
                return list(result)
        except Exception:
            pass

    # атрибут processes
    if hasattr(process_manager, "processes"):
        try:
            procs = process_manager.processes
            if isinstance(procs, dict):
                return list(procs.values())
            if isinstance(procs, (list, tuple)):
                return list(procs)
        except Exception:
            pass

    return None


def _format_metric_value(record: Dict[str, Any]) -> str:
    """Форматировать значение метрики для отображения."""
    mtype = record.get("type", record.get("metric_type", ""))

    if mtype in ("counter",):
        total = record.get("total", record.get("count", record.get("value", "?")))
        return f"total={total}"

    if mtype in ("gauge",):
        value = record.get("value", record.get("last_value", "?"))
        return f"value={value}"

    if mtype in ("timing",):
        avg = record.get("avg", record.get("mean", "?"))
        count = record.get("count", "?")
        return f"avg={avg}  count={count}"

    if mtype in ("histogram",):
        count = record.get("count", "?")
        avg = record.get("avg", record.get("mean", "?"))
        return f"count={count}  avg={avg}"

    # Неизвестный тип — показываем все числовые ключи
    numeric = {k: v for k, v in record.items() if isinstance(v, (int, float)) and k != "timestamp"}
    if numeric:
        return "  ".join(f"{k}={v}" for k, v in list(numeric.items())[:4])
    return str(record)
