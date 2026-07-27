# -*- coding: utf-8 -*-
"""
Реализации каналов записи логов.

Все каналы наследуют ILogChannel(IChannel) — совместимы с ChannelRoutingManager.
"""

import gzip
import logging
import logging.handlers
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

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


# =============================================================================
# Ретеншен каталога логов (Ф0.7)
# =============================================================================
#
# Ротация ограничивает КАЖДЫЙ файл (max_size × backup_count), но не ограничивает
# ЧИСЛО файлов. Живой замер 2026-07-26: ``logs/`` = 730 файлов / 291 МБ,
# старейший от 2026-05-05 (82 дня, ни одного удаления), ~700 различных
# ``.log``-баз. При исправно работающей ротации теоретический потолок — 41 ГБ.
# Потолок стоял не там, где происходил рост.
#
# Ретеншен закрывает именно рост: удаление по возрасту, потолок на суммарный
# вес каталога и компрессия ротированных бэкапов. ОБЕ политики выключены по
# умолчанию — механизм, который сам решает что удалить, не имеет права
# включаться молча.

#: Имена файлов, которые sweep не трогает НИКОГДА, каким бы старым файл ни был.
#: ``errors_floor.jsonl`` (Ф0.9) — последнее свидетельство о падении процесса;
#: политика дискового места не должна отменять политику сохранности улик.
PROTECTED_BASENAMES = frozenset({"errors_floor.jsonl"})

#: Что считается ротированным бэкапом: ``foo.log.1``, ``foo.log.12``.
#: Активный ``foo.log`` под шаблон НЕ попадает — сжимать файл, в который прямо
#: сейчас пишет открытый хэндлер, нельзя.
_ROTATED_BACKUP_RE = re.compile(r"\.log\.\d+$")

_MB = 1024 * 1024
_SEC_PER_DAY = 86400.0

# «Сказали один раз на файл»: неудаляемый файл (на Windows — занятый другим
# процессом) встречается на КАЖДОМ проходе sweep. Без памяти о сказанном
# предупреждение превратилось бы в периодический шум ровно того рода, которым
# логи и переполняются. Учёт при этом не глушится — счётчик растёт всегда.
_retention_warn_lock = threading.Lock()
_retention_warned_paths: set = set()
#: Потолок множества «кому уже сказали»: оно не должно само стать утечкой.
#: По достижении — предупреждения прекращаются (счётчик продолжает расти).
_RETENTION_WARNED_LIMIT = 512


def _reset_retention_warnings() -> None:
    """Забыть, о каких файлах уже предупреждали (тест-хелпер)."""
    with _retention_warn_lock:
        _retention_warned_paths.clear()


def _warn_retention_failure(path: Any, action: str, exc: BaseException) -> None:
    """Предупредить о сбое sweep — не более одного раза на файл за жизнь процесса."""
    key = _handler_key(path)
    with _retention_warn_lock:
        if key in _retention_warned_paths or len(_retention_warned_paths) >= _RETENTION_WARNED_LIMIT:
            return
        _retention_warned_paths.add(key)
    _fallback_logger.warning(
        "Ретеншен логов: не удалось %s '%s' (%s: %s). Файл остаётся на диске, "
        "место не освобождено; повторные отказы по этому же файлу не сообщаются.",
        action,
        path,
        type(exc).__name__,
        exc,
    )


def _new_retention_result() -> Dict[str, int]:
    return {
        "deleted": 0,
        "compressed": 0,
        "delete_failures": 0,
        "compress_failures": 0,
        "bytes_freed": 0,
    }


def _remove_file(path: Path, result: Dict[str, int]) -> bool:
    """Удалить файл; вернуть True, если после вызова его на диске нет.

    Отказ учитывается по ФАКТУ («файл на месте»), а не по типу исключения.
    Причина конкретная: при гонке двух подметальщиков за один файл Windows
    отдаёт проигравшему не ``FileNotFoundError``, а ``PermissionError``
    (WinError 5) — удаление уже идёт. Разбор по типу исключения давал бы
    ненулевой счётчик отказов на исправно работающей системе, то есть ровно
    ту ложную тревогу, ради борьбы с которой счётчик и заводился.
    """
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        # Кто-то удалил раньше — это результат, которого мы добивались.
        return True
    except OSError as exc:
        # ``os.path.exists`` (а НЕ ``Path.exists``) намеренно: на Windows файл в
        # состоянии delete-pending даёт PermissionError уже на stat, и
        # ``Path.exists`` это исключение пробрасывает. Трактовать его как «файл
        # на месте» значило бы записать в отказы ровно ту гонку, которая на
        # самом деле закончилась удалением. ``os.path.exists`` глотает любой
        # OSError и отвечает False — то есть «дотянуться нельзя», что для
        # нашего вопроса («осталось ли что удалять») и есть правильный ответ.
        if not os.path.exists(path):
            return True
        result["delete_failures"] += 1
        _warn_retention_failure(path, "удалить", exc)
        return False


