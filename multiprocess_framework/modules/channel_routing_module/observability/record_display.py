# -*- coding: utf-8 -*-
"""
record_display — единый нормализатор записей наблюдаемости в display-вид (Ф5.20b).

Живой хвост hub→GUI (Ф5.20b) и целая история из стора (Ф5.20a) должны отдавать
панели РАВНЫЙ по форме record, иначе виджет знал бы два формата. Это ЕДИНЫЙ
источник нормализации: ``ObservabilityStore`` тоже строит строку таблицы через
``hub_record_to_display`` (json-сериализация ``extra`` — только на границе БД),
поэтому форма live == форма history по построению (5.21 (b): убран дубль
``_row_from_record``).

Display-вид: ``{kind, process, module, ts, severity, message, extra(dict)}``
(стор добавляет ``id``). Собирается из двух живых источников:

  - hub-запись (дренаж log/stats):   {kind, module, ts, severity|metric_type, ...}
  - LogRecord-dict (error-tap):       {timestamp, level, scope, message, module, extra}

**Поле ``process`` (5.21 (c)):** hub тегирует запись ``module`` = именем ПРОЦЕССА
(hub — один на процесс), а error write-through несёт ``module`` = подробным именем
ИСТОЧНИКА (напр. ``CapturePlugin``/``main``). Чтобы вкладка всегда показывала
процесс-источник (``camera_0``), процесс проставляет форвардер/tap (знает
``sender``); при отсутствии — падаем на ``module``.

Функции чистые (Qt-free, без внешних зависимостей) — переиспользуются push-каналом
и стором, тестируются в изоляции.
"""

from __future__ import annotations

from typing import Any, Dict

from ..levels import UNKNOWN_SEVERITY, UNSPECIFIED, severity_of
from .observability_hub import KIND_STATS

KIND_ERROR = "error"  # локальная константа (не тянем observability_store → без цикла store↔display)

_ENVELOPE_KEYS = ("kind", "module", "process", "ts", "severity", "message", "observed_ts")
#: ``observed_ts`` в конверте, а не в ``extra`` (Ф3.6): иначе отметка приёма
#: уезжала бы в JSON-мешок, и пороговый/свежестный запрос по ней в сторе
#: пришлось бы делать разбором JSON вместо колонки.


#: Ключ отметки ПРИЁМА записи наблюдателем (Ф3.4). Рядом с ``ts`` и по тому же
#: сокращению — одно написание на display-вид, а не ``ts`` + ``observed_timestamp``.
OBSERVED_TS_KEY = "observed_ts"


def severity_number_for(kind: str, severity: str) -> int:
    """``SeverityNumber`` строки display-вида (Ф3.6).

    Выводится, а не хранится вторым источником правды: таблица чисел одна на
    весь слой (:data:`..levels.SEVERITY_NUMBERS`), здесь только применение.

    **У плоскости статистики оси важности нет вовсе**, и число берётся по
    ``kind``, а НЕ по неудаче ранжирования: в колонке ``severity`` у stats лежит
    ``metric_type`` (``gauge``/``counter``), и «не отранжировалось» там значит
    «это не уровень», а у лога — «опечатка в имени уровня». Считай мы их одним
    способом, метрика и опечатка стали бы неразличимы (:data:`..levels.UNSPECIFIED`
    ровно для первого случая и заведён).

    Считается в ЕДИНОМ нормализаторе, а не в сторе: форма живого хвоста и формa
    истории обязаны совпадать по построению — иначе вкладка знала бы два формата,
    и пороговый фильтр работал бы на одной половине данных.
    """
    if kind == KIND_STATS:
        return UNSPECIFIED
    number = severity_of(severity)
    return UNSPECIFIED if number == UNKNOWN_SEVERITY else number


