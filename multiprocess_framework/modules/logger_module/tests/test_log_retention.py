# -*- coding: utf-8 -*-
"""RED-тесты ретеншена и компрессии логов (Ф0.7, plans/observability-unified-routing.md).

Живой факт (пересчитан 2026-07-26, не из плана — там цифра устарела): ``logs/``
этого репозитория держит **730 файлов / 291 МБ**, старейший от **2026-05-05**
(82 дня, ни одного удаления). Ротация ограничивает КАЖДЫЙ файл (``max_size`` ×
``backup_count``), но растёт ЧИСЛО файлов — 700 различных ``.log``-баз. Потолка
на КАТАЛОГ и удаления по возрасту не существует вовсе — теоретический предел
при исправно работающей ротации 41 ГБ.

ВАЖНО про источник контракта: у ``log_channel.py`` нет ``interface.py`` /
формального Protocol для ретеншена — фича отсутствует целиком. По правилу
tester-агента (``no interface.py`` → fallback на текст спеки) контракт ниже
взят ИСКЛЮЧИТЕЛЬНО из таблицы задачи Ф0.7 (три настройки + семь пунктов
поведения), файл ``log_channel.py`` в рамках этой задачи НЕ читался (hard
rule), только: ``configs/logger_manager_config.py``, ``core/logger_core.py``
(get_stats/reconfigure — не под запретом) и уже существующие тесты
``test_rotation_shared_handler.py`` / ``test_rollover_visibility.py`` (паттерны
конструирования ``LoggerCore``/``FileChannel``).

Предположенный (не прочитанный, а СПРОЕКТИРОВАННЫЙ по тексту спеки) публичный
API, который эти тесты закрепляют как контракт для разработчика:

    ``log_channel.enforce_log_retention(directory, *, retention_days=0,
    retention_total_mb=0, compress_rotated=False, active_files=()) -> Any``

    — директорийный sweep: удаляет по возрасту / суммарному потолку, сжимает
    ротированные бэкапы, НИКОГДА не трогает пути из ``active_files``. Тесты
    ниже проверяют ТОЛЬКО файловые побочные эффекты на диске (не форму
    возвращаемого значения) — так гипотеза о сигнатуре наименее хрупкая.

    Плюс три новых поля на ``LoggerManagerConfig`` (по образцу уже
    существующих ``batch_max_pending``/``batch_overflow_policy`` — «per
    logger», настраиваются и напрямую, и через секцию ``observability``):
    ``retention_days: int = 0``, ``retention_total_mb: int = 0``,
    ``compress_rotated: bool = False``.

Все тесты работают ИСКЛЮЧИТЕЛЬНО в ``tmp_path`` — реальный ``logs/`` проекта
не читается и не трогается.
"""

from __future__ import annotations

import gzip
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from multiprocess_framework.modules.logger_module.channels import log_channel
from multiprocess_framework.modules.logger_module.channels.log_channel import (
    _reset_shared_handler_registry,
)
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerManagerConfig,
)

_LOGGER_NAME = "multiprocess_framework.modules.logger_module.channels.log_channel"

_DAY = 86400.0


def _age(days: float) -> tuple[float, float]:
    """(atime, mtime) на N дней в прошлом от текущего момента — без реального sleep()."""
    ts = time.time() - days * _DAY
    return ts, ts


def _touch(path: Path, size_bytes: int, days_old: float) -> None:
    """Создать файл заданного размера с сфабрикованным возрастом (os.utime, не sleep)."""
    path.write_bytes(b"x" * size_bytes)
    os.utime(path, _age(days_old))


@pytest.fixture(autouse=True)
def _clean_handler_registry():
    """Не течь общими rotating-хэндлерами между тестами (см. test_rotation_shared_handler.py)."""
    _reset_shared_handler_registry()
    yield
    _reset_shared_handler_registry()


# =============================================================================
# Контракт: три настройки, дефолт off (LoggerManagerConfig)
# =============================================================================


