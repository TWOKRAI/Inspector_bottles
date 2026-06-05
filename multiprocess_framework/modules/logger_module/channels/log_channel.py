# -*- coding: utf-8 -*-
"""
Реализации каналов записи логов.

Все каналы наследуют ILogChannel(IChannel) — совместимы с ChannelRoutingManager.
"""

import logging
import logging.handlers
from pathlib import Path
from typing import Dict, Any

try:
    import requests
except ImportError:
    requests = None

from ..interfaces import ILogChannel
from ..configs.logger_manager_config import LoggerChannelSchema


class LogChannel(ILogChannel):
    """Базовый класс канала логирования (реализует ILogChannel → IChannel)."""

    def __init__(self, config: LoggerChannelSchema):
        self.config = config
        self._name = config.name
        self._type = config.type

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return self._type

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler, устойчивый к WinError 32 при multiprocessing.

    На Windows несколько процессов не могут одновременно переименовать файл.
    При PermissionError пропускаем ротацию — запись продолжится в текущий файл.
    """

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            # Другой процесс уже ротирует или держит файл — пропускаем
            pass


class FileChannel(LogChannel):
    """Канал записи в файл"""

    def __init__(self, config: LoggerChannelSchema):
        super().__init__(config)
        self.file_path = Path(config.file_path or f"logs/{config.name}.log")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(config.format)
        if getattr(config, "rotate", True):
            self.handler = _SafeRotatingFileHandler(
                filename=self.file_path,
                maxBytes=config.max_size,
                backupCount=config.backup_count,
                encoding="utf-8",
            )
        else:
            self.handler = logging.FileHandler(self.file_path, encoding="utf-8", mode="a")
        self.handler.setFormatter(formatter)

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        try:
            log_record = logging.LogRecord(
                name=record["module"],
                level=getattr(logging, record["level"]),
                pathname="",
                lineno=0,
                msg=record["message"],
                args=(),
                exc_info=None,
            )
            log_record.created = record["timestamp"]
            extra = record.get("extra") or {}
            log_record.proc_name = extra.get("proc_name") or "-"

            self.handler.emit(log_record)
            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "error": str(e), "channel": self.name}

    def close(self):
        """Закрывает файловый канал"""
        if self.handler:
            self.handler.close()


class ConsoleChannel(LogChannel):
    """Канал записи в консоль"""

    def __init__(self, config: LoggerChannelSchema):
        super().__init__(config)
        self.handler = logging.StreamHandler()
        formatter = logging.Formatter(config.format)
        self.handler.setFormatter(formatter)

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        try:
            log_record = logging.LogRecord(
                name=record["module"],
                level=getattr(logging, record["level"]),
                pathname="",
                lineno=0,
                msg=record["message"],
                args=(),
                exc_info=None,
            )
            log_record.created = record["timestamp"]
            extra = record.get("extra") or {}
            log_record.proc_name = extra.get("proc_name") or "-"

            self.handler.emit(log_record)
            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "error": str(e), "channel": self.name}

    def close(self):
        """Закрывает консольный канал"""
        if self.handler:
            self.handler.close()


class HttpChannel(LogChannel):
    """Канал отправки логов по HTTP"""

    def __init__(self, config: LoggerChannelSchema):
        super().__init__(config)
        if requests is None:
            raise ImportError("requests library is required for HttpChannel")
        self.url = config.url
        self.headers = config.headers or {"Content-Type": "application/json"}

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = requests.post(self.url, json=record, headers=self.headers, timeout=5)
            response.raise_for_status()
            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "error": str(e), "channel": self.name}


class FrameTraceChannel(LogChannel):
    """Снимок ОДНОГО кадра: буферизует записи по seq_id, перезаписывает файл при смене кадра.

    Мотивация (Option A pipeline-live-control): вместо append-флуда — компактный
    снимок последнего завершённого кадра. Batched I/O: ровно ОДНА запись в файл на
    кадр (а не на каждую строку). Overwrite: хранится только последний кадр —
    мало данных, легко читать.

    Граница кадра — смена ``record['extra']['seq_id']``. Записи без seq_id
    игнорируются (только кадровая цепочка). На смену seq_id предыдущий (завершённый)
    кадр пишется в файл с truncate, затем начинается новый буфер.
    """

    def __init__(self, config: LoggerChannelSchema):
        super().__init__(config)
        self.file_path = Path(config.file_path or f"logs/trace/{config.name}.log")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._seq: Any = None
        self._lines: list[str] = []
        # Постоянный хэндл (mode='w+'): открываем ОДИН раз, на каждый кадр
        # seek(0)+truncate+write+flush — без open/close-сисколлов на кадр.
        # Файл per-process → конкуренции за хэндл нет.
        try:
            self._fh = open(self.file_path, "w+", encoding="utf-8")  # noqa: SIM115
        except Exception:
            self._fh = None

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        try:
            extra = record.get("extra") or {}
            seq = extra.get("seq_id")
            if seq is None:
                return {"status": "skipped", "channel": self.name}
            if seq != self._seq:
                if self._lines:
                    self._flush_frame()
                self._seq = seq
                self._lines = [f"=== frame seq={seq} ==="]
            self._lines.append(str(record.get("message", "")))
            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "error": str(e), "channel": self.name}

    def _flush_frame(self) -> None:
        # Перезапись файла последним завершённым кадром через постоянный хэндл.
        if self._fh is None:
            return
        content = "\n".join(self._lines) + "\n"
        self._fh.seek(0)
        self._fh.write(content)
        self._fh.truncate()  # обрезать хвост, если новый кадр короче предыдущего
        self._fh.flush()

    def close(self) -> None:
        # Финальный сброс незаписанного кадра + закрытие хэндла.
        try:
            if self._lines:
                self._flush_frame()
        finally:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:  # nosec B110 — закрытие файла на shutdown: ошибка не критична
                    pass
                self._fh = None


# Реестр фабрик sink-каналов: type → класс канала.
# Мутируемый: новые типы добавляются через register_sink_factory() без правки create_channel.
_SINK_FACTORIES: Dict[str, type] = {
    "file": FileChannel,
    "console": ConsoleChannel,
    "http": HttpChannel,
    "frame_trace": FrameTraceChannel,
}


def register_sink_factory(sink_type: str, factory: type) -> None:
    """Зарегистрировать тип sink-канала в реестре фабрик.

    Позволяет добавить кастомный канал (SQL, Socket, …) без правки create_channel.
    Повторная регистрация того же типа переопределяет предыдущую (последняя побеждает).

    Args:
        sink_type: Строковый идентификатор типа (значение config.type).
        factory:   Класс-наследник LogChannel (или класс с методом write()).

    Raises:
        TypeError: sink_type пустой/не str, либо factory не класс / не реализует write().
    """
    if not isinstance(sink_type, str) or not sink_type:
        raise TypeError(f"sink_type must be a non-empty str, got {sink_type!r}")
    if not isinstance(factory, type):
        raise TypeError(f"factory must be a class, got {factory!r}")
    if not (issubclass(factory, LogChannel) or callable(getattr(factory, "write", None))):
        raise TypeError(f"factory {factory!r} must subclass LogChannel or define write()")
    _SINK_FACTORIES[sink_type] = factory


def get_registered_sink_types() -> list[str]:
    """Вернуть список зарегистрированных типов sink-каналов."""
    return list(_SINK_FACTORIES)


def create_channel(channel_name: str, config: LoggerChannelSchema) -> LogChannel:
    """Фабрика для создания каналов (name задаётся ключом словаря channels)."""
    cfg = config.model_copy(update={"name": channel_name})
    channel_class = _SINK_FACTORIES.get(cfg.type)
    if not channel_class:
        raise ValueError(f"Unknown channel type: {cfg.type}")
    return channel_class(cfg)
