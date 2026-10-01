# -*- coding: utf-8 -*-
"""CodeReaderSdkPlugin — source-плагин «кадр и коды с прибора через MvCodeReader SDK».

В отличие от TCP-плагина (`plugin.py`, приём порта) здесь прибор берётся
эксклюзивно: `SdkCodeReader` держит handle и крутит захват в своём потоке. Каждое
срабатывание — один item с кодами и серой картинкой кадра.

Разделение потоков:
    поток захвата (SdkCodeReader) → `_on_frame` → очередь SdkFrame
    поток источника (SourceProducer) → `produce()` → декод + items наружу

Форма item совместима с TCP-плагином (плоские `code`, `status`, `ts`, `seq_id`,
`reader_id`), сверху — `codes`, `trigger_index`, `frame_num`, `no_read_num`,
`pixel_format` и `frame` (uint8 H×W). Картинка едет ТОЛЬКО под ключом `frame`:
claim check в SHM видит только его; JPEG-байты или отрисованный кадр под другим
ключом пошли бы через 64 КБ pipe. `data_type` плагин не ставит — его проставит
SourceProducer при наличии кадра.

`produce()` никогда не блокирует (контракт source-плагина, как у TCP-плагина).
Автопереподключения нет (решение 6 плана): `on_error` только публикует состояние и
`start()` не зовёт; вернуть прибор — команда `take_device`.

Слой: Services → framework. Плагин не импортирует `Plugins` и `multiprocess_prototype`.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from Services.code_reader.core.result import ReadStatus
from Services.code_reader.core.sdk_frame import SdkFrame, decode_image
from Services.code_reader.core.sdk_reader import SdkCodeReader

from .sdk_registers import CodeReaderSdkRegisters

# Глубина очереди между потоком захвата и produce(). Переполнение = pipeline стоит;
# старые кадры теряем (каждый несёт JPEG), потеря видна в `dropped`, а не молча.
_QUEUE_LIMIT = 8

# Сколько последних срабатываний держать в истории для GUI.
_HISTORY_LIMIT = 20

_STILL_HELD = "прибор ещё отпускается"


@register_plugin(
    "code_reader_sdk",
    category="source",
    description="Промышленный считыватель кодов Hikrobot ID3000 (кадр и коды через MvCodeReader SDK)",
)
class CodeReaderSdkPlugin(ProcessModulePlugin):
    """Источник кадров с кодами.

    Команды:
        take_device    — взять прибор и начать захват
        release_device — остановить захват и отпустить прибор
        get_status     — полная телеметрия
        reset_stats    — сбросить счётчики и историю
    """

    name = "code_reader_sdk"
    category = "source"

    register_class = CodeReaderSdkRegisters

    inputs: list[Port] = []
    outputs: list[Port] = [
        Port(
            name="code",
            dtype="str",
            shape="-",
            description="Текст первого читаемого кода срабатывания (пусто, если кода нет)",
        ),
        Port(
            name="frame",
            dtype="image/gray",
            shape="(H, W)",
            optional=True,
            description="Картинка кадра uint8; нет, если JPEG не декодировался",
        ),
    ]

    commands: dict[str, str] = {
        "take_device": "cmd_take_device",
        "release_device": "cmd_release_device",
        "get_status": "cmd_get_status",
        "reset_stats": "cmd_reset_stats",
    }

    # Шов для тестов: читается в configure() через тип, тест подменяет атрибут класса
    # на functools.partial(SdkCodeReader, api=FakeApi(...)).
    reader_factory: ClassVar[Callable[..., SdkCodeReader]] = SdkCodeReader

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """Прочитать register и создать читатель (прибор берётся в start()/take_device)."""
        self._ctx = ctx
        self._reg: CodeReaderSdkRegisters = self._init_register(ctx)
        self._queue: deque[tuple[int, float, SdkFrame]] = deque(maxlen=_QUEUE_LIMIT)
        self._history: deque[dict] = deque(maxlen=_HISTORY_LIMIT)
        self._lock = threading.Lock()  # состояние плагина; читатель под ним НЕ зовём
        self._seq = 0
        self._last_quality: dict | None = None
        self._decode_errors = 0
        # Единственный источник причины сбоя: все ошибки читателя (и отказ start()) приходят
        # в `_on_error`; сюда же — отказ декода и «ещё отпускается». Читателя не опрашиваем.
        self._last_error = ""
        # `device_held`, ушедший в дерево в последний раз: produce() публикует при смене.
        self._published_held = False
        # Сериализует «снимок → merge → отметка» между потоками захвата, источника и команд:
        # иначе устаревший снимок одного потока ложится в дерево поверх свежего и отметка
        # врёт (ревью 6.3 итерации 2, п.3: дерево застревало с device_held True). Под ним
        # берутся только короткие замки (читателя и self._lock), держатели которых сюда не ходят.
        self._publish_lock = threading.Lock()
        # Счётчики читателя не сбрасываются — reset_stats запоминает точку отсчёта.
        self._baseline = {"frames": 0, "ok": 0, "no_code": 0, "bad_code": 0, "errors": 0}
        self._reader: SdkCodeReader = type(self).reader_factory(
            self._on_frame,
            self._on_error,
            device_ip=self._reg.device_ip or None,
            timeout_ms=self._reg.timeout_ms,
        )
        ctx.log_info(
            f"CodeReaderSdkPlugin[{self._reg.reader_id}]: configured "
            f"(прибор {self._reg.device_ip or 'первый найденный'}, таймаут {self._reg.timeout_ms} мс)"
        )

    def start(self, ctx: PluginContext) -> None:
        """Взять прибор, если задан автозахват; иначе ждать команды из GUI."""
        if self._reg.auto_start:
            self.cmd_take_device({})
        else:
            self._publish_state()

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановить захват и отпустить прибор."""
        self._reader.stop()
        self._publish_state()
        ctx.log_info(f"CodeReaderSdkPlugin[{self._reg.reader_id}]: shutdown")

    # ------------------------------------------------------------------ #
    # Поток данных
    # ------------------------------------------------------------------ #

    def produce(self) -> list[dict]:
        """Слить очередь в items и декодировать картинки. Пусто — норма, не ошибка.

        Не блокирует: кадры приходят из потока захвата, ждать их здесь нельзя.
        """
        with self._lock:
            batch = list(self._queue)
            self._queue.clear()
        items: list[dict] = []
        for seq, ts, frame in batch:
            item = self._build_item(seq, ts, frame)
            # ponytail: декод в produce() — до 8 JPEG за проход (~до 100 мс). Если линия
            # быстрее, перенести декод в поток захвата или ограничить число кадров на проход.
            try:
                item["frame"] = decode_image(frame)
            except Exception as exc:  # noqa: BLE001 — код важнее картинки: item уходит без кадра
                self._on_decode_error(frame, exc)
            items.append(item)
        # Публикуем то, что принесли кадры. Смена состояния и ошибки публикуются из своих
        # колбэков: они происходят и когда кадров нет. Исключение — выход потока захвата после
        # позднего release_device: колбэка у него нет, о смене `device_held` узнаём здесь.
        # Читатель опрашиваем без замка плагина (у него свой короткий замок).
        held_changed = bool(self._reader.stats()["device_held"]) != self._published_held
        if items or held_changed:
            self._publish_state()
        return items

    def _build_item(self, seq: int, ts: float, frame: SdkFrame) -> dict:
        code = _first_readable(frame)
        return {
            "code": "" if code is None else code.text,
            "status": frame.status.value,
            "ts": ts,
            "seq_id": seq,
            "reader_id": self._reg.reader_id,
            "codes": [c.to_dict() for c in frame.codes],
            "trigger_index": frame.trigger_index,
            "frame_num": frame.frame_num,
            "no_read_num": frame.no_read_num,
            "pixel_format": frame.pixel_format,
        }

    def _on_frame(self, frame: SdkFrame) -> None:
        """Колбэк читателя. Вызывается в потоке захвата, не в source.

        Очередь, счётчик `seq`, `dropped` и история меняются под одним `self._lock`:
        поток захвата и `produce()` работают одновременно.
        """
        now = time.time()
        code = _first_readable(frame)
        with self._lock:
            self._seq += 1
            overflow = len(self._queue) == _QUEUE_LIMIT
            self._queue.append((self._seq, now, frame))
            self._history.append(
                {
                    "code": "" if code is None else code.text,
                    "status": frame.status.value,
                    "ts": now,
                    "trigger_index": frame.trigger_index,
                }
            )
            if overflow:
                self._reg.dropped += 1
            self._reg.last_status = frame.status.value
            if code is not None:
                self._reg.last_code = code.text
                self._last_quality = None if code.quality is None else code.quality.to_dict()
        # Переполнение = `produce()` не сливает очередь, публикации от него в этом
        # состоянии не будет — сообщаем о потере сразу.
        if overflow:
            self._publish_state()

    def _on_error(self, message: str) -> None:
        """Колбэк читателя: ошибка захвата или смена состояния. Только публикуем.

        `start()` отсюда НЕ зовём: автопереподключения нет (решение 6 плана), на
        финальном сбое читатель всё равно ответил бы отказом.
        """
        with self._lock:
            self._last_error = message
        self._ctx.log_error(f"CodeReaderSdkPlugin[{self._reg.reader_id}]: {message}")
        self._publish_state()

    def _on_decode_error(self, frame: SdkFrame, exc: Exception) -> None:
        message = f"кадр trigger={frame.trigger_index}: картинка не декодирована: {exc}"
        with self._lock:
            self._decode_errors += 1
            self._last_error = message
        self._ctx.log_error(f"CodeReaderSdkPlugin[{self._reg.reader_id}]: {message}")

    # ------------------------------------------------------------------ #
    # Состояние
    # ------------------------------------------------------------------ #

    def _snapshot(self) -> dict[str, Any]:
        """Телеметрия для дерева и `get_status`. `device_state` — всегда из читателя.

        Читатель опрашиваем ДО `self._lock`: под ним читателя не зовём, иначе колбэк
        потока захвата (ему нужен этот замок) сцепился бы с вызовом в читатель.
        """
        stats = self._reader.stats()
        reg = self._reg
        with self._lock:
            base = self._baseline
            device_held = bool(stats["device_held"])
            last_error = self._last_error
            # «ещё отпускается» — производное от device_held: поток вышел -> сообщение снято.
            if last_error == _STILL_HELD and not device_held:
                last_error = ""
            # register — зеркало для GUI, читают отсюда только при показе.
            reg.device_state = stats["state"]
            reg.total_reads = stats["ok"] - base["ok"]
            reg.no_reads = stats["no_code"] - base["no_code"]
            reg.bad_reads = stats["bad_code"] - base["bad_code"]
            reg.frames = stats["frames"] - base["frames"]
            reg.errors = stats["errors"] - base["errors"] + self._decode_errors
            reg.last_error = last_error
            return {
                "device_state": reg.device_state,
                "device": stats["device"],
                "device_held": device_held,
                "last_code": reg.last_code,
                "last_status": reg.last_status,
                "last_quality": self._last_quality,
                "total_reads": reg.total_reads,
                "no_reads": reg.no_reads,
                "bad_reads": reg.bad_reads,
                "frames": reg.frames,
                "errors": reg.errors,
                "dropped": reg.dropped,
                "last_error": last_error,
                "pending": len(self._queue),
                "history": list(self._history),
            }

    def _publish_state(self) -> None:
        """Опубликовать телеметрию в реактивное дерево (живой GUI).

        Зовётся там, где состояние изменилось: из `on_error`, при переполнении, из
        команд и из `produce()`, когда пришли кадры или сменился `device_held`.

        Отметку `_published_held` ставим только здесь, после записи в дерево: `_snapshot`
        зовёт и `get_status`, который не публикует, — отметка оттуда «съедала» бы смену
        (тест `test_status_poll_does_not_swallow_release_for_tree`).
        """
        proxy = getattr(self._ctx, "state_proxy", None)
        if proxy is None:
            return
        try:
            with self._publish_lock:
                snapshot = self._snapshot()
                proxy.merge(f"processes.{self._ctx.process_name}.state.code_reader_sdk", snapshot)
                self._published_held = snapshot["device_held"]
        except Exception as exc:  # noqa: BLE001 — публикация телеметрии не критична
            self._ctx.log_error(f"CodeReaderSdkPlugin: публикация состояния не удалась: {exc}")

    # ------------------------------------------------------------------ #
    # Команды из GUI
    # ------------------------------------------------------------------ #

    def cmd_take_device(self, data: dict) -> dict:
        """Взять прибор и начать захват. Отказ — `status: error` с причиной, не исключение."""
        # Старую причину стираем ДО start(): поток захвата может сбоить раньше, чем вернётся
        # start(), и его ошибка (через `_on_error`) уже принадлежит новой сессии.
        with self._lock:
            self._last_error = ""
        ok = self._reader.start()
        self._publish_state()
        snapshot = self._snapshot()
        result: dict[str, Any] = {"status": "ok" if ok else "error", "device_state": snapshot["device_state"]}
        if not ok:
            result["error"] = snapshot["last_error"]
        return result

    def cmd_release_device(self, data: dict) -> dict:
        """Остановить захват и отпустить прибор.

        Отпускает прибор поток захвата, а не эта команда: при позднем `get_frame` (или
        вызове из колбэка) прибор ещё удерживается, и об этом сказано прямо.
        """
        self._ctx.log_info(f"CodeReaderSdkPlugin[{self._reg.reader_id}]: прибор ОТПУСТИТЬ")
        self._reader.stop()
        held = bool(self._reader.stats()["device_held"])
        if held:
            with self._lock:
                self._last_error = _STILL_HELD
        self._publish_state()
        result: dict[str, Any] = {"status": "error" if held else "ok", "released": not held, "device_held": held}
        if held:
            result["error"] = _STILL_HELD
        return result

    def cmd_get_status(self, data: dict) -> dict:
        """Полная телеметрия."""
        return {
            "status": "ok",
            "reader_id": self._reg.reader_id,
            **self._snapshot(),
        }

    def cmd_reset_stats(self, data: dict) -> dict:
        """Сбросить счётчики и историю (наладка стенда)."""
        stats = self._reader.stats()
        reg = self._reg
        with self._lock:
            self._history.clear()
            self._baseline = {k: stats[k] for k in self._baseline}
            self._decode_errors = 0
            self._last_error = ""
            self._last_quality = None
            reg.dropped = 0
            reg.last_code = reg.last_status = ""
        self._publish_state()
        return {"status": "ok"}

    def get_status(self) -> dict[str, Any]:
        """Статус для внешнего опроса (та же форма, что у команды)."""
        return self.cmd_get_status({})


def _first_readable(frame: SdkFrame):
    """Первая читаемая запись кода кадра или None."""
    return next((c for c in frame.codes if c.status is ReadStatus.OK), None)