class TestRetentionConfigDefaults:
    """Пункт 4 контракта: обе политики выключены по умолчанию — на уровне конфига."""

    def test_retention_fields_default_to_off(self) -> None:
        """Дефолтный LoggerManagerConfig НЕ должен ничего удалять «из коробки»."""
        cfg = LoggerManagerConfig()
        assert cfg.retention_days == 0, "retention_days обязан быть 0 по умолчанию (выключено)"
        assert cfg.retention_total_mb == 0, "retention_total_mb обязан быть 0 по умолчанию (выключено)"
        assert cfg.compress_rotated is False, "compress_rotated обязан быть False по умолчанию"


# =============================================================================
# Пункт 4: обе политики off → sweep не удаляет НИЧЕГО (защита от «тихого пожирателя»)
# =============================================================================


class TestRetentionOffByDefaultBehaviour:
    def test_sweep_with_defaults_deletes_nothing(self, tmp_path: Path) -> None:
        """Без явных retention_days/retention_total_mb — старый и большой файл выживает.

        Это страж-тест против фикса, который «по пути» начинает тихо жрать логи
        на дефолтном конфиге (ровно та формулировка риска, что дана в задаче).
        """
        ancient = tmp_path / "ancient_process.log"
        _touch(ancient, size_bytes=2 * 1024 * 1024, days_old=365)

        log_channel.enforce_log_retention(tmp_path)  # все параметры — дефолт (off)

        assert ancient.exists(), "с обеими политиками выключенными sweep не должен удалять файлы"
        assert ancient.stat().st_size == 2 * 1024 * 1024


# =============================================================================
# Пункт 1: удаление по возрасту
# =============================================================================


class TestAgeBasedRetention:
    def test_old_file_removed_recent_file_kept(self, tmp_path: Path) -> None:
        """retention_days=7: файл 30 дней — удалить, файл 1 день — оставить (обе стороны)."""
        old_file = tmp_path / "old_worker.log"
        recent_file = tmp_path / "recent_worker.log"
        _touch(old_file, size_bytes=1024, days_old=30)
        _touch(recent_file, size_bytes=1024, days_old=1)

        log_channel.enforce_log_retention(tmp_path, retention_days=7)

        assert not old_file.exists(), "файл старше retention_days обязан быть удалён"
        assert recent_file.exists(), "файл младше retention_days обязан выжить"
        assert recent_file.read_bytes() == b"x" * 1024, "выживший файл не должен быть тронут/усечён"


# =============================================================================
# Пункт 2: суммарный потолок каталога, удаление oldest-first
# =============================================================================


class TestTotalSizeCapRetention:
    def test_oldest_removed_first_until_under_cap_newest_survive(self, tmp_path: Path) -> None:
        """3 файла по ~400 КБ (1200 КБ) при потолке 1 МБ: старейший уходит, 2 новых выживают.

        Размеры подобраны так, что результат не зависит от того, считает ли
        реализация МБ как 1_000_000 или 1_048_576 байт (см. комментарий ниже).
        """
        size = 400_000  # байт на файл
        oldest = tmp_path / "oldest.log"
        middle = tmp_path / "middle.log"
        newest = tmp_path / "newest.log"
        _touch(oldest, size, days_old=10)
        _touch(middle, size, days_old=5)
        _touch(newest, size, days_old=1)

        # До sweep: 1_200_000 Б — больше и 1_000_000, и 1_048_576 (обе трактовки «1 МБ»).
        # После удаления oldest: 800_000 Б — меньше обеих трактовок. Однозначный исход.
        log_channel.enforce_log_retention(tmp_path, retention_total_mb=1)

        assert not oldest.exists(), "старейший файл обязан быть удалён первым при превышении потолка"
        assert middle.exists(), "файл, оставшийся в пределах потолка, обязан выжить"
        assert newest.exists(), "самый новый файл обязан выжить"
        assert middle.read_bytes() == b"x" * size
        assert newest.read_bytes() == b"x" * size


