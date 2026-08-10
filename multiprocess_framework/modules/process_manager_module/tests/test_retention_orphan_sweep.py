# -*- coding: utf-8 -*-
"""Тесты D5 (plans/observability-review-remediation.md) — PM метёт ВСЁ дерево log_dir.

Слепая зона: до этой правки ретеншен метёт ровно ``log_dir/<имя ЖИВОГО
процесса>/`` (см. ``LoggerCore._retention_root()``), поэтому каталоги
процессов неактивного рецепта внутри того же ``log_dir`` не метёт никто —
подтверждено листингом (файлы 12 дней при ``retention_days=7``). Три новых
метода ``ProcessManagerProcess``:

    ``_live_process_names(processes_config) -> set``       — кто «живой» на boot'е
    ``_sweep_orphaned_log_dirs(live_process_names) -> None`` — метёт чужие подкаталоги
    ``_warn_foreign_log_roots() -> None``                    — один WARNING про деревья ВНЕ log_dir

Эти тесты проверяют ВЫЗЫВАЮЩИЙ код (PM), не сам алгоритм ретеншена — тот уже
закрыт ``logger_module/tests/test_retention_tree.py`` на синтетическом дереве,
повторяющем реальную раскладку ``<log_dir>/<процесс>/<файлы>``.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from ..process.process_manager_process import ProcessManagerProcess

_RETENTION_DAYS = 3  # намеренно не дефолт (0) и не «круглые» 7 из соседних тестов


def _write_aged_file(path: Path, *, age_days: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("содержимое", encoding="utf-8")
    stamp = time.time() - age_days * 86400.0
    os.utime(path, (stamp, stamp))
    return path


def _bare_pmp(*, name: str = "ProcessManager", log_directory: str | None, **cfg_overrides) -> ProcessManagerProcess:
    pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pmp.name = name
    pmp._log_info = MagicMock()
    pmp._log_warning = MagicMock()
    pmp._log_error = MagicMock()
    cfg = SimpleNamespace(
        log_directory=log_directory,
        retention_days=cfg_overrides.get("retention_days", _RETENTION_DAYS),
        retention_total_mb=cfg_overrides.get("retention_total_mb", 0),
        compress_rotated=cfg_overrides.get("compress_rotated", False),
    )
    pmp.logger_manager = SimpleNamespace(config=cfg)
    return pmp


class TestLiveProcessNames:
    def test_includes_configured_process_names_and_own_name(self) -> None:
        pmp = _bare_pmp(name="ProcessManager", log_directory=None)

        live = pmp._live_process_names({"camera_0": {}, "detector": {}})

        assert live == {"camera_0", "detector", "ProcessManager"}

    def test_own_name_present_even_without_processes_config(self) -> None:
        pmp = _bare_pmp(name="ProcessManager", log_directory=None)

        assert pmp._live_process_names({}) == {"ProcessManager"}
        assert pmp._live_process_names(None) == {"ProcessManager"}


class TestSweepOrphanedLogDirs:
    """Хазард-тест на РЕАЛЬНОЙ функции (не мок) — синтетика повторяет раскладку рецепта."""

    def test_sweeps_dead_recipe_dirs_but_never_touches_live_ones(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "prototype_2"
        live_file = _write_aged_file(log_dir / "camera_0" / "app.log", age_days=30)
        dead_file = _write_aged_file(log_dir / "old_recipe_proc" / "app.log", age_days=30)

        pmp = _bare_pmp(log_directory=str(log_dir))
        pmp._sweep_orphaned_log_dirs({"camera_0", "ProcessManager"})

        assert live_file.exists(), "живой подкаталог рецепта sweep трогать не должен"
        assert not dead_file.exists(), "каталог процесса неактивного рецепта обязан быть подметён"
        pmp._log_info.assert_called_once()
        assert "удалено=1" in pmp._log_info.call_args[0][0]
        pmp._log_error.assert_not_called()

    def test_silent_when_nothing_deleted(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "prototype_2"
        _write_aged_file(log_dir / "camera_0" / "app.log", age_days=0.1)

        pmp = _bare_pmp(log_directory=str(log_dir))
        pmp._sweep_orphaned_log_dirs({"camera_0", "ProcessManager"})

        pmp._log_info.assert_not_called()
        pmp._log_error.assert_not_called()

    def test_noop_without_logger_manager_config(self) -> None:
        pmp = _bare_pmp(log_directory=None)
        pmp._sweep_orphaned_log_dirs(set())
        pmp._log_info.assert_not_called()
        pmp._log_error.assert_not_called()

    def test_sweep_failure_is_logged_not_raised(self, tmp_path: Path, monkeypatch) -> None:
        """Уборка чужих каталогов не имеет права уронить boot (см. докстринг метода)."""
        import multiprocess_framework.modules.process_manager_module.process.process_manager_process as pmp_module

        def _boom(*a, **kw):
            raise RuntimeError("диск недоступен")

        monkeypatch.setattr(pmp_module, "sweep_log_dir_tree", _boom)
        pmp = _bare_pmp(log_directory=str(tmp_path / "log_dir"))

        pmp._sweep_orphaned_log_dirs(set())  # не должно бросить исключение

        pmp._log_error.assert_called_once()
        assert "диск недоступен" in pmp._log_error.call_args[0][0]


class TestWarnForeignLogRoots:
    def test_speaks_once_naming_all_foreign_roots_and_deletes_nothing(self, tmp_path: Path) -> None:
        """Молчащий детектор ничего не доказывает — сперва показываем его КРАСНЫМ/говорящим."""
        active = tmp_path / "prototype_2"
        active.mkdir()
        foreign_a = tmp_path / "logs"
        marker_a = foreign_a / "camera_0" / "old.log"
        marker_a.parent.mkdir(parents=True)
        marker_a.write_text("aaaa", encoding="utf-8")
        foreign_b = tmp_path / "multiprocess_prototype_logs"
        marker_b = foreign_b / "camera_0" / "old.log"
        marker_b.parent.mkdir(parents=True)
        marker_b.write_text("bb", encoding="utf-8")

        pmp = _bare_pmp(log_directory=str(active))
        pmp._foreign_log_root_candidates = MagicMock(return_value=[foreign_a, foreign_b])

        pmp._warn_foreign_log_roots()

        pmp._log_warning.assert_called_once()
        message = pmp._log_warning.call_args[0][0]
        assert str(foreign_a) in message
        assert str(foreign_b) in message
        # ничего не удалено — оба маркера на месте
        assert marker_a.exists()
        assert marker_b.exists()

    def test_silent_when_no_foreign_trees_exist(self, tmp_path: Path) -> None:
        active = tmp_path / "prototype_2"
        active.mkdir()

        pmp = _bare_pmp(log_directory=str(active))
        pmp._foreign_log_root_candidates = MagicMock(return_value=[tmp_path / "нет_такого"])

        pmp._warn_foreign_log_roots()

        pmp._log_warning.assert_not_called()

    def test_default_candidate_is_cwd_relative_logs(self) -> None:
        pmp = _bare_pmp(log_directory=None)
        candidates = pmp._foreign_log_root_candidates()
        assert candidates == [Path.cwd() / "logs"]

    def test_noop_without_logger_manager_config(self) -> None:
        pmp = _bare_pmp(log_directory=None)
        pmp._warn_foreign_log_roots()
        pmp._log_warning.assert_not_called()
        pmp._log_error.assert_not_called()
