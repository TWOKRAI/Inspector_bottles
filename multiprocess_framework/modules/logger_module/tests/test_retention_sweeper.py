# -*- coding: utf-8 -*-
"""Ф6.9 — фоновый свип ретеншена: чистка не ждёт рестарта процесса.

Находка Н-3 живого прогона (2026-08-03): в ``logs/`` 471 МБ, удалено ноль.
Ретеншен не сломан — он был **выключен по построению** дважды:

  1. обе политики оставались нулями фреймворка (приложение слой не задавало);
  2. свип звался только на старте и на ``reconfigure`` — на стенде, живущем
     сутками без reload'а, он не срабатывал НИ РАЗУ.

Заявленные свойства и как каждое ломается по отдельности:

  A. свип идёт по таймеру и удаляет просроченный файл БЕЗ рестарта;
  B. при выключенном ретеншене поток не поднимается вовсе (пара к A —
     иначе «работает» неотличимо от «поток крутится вхолостую»);
  C. ``shutdown`` останавливает поток, а не оставляет демона;
  D. ``reconfigure`` перезапускает подметальщика по НОВОМУ конфигу —
     выключенный ретеншен перестаёт мести;
  E. подметальщик у процесса ОДИН: ErrorManager второго не поднимает.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

#: Интервал свипа в тестах. Не «поменьше, чтобы быстрее»: ожидание ниже идёт
#: по факту удаления с дедлайном, а не по sleep, поэтому короткий интервал
#: только сокращает время до первого прохода.
_TICK = 0.05


def _config(directory: Path, **overrides: Any) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "app_name": "sweeper",
        "log_directory": str(directory),
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(directory / "a.log")}},
        "scopes": {"SYSTEM": {"enabled": True, "min_level": "INFO", "channels": ["a"]}},
        "retention_days": 1,
        "retention_sweep_interval_sec": _TICK,
    }
    config.update(overrides)
    return config


def _stale_file(directory: Path, name: str = "старый.log", age_days: float = 5.0) -> Path:
    """Файл, который уже просрочен: mtime сдвинут в прошлое."""
    path = directory / name
    path.write_text("старое содержимое", encoding="utf-8")
    old = time.time() - age_days * 86400
    os.utime(path, (old, old))
    return path


def _wait_gone(path: Path, timeout: float = 10.0) -> bool:
    """Дождаться исчезновения файла с ДЕДЛАЙНОМ.

    Не ``sleep(N)`` и не бесконечный цикл: тест, который висит вместо падения,
    хуже отсутствующего — он прячет регресс за таймаутом прогона.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not path.exists():
            return True
        time.sleep(0.02)
    return False


def _sweeper_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.endswith("-retention")]


class TestPeriodicSweep:
    def test_stale_file_disappears_without_restart(self, tmp_path: Path) -> None:
        """A — главное свойство: процесс живёт, а просроченный файл исчезает.

        Файл создаётся ПОСЛЕ ``initialize()`` намеренно. Созданный до — его
        удалил бы стартовый свип, который был и раньше, и тест остался бы
        зелёным на коде вообще без периодики (проверено инъекцией J-1).
        """
        mgr = LoggerManager(manager_name="SweepProbe", config=_config(tmp_path))
        mgr.initialize()
        stale = _stale_file(tmp_path)
        try:
            assert _wait_gone(stale), "фоновый свип не удалил просроченный файл за 10 с"
            assert mgr.get_stats()["retention_files_deleted"] >= 1, "удаление не попало в счётчик"
            assert mgr.get_stats()["retention_bytes_freed"] > 0, "освобождённые байты не посчитаны"
        finally:
            mgr.shutdown()

    def test_file_created_after_start_is_swept_too(self, tmp_path: Path) -> None:
        """Свип повторяется, а не отрабатывает один раз после старта.

        Файл появляется УЖЕ после ``initialize()``: первый (стартовый) проход
        его не видел, значит удалить его мог только периодический.
        """
        mgr = LoggerManager(manager_name="SweepProbe2", config=_config(tmp_path))
        mgr.initialize()
        try:
            time.sleep(_TICK * 2)
            late = _stale_file(tmp_path, "появился_позже.log")
            assert _wait_gone(late), "второй проход свипа не состоялся"
        finally:
            mgr.shutdown()

    def test_active_file_survives_the_sweep(self, tmp_path: Path) -> None:
        """Свой открытый файл не удаляется, даже если он «старый».

        Иначе фоновая чистка отстреливала бы канал, в который пишет сама, —
        и поток записей исчезал бы молча.
        """
        mgr = LoggerManager(manager_name="SweepProbe3", config=_config(tmp_path))
        mgr.initialize()
        try:
            mgr.info("живая запись", module="probe")
            mgr.flush()
            active = tmp_path / "a.log"
            old = time.time() - 30 * 86400
            os.utime(active, (old, old))
            time.sleep(_TICK * 4)
            assert active.exists(), "свип удалил файл собственного открытого канала"
        finally:
            mgr.shutdown()