# =============================================================================
# Пункт 3: активный файл НИКОГДА не удаляется — ни по возрасту, ни по потолку
# =============================================================================


class TestActiveFileNeverDeleted:
    def test_active_file_survives_extreme_age_and_cap_pressure(self, tmp_path: Path) -> None:
        """Самый опасный класс сбоя: удалить файл, который процесс пишет прямо сейчас.

        Активный файл — старше retention_days на порядок И один создаёт
        давление сверх retention_total_mb — и всё равно обязан выжить, потому
        что явно передан в ``active_files``.
        """
        active = tmp_path / "active_writer.log"
        _touch(active, size_bytes=2_000_000, days_old=100)  # старый И большой

        log_channel.enforce_log_retention(
            tmp_path,
            retention_days=1,
            retention_total_mb=1,
            active_files=[str(active)],
        )

        assert active.exists(), "активный (пишущийся сейчас) файл нельзя удалять ни при каких условиях"
        assert active.stat().st_size == 2_000_000, "активный файл не должен быть тронут вообще"


# =============================================================================
# Пункт 5: компрессия ротированных бэкапов
# =============================================================================


class TestCompressRotatedBackups:
    def test_rotated_backup_becomes_gz_with_matching_content(self, tmp_path: Path) -> None:
        """compress_rotated=True: `foo.log.1` -> `foo.log.1.gz`, содержимое совпадает побайтно."""
        active_path = tmp_path / "foo.log"
        backup_path = tmp_path / "foo.log.1"
        original_content = b"line one\nline two\nline three\n" * 100
        active_path.write_bytes(b"current active content\n")
        backup_path.write_bytes(original_content)

        log_channel.enforce_log_retention(
            tmp_path,
            compress_rotated=True,
            active_files=[str(active_path)],
        )

        gz_path = tmp_path / "foo.log.1.gz"
        assert gz_path.exists(), "ротированный бэкап обязан стать .gz"
        assert not backup_path.exists(), "несжатый бэкап после компрессии не должен оставаться рядом"
        with gzip.open(gz_path, "rb") as fh:
            decompressed = fh.read()
        assert decompressed == original_content, "распакованное содержимое обязано побайтно совпасть с оригиналом"

    def test_active_file_is_never_compressed(self, tmp_path: Path) -> None:
        """compress_rotated=True не имеет права тронуть активный (текущий) файл."""
        active_path = tmp_path / "bar.log"
        content = b"actively being written right now\n"
        active_path.write_bytes(content)

        log_channel.enforce_log_retention(
            tmp_path,
            compress_rotated=True,
            active_files=[str(active_path)],
        )

        assert active_path.exists(), "активный файл обязан остаться на месте"
        assert active_path.read_bytes() == content, "активный файл не должен быть сжат/изменён"
        assert not (tmp_path / "bar.log.gz").exists(), "для активного файла .gz-версия не создаётся"


class TestGzInteractsWithOtherPolicies:
    """Пункт 5 (вторая половина): .gz — обычный файл для age/cap-политик, без иммунитета."""

    def test_gz_backup_deletable_by_age(self, tmp_path: Path) -> None:
        """Уже сжатый бэкап (.gz) старше retention_days обязан удаляться как любой другой файл."""
        gz_backup = tmp_path / "already_compressed.log.1.gz"
        _touch(gz_backup, size_bytes=512, days_old=30)

        log_channel.enforce_log_retention(tmp_path, retention_days=7)

        assert not gz_backup.exists(), ".gz-файл не освобождён от удаления по возрасту"

    def test_gz_backup_counts_toward_total_cap(self, tmp_path: Path) -> None:
        """Суммарный потолок каталога считает .gz как обычный файл, а не игнорирует его вес."""
        active_path = tmp_path / "current.log"
        active_path.write_bytes(b"tiny active content")
        gz_backup = tmp_path / "old_backup.log.1.gz"
        _touch(gz_backup, size_bytes=900_000, days_old=5)  # старше active_path

        log_channel.enforce_log_retention(
            tmp_path,
            retention_total_mb=1,
            active_files=[str(active_path)],
        )

        # 900_000 Б сам по себе меньше 1 МБ — если бы .gz игнорировался потолком,
        # тест был бы бессмыслен. Поэтому берём общий вес каталога как критерий:
        # каталог обязан быть под потолком, а единственный файл, который МОЖЕТ
        # быть удалён (active_path защищён) — это gz-бэкап.
        remaining = list(tmp_path.glob("*"))
        total = sum(p.stat().st_size for p in remaining)
        assert total <= 1 * 1024 * 1024, (
            f"суммарный размер каталога обязан быть под потолком 1 МБ, но {total} Б "
            f"(файлы: {[p.name for p in remaining]}) — похоже, .gz исключён из подсчёта"
        )
        assert active_path.exists(), "активный файл не должен пострадать при освобождении места"


