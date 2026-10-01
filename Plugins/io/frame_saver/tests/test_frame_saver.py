"""Тесты FrameSaverPlugin (Фаза 0 — запись изображений на диск).

Используем mock PluginContext (ctx.registers=None → локальный register + config overrides)
и numpy-заглушку кадра. Для тестов по дате подменяем модульный datetime плагина.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

import Plugins.io.frame_saver.plugin as plugin_mod
from Plugins.io.frame_saver.plugin import FrameSaverPlugin


# ---------------------------------------------------------------------------
# Фикстуры / хелперы
# ---------------------------------------------------------------------------


def make_plugin(tmp_path: Path, **overrides) -> FrameSaverPlugin:
    """Создать сконфигурированный плагин с output_dir=tmp_path и overrides через config."""
    cfg: dict = {"output_dir": str(tmp_path)}
    cfg.update(overrides)
    plugin = FrameSaverPlugin()
    ctx = MagicMock()
    ctx.config = cfg
    ctx.registers = None  # → локальный register + YAML overrides из config
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    plugin.configure(ctx)
    return plugin


def frame(fid: int = 0) -> dict:
    """item с маленьким BGR-кадром."""
    return {"frame": np.zeros((4, 4, 3), dtype=np.uint8), "frame_id": fid}


def list_images(d: Path, ext: str = "jpg") -> list[str]:
    """Имена файлов *.ext в папке (отсортированы)."""
    return sorted(f.name for f in d.glob(f"*.{ext}"))


class FakeDateTime(_dt.datetime):
    """datetime с управляемым now() — для тестов по дате."""

    _now = _dt.datetime(2026, 6, 8, 12, 0, 0)

    @classmethod
    def now(cls, tz=None):  # noqa: D102
        return cls._now


@pytest.fixture
def fake_dt(monkeypatch):
    """Подменить datetime в модуле плагина на FakeDateTime."""
    monkeypatch.setattr(plugin_mod, "datetime", FakeDateTime)
    FakeDateTime._now = _dt.datetime(2026, 6, 8, 12, 0, 0)
    return FakeDateTime


# ---------------------------------------------------------------------------
# Stream / save_every_n / index_source
# ---------------------------------------------------------------------------


class TestStream:
    def test_save_every_n(self, tmp_path):
        """stream + save_every_n=3 → сохраняется каждый 3-й кадр."""
        p = make_plugin(tmp_path, subfolder_by_date=False, save_every_n=3, index_source="frame_id")
        for i in range(6):
            p.process([frame(i)])
        # кадры 2 и 5 (frame_count 3 и 6) сохранены, имя по frame_id
        assert list_images(tmp_path) == ["frame_000002.jpg", "frame_000005.jpg"]

    def test_save_now_forces_next(self, tmp_path):
        """stream + save_now → следующий кадр сохраняется немедленно (флаг _force_next)."""
        p = make_plugin(tmp_path, subfolder_by_date=False, save_every_n=1000)
        p.process([frame(0)])  # 1-й из 1000 — не сохраняется
        assert list_images(tmp_path) == []
        p._cmd_save_now({})
        p.process([frame(1)])  # форсирован
        assert len(list_images(tmp_path)) == 1

    def test_frame_id_missing_no_overwrite(self, tmp_path):
        """index_source=frame_id, но frame_id отсутствует → fallback на счётчик, без перезаписи."""
        p = make_plugin(tmp_path, subfolder_by_date=False, index_source="frame_id")
        p._save_frame({"frame": np.zeros((4, 4, 3), dtype=np.uint8)})  # без frame_id
        p._save_frame({"frame": np.zeros((4, 4, 3), dtype=np.uint8)})  # без frame_id
        assert len(list_images(tmp_path)) == 2  # не перезаписали друг друга

    def test_index_source_counter(self, tmp_path):
        """index_source=counter → индекс от счётчика, не от frame_id."""
        p = make_plugin(tmp_path, subfolder_by_date=False, index_source="counter")
        p.process([frame(100)])
        p.process([frame(200)])
        assert list_images(tmp_path) == ["frame_000001.jpg", "frame_000002.jpg"]

    def test_custom_prefix_padding(self, tmp_path):
        """Префикс и padding применяются к имени."""
        p = make_plugin(tmp_path, subfolder_by_date=False, filename_prefix="cam0", index_padding=3)
        p.process([frame(0)])
        assert list_images(tmp_path) == ["cam0_001.jpg"]


# ---------------------------------------------------------------------------
# Trigger / buffer
# ---------------------------------------------------------------------------


class TestTrigger:
    def test_trigger_last(self, tmp_path):
        """trigger + last → в потоке файлов нет; save_now сохраняет ровно 1 (последний)."""
        p = make_plugin(tmp_path, subfolder_by_date=False, save_mode="trigger", buffer_mode="last")
        for i in range(3):
            p.process([frame(i)])
        assert list_images(tmp_path) == []
        res = p._cmd_save_now({})
        assert res["saved"] == 1
        assert len(list_images(tmp_path)) == 1

    def test_trigger_accumulate(self, tmp_path):
        """trigger + accumulate → save_now сохраняет все накопленные."""
        p = make_plugin(tmp_path, subfolder_by_date=False, save_mode="trigger", buffer_mode="accumulate")
        for i in range(3):
            p.process([frame(i)])
        assert list_images(tmp_path) == []
        res = p._cmd_save_now({})
        assert res["saved"] == 3
        assert len(list_images(tmp_path)) == 3

    def test_accumulate_buffer_cap(self, tmp_path):
        """buffer_size ограничивает накопление (deque maxlen)."""
        p = make_plugin(
            tmp_path,
            subfolder_by_date=False,
            save_mode="trigger",
            buffer_mode="accumulate",
            buffer_size=2,
        )
        for i in range(5):
            p.process([frame(i)])
        res = p._cmd_save_now({})
        assert res["saved"] == 2  # только 2 последних остались в буфере

    def test_shutdown_flushes_buffer(self, tmp_path):
        """shutdown в trigger с непустым буфером → кадры сброшены на диск."""
        p = make_plugin(tmp_path, subfolder_by_date=False, save_mode="trigger", buffer_mode="accumulate")
        p.process([frame(0)])
        p.process([frame(1)])
        p.shutdown(p._ctx)
        assert len(list_images(tmp_path)) == 2


# ---------------------------------------------------------------------------
# Форматы
# ---------------------------------------------------------------------------


class TestFormats:
    @pytest.mark.parametrize(
        "fmt,ext",
        [("jpeg", "jpg"), ("png", "png"), ("bmp", "bmp"), ("tiff", "tiff"), ("webp", "webp")],
    )
    def test_format_extension(self, tmp_path, fmt, ext):
        """Каждый формат → корректное расширение, файл читается обратно."""
        p = make_plugin(tmp_path, subfolder_by_date=False, image_format=fmt)
        meta = p._save_frame(frame(0))
        files = list_images(tmp_path, ext)
        assert files == [f"frame_000001.{ext}"]
        assert meta is not None and meta["format"] == fmt
        assert cv2.imread(str(tmp_path / files[0])) is not None


# ---------------------------------------------------------------------------
# Триггер-вход (True/False по проводу + ручной)
# ---------------------------------------------------------------------------


class TestTriggerInput:
    def test_wired_trigger_flushes(self, tmp_path):
        """Сигнал True по проводу (отдельный item) → фронт сбрасывает буфер (trigger+accumulate)."""
        p = make_plugin(tmp_path, subfolder_by_date=False, save_mode="trigger", buffer_mode="accumulate")
        p.process([frame(0)])
        p.process([frame(1)])
        assert list_images(tmp_path) == []
        p.process([{"trigger": True}])  # фронт False→True → flush
        assert len(list_images(tmp_path)) == 2

    def test_wired_trigger_level_no_double_fire(self, tmp_path):
        """Удержание True не даёт повторных срабатываний; повтор только после False→True."""
        p = make_plugin(tmp_path, subfolder_by_date=False, save_mode="trigger", buffer_mode="last")
        p.process([frame(0)])
        p.process([{"trigger": True}])  # фронт → сохранён 1
        assert len(list_images(tmp_path)) == 1
        p.process([frame(1)])
        p.process([{"trigger": True}])  # всё ещё True (уровень) → НЕ срабатывает
        assert len(list_images(tmp_path)) == 1
        p.process([{"trigger": False}])  # сброс
        p.process([{"trigger": True}])  # новый фронт → +1
        assert len(list_images(tmp_path)) == 2

    def test_manual_trigger_stream(self, tmp_path):
        """manual_trigger (ручной) в stream-режиме → сохраняет последний кадр по фронту."""
        p = make_plugin(tmp_path, subfolder_by_date=False, save_mode="stream", save_every_n=1000, manual_trigger=True)
        p.process([frame(0)])  # stream не сохранит (1%1000), но manual-фронт → сохранит последний
        assert len(list_images(tmp_path)) == 1
        p.process([frame(1)])  # manual всё ещё True (уровень) → без повтора
        assert len(list_images(tmp_path)) == 1

    def test_no_trigger_by_default(self, tmp_path):
        """Без trigger-сигнала и manual_trigger=False — поведение не меняется (обратная совместимость)."""
        p = make_plugin(tmp_path, subfolder_by_date=False, save_mode="trigger", buffer_mode="accumulate")
        for i in range(3):
            p.process([frame(i)])
        assert list_images(tmp_path) == []  # ничего не сработало


# ---------------------------------------------------------------------------
# Дата / resume
# ---------------------------------------------------------------------------


class TestDateAndResume:
    def test_subfolder_by_date(self, tmp_path, fake_dt):
        """subfolder_by_date=True → файл в output_dir/<date>/."""
        p = make_plugin(tmp_path, subfolder_by_date=True)
        p.process([frame(0)])
        day = tmp_path / "2026-06-08"
        assert day.is_dir()
        assert list_images(day) == ["frame_000001.jpg"]

    def test_resume_continues_index(self, tmp_path, fake_dt):
        """resume: существующий frame_000007.jpg → следующий frame_000008.jpg."""
        day = tmp_path / "2026-06-08"
        day.mkdir(parents=True)
        cv2.imwrite(str(day / "frame_000007.jpg"), np.zeros((4, 4, 3), dtype=np.uint8))
        p = make_plugin(tmp_path, subfolder_by_date=True, index_source="counter")
        p.process([frame(0)])
        assert "frame_000008.jpg" in list_images(day)
        assert "frame_000007.jpg" in list_images(day)  # старый не перезаписан

    def test_empty_folder_starts_at_one(self, tmp_path, fake_dt):
        """Пустая папка дня → нумерация с frame_000001."""
        p = make_plugin(tmp_path, subfolder_by_date=True, index_source="counter")
        p.process([frame(0)])
        assert list_images(tmp_path / "2026-06-08") == ["frame_000001.jpg"]


# ---------------------------------------------------------------------------
# Атомарность / .tmp / ошибки
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_atomic_no_tmp_left(self, tmp_path):
        """После сохранения нет *.tmp, целевой файл существует."""
        p = make_plugin(tmp_path, subfolder_by_date=False)
        p._save_frame(frame(0))
        assert list(tmp_path.glob("*.tmp")) == []
        assert (tmp_path / "frame_000001.jpg").exists()

    def test_orphan_tmp_ignored_and_cleaned(self, tmp_path, fake_dt):
        """Осиротевший *.tmp игнорируется resume-сканом и удаляется при открытии папки."""
        day = tmp_path / "2026-06-08"
        day.mkdir(parents=True)
        (day / "frame_000003.jpg.tmp").write_bytes(b"junk")
        p = make_plugin(tmp_path, subfolder_by_date=True, index_source="counter")
        p.process([frame(0)])
        # tmp не повлиял на индекс (счёт с 1) и был удалён
        assert list(day.glob("*.tmp")) == []
        assert "frame_000001.jpg" in list_images(day)

    def test_write_error_counted_no_crash(self, tmp_path, monkeypatch):
        """Ошибка кодирования: total_errors растёт, файла нет, без краша."""
        p = make_plugin(tmp_path, subfolder_by_date=False)
        monkeypatch.setattr(plugin_mod.cv2, "imencode", lambda *a, **k: (False, None))
        meta = p._save_frame(frame(0))
        assert meta is None
        assert p._total_errors == 1
        assert list(tmp_path.glob("*.jpg")) == []
        assert list(tmp_path.glob("*.tmp")) == []  # частичный tmp подчищен

    def test_no_frame_is_noop(self, tmp_path):
        """item без frame → ничего не сохраняется, не падает."""
        p = make_plugin(tmp_path, subfolder_by_date=False)
        assert p._save_frame({"frame_id": 1}) is None
        assert list_images(tmp_path) == []


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_process_and_save_now_concurrent(self, tmp_path):
        """process() (data-worker) и save_now (system-thread) одновременно — без гонок/исключений."""
        import threading

        p = make_plugin(tmp_path, subfolder_by_date=False, save_every_n=5)
        errors: list = []
        stop = threading.Event()

        def producer():
            i = 0
            try:
                while not stop.is_set():
                    p.process([frame(i)])
                    i += 1
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def commander():
            try:
                for _ in range(50):
                    p._cmd_save_now({})
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=commander)
        t1.start()
        t2.start()
        t2.join()
        stop.set()
        t1.join()

        assert errors == []
        # все сохранённые файлы — валидные изображения (атомарность, нет битых/.tmp)
        assert list(tmp_path.glob("*.tmp")) == []
        for f in tmp_path.glob("*.jpg"):
            assert cv2.imread(str(f)) is not None


class TestRetention:
    def test_max_days_keeps_recent(self, tmp_path, fake_dt):
        """max_days=2 → остаётся 2 последних дня; старые удалены, чужое не тронуто."""
        # Папки за 5 дней: 2026-06-04 .. 2026-06-08
        for d in range(4, 9):
            (tmp_path / f"2026-06-0{d}").mkdir(parents=True)
        # Чужие объекты — не должны удаляться (safeguard DATE_FMT)
        (tmp_path / "misc").mkdir()
        (tmp_path / "README.txt").write_text("keep me")

        FakeDateTime._now = _dt.datetime(2026, 6, 8, 12, 0, 0)
        p = make_plugin(tmp_path, subfolder_by_date=True, index_source="counter", max_days=2)
        # сохранение в сегодняшнюю папку триггерит retention (вне lock)
        p.process([frame(0)])

        remaining = sorted(s.name for s in tmp_path.iterdir() if s.is_dir())
        assert remaining == ["2026-06-07", "2026-06-08", "misc"]
        assert (tmp_path / "README.txt").exists()

    def test_max_days_zero_no_cleanup(self, tmp_path, fake_dt):
        """max_days=0 → retention не выполняется."""
        (tmp_path / "2026-01-01").mkdir(parents=True)
        p = make_plugin(tmp_path, subfolder_by_date=True, index_source="counter", max_days=0)
        p.process([frame(0)])
        assert (tmp_path / "2026-01-01").exists()


# ---------------------------------------------------------------------------
# 4.7b2: вход конвейера — view в слот кольца; удерживаемые кадры обязаны быть копиями
# ---------------------------------------------------------------------------


def test_trigger_accumulate_buffer_survives_ring_overwrite(tmp_path: Path) -> None:
    """Реальное кольцо глубиной 8 (restore_frame -> read-only view), 20 кадров, buffer_size=10:
    буфер хранит [10..19], а не перезаписанные слоты. Красный revert: ``kept = item`` в process()."""
    from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
    from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

    wmm, rmm = MemoryManager(), MemoryManager()
    writer = FrameShmMiddleware(wmm, owner="cam0", slot="output_frames", coll=8)
    reader = FrameShmMiddleware(rmm, owner="reader", slot="unused")
    plugin = make_plugin(tmp_path, save_mode="trigger", buffer_mode="accumulate", buffer_size=10)
    try:
        for i in range(20):
            out = writer.strip_and_write({"frame": np.full((64, 64, 3), i, np.uint8)})
            msg = reader.restore_frame({"data": out})
            fr = msg["frame"] if msg.get("frame") is not None else msg["data"]["frame"]
            assert not fr.flags.owndata, "предпосылка: вход — view в слот"
            plugin.process([{"frame": fr}])
            del fr, msg
        assert [int(it["frame"][0, 0, 0]) for it in plugin._buffer] == list(range(10, 20))
        assert int(plugin._last_frame_item["frame"][0, 0, 0]) == 19
    finally:
        import gc

        gc.collect()
        plugin._buffer.clear()
        plugin._last_frame_item = None
        gc.collect()
        for fin in (reader.close_handle_cache, writer.release_owned_memory, rmm.close_all, wmm.close_all):
            try:
                fin()
            except Exception:  # noqa: BLE001 — уборка
                pass


def _ring_pair(depth: int):
    from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
    from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

    wmm, rmm = MemoryManager(), MemoryManager()
    return (
        wmm,
        rmm,
        FrameShmMiddleware(wmm, owner="cam0", slot="output_frames", coll=depth),
        FrameShmMiddleware(rmm, owner="reader", slot="unused"),
    )


def _close_ring(*objs) -> None:
    import gc

    gc.collect()
    for o in objs:
        for fin in ("close_handle_cache", "release_owned_memory", "close_all"):
            f = getattr(o, fin, None)
            if callable(f):
                try:
                    f()
                except Exception:  # noqa: BLE001 — уборка
                    pass


def test_stream_last_frame_survives_ring_overwrite_until_trigger(tmp_path: Path) -> None:
    """stream, save_every_n огромный (в цикле ничего не сохраняется): 20 кадров через реальное кольцо глубиной 8,
    потом ещё 8 записей в кольцо (перезаписывают слот кадра 19), триггер -> на диске кадр 19.
    Красный revert: ``self._last_frame_item = item`` в process() (на диске пиксель перезаписанного слота)."""
    wmm, rmm, writer, reader = _ring_pair(8)
    plugin = make_plugin(tmp_path, save_mode="stream", save_every_n=10_000, image_format="png", subfolder_by_date=False)
    try:
        for i in range(20):
            out = writer.strip_and_write({"frame": np.full((64, 64, 3), i, np.uint8)})
            msg = reader.restore_frame({"data": out})
            fr = msg["frame"] if msg.get("frame") is not None else msg["data"]["frame"]
            assert not fr.flags.owndata, "предпосылка: вход — view в слот"
            plugin.process([{"frame": fr}])
            del fr, msg
        for i in range(100, 108):  # кольцо обернулось: слот кадра 19 перезаписан
            writer.strip_and_write({"frame": np.full((64, 64, 3), i, np.uint8)})
        assert list(tmp_path.glob("*.png")) == [], "предпосылка: в цикле ничего не сохранено"
        plugin._fire_trigger()
        files = sorted(tmp_path.glob("*.png"))
        assert len(files) == 1
        assert int(cv2.imread(str(files[0]))[0, 0, 0]) == 19
    finally:
        plugin._last_frame_item = None
        _close_ring(reader, writer, rmm, wmm)
