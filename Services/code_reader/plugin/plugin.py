# -*- coding: utf-8 -*-
"""CodeReaderPlugin — source-плагин «код с промышленного считывателя ID3000».

Прибор настроен как `TCP Client`: подключается к нам сам и на каждое
срабатывание триггера присылает один пакет. Поэтому плагин поднимает внутри
своего процесса приёмник `Services.code_reader.core.sink.ResultSink`
(TCP-сервер) и отдаёт принятые результаты в pipeline через `produce()`.

Разделение потоков:
    поток соединения (ResultSink) → `_on_result` → очередь
    поток источника (SourceProducer) → `produce()` → items наружу

`produce()` только сливает очередь и НЕ блокирует: контракт source-плагина —
вернуть управление быстрее ~2 интервалов кадра, иначе `SourceProducer.run_loop`
не увидит `stop_event` и процесс получит `terminate()` (тот же довод, что у
`_CAPTURE_TIMEOUT_MS = 200` в `Services/hikvision_camera/plugin/plugin.py`).
Ждать код в потоке источника не нужно вообще: срабатывание асинхронное.

Боевой триггер у прибора аппаратный (DI_0 от датчика линии) и через ПК не
проходит — команды `trigger` здесь нет намеренно. Сетевого триггера в мануалах
серии ID3000 не нашлось, см. `plans/qr-code-reader.md`.

Слой: Services → framework. Плагин не импортирует `Plugins` и
`multiprocess_prototype`.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from Services.code_reader.core.result import ReadResult, ReadStatus
from Services.code_reader.core.sink import ResultSink

from .registers import CodeReaderRegisters

# Глубина очереди между потоком соединения и produce(). При 20 fps источника это
# больше 12 секунд буфера — переполнение означает, что pipeline стоит, и терять
# старые результаты правильнее, чем копить память без предела. Потери видны в
# телеметрии (`dropped`), тихо они не исчезают.
_QUEUE_LIMIT = 256

# Сколько последних кодов держать в истории для GUI.
_HISTORY_LIMIT = 20


@register_plugin(
    "code_reader",
    category="source",
    description="Промышленный считыватель кодов Hikrobot ID3000 (приём по TCP)",
)
class CodeReaderPlugin(ProcessModulePlugin):
    """Источник результатов чтения кодов.

    Команды:
        start_sink / stop_sink — включить/выключить приём (порт освобождается)
        get_status             — полная телеметрия приёма
        reset_stats            — сбросить счётчики и историю
    """

    name = "code_reader"
    category = "source"

    register_class = CodeReaderRegisters

    inputs: list[Port] = []
    outputs: list[Port] = [
        Port(
            name="code",
            dtype="dict",
            shape="-",
            description="Результат чтения: code, status, ts, seq_id, reader_id",
        ),
    ]

    commands: dict[str, str] = {
        "start_sink": "cmd_start_sink",
        "stop_sink": "cmd_stop_sink",
        "get_status": "cmd_get_status",
        "reset_stats": "cmd_reset_stats",
    }

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """Прочитать register; приёмник создаётся в start()."""
        self._ctx = ctx
        self._reg: CodeReaderRegisters = self._init_register(ctx)
        self._queue: deque[dict] = deque(maxlen=_QUEUE_LIMIT)
        self._history: deque[dict] = deque(maxlen=_HISTORY_LIMIT)
        self._lock = threading.Lock()
        self._seq = 0
        self._sink: ResultSink | None = None
        ctx.log_info(
            f"CodeReaderPlugin[{self._reg.reader_id}]: configured "
            f"({self._reg.host}:{self._reg.port}, терминатор {self._reg.terminator!r})"
        )

    def start(self, ctx: PluginContext) -> None:
        """Поднять приём, если задан автоприём; иначе ждать команды из GUI."""
        if self._reg.auto_start:
            self._start_sink()
        else:
            self._reg.sink_state = "stopped"

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановить приём и освободить порт."""
        self._stop_sink()
        ctx.log_info(f"CodeReaderPlugin[{self._reg.reader_id}]: shutdown")

    # ------------------------------------------------------------------ #
    # Поток данных
    # ------------------------------------------------------------------ #

    def produce(self) -> list[dict]:
        """Слить накопленные результаты в items. Пусто — норма, не ошибка.

        Никогда не блокирует: срабатывания приходят из потока соединения, ждать
        их в потоке источника нельзя (см. докстринг модуля).
        """
        with self._lock:
            if not self._queue:
                return []
            items = list(self._queue)
            self._queue.clear()
        self._publish_state()
        return items

    def _on_result(self, result: ReadResult) -> None:
        """Обработчик ResultSink. Вызывается в потоке соединения, не в source."""
        self._seq += 1
        item = {
            "code": result.payload,
            "status": result.status.value,
            "raw_hex": result.raw.hex(" ").upper(),
            "ts": time.time(),
            "seq_id": self._seq,
            "reader_id": self._reg.reader_id,
            "data_type": "code",
        }
        with self._lock:
            overflow = len(self._queue) == _QUEUE_LIMIT
            self._queue.append(item)
            self._history.append({"code": item["code"], "status": item["status"], "ts": item["ts"]})
            if overflow:
                self._reg.dropped += 1
        self._count(result.status)
        if result.status is ReadStatus.OK:
            self._reg.last_code = result.payload
        self._reg.last_status = result.status.value

    def _count(self, status: ReadStatus) -> None:
        """Счётчики по исходу срабатывания — три разных, не один общий."""
        if status is ReadStatus.OK:
            self._reg.total_reads += 1
        elif status is ReadStatus.NO_CODE:
            self._reg.no_reads += 1
        else:
            self._reg.bad_reads += 1

    def _on_client(self, count: int) -> None:
        """Прибор подключился/отвалился — обновить состояние связи."""
        self._reg.sink_state = "connected" if count else "listening"
        self._ctx.log_info(f"CodeReaderPlugin[{self._reg.reader_id}]: соединений {count} ({self._reg.sink_state})")

    def _publish_state(self) -> None:
        """Опубликовать телеметрию в реактивное дерево (живой GUI)."""
        proxy = getattr(self._ctx, "state_proxy", None)
        if proxy is None:
            return
        with self._lock:
            history = list(self._history)
        try:
            proxy.merge(
                f"processes.{self._ctx.process_name}.state.code_reader",
                {
                    "last_code": self._reg.last_code,
                    "last_status": self._reg.last_status,
                    "sink_state": self._reg.sink_state,
                    "total_reads": self._reg.total_reads,
                    "no_reads": self._reg.no_reads,
                    "bad_reads": self._reg.bad_reads,
                    "history": history,
                },
            )
        except Exception as exc:  # noqa: BLE001 — публикация телеметрии не критична
            self._ctx.log_error(f"CodeReaderPlugin: публикация состояния не удалась: {exc}")

    # ------------------------------------------------------------------ #
    # Приём: включение / выключение
    # ------------------------------------------------------------------ #

    def _start_sink(self) -> dict:
        """Поднять TCP-приёмник (идемпотентно)."""
        if self._sink is not None and self._sink.is_running:
            return {"status": "ok", "running": True, "port": self._sink.port}
        reg = self._reg
        sink = ResultSink(
            self._on_result,
            host=reg.host,
            port=reg.port,
            terminator=reg.terminator,
            prefix=reg.prefix,
            no_code_text=reg.no_code_text,
            bad_code_text=reg.bad_code_text or None,
            on_client=self._on_client,
        )
        try:
            sink.start()
        except OSError as exc:
            # Порт занят (не освобождён прошлым процессом) или нет прав. Не падаем:
            # процесс живёт, GUI видит причину в last_error.
            self._reg.sink_state = "stopped"
            self._reg.last_error = str(exc)
            self._ctx.log_error(f"CodeReaderPlugin[{reg.reader_id}]: не удалось занять порт {reg.port}: {exc}")
            return {"status": "error", "running": False, "error": str(exc)}
        self._sink = sink
        self._reg.sink_state = "listening"
        self._reg.last_error = ""
        self._ctx.log_info(
            f"CodeReaderPlugin[{reg.reader_id}]: приём на {reg.host}:{sink.port} "
            f"(прибор подключается сам, режим TCP Client)"
        )
        return {"status": "ok", "running": True, "port": sink.port}

    def _stop_sink(self) -> dict:
        """Погасить приёмник (идемпотентно)."""
        if self._sink is not None:
            self._sink.stop()
            self._sink = None
        self._reg.sink_state = "stopped"
        return {"status": "ok", "running": False}

    # ------------------------------------------------------------------ #
    # Команды из GUI
    # ------------------------------------------------------------------ #

    def cmd_start_sink(self, data: dict) -> dict:
        """Включить приём результатов."""
        return self._start_sink()

    def cmd_stop_sink(self, data: dict) -> dict:
        """Выключить приём и освободить порт."""
        self._ctx.log_info(f"CodeReaderPlugin[{self._reg.reader_id}]: приём ВЫКЛ")
        return self._stop_sink()

    def cmd_get_status(self, data: dict) -> dict:
        """Полная телеметрия приёма."""
        sink = self._sink
        with self._lock:
            pending = len(self._queue)
            history = list(self._history)
        return {
            "status": "ok",
            "reader_id": self._reg.reader_id,
            "sink_state": self._reg.sink_state,
            "running": bool(sink is not None and sink.is_running),
            "clients": sink.client_count if sink is not None else 0,
            "port": sink.port if sink is not None else self._reg.port,
            "pending": pending,
            "last_code": self._reg.last_code,
            "last_status": self._reg.last_status,
            "total_reads": self._reg.total_reads,
            "no_reads": self._reg.no_reads,
            "bad_reads": self._reg.bad_reads,
            "dropped": self._reg.dropped,
            "last_error": self._reg.last_error,
            "history": history,
        }

    def cmd_reset_stats(self, data: dict) -> dict:
        """Сбросить счётчики и историю (наладка стенда)."""
        with self._lock:
            self._history.clear()
        reg = self._reg
        reg.total_reads = reg.no_reads = reg.bad_reads = reg.dropped = 0
        reg.last_code = reg.last_status = reg.last_error = ""
        return {"status": "ok"}

    def get_status(self) -> dict[str, Any]:
        """Статус для внешнего опроса (та же форма, что у команды)."""
        return self.cmd_get_status({})
