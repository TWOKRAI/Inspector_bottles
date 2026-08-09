# -*- coding: utf-8 -*-
"""Прогон C2 — куда РЕАЛЬНО попадает строка из трёх «ошибочных» разъёмов плагина.

Стенд НЕ поднимается и порт не занимается: вопрос здесь про маршрут внутри
процесса, и ответ на него — файлы. Поднимаются НАСТОЯЩИЕ `LoggerManager` и
`ErrorManager` (та же сборка, что у `process_managers`), в свежий временный
каталог, каждая дорога зовётся с уникальным маркером, и потом маркеры ищутся
по ВСЕМ файлам обоих плоскостей.

Три дороги, которые в коде плагина выглядят взаимозаменяемо:

    ctx.log_error("...")            — строка
    ctx.health.report_error(exc)    — инцидент
    services._track_error(exc)      — путь фреймворковых менеджеров

Основание — major-1 приёмочного ревью 2026-08-09: «интуитивный путь плагина
(`ctx.log_error`) ведёт в logger-маршрут, а не в ErrorManager; в файлы
critical/errors/warnings ведёт только `ctx.health.report_error`». Вторую
половину этого утверждения проба ПРОВЕРЯЕТ, а не наследует.

Запуск: ``python -m backend_ctl.probes.probe_c2_error_route``
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")


def build_managers(log_dir: Path) -> Dict[str, Any]:
    """Собрать logger+error ровно так, как это делает `process_managers`."""
    from multiprocess_framework.modules.error_module import ErrorManager, ErrorManagerConfig
    from multiprocess_framework.modules.logger_module import LoggerManager, LoggerManagerConfig
    from multiprocess_framework.modules.process_module.configs.managers_config import (
        ManagersConfig,
        managers_from_log_dir,
        managers_payload_for_proc,
    )

    payload = managers_payload_for_proc(managers_from_log_dir(str(log_dir), model_cls=ManagersConfig))

    logger_cfg = dict(payload.get("logger") or {})
    logger_cfg.setdefault("app_name", "probe_c2")
    logger = LoggerManager(
        manager_name="logger_probe_c2",
        config=LoggerManagerConfig.model_validate(logger_cfg),
    )
    logger.initialize()

    error_cfg = ErrorManagerConfig.model_validate(dict(payload.get("error") or {}))
    error_cfg.manager_name = "error_probe_c2"
    error = ErrorManager(manager_name="error_probe_c2", config=error_cfg)
    error.initialize()
    return {"logger": logger, "error": error}


class _Services:
    """Минимальный процесс: имя + пятёрка log_* + слот error, как у реального."""

    def __init__(self, managers: Dict[str, Any]) -> None:
        from multiprocess_framework.modules.base_manager import ObservableMixin

        self.name = "probe_c2"

        class _Host(ObservableMixin):
            def __init__(self, mgrs: Dict[str, Any]) -> None:
                ObservableMixin.__init__(self, managers=mgrs)

        self._host = _Host(managers)

    # Пятёрка фасада — ровно те имена, что штампует PluginContext.
    def log_debug(self, message: str, **kw: Any) -> None:
        self._host._log_debug(message, **kw)

    def log_info(self, message: str, **kw: Any) -> None:
        self._host._log_info(message, **kw)

    def log_warning(self, message: str, **kw: Any) -> None:
        self._host._log_warning(message, **kw)

    def log_error(self, message: str, **kw: Any) -> None:
        self._host._log_error(message, **kw)

    def log_critical(self, message: str, **kw: Any) -> None:
        self._host._log_critical(message, **kw)

    def track_error(self, exc: BaseException, context: Any = None) -> None:
        self._host._track_error(exc, context)


def files_with(root: Path, marker: str) -> List[str]:
    hits = []
    for path in sorted(root.rglob("*.log")):
        try:
            if marker in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(str(path.relative_to(root)).replace("\\", "/"))
        except OSError:
            continue
    return hits


def quote(root: Path, marker: str) -> str:
    for path in sorted(root.rglob("*.log")):
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if marker in line:
                    return f"{path.relative_to(root)}: {line.strip()[:150]}"
        except OSError:
            continue
    return "—"


def main() -> int:
    from multiprocess_framework.modules.process_module.plugins.base import PluginContext

    root = Path(tempfile.mkdtemp(prefix="probe_c2_"))
    print("=" * 78)
    print("Прогон C2 — маршруты «ошибочных» разъёмов плагина")
    print(f"каталог: {root}")
    print("=" * 78, flush=True)

    managers = build_managers(root)
    services = _Services(managers)
    ctx = PluginContext(services=services, plugin_name="probe_plugin")

    ctx.log_error("C2-MARK-LOG-ERROR: строка из ctx.log_error")
    ctx.health.report_error(RuntimeError("C2-MARK-HEALTH: инцидент из ctx.health.report_error"))
    services.track_error(RuntimeError("C2-MARK-TRACK: инцидент из _track_error"))

    for manager in managers.values():
        manager.flush()

    result = 0
    rows = [
        ("ctx.log_error", "C2-MARK-LOG-ERROR"),
        ("ctx.health.report_error", "C2-MARK-HEALTH"),
        ("services.track_error (слот error)", "C2-MARK-TRACK"),
    ]
    report: Dict[str, List[str]] = {}
    for title, marker in rows:
        hits = files_with(root, marker)
        report[title] = hits
        print(f"\n--- {title}")
        print(f"    попало в: {hits or 'НИКУДА'}")
        print(f"    цитата  : {quote(root, marker)}", flush=True)

    print("\n" + "=" * 78)
    error_plane = {"errors.log", "critical.log", "warnings.log"}

    def touches_error_plane(hits: List[str]) -> bool:
        return any(Path(h).name in error_plane for h in hits)

    print(f"ctx.log_error задевает плоскость ошибок: {touches_error_plane(report['ctx.log_error'])}")
    print(
        f"ctx.health.report_error задевает плоскость ошибок: {touches_error_plane(report['ctx.health.report_error'])}"
    )
    print(
        f"services.track_error задевает плоскость ошибок: "
        f"{touches_error_plane(report['services.track_error (слот error)'])}"
    )

    for manager in managers.values():
        manager.shutdown()
    shutil.rmtree(root, ignore_errors=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