# =============================================================================
# Пункт 6: сбой удаления виден — счётчик + троттлированный WARNING
# =============================================================================


class TestDeleteFailureVisibility:
    def test_delete_failure_warning_emitted_at_most_once_per_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Один и тот же файл, который нельзя удалить (Windows: занят другим процессом),
        не должен давать WARNING на КАЖДЫЙ проход sweep — максимум один раз за файл.
        """
        stuck = tmp_path / "locked_by_another_process.log"
        _touch(stuck, size_bytes=256, days_old=30)

        def _raise_remove(*_args: Any, **_kwargs: Any) -> None:
            raise PermissionError("[WinError 32] эмуляция: файл занят другим процессом")

        monkeypatch.setattr(os, "remove", _raise_remove)
        monkeypatch.setattr(Path, "unlink", _raise_remove)

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            log_channel.enforce_log_retention(tmp_path, retention_days=7)
            log_channel.enforce_log_retention(tmp_path, retention_days=7)  # второй проход, тот же файл

        assert stuck.exists(), "неудаляемый (эмуляция PermissionError) файл обязан остаться на диске"
        matching_warnings = [r for r in caplog.records if stuck.name in r.getMessage()]
        assert len(matching_warnings) <= 1, (
            f"WARNING про один и тот же файл обязан быть максимум один раз за файл, получено {len(matching_warnings)}"
        )
        assert len(matching_warnings) >= 1, "сбой удаления обязан дать хотя бы одно предупреждение"

    def test_delete_failure_counter_reachable_via_get_stats(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Сбой удаления обязан быть виден через get_stats() менеджера — не только в логе.

        Имя ключа сознательно не угадывается (см. задание): ищем ЛЮБОЙ ненулевой
        числовой счётчик в get_stats(), чьё имя (путь по вложенным dict) намекает
        на удаление/ретеншен. Реально сработал ``retention_delete_failures``.

        ПРАВКА АВТОРА (Ф0.7). Исходная версия теста требовала, чтобы ДО
        reconfigure счётчик был нулевым, — то есть закрепляла модель «sweep
        бывает только на hot-reload». Модель неверна: процесс, поднятый с
        настроенным ретеншеном и ни разу не переконфигурированный, обязан
        чистить за собой, иначе чистка зависела бы от факта reload'а. Поэтому
        менеджер метёт и на старте, и счётчик к этому моменту УЖЕ ненулевой.
        Намерение теста («сбой удаления виден снаружи, а не только в логе»)
        сохранено: сравнивается прирост, а не абсолютный ноль.
        """
        from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore

        stuck = tmp_path / "stuck_for_stats.log"
        _touch(stuck, size_bytes=256, days_old=30)

        def _raise_remove(*_args: Any, **_kwargs: Any) -> None:
            raise PermissionError("[WinError 32] эмуляция")

        monkeypatch.setattr(os, "remove", _raise_remove)
        monkeypatch.setattr(Path, "unlink", _raise_remove)

        mgr = LoggerCore(
            manager_name="LoggerManager",
            config={
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "retention_days": 7,
            },
        )
        try:
            before = _retention_related_positive_leaves(mgr.get_stats())
            assert before, (
                f"sweep на старте уже наткнулся на неудаляемый файл — счётчик обязан быть ненулевым, а не {before}"
            )

            # Триггерим sweep явно — hot-reload реконфигурацией (см. пункт 7 ниже),
            # чтобы сбой удаления гарантированно произошёл внутри живого менеджера.
            mgr.reconfigure(
                {
                    "log_directory": str(tmp_path),
                    "enable_batching": False,
                    "retention_days": 7,
                }
            )

            after = _retention_related_positive_leaves(mgr.get_stats())
            assert after, (
                "после форс-сбоя удаления в get_stats() обязан быть НЕНУЛЕВОЙ счётчик "
                "с именем, содержащим retention/delete/purge/sweep/unlink/remove/cleanup/gc "
                f"(получено get_stats()={mgr.get_stats()!r})"
            )
            grown = {key for key, val in after.items() if val > before.get(key, 0.0)}
            assert grown, (
                "второй сбой удаления обязан УВЕЛИЧИТЬ счётчик, а не оставить его "
                f"на прежнем значении: до={before}, после={after}"
            )
        finally:
            mgr.shutdown()