def stamp_observed(records: Any, now: float) -> Any:
    """Проставить записям время, когда их УВИДЕЛ приёмник (OTel ``ObservedTimestamp``).

    Ф3.4. Отвечает на вопрос, на который ``ts`` ответить не может: **свеж ли
    хвост**. Запись несёт момент эмиссии; если плоскость наблюдаемости встала,
    в GUI приедут записи с честными старыми ``ts``, и «ничего не происходит»
    будет неотличимо от «хвост застрял». Разность ``observed_ts - ts`` и есть
    задержка доставки, а на истории она восстановима только если её записали.

    **Штампует ПРИНИМАЮЩАЯ сторона, и только она.** У эмитента отметка была бы
    равна ``ts`` с точностью до микросекунд и не несла бы ни бита: наблюдатель и
    источник — один процесс. Информация появляется ровно на границе процессов,
    поэтому единственное законное место вызова — обработчик приёма у подписчика
    (GUI), а не форвардер, который отправляет.

    Часы — **параметром**, а не ``time.time()`` внутри: глобальный патч часов в
    тестах даёт флейк, а зависимость передаётся явно и проверяется литералом.

    Существующий ключ **не перетирается**: пересылка через несколько рук должна
    сохранять отметку первого, кто увидел, — иначе задержка обнулялась бы на
    каждом пересказе.

    Не путать с ``observed_at`` (:data:`..core.channel_routing_manager.OBSERVED_AT_KEY`) —
    там момент СНЯТИЯ СНИМКА СЧЁТЧИКОВ для расчёта темпа (5.6/5.7), а не
    приём записи. Разные вещи, похожие имена; см. дисциплину ADR-LOG-005.

    Args:
        records: список display-записей (мутируются на месте — их только что
            собрали из пришедшего сообщения, владельца у них ещё нет).
        now: показания часов приёмника (wall). Кросс-процессно сравнимы на одной
            машине — та же конвенция, что у ``capture_ts`` кадра.

    Returns:
        Тот же список — ради читаемости вызова, не ради копии.
    """
    if not isinstance(records, list):
        return records
    for record in records:
        if isinstance(record, dict) and not record.get(OBSERVED_TS_KEY):
            record[OBSERVED_TS_KEY] = now
    return records


def hub_record_to_display(record: Dict[str, Any], process: str = "") -> Dict[str, Any]:
    """Нормализовать hub-запись (drain log/stats) в display-вид.

    ЕДИНЫЙ нормализатор для live-хвоста И стора: ``extra`` здесь — dict (не
    JSON-строка), стор сериализует его в JSON только на границе БД. Для stats
    severity=metric_type, message=metric.

    Args:
        record: hub-запись (или tap-запись стора той же формы, с ключом ``context``).
        process: имя процесса-источника; пусто → ``record['process']`` → ``module``.
    """
    kind = record.get("kind", "")
    module = record.get("module", "")
    ts = float(record.get("ts", 0.0) or 0.0)
    proc = process or record.get("process") or module

    if kind == KIND_STATS:
        severity = str(record.get("metric_type", "")).lower()
        message = record.get("metric", "")
        extra: Dict[str, Any] = {"value": record.get("value"), "tags": record.get("tags", {})}
    else:
        severity = str(record.get("severity", "")).lower()
        message = record.get("message", "")
        extra = {k: v for k, v in record.items() if k not in _ENVELOPE_KEYS}

    display = {
        "kind": kind,
        "process": proc,
        "module": module,
        "ts": ts,
        "severity": severity,
        "severity_number": severity_number_for(kind, severity),
        "message": message,
        "extra": extra,
    }
    # Отметка приёма ставится ЧУЖИМ процессом (Ф3.4) и потому есть не всегда.
    # Ключ добавляется только когда она реально была: постоянный ``None`` весил
    # бы в каждой живой записи и читался бы как «принято в 1970».
    observed = record.get(OBSERVED_TS_KEY)
    if observed:
        display[OBSERVED_TS_KEY] = observed
    return display


def log_record_to_display(record_dict: Dict[str, Any], kind: str = KIND_ERROR, process: str = "") -> Dict[str, Any]:
    """Нормализовать LogRecord-dict (error/critical у tap'а) в display-вид.

    На вход — ``LogRecord.to_dict()``: {timestamp, level, scope, message, module, extra}.
    По дизайну Ф5.16 error/critical идут write-through в реальный менеджер, а tap
    ловит их у sink'а — поэтому kind по умолчанию 'error'.

    Args:
        process: имя процесса-источника (tap знает ``sender``); пусто → падаем на
            ``module`` LogRecord (подробное имя источника) — хуже, но не пусто.
    """
    module = record_dict.get("module", "")
    severity = str(record_dict.get("level", "")).lower()
    return {
        "kind": kind,
        "process": process or module,
        "module": module,
        "ts": float(record_dict.get("timestamp", 0.0) or 0.0),
        "severity": severity,
        # Ф3.6: оба нормализатора дают ОДНУ форму — иначе пороговый фильтр
        # работал бы на половине данных (error-tap идёт этой дорогой).
        "severity_number": severity_number_for(kind, severity),
        "message": record_dict.get("message", ""),
        # extra под ключом "context" — паритет с историей: StoreTapChannel кладёт
        # LogRecord.extra в "context", и стор сохраняет его как {"context": {...}}.
        # Плоский extra здесь давал бы РАЗНУЮ форму записи в live-хвосте и после
        # reload из стора (нарушение контракта record_display).
        "extra": {"context": record_dict.get("extra", {}) or {}},
    }
