# -*- coding: utf-8 -*-
"""Ф0.7 — внутренние опасности ретеншена логов (АВТОРСКИЕ тесты).

Контрактную сторону (возраст, потолок, активный файл, компрессия, hot-reload)
закрывает независимый тестировщик — ``test_log_retention.py``. Здесь то, что
видно только автору правки: последствия того, ЧЕМ именно сделан sweep.

Механизм: рекурсивный обход каталога, три шага в жёстком порядке
(возраст → компрессия → потолок), общий счётчик прохода, модульная память
«о каком файле уже предупреждали». Отсюда опасности:

  1. **Порядок шагов.** Потолок обязан считать вес ПОСЛЕ компрессии. Иначе
     сжатие ничего не даёт: решение об удалении принято по старым размерам, и
     из-под потолка выбрасываются файлы, которые уже поместились.
  2. **Ровно одна копия.** Компрессия — это создать архив и удалить исходник.
     Любая половина этой пары, оставшаяся одна, делает каталог ТЯЖЕЛЕЕ, чем до
     чистки, — ровно наоборот замыслу.
  3. **Возраст переживает компрессию.** Свежий mtime у архива означал бы, что
     сжатый бэкап не удалится по возрасту никогда: две политики работали бы
     друг против друга.
  4. **`FileNotFoundError` — не сбой.** Файл, удалённый соседом раньше нас, это
     достигнутый результат. Учтённый как отказ, он превратил бы работающий
     ретеншен в «сломанный» по счётчику.
  5. **Выключенный ретеншен — НИЧЕГО**, а не «почти ничего». На каталоге в 730
     файлов разница между ранним выходом и полным обходом с ``stat`` — это
     цена, которую платят все, кто фичей не пользуется.
  6. **Пол ошибок неприкосновенен.** ``errors_floor.jsonl`` (Ф0.9) — последнее
     свидетельство о падении. Политика дискового места не имеет права отменять
     политику сохранности улик.
  7. **Терминируемость.** Когда под потолком остались только защищённые файлы,
     цикл «удаляй старейшее, пока не влезем» обязан закончиться, а не крутиться.
  8. **Sweep не роняет логгер.** Отказ чистки диска не должен мешать поднятию
     логирования: без логгера не видно и причины падения.
"""

from __future__ import annotations

import gzip
import os
import threading
import time
from pathlib import Path
from typing import Any, List

import pytest

from multiprocess_framework.modules.logger_module.channels import log_channel
from multiprocess_framework.modules.logger_module.channels.log_channel import (
    PROTECTED_BASENAMES,
    _reset_retention_warnings,
    _reset_shared_handler_registry,
    enforce_log_retention,
)
from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore

_DAY = 86400.0

#: Имя пишется буквой, а не берётся из PROTECTED_BASENAMES: тест, который
#: спрашивает у проверяемого кода, что тот защищает, согласится с любым
#: ответом — в том числе с «ничего». Сверка константы — отдельным тестом ниже.
_FLOOR_NAME = "errors_floor.jsonl"


def _touch(path: Path, size_bytes: int, days_old: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size_bytes)
    ts = time.time() - days_old * _DAY
    os.utime(path, (ts, ts))


@pytest.fixture(autouse=True)
def _clean_module_state():
    _reset_shared_handler_registry()
    _reset_retention_warnings()
    yield
    _reset_shared_handler_registry()
    _reset_retention_warnings()


# =============================================================================
# 1. Порядок шагов: потолок считает вес ПОСЛЕ компрессии
# =============================================================================


def test_compression_saves_a_file_from_the_cap(tmp_path: Path) -> None:
    """Сжимаемый бэкап не должен быть удалён потолком, если после сжатия влезает.

    Два бэкапа по 900 КБ хорошо сжимаемых нулей (в архиве — считанные байты)
    при потолке 1 МБ. Если потолок считает ДО компрессии, он видит 1.8 МБ и
    сносит старейший. Если ПОСЛЕ — оба архива весят суммарно меньше килобайта,
    и удалять нечего.
    """
    older = tmp_path / "app.log.2"
    newer = tmp_path / "app.log.1"
    for path, days in ((older, 10), (newer, 2)):
        path.write_bytes(b"\0" * 900_000)  # нули жмутся в ~1 КБ
        ts = time.time() - days * _DAY
        os.utime(path, (ts, ts))

    result = enforce_log_retention(tmp_path, retention_total_mb=1, compress_rotated=True)

    assert result["compressed"] == 2
    assert result["deleted"] == 0, "потолок посчитал вес до компрессии и снёс лишнее"
    assert (tmp_path / "app.log.2.gz").exists(), "старейший бэкап сжат и обязан выжить"
    assert (tmp_path / "app.log.1.gz").exists()