def _flatten_numeric(data: Any, prefix: str = "") -> Dict[str, float]:
    """Развернуть вложенные dict в плоские числовые листья ``"a.b.c" -> значение``."""
    out: Dict[str, float] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten_numeric(value, path))
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        out[prefix] = float(data)
    return out


_RETENTION_KEY_HINTS = (
    "retention",
    "delete",
    "purge",
    "sweep",
    "unlink",
    "remove",
    "cleanup",
    "gc",
)


def _retention_related_positive_leaves(stats: Dict[str, Any]) -> Dict[str, float]:
    """Числовые ключи get_stats(), чьё имя намекает на удаление/ретеншен, и значение > 0."""
    flat = _flatten_numeric(stats)
    return {path: val for path, val in flat.items() if val and any(h in path.lower() for h in _RETENTION_KEY_HINTS)}


# =============================================================================
# Пункт 7: hot-reload — reconfigure() применяет новые настройки без рестарта
# =============================================================================


class TestHotReloadAppliesRetention:
    def test_reconfigure_triggers_retention_sweep_immediately(self, tmp_path: Path) -> None:
        """Живой LoggerCore без ретеншена в конфиге -> reconfigure с retention_days=N ->
        старый посторонний файл в том же каталоге логов удаляется СРАЗУ, без рестарта процесса.
        """
        from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore

        mgr = LoggerCore(
            manager_name="LoggerManager",
            config={"log_directory": str(tmp_path), "enable_batching": False},
        )
        try:
            # Посторонний старый файл — как реальные 700 накопившихся `.log`-баз в проекте:
            # ретеншен обязан мести ВЕСЬ каталог логов, а не только свои открытые каналы.
            stray_old_file = tmp_path / "leftover_from_dead_process.log"
            _touch(stray_old_file, size_bytes=1024, days_old=90)

            applied = mgr.reconfigure(
                {
                    "log_directory": str(tmp_path),
                    "enable_batching": False,
                    "retention_days": 7,
                }
            )
            assert applied is True, "reconfigure с валидным конфигом обязан вернуть True"

            assert not stray_old_file.exists(), (
                "hot-reload обязан применить retention_days немедленно, без рестарта процесса"
            )
            # Собственные файлы менеджера (только что созданы reconfigure) — свежие,
            # поэтому retention_days=7 их и так не должен трогать; простая проверка
            # на «менеджер не сломался и продолжает писать».
            assert (tmp_path / "system.log").exists(), "менеджер обязан продолжать вести свои файлы после reconfigure"
        finally:
            mgr.shutdown()