class TestSweeperLifecycle:
    def test_no_thread_when_retention_is_off(self, tmp_path: Path) -> None:
        """B — пара к A: выключенный ретеншен не заводит потока.

        Без этой половины «свип работает» неотличимо от «поток просыпается раз
        в час только чтобы выйти по первому ``if``». Дефолт фреймворка — обе
        политики в нуле, и он обязан остаться бесплатным.
        """
        before = _sweeper_threads()
        mgr = LoggerManager(
            manager_name="OffProbe",
            config=_config(tmp_path, retention_days=0, retention_total_mb=0),
        )
        mgr.initialize()
        try:
            assert _sweeper_threads() == before, "поток поднялся при выключенном ретеншене"
        finally:
            mgr.shutdown()

    def test_no_thread_when_interval_is_zero(self, tmp_path: Path) -> None:
        """Нулевой интервал = «мести только на старте и на reconfigure»."""
        before = _sweeper_threads()
        mgr = LoggerManager(
            manager_name="ZeroProbe",
            config=_config(tmp_path, retention_sweep_interval_sec=0.0),
        )
        mgr.initialize()
        try:
            assert _sweeper_threads() == before, "нулевой интервал всё равно поднял поток"
        finally:
            mgr.shutdown()

    def test_shutdown_stops_the_thread(self, tmp_path: Path) -> None:
        """C — демон, переживший shutdown, метёт каталог уже закрытого менеджера."""
        mgr = LoggerManager(manager_name="StopProbe", config=_config(tmp_path))
        mgr.initialize()
        assert "StopProbe-retention" in _sweeper_threads(), "поток вообще не поднялся"

        mgr.shutdown()

        deadline = time.time() + 5.0
        while time.time() < deadline and "StopProbe-retention" in _sweeper_threads():
            time.sleep(0.02)
        assert "StopProbe-retention" not in _sweeper_threads(), "поток пережил shutdown"

    def test_reconfigure_turning_retention_off_stops_sweeping(self, tmp_path: Path) -> None:
        """D — свип перезапускается по НОВОМУ конфигу, а не живёт со старым."""
        mgr = LoggerManager(manager_name="ReconfProbe", config=_config(tmp_path))
        mgr.initialize()
        try:
            assert "ReconfProbe-retention" in _sweeper_threads()

            mgr.reconfigure(_config(tmp_path, retention_days=0, retention_total_mb=0))

            deadline = time.time() + 5.0
            while time.time() < deadline and "ReconfProbe-retention" in _sweeper_threads():
                time.sleep(0.02)
            assert "ReconfProbe-retention" not in _sweeper_threads(), (
                "подметальщик пережил выключение ретеншена и метёт по старому конфигу"
            )

            stale = _stale_file(tmp_path, "после_выключения.log")
            time.sleep(_TICK * 4)
            assert stale.exists(), "чистка продолжилась после выключения ретеншена"
        finally:
            mgr.shutdown()


class TestSingleSweeperPerProcess:
    def test_error_manager_does_not_raise_a_second_sweeper(self, tmp_path: Path) -> None:
        """E — «один каталог — один хозяин» проверяется, а не декларируется.

        ``expand_observability`` отдаёт ретеншен ТОЛЬКО секции logger (комментарий
        в ``observability_config.py``). Второй подметальщик означал бы два обхода
        одного дерева и гонку за одни и те же файлы — на Windows это ещё и
        ``delete_failures`` на ровном месте, то есть ложная тревога.
        """
        from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        expanded = expand_observability(
            {
                "log_directory": str(tmp_path),
                "retention_days": 1,
                "retention_total_mb": 10,
                "retention_sweep_interval_sec": _TICK,
            }
        )
        assert "retention_days" not in expanded["error"], (
            "ретеншен просочился в секцию error — появился второй хозяин каталога"
        )

        em = ErrorManager(manager_name="ErrProbe", config=expanded["error"])
        em.initialize()
        try:
            assert "ErrProbe-retention" not in _sweeper_threads(), (
                "ErrorManager поднял собственный подметальщик того же каталога"
            )
        finally:
            em.shutdown()