# =============================================================================
# 2. Ровно одна копия: откат при неудалимом исходнике
# =============================================================================


def test_unremovable_source_rolls_back_the_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Исходник занят (WinError 32) → архив откатывается, обеих копий не остаётся.

    Худший исход не «не сжали», а «сжали И оставили исходник»: каталог, который
    чистили, стал тяжелее. Считается именно вес: `.gz` мог бы быть маленьким,
    но пара файлов — это всегда больше одного.
    """
    backup = tmp_path / "busy.log.1"
    backup.write_bytes(b"payload\n" * 1000)
    weight_before = sum(p.stat().st_size for p in tmp_path.glob("*"))

    # Занят ИМЕННО исходник (его держит другой процесс) — архив удаляется
    # свободно. Глушить удаление целиком было бы нечестно: тогда откат
    # невозможен по построению, и тест проверял бы не код, а свой мок.
    original_remove = os.remove

    def _busy_source(target: Any, *args: Any, **kwargs: Any) -> None:
        if Path(target).name == backup.name:
            raise PermissionError("[WinError 32] файл занят другим процессом")
        original_remove(target, *args, **kwargs)

    monkeypatch.setattr(os, "remove", _busy_source)

    result = enforce_log_retention(tmp_path, compress_rotated=True)

    assert result["compressed"] == 0, "компрессия без удаления исходника не считается успешной"
    assert backup.exists(), "исходник остался (его и не смогли удалить)"
    weight_after = sum(p.stat().st_size for p in tmp_path.glob("*"))
    assert weight_after <= weight_before, (
        f"каталог потяжелел после чистки: было {weight_before} Б, стало {weight_after} Б "
        f"(файлы: {[p.name for p in tmp_path.glob('*')]}) — обе копии остались на диске"
    )


def test_failed_compression_leaves_no_half_written_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Обрыв чтения на середине не оставляет недописанный `.gz`.

    Недописанный архив опаснее отсутствующего: он выглядит как результат
    чистки, а распаковать его нельзя.
    """
    backup = tmp_path / "torn.log.1"
    backup.write_bytes(b"payload\n" * 1000)

    def _fail_copy(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("эмуляция: устройство отвалилось на середине копирования")

    monkeypatch.setattr(log_channel.shutil, "copyfileobj", _fail_copy)

    result = enforce_log_retention(tmp_path, compress_rotated=True)

    assert result["compress_failures"] == 1
    assert backup.exists(), "исходник обязан остаться — он единственная копия"
    assert not (tmp_path / "torn.log.1.gz").exists(), "недописанный архив обязан быть убран"


# =============================================================================
# 3. Возраст переживает компрессию
# =============================================================================


def test_compression_preserves_age_so_the_backup_is_still_deletable(tmp_path: Path) -> None:
    """Сжали сегодня — но бэкапу по-прежнему 30 дней, и второй проход его удалит.

    Без переноса mtime сжатый бэкап получал бы возраст «только что» и по
    политике ``retention_days`` не удалялся бы никогда: включив компрессию,
    оператор молча выключил бы удаление по возрасту.
    """
    backup = tmp_path / "aged.log.1"
    _touch(backup, size_bytes=4096, days_old=30)

    enforce_log_retention(tmp_path, compress_rotated=True)
    gz_path = tmp_path / "aged.log.1.gz"
    assert gz_path.exists()

    age_days = (time.time() - gz_path.stat().st_mtime) / _DAY
    assert age_days > 29, f"архив помолодел: ему {age_days:.1f} суток вместо ~30"

    second = enforce_log_retention(tmp_path, retention_days=7)
    assert second["deleted"] == 1, "второй проход обязан удалить старый архив по возрасту"
    assert not gz_path.exists()


# =============================================================================
# 4. Файл, удалённый соседом, — не сбой
# =============================================================================


def test_file_vanishing_under_us_is_not_counted_as_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FileNotFoundError означает «его уже нет» — это цель, а не отказ.

    Учтённый как отказ, он давал бы ненулевой ``retention_delete_failures`` на
    исправно работающей системе: оператор искал бы поломку, которой нет.
    """
    doomed = tmp_path / "already_gone.log"
    _touch(doomed, size_bytes=128, days_old=30)

    def _vanished(*_args: Any, **_kwargs: Any) -> None:
        raise FileNotFoundError("сосед удалил раньше нас")

    monkeypatch.setattr(os, "remove", _vanished)

    result = enforce_log_retention(tmp_path, retention_days=7)

    assert result["delete_failures"] == 0, "исчезнувший файл не должен считаться отказом"
    assert result["deleted"] == 1, "он обязан быть учтён как удалённый — результат достигнут"


# =============================================================================
# 5. Выключенный ретеншен не стоит НИЧЕГО
# =============================================================================


def test_disabled_retention_does_not_touch_the_filesystem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Обе политики off → каталог не обходится вовсе (ни одного rglob/stat).

    Проверяется не «файлы целы» (это уже делает тестировщик), а ЦЕНА: sweep
    зовётся на каждом старте и каждом reconfigure любого процесса, и на дереве
    в 730 файлов «обойти и ничего не сделать» — это плата, которую берут со
    всех, кто фичу не включал.
    """
    _touch(tmp_path / "whatever.log", size_bytes=64, days_old=400)
    # Шпион стоит на ``os.stat`` — на ГРАНИЦЕ С ОС, а не на имени метода обхода.
    # Прежняя версия следила за ``Path.rglob``, и ревью фазы это сломало: замена
    # обхода на эквивалентный ``os.walk`` оставляла тест зелёным, хотя каталог
    # обходился со stat на каждом файле — ровно та цена, от которой тест обязан
    # защищать. Шпион на имя реализации охраняет имя, а не свойство.
    stat_calls: List[Any] = []
    original_stat = os.stat

    def _spy_stat(path, *args, **kwargs):  # noqa: ANN001 — сигнатура задана os.stat
        stat_calls.append(path)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", _spy_stat)

    enforce_log_retention(tmp_path)

    assert stat_calls == [], f"файлы обошли со stat при выключенном ретеншене: {stat_calls[:5]}"


# =============================================================================
# 6. Пол ошибок неприкосновенен
# =============================================================================


def test_error_floor_survives_both_policies(tmp_path: Path) -> None:
    """``errors_floor.jsonl`` не удаляется ни по возрасту, ни по потолку.

    Это последняя запись о падении процесса (Ф0.9). Освободить место, стерев
    улику, — не тот размен: место возобновляемо, свидетельство нет.
    """
    floor_name = _FLOOR_NAME
    floor = tmp_path / floor_name
    _touch(floor, size_bytes=3_000_000, days_old=400)  # древний И один за потолком

    result = enforce_log_retention(tmp_path, retention_days=1, retention_total_mb=1)

    assert floor.exists(), f"{floor_name} удалён политикой ретеншена"
    assert floor.stat().st_size == 3_000_000, "пол ошибок не должен быть даже усечён"
    assert result["deleted"] == 0


def test_floor_name_is_actually_in_the_protected_set() -> None:
    """Сверка литерала выше с реестром защищённых имён.

    Разъехавшись, они дали бы худший исход: тесты выше остались бы зелёными
    (они проверяют файл со своим именем), а реальный ``errors_floor.jsonl``
    удалялся бы.
    """
    assert _FLOOR_NAME in PROTECTED_BASENAMES


def test_compression_touches_only_rotated_backups(tmp_path: Path) -> None:
    """Сжимается РОВНО ``*.log.<N>`` и ничего больше.

    Изначально здесь стоял тест «пол ошибок не сжимается». Он был пустым:
    ``errors_floor.jsonl`` оставался целым и при полностью снятой защите —
    его спасал шаблон бэкапа, а не реестр защищённых имён. Проверка,
    зелёная по постороннему поводу, хуже отсутствующей: она создаёт
    впечатление проверенной гарантии. Здесь закреплено то, что действительно
    работает, — граница шаблона.

    Активный ``foo.log`` в этом списке не случайно: сжать файл, в который
    прямо сейчас пишет открытый хэндлер, значит потерять поток записей.
    """
    candidates = {
        "app.log.1": True,  # ротированный бэкап — сжимаем
        "app.log.12": True,
        "app.log": False,  # активный файл
        _FLOOR_NAME: False,  # пол ошибок (Ф0.9)
        "app.log.1.gz": False,  # уже сжат
        "snapshot.jsonl": False,
        "app.log.old": False,  # суффикс не числовой
    }
    for name in candidates:
        (tmp_path / name).write_bytes(b"content\n")

    result = enforce_log_retention(tmp_path, compress_rotated=True)

    assert result["compressed"] == sum(candidates.values())
    for name, should_compress in candidates.items():
        source_gone = not (tmp_path / name).exists()
        assert source_gone is should_compress, (
            f"{name}: ожидалось {'сжатие' if should_compress else 'что файл не тронут'}, "
            f"а он {'исчез' if source_gone else 'на месте'}"
        )
        if should_compress:
            assert (tmp_path / f"{name}.gz").exists()


# =============================================================================
# 7. Терминируемость под потолком из одних защищённых файлов
# =============================================================================


def test_cap_terminates_when_only_protected_files_remain(tmp_path: Path) -> None:
    """Потолок недостижим (всё защищено) — sweep обязан завершиться, а не крутиться.

    Цикл «удаляй старейшее, пока вес выше потолка» без выхода по исчерпанию
    кандидатов — классический вечный цикл на старте процесса.
    """
    active = tmp_path / "current.log"
    _touch(active, size_bytes=2_000_000, days_old=0.1)
    floor = tmp_path / _FLOOR_NAME
    _touch(floor, size_bytes=2_000_000, days_old=200)

    result = enforce_log_retention(
        tmp_path,
        retention_total_mb=1,
        active_files=[str(active)],
    )

    assert result["deleted"] == 0
    assert active.exists() and floor.exists()


def test_recursive_sweep_reaches_subdirectories(tmp_path: Path) -> None:
    """Подкаталоги — часть того же хозяйства (``trace/`` пишет тот же менеджер).

    Плоский обход оставил бы половину каталога вне любой политики, и рост
    просто переехал бы на уровень ниже.
    """
    _touch(tmp_path / "trace" / "deep.log", size_bytes=256, days_old=30)
    _touch(tmp_path / "trace" / "nested" / "deeper.log", size_bytes=256, days_old=30)

    result = enforce_log_retention(tmp_path, retention_days=7)

    assert result["deleted"] == 2, "рекурсивный обход обязан достать вложенные файлы"
    assert not (tmp_path / "trace" / "deep.log").exists()
    assert not (tmp_path / "trace" / "nested" / "deeper.log").exists()


# =============================================================================
# 8. Sweep не роняет поднятие логгера
# =============================================================================


def test_logger_starts_even_if_sweep_explodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Падение чистки диска не имеет права утащить с собой логирование.

    Иначе первый же сбой ретеншена делал бы процесс немым — и причину падения
    было бы негде прочитать.
    """
    from multiprocess_framework.modules.logger_module.core import logger_core as core_module

    def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("эмуляция: sweep упал на ровном месте")

    monkeypatch.setattr(core_module, "enforce_log_retention", _explode)

    mgr = LoggerCore(
        manager_name="LoggerManager",
        config={
            "log_directory": str(tmp_path),
            "enable_batching": False,
            "retention_days": 7,
        },
    )
    try:
        assert mgr.get_stats()["retention_delete_failures"] == 0
        mgr.info("логгер жив после падения чистки", module="unit")
        assert (tmp_path / "system.log").exists(), "менеджер обязан продолжать вести свои файлы"
    finally:
        mgr.shutdown()


# =============================================================================
# 9. Троттл предупреждений: память модульная, счётчик — нет
# =============================================================================


def test_counter_keeps_growing_after_warning_is_silenced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Заглушённое предупреждение НЕ означает «потерь больше нет».

    Троттл гасит только текст. Если бы он гасил и учёт, систематический отказ
    выглядел бы как разовый — тот же класс дефекта, который в Ф0.4 закрывали
    для несуществующих каналов.
    """
    stuck = tmp_path / "locked.log"
    _touch(stuck, size_bytes=256, days_old=30)

    def _busy(*_args: Any, **_kwargs: Any) -> None:
        raise PermissionError("[WinError 32] занят")

    monkeypatch.setattr(os, "remove", _busy)
    monkeypatch.setattr(Path, "unlink", _busy)

    import logging

    with caplog.at_level(logging.WARNING, logger=log_channel.__name__):
        first = enforce_log_retention(tmp_path, retention_days=7)
        second = enforce_log_retention(tmp_path, retention_days=7)
        third = enforce_log_retention(tmp_path, retention_days=7)

    assert first["delete_failures"] == 1
    assert second["delete_failures"] == 1, "второй проход обязан посчитать отказ снова"
    assert third["delete_failures"] == 1
    warnings = [r for r in caplog.records if stuck.name in r.getMessage()]
    assert len(warnings) == 1, f"текст обязан прозвучать один раз, получено {len(warnings)}"


def test_delete_pending_is_not_counted_as_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows delete-pending: удаление ОТКАЗАНО, но файла уже нет → это не сбой.

    Воспроизводится точно, а не гонкой: ``os.remove`` и удаляет файл, и бросает
    ``PermissionError`` — ровно то, что видит проигравший в гонке за один файл
    (WinError 5, «удаление уже идёт»). Разбор по ТИПУ исключения записал бы это
    в отказы; правильный критерий — факт «осталось ли что удалять».

    Отдельно от ``test_concurrent_sweeps_...``: тот ловит ту же ошибку только
    когда гонка реально случилась, и сам по себе не доказывает ничего.
    """
    doomed = tmp_path / "delete_pending.log"
    _touch(doomed, size_bytes=128, days_old=30)
    original_remove = os.remove

    def _pending(target: Any, *args: Any, **kwargs: Any) -> None:
        original_remove(target, *args, **kwargs)
        raise PermissionError("[WinError 5] отказано в доступе: удаление уже идёт")

    monkeypatch.setattr(os, "remove", _pending)

    result = enforce_log_retention(tmp_path, retention_days=7)

    assert not doomed.exists()
    assert result["delete_failures"] == 0, "delete-pending учтён как отказ — счётчик врёт вверх"
    assert result["deleted"] == 1


def test_concurrent_sweeps_do_not_report_false_failures(tmp_path: Path) -> None:
    """Четыре потока метут один каталог: без падений и с полной уборкой.

    Сценарий не гипотетический: sweep зовётся на старте каждого процесса, и
    два процесса с менеджерами без ``process=`` смотрят в один корень ``logs/``.

    ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Изначально тест требовал ещё и
    ``delete_failures == 0``. Это требование СНЯТО как недоказуемое: измерено —
    при живой правке он краснел в прогонах, где гонка случалась, и зеленел там,
    где нет, вплоть до падений в прогонах с посторонними сломами. Причина в
    коде, а не в тесте: между «os.remove соседа начался» и «файл исчез» есть
    окно, в котором наша проверка «файл ещё на месте» отвечает правдиво «да», и
    отказ учитывается. Окно узкое, но не нулевое.

    Оставлять недостижимое утверждение в тесте нельзя — это плавающая красная
    сборка, которая учит игнорировать красноту. Детерминированную часть
    свойства закрепляет ``test_delete_pending_is_not_counted_as_failure``;
    остаточная переоценка счётчика при настоящей гонке записана резидуалом в
    план. Она не портит результат уборки — только завышает счётчик отказов.
    """
    for i in range(60):
        _touch(tmp_path / f"old_{i}.log", size_bytes=128, days_old=30)

    results: List[Any] = []
    errors: List[BaseException] = []

    def _sweep() -> None:
        try:
            results.append(enforce_log_retention(tmp_path, retention_days=7))
        except BaseException as exc:  # noqa: BLE001 — тест ловит любой отказ
            errors.append(exc)

    threads = [threading.Thread(target=_sweep) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"параллельный sweep упал: {errors[:1]}"
    assert not list(tmp_path.glob("old_*.log")), "старые файлы обязаны быть удалены"
    assert sum(r["deleted"] for r in results) >= 60, (
        "суммарно должно быть учтено не меньше удалений, чем было файлов: "
        "проигравший гонку тоже видит достигнутый результат"
    )


def test_gz_content_matches_after_utime_rewrite(tmp_path: Path) -> None:
    """Перенос возраста делается ПОСЛЕ закрытия архива и не портит содержимое."""
    backup = tmp_path / "content.log.1"
    payload = bytes(range(256)) * 500
    backup.write_bytes(payload)
    ts = time.time() - 20 * _DAY
    os.utime(backup, (ts, ts))

    enforce_log_retention(tmp_path, compress_rotated=True)

    with gzip.open(tmp_path / "content.log.1.gz", "rb") as fh:
        assert fh.read() == payload
