"""FrameSaverPlugin -- сохранение кадров на диск (Фаза 0).

Output-плагин: process(items) -> items (pass-through с side-effect сохранения).

Возможности:
  * Имя файла: префикс + индекс (counter с resume с диска / frame_id из данных).
  * Организация по дате: output_dir/<YYYY-MM-DD>/ (папка дня).
  * Resume нумерации: при старте/смене суток читаем последний файл, продолжаем с max+1.
  * Retention: хранить N последних дней (старые папки-даты удаляются).
  * Форматы: jpeg / png / bmp / tiff / webp.
  * Режимы: stream (каждый N-й кадр) и trigger (по команде save_now) с буфером last/accumulate.
  * Вход trigger (True/False, optional): сохранение по фронту False→True — с провода (сигнал
    другой ноды) или вручную через register manual_trigger в инспекторе.
  * Атомарная запись: *.tmp + rename — крах не оставляет битый кадр.

Thread-safety: process() идёт из data-worker потока, _cmd_save_now() — из system-потока.
Доступ к буферу/индексу/папке/счётчикам — под self._lock. Тяжёлый retention (rmtree)
выполняется ВНЕ lock, чтобы не блокировать data-worker.

V3_MY_PURE: plugin самодостаточен — все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import cv2

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin

from .registers import FrameSaverRegisters

# Формат имени подпапки дня. Хардкод (не пользовательский параметр), иначе
# пользователь мог бы задать "%Y/%m/%d" (вложенные папки) или "%H" (по часам).
DATE_FMT = "%Y-%m-%d"

# Маппинг формата → расширение файла (cv2.imwrite определяет кодек по расширению).
_EXT_BY_FORMAT = {
    "jpeg": "jpg",
    "png": "png",
    "bmp": "bmp",
    "tiff": "tiff",
    "webp": "webp",
}

# Порог троттлинга логов ошибок записи (не спамить при заполненном диске).
_ERROR_LOG_EVERY = 50


@register_plugin(
    "frame_saver",
    category="output",
    description="Сохранение изображений на диск (папки по дате, resume, retention, форматы)",
)
class FrameSaverPlugin(ProcessModulePlugin):
    """Сохранение кадров на диск с настраиваемым именем, датой и retention."""

    name = "frame_saver"
    category = "output"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр"),
        Port(
            name="trigger",
            dtype="bool",
            shape="-",
            optional=True,  # не подключён → используется register manual_trigger (false/true, в рецепте)
            description="Сигнал True/False: по фронту False→True сохранить (вместо/вместе с save_now)",
        ),
    ]
    # outputs пуст: frame_saver — терминальная нода (sink). process() возвращает items для
    # совместимости с chain-протоколом, но wire-through наружу не предполагается.
    # TODO(Phase 1): если понадобится цепочка после saver — объявить Port "frame" в outputs.
    outputs = []

    commands = {
        "save_now": "_cmd_save_now",
        "get_stats": "_cmd_get_stats",
    }
    register_class = FrameSaverRegisters

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        # camera_id из cfg (не входит в register — идентификатор хоста, для логов).
        self._camera_id: int = ctx.config.get("camera_id", 0)

        # Состояние (общий lock — буфер + индекс + папка + счётчики).
        self._lock = threading.Lock()
        self._buffer: deque[dict] = deque(maxlen=max(1, self._reg.buffer_size))
        self._frame_count: int = 0
        self._index: int = 0  # текущий индекс (counter); resume сидит его с диска
        self._cur_dir: Path | None = None  # текущая папка дня (для детекта смены суток)
        self._saved_count: int = 0
        self._total_errors: int = 0
        self._error_streak: int = 0  # подряд идущих ошибок записи
        self._pending_cleanup: bool = False  # взводится в _resolve_dir, retention выполняется вне lock
        self._force_next: bool = False  # save_now в stream-режиме: форсировать сохранение след. кадра
        self._last_meta: dict | None = None
        # Триггер True/False (вход trigger + ручной manual_trigger): срабатывает по фронту.
        self._wired_trigger: bool = False  # последнее значение с провода (вход trigger)
        self._prev_trigger: bool = False  # предыдущее объединённое состояние (для детекта фронта)
        self._last_frame_item: dict | None = None  # последний кадр (для триггера в stream-режиме)

        # Папку НЕ создаём заранее — папка дня создаётся лениво в _resolve_dir.
        ctx.log_info(
            f"FrameSaverPlugin[{self._camera_id}]: dir={self._reg.output_dir}, "
            f"mode={self._reg.save_mode}, format={self._reg.image_format}, "
            f"prefix={self._reg.filename_prefix}, max_days={self._reg.max_days}"
        )

    def shutdown(self, ctx: PluginContext) -> None:
        """Финальный flush буфера (trigger) + статистика."""
        if self._reg.save_mode == "trigger":
            flushed = self._flush_buffer()
            if flushed:
                ctx.log_info(f"FrameSaverPlugin[{self._camera_id}]: сброшено {flushed} буферных кадров при остановке")
        ctx.log_info(f"FrameSaverPlugin[{self._camera_id}]: shutdown, сохранено кадров: {self._saved_count}")

    def process(self, items: list[dict]) -> list[dict]:
        """Кадры — stream-сохранение / буферизация; trigger-вход — сохранение по фронту.

        Кадры приходят на порт frame (item["frame"]), сигнал True/False — на порт trigger
        (item[trigger_key]) ОТДЕЛЬНЫМИ item-ами. Сохранение триггерится по фронту False→True
        объединённого сигнала (провод trigger ИЛИ ручной manual_trigger). Pass-through.
        """
        for item in items:
            save_it = False
            do_fire = False
            # Общее состояние (буфер/счётчик/триггер) — под lock (system-поток тоже пишет).
            # _save_frame/_fire_trigger берут lock сами → вызываем ВНЕ блока (Lock не reentrant).
            with self._lock:
                if "frame" in item:
                    self._frame_count += 1
                    self._last_frame_item = item
                    if self._reg.save_mode == "stream":
                        if self._force_next or self._frame_count % self._reg.save_every_n == 0:
                            self._force_next = False
                            save_it = True
                    else:  # trigger — не сохраняем в потоке, буферизуем
                        if self._reg.buffer_mode == "last":
                            self._buffer.clear()
                            self._buffer.append(item)  # держим только последний
                        else:  # accumulate — deque(maxlen) сам вытесняет старые
                            self._buffer.append(item)

                # Сигнал с провода (отдельный item с trigger_key).
                if self._reg.trigger_key in item:
                    self._wired_trigger = bool(item.get(self._reg.trigger_key))

                # Детект фронта False→True объединённого сигнала (провод ИЛИ ручной).
                combined = bool(self._reg.manual_trigger) or self._wired_trigger
                if combined and not self._prev_trigger:
                    do_fire = True
                self._prev_trigger = combined

            if save_it:
                self._save_frame(item)
            if do_fire:
                self._fire_trigger()
        return items

    def _fire_trigger(self) -> None:
        """Сработал триггер (фронт): trigger-режим → сброс буфера; stream → сохранить последний кадр."""
        if self._reg.save_mode == "trigger":
            self._flush_buffer()
        elif self._last_frame_item is not None:
            self._save_frame(self._last_frame_item)

    # --- Запись на диск ---

    def _save_frame(self, item: dict) -> dict | None:
        """Сохранить кадр из item["frame"] на диск (папка дня + resume + атомарная запись).

        Запись/индекс/счётчики — под self._lock. Тяжёлый retention выполняется ВНЕ lock.
        Возвращает meta-dict сохранённого кадра (или None если кадра нет / ошибка).
        """
        frame = item.get("frame")
        if frame is None:
            return None

        meta: dict | None = None
        do_cleanup = False
        with self._lock:
            target = self._resolve_dir()  # папка дня; при смене суток — rescan индекса + флаг cleanup
            ext = self._ext()

            fid = item.get("frame_id") if self._reg.index_source == "frame_id" else None
            if fid is not None:
                idx = int(fid)
            else:  # counter (или frame_id отсутствует) — сквозная нумерация, без перезаписи
                self._index += 1
                idx = self._index

            filename = f"{self._reg.filename_prefix}_{idx:0{self._reg.index_padding}d}.{ext}"
            path = target / filename
            tmp = path.with_suffix(path.suffix + ".tmp")  # сначала во временный файл

            # Кодируем через imencode (расширение задаётся явно — imwrite не понял бы .tmp),
            # пишем байты во временный файл и атомарно переименовываем: крах не оставит битый кадр.
            ok = False
            try:
                enc_ok, buf = cv2.imencode(f".{ext}", frame, self._params())
                if enc_ok:
                    tmp.write_bytes(buf.tobytes())
                    tmp.replace(path)  # АТОМАРНЫЙ rename
                    ok = True
            except (cv2.error, OSError, ValueError):
                ok = False

            if ok:
                self._saved_count += 1
                self._error_streak = 0
                h, w = (frame.shape[0], frame.shape[1]) if hasattr(frame, "shape") else (0, 0)
                meta = {
                    "path": str(path),
                    "frame_id": item.get("frame_id"),
                    "ts": time.time(),
                    "w": int(w),
                    "h": int(h),
                    "format": self._reg.image_format,
                }
                self._last_meta = meta
                if self._reg.write_sidecar:
                    self._write_sidecar(path, item, meta)
            else:
                self._on_write_error(tmp)

            # Захватываем и сбрасываем флаг retention ПОД lock (гонка между потоками).
            do_cleanup = self._pending_cleanup
            self._pending_cleanup = False

        # --- вне self._lock: тяжёлый retention не держит data-worker ---
        if do_cleanup:
            self._cleanup_old_days(Path(self._reg.output_dir).resolve())

        return meta

    def _write_sidecar(self, path: Path, item: dict, meta: dict) -> None:
        """Записать .json с метаданными рядом с кадром (для разметки датасета).

        Источник — item[sidecar_key] (dict), дополненный полями кадра (w/h/ts/file).
        Атомарно (*.tmp + replace). Ошибки не роняют сохранение кадра.
        """
        payload = item.get(self._reg.sidecar_key)
        if not isinstance(payload, dict):
            return
        data = {
            **payload,
            "file": path.name,
            "width": meta["w"],
            "height": meta["h"],
            "saved_ts": meta["ts"],
        }
        sidecar = path.with_suffix(".json")
        tmp = sidecar.with_suffix(".json.tmp")
        try:
            # default=str: не-JSON-значение (напр. numpy-скаляр от downstream) сериализуется
            # как строка, а не роняет ВЕСЬ sidecar — лучше записать с фолбэком, чем потерять.
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            tmp.replace(sidecar)
        except (OSError, TypeError, ValueError) as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            self._ctx.log_error(f"FrameSaver: sidecar не записан для {path.name}: {exc}")

    def _resolve_dir(self) -> Path:
        """Папка дня (output_dir/<date>): ленивое создание + resume индекса при смене суток.

        Вызывается ПОД self._lock. Тяжёлый retention НЕ запускает — только взводит флаг.
        """
        base = Path(self._reg.output_dir).resolve()  # cwd дочернего процесса ≠ корня → абсолютизируем
        if self._reg.subfolder_by_date:
            d = base / datetime.now().strftime(DATE_FMT)
        else:
            d = base

        if d != self._cur_dir:
            d.mkdir(parents=True, exist_ok=True)
            self._cur_dir = d
            self._cleanup_tmp(d)  # удалить осиротевшие *.tmp (краш между imwrite и replace)
            if self._reg.index_source == "counter":
                self._index = self._scan_last_index(d)  # продолжить с max+1
            if self._reg.max_days > 0 and self._reg.subfolder_by_date:
                self._pending_cleanup = True  # retention выполнится вне lock
        return d

    def _scan_last_index(self, d: Path) -> int:
        """Найти max существующий индекс для prefix/ext в папке (0 если файлов нет)."""
        ext = self._ext()
        prefix = self._reg.filename_prefix
        rx = re.compile(rf"^{re.escape(prefix)}_(\d+)\.{re.escape(ext)}$")
        return max(
            (int(m.group(1)) for f in d.glob(f"{prefix}_*.{ext}") if (m := rx.match(f.name))),
            default=0,
        )

    def _cleanup_tmp(self, d: Path) -> None:
        """Удалить осиротевшие *.tmp в папке (остаток от краша между imwrite и replace)."""
        for f in d.glob("*.tmp"):
            try:
                f.unlink()
            except OSError:
                pass

    def _cleanup_old_days(self, base: Path) -> None:
        """Retention: оставить max_days последних папок-дат, старые удалить.

        Формула: cutoff = today - (max_days - 1) дней; удаляем папки с date < cutoff.
        max_days=7 → хранится 7 дней (сегодня + 6 предыдущих).
        Safeguard: трогаем только подпапки, чьё имя ПАРСИТСЯ как дата по DATE_FMT —
        чужие файлы/папки (.git, README, misc) не матчатся.
        """
        if not base.exists():
            return
        cutoff = (datetime.now() - timedelta(days=self._reg.max_days - 1)).date()
        for sub in base.iterdir():
            if not sub.is_dir():
                continue
            try:
                folder_date = datetime.strptime(sub.name, DATE_FMT).date()
            except ValueError:
                continue  # не папка-дата — не трогаем
            if folder_date < cutoff:
                try:
                    shutil.rmtree(sub)
                except OSError as e:
                    self._ctx.log_error(f"FrameSaver retention: не удалось удалить {sub}: {e}")

    def _on_write_error(self, tmp: Path) -> None:
        """Учёт ошибки записи: счётчик + троттлинг логов + подчистка tmp."""
        self._total_errors += 1
        self._error_streak += 1
        if self._error_streak == 1 or self._error_streak % _ERROR_LOG_EVERY == 0:
            self._ctx.log_error(
                f"FrameSaver: запись не удалась ({self._error_streak} подряд, "
                f"всего {self._total_errors}); проверьте путь/диск: {tmp.parent}"
            )
        try:
            tmp.unlink(missing_ok=True)  # частично записанный tmp не нужен
        except OSError:
            pass

    def _ext(self) -> str:
        """Расширение файла по формату."""
        return _EXT_BY_FORMAT[self._reg.image_format]

    def _params(self) -> list[int]:
        """Параметры cv2.imwrite по формату."""
        fmt = self._reg.image_format
        if fmt == "jpeg":
            return [cv2.IMWRITE_JPEG_QUALITY, self._reg.jpeg_quality]
        if fmt == "webp":
            return [cv2.IMWRITE_WEBP_QUALITY, self._reg.jpeg_quality]
        if fmt == "png":
            return [cv2.IMWRITE_PNG_COMPRESSION, 3]
        return []  # bmp / tiff — без параметров

    def _flush_buffer(self) -> int:
        """Сбросить буфер (trigger) на диск. Возвращает число сохранённых."""
        with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
        saved = 0
        for it in items:  # _save_frame берёт lock сам, без вложенности
            if self._save_frame(it) is not None:
                saved += 1
        return saved

    # --- Команды ---

    def _cmd_save_now(self, data: dict) -> dict:
        """stream — форсировать следующий кадр; trigger — сбросить буфер на диск."""
        if self._reg.save_mode == "stream":
            with self._lock:
                self._force_next = True
            return {"status": "ok", "message": "next frame will be saved"}
        saved = self._flush_buffer()
        return {"status": "ok", "saved": saved, "total": self._saved_count}

    def _cmd_get_stats(self, data: dict) -> dict:
        """Статистика (консистентный снимок под lock)."""
        with self._lock:
            return {
                "status": "ok",
                "saved_count": self._saved_count,
                "total_frames": self._frame_count,
                "total_errors": self._total_errors,
                "pending": len(self._buffer),
                "output_dir": str(self._cur_dir or self._reg.output_dir),
                "last_saved": self._last_meta,
            }