def _compress_backup(path: Path, result: Dict[str, int], mtime: float) -> bool:
    """Сжать ротированный бэкап в ``<имя>.gz`` и удалить исходник.

    Инвариант: на диске остаётся РОВНО ОДНА копия. Оборвавшаяся компрессия
    убирает недописанный ``.gz`` (неполный архив хуже отсутствующего), а
    неудачное удаление исходника откатывает уже созданный ``.gz`` — иначе
    каталог получил бы обе копии и вырос вместо того, чтобы уменьшиться.

    Возраст переносится на архив (``os.utime``). Без этого компрессия обнуляла
    бы возраст: свежесозданный ``.gz`` выглядел бы для политики
    ``retention_days`` минутным, и достаточно старый бэкап не удалялся бы
    НИКОГДА — две политики работали бы друг против друга.
    """
    gz_path = Path(str(path) + ".gz")
    try:
        with open(path, "rb") as src, gzip.open(gz_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    except OSError as exc:
        result["compress_failures"] += 1
        _warn_retention_failure(path, "сжать", exc)
        try:
            os.remove(gz_path)
        except OSError:  # nosec B110 — уборка недописанного архива best-effort
            pass
        return False

    if not _remove_file(path, result):
        # Исходник занят (WinError 32): откатываем архив, иначе двойной вес.
        try:
            os.remove(gz_path)
        except OSError:  # nosec B110 — откат best-effort
            pass
        return False

    try:
        os.utime(gz_path, (mtime, mtime))
    except OSError:  # nosec B110 — перенос возраста best-effort, архив уже валиден
        pass
    result["compressed"] += 1
    return True


def _scan_directory(root: Path, protected: set) -> Tuple[List[List[Any]], int]:
    """Собрать кандидатов sweep и суммарный вес каталога.

    Returns:
        (entries, total_bytes) — ``entries`` это ``[path, mtime, size]`` только
        для файлов, которые МОЖНО трогать; ``total_bytes`` считает и защищённые
        тоже: место на диске они занимают наравне со всеми, и потолок каталога,
        который их «не видит», был бы потолком не на то.
    """
    entries: List[List[Any]] = []
    total = 0
    for path in root.rglob("*"):
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            # Файл исчез между listdir и stat (сосед отротировал) — пропускаем.
            continue
        total += stat.st_size
        if path.name in PROTECTED_BASENAMES or _handler_key(path) in protected:
            continue
        entries.append([path, stat.st_mtime, stat.st_size])
    return entries, total


def enforce_log_retention(
    directory: Any,
    *,
    retention_days: int = 0,
    retention_total_mb: int = 0,
    compress_rotated: bool = False,
    active_files: Iterable[Any] = (),
) -> Dict[str, int]:
    """Применить политики ретеншена к каталогу логов (рекурсивно).

    Порядок шагов не произволен: сперва возраст (не тратить CPU на компрессию
    того, что сейчас удалим), затем компрессия (освобождает место и может
    увести каталог под потолок сама), затем потолок (добирает остаток
    удалением старейших).

    Args:
        directory: корень каталога логов; обходится рекурсивно (``trace/`` и
            прочие подпапки — часть того же хозяйства).
        retention_days: удалять файлы старше N суток по mtime. 0 — выключено.
        retention_total_mb: потолок суммарного веса каталога, МБ; при
            превышении удаляются старейшие, пока каталог не уйдёт под потолок.
            0 — выключено.
        compress_rotated: сжимать ротированные бэкапы (``foo.log.1`` →
            ``foo.log.1.gz``). Уже сжатые ``.gz`` — обычные файлы для политик
            возраста и потолка, иммунитета у них нет.
        active_files: пути, в которые прямо сейчас пишут открытые каналы. Не
            удаляются и не сжимаются ни при каких условиях — удалить файл под
            работающим хэндлером значит потерять поток записей молча.

    Returns:
        Счётчики прохода: ``deleted``, ``compressed``, ``delete_failures``,
        ``compress_failures``, ``bytes_freed``.

    Note:
        Каждый менеджер метёт СВОЙ подкаталог (``logs/<процесс>/``), поэтому в
        штатной раскладке он не пересекается с чужими активными файлами.

        Прежняя формулировка здесь гласила «удалить активный файл соседнего
        процесса структурно невозможно» — это НЕВЕРНО, и ревью фазы это
        воспроизвело. Структурной защиты нет: есть список СВОИХ открытых файлов
        (``active_files``) плюс блокировка файловой системы. Второй менеджер,
        нацеленный на тот же каталог, активный файл первого удалить ПЫТАЕТСЯ —
        на Windows это даёт ``delete_failures=1`` и файл выживает по WinError 32,
        **на POSIX он был бы удалён**. Менеджер без ``process`` метёт корень
        рекурсивно, включая каталоги чужих процессов. В проде менеджеры
        получают ``process`` (``process_managers.py``), поэтому это край, а не
        рабочий режим — но называть случайность блокировки ФС гарантией нельзя.

        Обратная сторона разводки по подкаталогам: каталоги давно умерших
        процессов не метёт никто — это разовая уборка, а не рост, и она вне
        объёма Ф0.7.
    """
    result = _new_retention_result()
    if retention_days <= 0 and retention_total_mb <= 0 and not compress_rotated:
        # Обе политики выключены — sweep обязан быть НИЧЕМ, а не «почти ничем»:
        # выход до обхода каталога, ни одного stat.
        return result

    root = Path(directory)
    if not root.is_dir():
        return result

    protected = {_handler_key(p) for p in active_files}
    entries, total = _scan_directory(root, protected)

    # 1. Возраст.
    if retention_days > 0:
        cutoff = time.time() - retention_days * _SEC_PER_DAY
        survivors: List[List[Any]] = []
        for entry in entries:
            path, mtime, size = entry
            if mtime < cutoff and _remove_file(path, result):
                result["deleted"] += 1
                result["bytes_freed"] += size
                total -= size
                continue
            survivors.append(entry)
        entries = survivors

    # 2. Компрессия ротированных бэкапов.
    if compress_rotated:
        for entry in entries:
            path, mtime, size = entry
            if not _ROTATED_BACKUP_RE.search(path.name):
                continue
            if not _compress_backup(path, result, mtime):
                continue
            gz_path = Path(str(path) + ".gz")
            try:
                new_size = gz_path.stat().st_size
            except OSError:
                new_size = 0
            total -= size - new_size
            entry[0] = gz_path
            entry[2] = new_size

    # 3. Потолок каталога — старейшие уходят первыми.
    if retention_total_mb > 0:
        cap = retention_total_mb * _MB
        if total > cap:
            for entry in sorted(entries, key=lambda e: e[1]):
                if total <= cap:
                    break
                path, _mtime, size = entry
                if _remove_file(path, result):
                    result["deleted"] += 1
                    result["bytes_freed"] += size
                    total -= size

    return result


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
    """Канал записи в консоль — с пределом ожидания занятой консоли (R2).

    Запись в консоль синхронна в потоке-эмитенте, и после Ф0.9 путь
    ``error``/``critical`` идёт мимо батч-буфера вообще: прямо в
    ``stream.write()`` вызывающего потока. Если stdout перенаправлен в трубу,
    которую никто не читает, поток виснет навсегда — и до этой правки за ним
    выстраивались ВСЕ остальные потоки-эмитенты: один заткнувшийся приёмник
    останавливал процесс целиком.

    Предел ставится там, где он достижим: ожидание ОСВОБОЖДЕНИЯ консоли
    ограничено :attr:`_BUSY_WAIT_SEC`, после чего запись отбрасывается со
    статусом ``error`` (не ``skipped``: запись никуда не попала, и floor
    ошибок обязан это узнать). Обычная конкуренция стоит микросекунды и в
    предел не упирается никогда — потери начинаются только на реально
    застрявшей консоли.

    Одного предела мало, и это выяснилось не сразу (R12). Ждать по
    :attr:`_BUSY_WAIT_SEC` на КАЖДОЙ записи — значит платить четверть секунды
    за строку, пока консоль стоит: процесс не виснет, но ползёт, а на
    пер-кадровом логировании это хуже честного отказа. Поэтому предел
    дополнен **размыкателем**: после :attr:`_DEGRADE_AFTER_TIMEOUTS` подряд
    канал переходит в разомкнутое состояние и перестаёт ждать вовсе — берёт
    лок без блокировки и мгновенно отбрасывает. Стоимость затыка падает с
    «0.25 с на запись» до нуля.

    Возврат в строй бесплатен и автоматичен: та же неблокирующая попытка
    удастся, как только застрявший поток отпустит лок. Отдельного таймера
    перепроверки нет — состояние канала и есть проба.

    ЧЕГО ЭТО НЕ ДЕЛАЕТ, и это надо знать честно: поток, который УЖЕ вошёл в
    блокирующий ``stream.write()``, остаётся заблокированным навсегда.
    Ограничить его можно только вынеся запись в отдельный поток-писатель.
    Такой размен здесь отвергнут сознательно: он покупает один потерянный
    поток ценой того, что консоль перестаёт переживать падение процесса
    (очередь writer'а умирает вместе с ним) — а консоль это то, на что
    смотрит человек в момент падения. Размыкатель снимает системную цену
    затыка, не трогая этот размен.
    """

    #: Сколько ждать освобождения консоли, прежде чем бросить запись.
    #: Здоровая запись занимает микросекунды — этот предел на неё не влияет.
    _BUSY_WAIT_SEC = 0.25
    #: После скольких отказов подряд перестать ждать вовсе (разомкнуть).
    #: Не 1: одиночный таймаут может быть случайным всплеском, а размыкание —
    #: это переход к гарантированным потерям, и объявлять его по одному
    #: событию значит терять записи на дрожании.
    _DEGRADE_AFTER_TIMEOUTS = 3
    #: С какой длительности запись считается подозрительно медленной.
    _SLOW_WRITE_SEC = 0.05
    #: Не чаще одного предупреждения за интервал — по тем же соображениям,
    #: что у ``_SafeRotatingFileHandler``: затык даёт отказ на КАЖДОЙ записи.
    _WARNING_INTERVAL_SEC = 60.0

    def __init__(self, config: LoggerChannelSchema):
        super().__init__(config)
        self.handler = logging.StreamHandler()
        formatter = logging.Formatter(config.format)
        self.handler.setFormatter(formatter)

        self._write_lock = threading.Lock()
        self._counter_lock = threading.Lock()
        self.console_writes_dropped = 0
        self.console_slow_writes = 0
        self._consecutive_timeouts = 0
        self._max_write_sec = 0.0
        self._last_warning_ts = 0.0

    @property
    def console_degraded(self) -> bool:
        """Канал разомкнут: ожидание больше не оплачивается, записи отбрасываются сразу."""
        return self._consecutive_timeouts >= self._DEGRADE_AFTER_TIMEOUTS

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        # Разомкнутый канал не ждёт вообще: неблокирующая попытка здесь и есть
        # проба «консоль ожила?» — отдельный таймер перепроверки не нужен.
        if self.console_degraded:
            acquired = self._write_lock.acquire(blocking=False)
        else:
            acquired = self._write_lock.acquire(timeout=self._BUSY_WAIT_SEC)

        if not acquired:
            with self._counter_lock:
                self.console_writes_dropped += 1
                self._consecutive_timeouts += 1
                dropped = self.console_writes_dropped
            self._warn_console_stuck(dropped)
            return {
                "status": "error",
                "error": "console busy: запись отброшена по пределу ожидания",
                "channel": self.name,
            }

        started = time.monotonic()
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
        finally:
            elapsed = time.monotonic() - started
            self._write_lock.release()
            with self._counter_lock:
                # Сбрасываем ЗДЕСЬ, а не сразу после взятия лока: «вошли» ещё не
                # значит «вышли». Поток, взявший лок и застрявший внутри
                # stream.write(), не имеет права объявить канал здоровым — иначе
                # размыкатель смыкался бы ровно тем потоком, который и застрял.
                self._consecutive_timeouts = 0
                if elapsed >= self._SLOW_WRITE_SEC:
                    self.console_slow_writes += 1
                    self._max_write_sec = max(self._max_write_sec, elapsed)

    def _warn_console_stuck(self, dropped_total: int) -> None:
        """Троттлированное предупреждение о занятой консоли.

        Уходит через fallback-логгер (stdlib), а не через собственную
        маршрутизацию: сообщение о том, что консоль не принимает записи, не
        имеет права идти в консоль тем же путём, который сейчас затык.
        """
        now = time.monotonic()
        with self._counter_lock:
            if now - self._last_warning_ts < self._WARNING_INTERVAL_SEC:
                return
            self._last_warning_ts = now
        _fallback_logger.warning(
            "Консольный канал '%s' не освободился за %.2f с — запись отброшена "
            "(всего отброшено: %d). Похоже, поток вывода перенаправлен туда, где его "
            "никто не читает: записи в консоль теряются, файловые каналы не затронуты.",
            self.name,
            self._BUSY_WAIT_SEC,
            dropped_total,
        )

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        with self._counter_lock:
            info.update(
                {
                    "console_writes_dropped": self.console_writes_dropped,
                    "console_slow_writes": self.console_slow_writes,
                    "console_degraded": self._consecutive_timeouts >= self._DEGRADE_AFTER_TIMEOUTS,
                    "max_write_sec": round(self._max_write_sec, 4),
                }
            )
        return info

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
