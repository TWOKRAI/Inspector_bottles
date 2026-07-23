# -*- coding: utf-8 -*-
"""
Реализации каналов записи логов.

Все каналы наследуют ILogChannel(IChannel) — совместимы с ChannelRoutingManager.
"""

import logging
import logging.handlers
import os
import threading
import time
from pathlib import Path
from typing import Dict, Any, Tuple

try:
    import requests
except ImportError:
    requests = None

from ..interfaces import ILogChannel
from ..configs.logger_manager_config import LoggerChannelSchema

# Отдельный stdlib-логгер для сообщений О САМОМ логировании (сбой ротации).
# НЕ маршрутизируется через LoggerManager/каналы — тот механизм и есть то,
# что может быть сломано в этот момент (циклическая зависимость). Тот же
# приём, что _fallback_logger в core/logger_core.py (LoggerCore._fallback_log).
_fallback_logger = logging.getLogger(__name__)


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
    При PermissionError пропускаем ротацию — запись продолжится в текущий файл
    (fail-open: сбой ротации НЕ должен ронять логирование).

    Раньше PermissionError глушился молча (``except: pass``) — без счётчика и
    без предупреждения. Расчёт «другой процесс уже отротирует» не выполняется,
    когда несколько процессов ПОСТОЯННО конкурируют за файл (не разовая
    коллизия, а систематика): ротация не срабатывает НИКОГДА, и файл растёт
    неограниченно — так ``messages.log`` в реальном прогоне вырос до 645 МБ
    при лимите ~60 МБ (10 МБ × 5 бэкапов), и узнать об этом изнутри системы
    было нельзя. Счётчик + троттлированный WARNING делают систематический
    отказ видимым, не трогая fail-open поведение записи.
    """

    #: Не чаще одного WARNING за этот интервал (сек), НЕ «раз в N неудач»:
    #: shouldRollover() у RotatingFileHandler возвращает True на КАЖДОЙ
    #: записи, пока файл выше max_size, а ротация не срабатывает — при
    #: тысячах строк/сек в бизнес-логе это тысячи попыток ротации в секунду.
    #: Счётчик-порог "каждая N-я неудача" на такой скорости всё равно давал
    #: бы много WARNING в секунду; интервал по времени — предсказуемый
    #: потолок независимо от частоты записи.
    _ROLLOVER_WARNING_INTERVAL_SEC = 60.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rollover_failures = 0
        self._last_rollover_warning_ts = 0.0

    def doRollover(self):
        try:
            super().doRollover()
            self._rollover_failures = 0
        except PermissionError:
            # Другой процесс уже ротирует или держит файл — пропускаем (запись
            # продолжится в текущий файл), но считаем и предупреждаем — иначе
            # систематический отказ неотличим от разовой коллизии.
            self._rollover_failures += 1
            self._warn_rollover_stuck()

    def _warn_rollover_stuck(self) -> None:
        """Троттлированное WARNING о застрявшей ротации (не чаще раза в интервал)."""
        now = time.monotonic()
        if now - self._last_rollover_warning_ts < self._ROLLOVER_WARNING_INTERVAL_SEC:
            return
        self._last_rollover_warning_ts = now
        try:
            size_bytes = Path(self.baseFilename).stat().st_size
            size_str = f"{size_bytes / (1024 * 1024):.1f} МБ"
        except OSError:
            size_str = "неизвестен"
        _fallback_logger.warning(
            "Ротация лог-файла '%s' не удалась %d раз(а) подряд (PermissionError — файл "
            "занят другим процессом): лимит max_size НЕ соблюдается, файл растёт "
            "неограниченно (текущий размер: %s)",
            self.baseFilename,
            self._rollover_failures,
            size_str,
        )


# =============================================================================
# Реестр общих rotating-хэндлеров по абсолютному пути (в рамках процесса)
# =============================================================================
#
# Несколько каналов НАМЕРЕННО пишут в один файл. Пример из боевого конфига:
# ``messages.log`` получают и scope-канал ``messages_file``, и module-канал
# ``router_messages`` — это единый лог сообщений (продуктовое поведение, менять
# нельзя). Если каждый канал создаёт СВОЙ ``_SafeRotatingFileHandler`` на один
# путь, в процессе открывается два fd на один файл. На Windows ``doRollover()``
# сперва закрывает СВОЙ stream, затем ``os.rename(messages.log -> .1)`` — и этот
# rename падает WinError 32, пока ВТОРОЙ хэндлер держит свой fd открытым. Ротация
# не срабатывает НИКОГДА, файл растёт без предела (в живом прогоне ``messages.log``
# дорос до 645 МБ при лимите ~60 МБ).
#
# Решение: один ``_SafeRotatingFileHandler`` на абсолютный путь в рамках процесса.
# Каналы с тем же файлом делят его — один ротатор, один fd, конкуренции нет.
# Реестр потокобезопасен (lock) и refcounted: физическое закрытие хэндлера
# происходит только когда его отпустил ПОСЛЕДНИЙ владелец-канал.

_handler_registry_lock = threading.RLock()
_shared_handlers: Dict[str, "_SafeRotatingFileHandler"] = {}
_shared_handler_refs: Dict[str, int] = {}


def _handler_key(path: Any) -> str:
    """Канонический ключ реестра — тот же abspath, что RotatingFileHandler кладёт в ``baseFilename``."""
    return os.path.abspath(os.fspath(path))


def acquire_shared_rotating_handler(
    path: Any, max_bytes: int, backup_count: int
) -> Tuple["_SafeRotatingFileHandler", bool]:
    """Вернуть общий rotating-хэндлер для пути (создать при первом обращении).

    Повторный вызов с тем же путём в этом процессе отдаёт уже созданный хэндлер
    (refcount++), а не открывает второй fd на тот же файл. Расхождение
    ``max_bytes``/``backup_count`` с первым зарегистрировавшим — WARNING; побеждают
    параметры первого владельца (менять их на живом хэндлере нельзя — это сменило
    бы политику ротации под ногами уже пишущего канала).

    Returns:
        (handler, created): ``created=True`` только если хэндлер создан этим
        вызовом (первый владелец) — тогда вызывающему стоит выставить formatter;
        для переиспользованного (``created=False``) formatter первого сохраняется.
    """
    key = _handler_key(path)
    with _handler_registry_lock:
        handler = _shared_handlers.get(key)
        if handler is not None:
            if handler.maxBytes != max_bytes or handler.backupCount != backup_count:
                _fallback_logger.warning(
                    "Канал открывает уже используемый лог-файл '%s' с другими параметрами "
                    "ротации (max_size %d против %d, backup %d против %d): применяются "
                    "параметры первого зарегистрировавшего канала.",
                    key,
                    handler.maxBytes,
                    max_bytes,
                    handler.backupCount,
                    backup_count,
                )
            _shared_handler_refs[key] += 1
            return handler, False
        handler = _SafeRotatingFileHandler(
            filename=key,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        _shared_handlers[key] = handler
        _shared_handler_refs[key] = 1
        return handler, True


def release_shared_rotating_handler(handler: "_SafeRotatingFileHandler") -> None:
    """Отпустить общий rotating-хэндлер; физически закрыть, когда отпустил последний владелец.

    Идемпотентность — на совести вызывающего: :class:`FileChannel` обнуляет ссылку
    после release, поэтому повторный ``close()`` не даёт двойной decrement.
    """
    key = _handler_key(handler.baseFilename)
    with _handler_registry_lock:
        refs = _shared_handler_refs.get(key)
        if refs is None:
            # Хэндлер не из реестра (например, создан напрямую в тесте) — просто закрыть.
            try:
                handler.close()
            except Exception:  # nosec B110 — закрытие best-effort
                pass
            return
        if refs <= 1:
            _shared_handlers.pop(key, None)
            _shared_handler_refs.pop(key, None)
            try:
                handler.close()
            except Exception:  # nosec B110 — закрытие best-effort
                pass
        else:
            _shared_handler_refs[key] = refs - 1


def _reset_shared_handler_registry() -> None:
    """Закрыть и очистить все общие хэндлеры (тест-хелпер для teardown между тестами)."""
    with _handler_registry_lock:
        for handler in list(_shared_handlers.values()):
            try:
                handler.close()
            except Exception:  # nosec B110 — закрытие best-effort
                pass
        _shared_handlers.clear()
        _shared_handler_refs.clear()


class FileChannel(LogChannel):
    """Канал записи в файл"""

    def __init__(self, config: LoggerChannelSchema):
        super().__init__(config)
        self.file_path = Path(config.file_path or f"logs/{config.name}.log")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(config.format)
        if getattr(config, "rotate", True):
            # Общий хэндлер на путь: несколько каналов на один файл делят один
            # ротатор (иначе конкуренция fd ломает ротацию на Windows — см. реестр
            # выше). formatter выставляет только первый владелец пути.
            self.handler, created = acquire_shared_rotating_handler(
                self.file_path,
                config.max_size,
                config.backup_count,
            )
            self._shared_handler = True
            if created:
                self.handler.setFormatter(formatter)
        else:
            self.handler = logging.FileHandler(self.file_path, encoding="utf-8", mode="a")
            self._shared_handler = False
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
        """Закрывает файловый канал.

        Общий rotating-хэндлер отпускается через реестр (refcount--): физически
        закрывается, только когда его отпустил последний канал. Обнуление
        ``self.handler`` защищает от двойного decrement при повторном ``close()``.
        """
        if self.handler is None:
            return
        if getattr(self, "_shared_handler", False):
            release_shared_rotating_handler(self.handler)
        else:
            self.handler.close()
        self.handler = None


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
