"""FrameBufferPlugin — буфер кадров в RAM по времени съёма (T10).

Purpose: процесс записи кодирует кадр в JPEG, кладёт в `TimeRing` по `capture_ns`, считает потери
(`missed_seq`, `missed_device`, разрывы окна) и отдаёт состояние командами `buffer.range`,
`buffer.seek`, `buffer.pin`. Буфер живёт в RAM независимо от gui и Qt; `process()` диск не трогает
(запись на диск — T12). Один процесс записи — одна камера: имена команд общие на процесс.

Public API:
    FrameBufferPlugin — `process(items)` (pass-through), команды `buffer.range`, `buffer.seek`,
    `buffer.pin`; счётчики через `ctx.publish_metric` в конце каждого `process()`: frames_in, encoded,
    enc_ms_p99, bytes_held, span_s, gaps, missed_seq, missed_device, rejected_no_capture_ns,
    encode_errors, lag_markers, rejected_order, rejected_oversize, rejected_invalid.

Stability: lite

Потоки: `process()` идёт из data-потока, команды — из system-потока. Кольцо потокобезопасно; счётчики
плагина — под отдельным `threading.Lock`, который не держится на `imencode` / `imdecode`.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from fractions import Fraction

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import is_marker
from Services.frame_buffer import TimeRing

from .registers import FrameBufferRegisters

__all__ = ["FrameBufferPlugin"]

_MB = 1024 * 1024

#: Окно скользящего p99 времени кодирования: последние 512 кадров (около 20 с на 25 Гц).
_ENC_WINDOW = 512

#: Интервал троттлинга `health.report_error` (с): сбой кодирования на каждом кадре не должен спамить.
_ERROR_THROTTLE_S = 30.0

_SEEK_MODES = frozenset({"nearest", "prev", "next"})

#: Счётчики плагина (кумулятивные). Отказы кольца `rejected_order` / `rejected_oversize` берутся из кольца.
_COUNTER_NAMES = (
    "frames_in",
    "encoded",
    "missed_seq",
    "missed_device",
    "rejected_no_capture_ns",
    "encode_errors",
    "lag_markers",
    "rejected_invalid",
)


def _is_int(value: object) -> bool:
    """Целое без bool (bool — подкласс int, но не штамп и не граница)."""
    return type(value) is int


def _limit_ok(value: object) -> bool:
    """Предел вписывания: None (без предела) или положительное целое."""
    return value is None or (_is_int(value) and value > 0)


def _fit_size(width: int, height: int, max_w: int | None, max_h: int | None) -> tuple[int, int]:
    """Размер, вписанный в пределы с пропорциями, без увеличения; округление до ближайшего целого.

    Отсутствующий предел (`None`) — без предела по этой стороне. Дробь точная (Fraction), без дрейфа float.
    """
    scale = Fraction(1)
    if max_w is not None:
        scale = min(scale, Fraction(max_w, width))
    if max_h is not None:
        scale = min(scale, Fraction(max_h, height))
    if scale == 1:
        return width, height
    num, den = scale.numerator, scale.denominator
    # round-half-up: (2*x*num + den) // (2*den); не меньше 1 пикселя
    return max(1, (2 * width * num + den) // (2 * den)), max(1, (2 * height * num + den) // (2 * den))


@register_plugin(
    "frame_buffer",
    category="output",
    description="Буфер кадров в RAM по времени съёма: JPEG, индекс по capture_ns, учёт потерь, команды range/seek/pin",
)
class FrameBufferPlugin(ProcessModulePlugin):
    """Буфер кадров на `Services/frame_buffer.TimeRing` (copy-out потребитель кадров)."""

    name = "frame_buffer"
    category = "output"
    # Маркер not_inspected без capture_ns приходит обычным item; без флага он отсёкся бы до process().
    accepts_markers = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр со штампом capture_ns"),
    ]
    outputs = []

    commands = {
        "buffer.range": "_cmd_range",
        "buffer.seek": "_cmd_seek",
        "buffer.pin": "_cmd_pin",
    }
    register_class = FrameBufferRegisters

    def __init__(self) -> None:
        super().__init__()
        # Безопасное состояние до (и после неудачного) configure(): фреймворк зовёт shutdown() и команды
        # даже после отказа конфигурации.
        self._ctx: PluginContext | None = None
        self._ring: TimeRing | None = None
        self._lock = threading.Lock()
        self._reset_counters()

    def _reset_counters(self) -> None:
        self._counters: dict[str, int] = dict.fromkeys(_COUNTER_NAMES, 0)
        self._enc_ms: deque[float] = deque(maxlen=_ENC_WINDOW)
        self._prev_seq: int | None = None
        self._prev_device: int | None = None
        # Последние виденные кольцевые отказы: рост после append() = кадр отвергнут кольцом.
        self._seen_order = 0
        self._seen_oversize = 0

    # ------------------------------------------------------------------ жизненный цикл

    def configure(self, ctx: PluginContext) -> None:
        """Регистры -> кольцо. `pin_max_mb` 0 = равен `buffer_max_mb`; больше — отказ с причиной.

        Атомарно: сначала проверка и сборка нового кольца, и только после успеха присваиваются
        ctx / регистры / кольцо / счётчики. Отказ повторного configure оставляет всё как было
        (плагин продолжает на прежнем кольце и прежнем ctx); при отказе первого — кольца нет, `process`
        возвращает items без изменений, команды отвечают `status: "error"`.
        """
        reg = self._init_register(ctx)
        if reg.pin_max_mb > reg.buffer_max_mb:
            # Плагин остаётся IDLE: оркестратор ловит бросок из configure() и пишет причину в лог.
            raise ValueError("frame_buffer: pin_max_mb не может превышать buffer_max_mb")
        pin_mb = reg.buffer_max_mb if reg.pin_max_mb == 0 else reg.pin_max_mb
        ring = TimeRing(reg.buffer_seconds, reg.buffer_max_mb * _MB, pin_mb * _MB)
        self._ctx = ctx
        self._reg = reg
        self._jpeg_params = [cv2.IMWRITE_JPEG_QUALITY, int(reg.jpeg_quality)]
        with self._lock:
            self._reset_counters()
        self._ring = ring
        ctx.log_info(
            f"FrameBufferPlugin: buffer_seconds={reg.buffer_seconds}, buffer_max_mb={reg.buffer_max_mb}, "
            f"pin_max_mb={pin_mb}, jpeg_quality={reg.jpeg_quality}"
        )

    # ------------------------------------------------------------------ data-поток

    def process(self, items: list[dict]) -> list[dict]:
        """Кодировать и положить каждый кадр в кольцо; счётчики публикуются в конце каждого вызова."""
        ring = self._ring
        if ring is None:  # configure() отказал
            return items
        for item in items:
            if is_marker(item):  # маркер проверяется ДО штампа
                self._count_marker(item)
            elif "frame" in item:
                self._ingest(ring, item)
        self._publish(ring)
        return items

    def _count_marker(self, item: dict) -> None:
        count = item.get("count", 1)
        with self._lock:
            self._counters["lag_markers"] += count if _is_int(count) and count > 0 else 1

    def _bump(self, name: str) -> None:
        with self._lock:
            self._counters[name] += 1

    def _ingest(self, ring: TimeRing, item: dict) -> None:
        self._bump("frames_in")
        capture_ns = item.get("capture_ns")
        if not _is_int(capture_ns):  # штамп обязателен; float / bool / None — не штамп (ADR-177)
            self._bump("rejected_no_capture_ns")
            return

        # Вход — read-only view в слот SHM: кодируем здесь же, ссылку не храним. Замок счётчиков не держим.
        started = time.perf_counter()
        try:
            ok, buf = cv2.imencode(".jpg", item["frame"], self._jpeg_params)
            error: BaseException | None = None if ok else RuntimeError("imencode не закодировал кадр")
        except cv2.error as exc:
            ok, buf, error = False, None, exc
        if error is not None:
            self._bump("encode_errors")
            self._report(error, "frame_buffer.encode")
            return
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        with self._lock:
            self._counters["encoded"] += 1
            self._enc_ms.append(elapsed_ms)

        seq = item.get("seq_id")
        device = item.get("device_frame_num")
        try:
            ring.append(capture_ns, item.get("capture_ts"), buf.tobytes(), seq, device, item.get("group_id"))
        except ValueError as exc:
            self._bump("rejected_invalid")
            self._report(exc, "frame_buffer.append")
            return

        # append() отказы (порядок, размер) не бросает, а считает: приняли ли кадр — по росту счётчиков кольца.
        stats = ring.stats()
        rejected = stats["rejected_order"] != self._seen_order or stats["rejected_oversize"] != self._seen_oversize
        self._seen_order, self._seen_oversize = stats["rejected_order"], stats["rejected_oversize"]
        if rejected:
            return
        self._account_accepted(int(seq), None if device is None else int(device))

    def _account_accepted(self, seq: int, device: int | None) -> None:
        """Потери нумерации; prev двигается ТОЛЬКО на кадре, принятом кольцом (рестарт не пропуск)."""
        with self._lock:
            if self._prev_seq is not None and seq > self._prev_seq:
                self._counters["missed_seq"] += seq - self._prev_seq - 1
            if device is not None and self._prev_device is not None and device > self._prev_device:
                self._counters["missed_device"] += device - self._prev_device - 1
            self._prev_seq = seq
            self._prev_device = device

    def _report(self, exc: BaseException, context: str) -> None:
        if self._ctx is not None:
            self._ctx.health.report_error(exc, context=context, throttle=_ERROR_THROTTLE_S)

    def _publish(self, ring: TimeRing) -> None:
        stats = ring.stats()
        gaps = len(ring.range()["gaps"])
        with self._lock:
            values: dict[str, float | int] = dict(self._counters)
            window = sorted(self._enc_ms)
        values["enc_ms_p99"] = window[math.ceil(0.99 * len(window)) - 1] if window else 0.0
        values["bytes_held"] = stats["bytes_held"]
        values["span_s"] = stats["span_s"]
        values["gaps"] = gaps
        values["rejected_order"] = stats["rejected_order"]
        values["rejected_oversize"] = stats["rejected_oversize"]
        ctx = self._ctx
        for name, value in values.items():
            ctx.publish_metric(name, value)

    # ------------------------------------------------------------------ команды (system-поток)

    def _cmd_range(self, data: dict | None = None) -> dict:
        """`buffer.range` -> `ring.range()`: `t_min_ns`, `t_max_ns`, `frames`, `gaps`."""
        if self._ring is None:
            return {"status": "error", "error": "буфер не сконфигурирован"}
        return self._ring.range()

    def _cmd_seek(self, data: dict | None = None) -> dict:
        """`buffer.seek` `{t_ns, mode, max_width, max_height}` -> кадр на момент `t_ns` (BGR) и его `capture_ns`.

        `mode`: `nearest` (по умолчанию), `prev`, `next`. Кадр вписывается в пределы с пропорциями и без
        увеличения; отсутствующий или `None` предел = без предела по стороне. Кадра нет -> `status: "empty"`.
        """
        data = {} if data is None else data
        if self._ring is None:
            return {"status": "error", "error": "буфер не сконфигурирован"}
        if not isinstance(data, dict):
            return {"status": "error", "error": "buffer.seek: ожидается dict"}
        t_ns = data.get("t_ns")
        mode = data.get("mode", "nearest")
        max_w, max_h = data.get("max_width"), data.get("max_height")
        mode_ok = isinstance(mode, str) and mode in _SEEK_MODES  # str до членства: list/dict нехешируемы
        if not _is_int(t_ns) or not mode_ok or not (_limit_ok(max_w) and _limit_ok(max_h)):
            return {
                "status": "error",
                "error": "buffer.seek: ожидаются целый t_ns, mode nearest|prev|next, положительные пределы",
            }
        found = self._ring.at(t_ns, mode)
        if found is None:
            return {"status": "empty"}
        # Декодирование вне каких-либо замков плагина; payload кольца отдан без копии, frombuffer его не копирует.
        image = cv2.imdecode(np.frombuffer(found["payload"], np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return {"status": "error", "error": "buffer.seek: кадр не раскодирован"}
        height, width = image.shape[:2]
        new_w, new_h = _fit_size(width, height, max_w, max_h)
        if (new_w, new_h) != (width, height):
            image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return {"status": "ok", "frame": image, "capture_ns": found["capture_ns"]}

    def _cmd_pin(self, data: dict | None = None) -> dict:
        """`buffer.pin` `{t0_ns, t1_ns, tag}` -> `ring.pin`; окно события считает вызывающий (О12)."""
        data = {} if data is None else data
        if self._ring is None:
            return {"status": "error", "error": "буфер не сконфигурирован"}
        if not isinstance(data, dict):
            return {"status": "error", "error": "buffer.pin: ожидается dict"}
        t0, t1, tag = data.get("t0_ns"), data.get("t1_ns"), data.get("tag")
        if not (_is_int(t0) and _is_int(t1)) or isinstance(tag, bool) or not isinstance(tag, (str, int)):
            return {"status": "error", "error": "buffer.pin: ожидаются целые t0_ns, t1_ns и tag (str или int)"}
        try:
            self._ring.pin(t0, t1, tag)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}  # текст кольца константный, без значений входа
        return {"status": "ok"}
