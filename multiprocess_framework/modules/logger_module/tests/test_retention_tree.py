# -*- coding: utf-8 -*-
"""Тесты D5 (plans/observability-review-remediation.md) — слепые зоны ретеншена.

Слепая зона, воспроизведённая живым листингом: ``enforce_log_retention()``
метёт ровно ОДИН каталог, переданный ей вызывающим кодом, и (см. её же
докстринг) «каждый менеджер метёт СВОЙ подкаталог (``logs/<процесс>/``)» —
из-за этого «каталоги давно умерших процессов не метёт никто». Тесты ниже
закрепляют два новых публичных помощника ``log_channel.py``:

    ``sweep_log_dir_tree(log_dir, *, live_process_names, retention_days=0,
    retention_total_mb=0, compress_rotated=False) -> Dict[str, int]``

        метёт ВСЕ непосредственные подкаталоги ``log_dir``, КРОМЕ тех, чьё имя
        в ``live_process_names`` — те остаются на попечении собственного
        подметальщика процесса (``LoggerCore._enforce_retention``, не тронут).

    ``find_foreign_log_roots(active_log_dir, candidates) -> List[Dict]``

        только НАЗЫВАЕТ непустые каталоги-кандидаты вне ``active_log_dir`` —
        ничего не удаляет и не трогает (развилка Р-5: уборка legacy —
        решение владельца).

Числа ``retention_days`` в тестах ниже отличны от дефолта фреймворка (0,
выключено) — правило проекта «тест, чьи числа совпадают с дефолтом, проверяет
дефолт, а не ручку».
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from multiprocess_framework.modules.logger_module.channels.log_channel import (
    find_foreign_log_roots,
    sweep_log_dir_tree,
)

#: retention_days для тестов — намеренно НЕ дефолтный (0) и не «круглый» (7,
#: как в соседних тестах ретеншена), чтобы не подхватить чужой дефолт по совпадению.
_RETENTION_DAYS = 3
_SEC_PER_DAY = 86400.0


def _write_aged_file(path: Path, *, age_days: float, content: str = "содержимое") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    stamp = time.time() - age_days * _SEC_PER_DAY
    os.utime(path, (stamp, stamp))
    return path


class TestSweepLogDirTreeRealisticLayout:
    """Синтетическое дерево, повторяющее реальную раскладку ``<log_dir>/<процесс>/<файлы>``."""

    def test_sweeps_dead_process_dir_but_skips_live(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "prototype_2"

        # Живой процесс текущего рецепта: файл старый, но каталог живой — не трогаем.
        live_old = _write_aged_file(log_dir / "camera_0" / "app.log", age_days=30)
        # Мёртвый процесс (рецепт переключился, каталог остался): файл старый — удалить.
        dead_old = _write_aged_file(log_dir / "detector" / "app.log", age_days=30)
        # У мёртвого процесса тоже может быть вложенная подпапка (trace/ и т.п.) —
        # enforce_log_retention обходит рекурсивно, sweep_log_dir_tree обязан это унаследовать.
        dead_nested_old = _write_aged_file(log_dir / "detector" / "trace" / "old.jsonl", age_days=30)
        # Свежий файл мёртвого процесса — моложе retention_days, должен выжить.
        dead_recent = _write_aged_file(log_dir / "detector" / "recent.log", age_days=0.1)

        result = sweep_log_dir_tree(
            log_dir,
            live_process_names={"camera_0", "ProcessManager"},
            retention_days=_RETENTION_DAYS,
        )

        assert live_old.exists(), "подкаталог живого процесса подметальщик дерева трогать не должен"
        assert not dead_old.exists(), "старый файл мёртвого процесса обязан быть удалён"
        assert not dead_nested_old.exists(), "вложенная подпапка мёртвого процесса тоже обязана быть подметена"
        assert dead_recent.exists(), "свежий файл мёртвого процесса моложе retention_days обязан выжить"
        assert result["deleted"] == 2, f"ожидалось 2 удаления (app.log + trace/old.jsonl), получили {result}"
        assert result["bytes_freed"] > 0

    def test_does_not_delete_log_dir_itself(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "prototype_2"
        _write_aged_file(log_dir / "detector" / "app.log", age_days=30)

        sweep_log_dir_tree(log_dir, live_process_names=set(), retention_days=_RETENTION_DAYS)

        assert log_dir.is_dir(), "sweep не имеет права удалить сам log_dir"

    def test_root_level_shared_files_untouched(self, tmp_path: Path) -> None:
        """errors.log/critical.log в КОРНЕ log_dir (общие для всех процессов) не трогаем —
        sweep_log_dir_tree проходит только по подкаталогам, не по файлам верхнего уровня."""
        log_dir = tmp_path / "prototype_2"
        shared_errors = _write_aged_file(log_dir / "errors.log", age_days=30)
        _write_aged_file(log_dir / "detector" / "app.log", age_days=30)

        sweep_log_dir_tree(log_dir, live_process_names=set(), retention_days=_RETENTION_DAYS)

        assert shared_errors.exists(), "общий файл корня log_dir — не подкаталог процесса, sweep его не видит"

    def test_disabled_policies_do_not_touch_disk(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "prototype_2"
        old = _write_aged_file(log_dir / "detector" / "app.log", age_days=30)

        result = sweep_log_dir_tree(log_dir, live_process_names=set(), retention_days=0, retention_total_mb=0)

        assert old.exists()
        assert result == {
            "deleted": 0,
            "compressed": 0,
            "delete_failures": 0,
            "compress_failures": 0,
            "bytes_freed": 0,
        }

    def test_missing_log_dir_is_a_noop(self, tmp_path: Path) -> None:
        result = sweep_log_dir_tree(
            tmp_path / "не_существует", live_process_names=set(), retention_days=_RETENTION_DAYS
        )
        assert result["deleted"] == 0

    def test_skips_symlinked_subdirectory(self, tmp_path: Path) -> None:
        """Символическая ссылка на подкаталог не разыменовывается — sweep не выходит за log_dir."""
        outside = tmp_path / "снаружи"
        outside_file = _write_aged_file(outside / "app.log", age_days=30)

        log_dir = tmp_path / "prototype_2"
        log_dir.mkdir()
        link = log_dir / "detector"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            import pytest

            pytest.skip("создание symlink недоступно в этом окружении (нужны права на Windows)")

        sweep_log_dir_tree(log_dir, live_process_names=set(), retention_days=_RETENTION_DAYS)

        assert outside_file.exists(), "ссылка не разыменовывается — каталог СНАРУЖИ log_dir трогать нельзя"


class TestFindForeignLogRoots:
    def test_names_nonempty_foreign_root_with_numbers(self, tmp_path: Path) -> None:
        active = tmp_path / "prototype_2"
        active.mkdir()
        foreign = tmp_path / "logs"
        (foreign / "camera_0").mkdir(parents=True)
        (foreign / "camera_0" / "a.log").write_text("12345", encoding="utf-8")
        (foreign / "camera_0" / "b.log").write_text("67", encoding="utf-8")

        found = find_foreign_log_roots(active, [foreign])

        assert len(found) == 1
        assert found[0]["path"] == str(foreign)
        assert found[0]["files"] == 2
        assert found[0]["bytes"] == 5 + 2

    def test_excludes_active_log_dir_itself(self, tmp_path: Path) -> None:
        active = tmp_path / "prototype_2"
        (active / "camera_0").mkdir(parents=True)
        (active / "camera_0" / "a.log").write_text("x", encoding="utf-8")

        found = find_foreign_log_roots(active, [active])

        assert found == [], "активный log_dir не может считаться чужим самому себе"

    def test_excludes_empty_and_missing_candidates(self, tmp_path: Path) -> None:
        active = tmp_path / "prototype_2"
        active.mkdir()
        empty = tmp_path / "пусто"
        empty.mkdir()
        missing = tmp_path / "нет_такого"

        found = find_foreign_log_roots(active, [empty, missing])

        assert found == []

    def test_multiple_foreign_roots_all_named(self, tmp_path: Path) -> None:
        active = tmp_path / "prototype_2"
        active.mkdir()
        root_a = tmp_path / "logs"
        (root_a / "x").mkdir(parents=True)
        (root_a / "x" / "f.log").write_text("aaaa", encoding="utf-8")
        root_b = tmp_path / "multiprocess_prototype_logs"
        (root_b / "y").mkdir(parents=True)
        (root_b / "y" / "g.log").write_text("bb", encoding="utf-8")

        found = find_foreign_log_roots(active, [root_a, root_b])

        paths = {item["path"] for item in found}
        assert paths == {str(root_a), str(root_b)}

    def test_never_deletes_anything(self, tmp_path: Path) -> None:
        active = tmp_path / "prototype_2"
        active.mkdir()
        foreign = tmp_path / "logs"
        marker = foreign / "camera_0" / "a.log"
        marker.parent.mkdir(parents=True)
        marker.write_text("x", encoding="utf-8")

        find_foreign_log_roots(active, [foreign])

        assert marker.exists(), "find_foreign_log_roots только называет, не трогает файлы"
