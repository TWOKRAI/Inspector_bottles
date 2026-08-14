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

from ..levels import ERROR_SEVERITY, UNKNOWN_SEVERITY, UNSPECIFIED, severity_of
from .observability_hub import KIND_STATS, STATS_AGGREGATE_KEY

KIND_ERROR = "error"  # локальная константа (не тянем observability_store → без цикла store↔display)
KIND_LOG = "log"

_ENVELOPE_KEYS = ("kind", "module", "process", "ts", "severity", "message", "observed_ts")
#: ``observed_ts`` в конверте, а не в ``extra`` (Ф3.6): иначе отметка приёма
#: уезжала бы в JSON-мешок, и пороговый/свежестный запрос по ней в сторе
#: пришлось бы делать разбором JSON вместо колонки.


#: Ключ отметки ПРИЁМА записи наблюдателем (Ф3.4). Рядом с ``ts`` и по тому же
#: сокращению — одно написание на display-вид, а не ``ts`` + ``observed_timestamp``.
OBSERVED_TS_KEY = "observed_ts"

#: Значение колонки ``severity`` у записи-агрегата (задача 2.1). У сырой
#: stats-записи там лежит ``metric_type`` (``counter``/``gauge``), у агрегата
#: типа нет — в нём метрики РАЗНЫХ типов. Пустая строка сделала бы колонку
#: неотличимой от «тип не проставлен»; слово называет класс записи.
STATS_SNAPSHOT_SEVERITY = "snapshot"

#: Ключи записи-агрегата, которые нормализатор читает по имени. Остальное
#: содержимое едет в ``extra`` целиком — правилом конверта, как у лога.
SNAPSHOT_METRICS_KEY = "metrics"
SNAPSHOT_TOTAL_KEY = "total_count"


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


def snapshot_message(record: Dict[str, Any]) -> str:
    """Текст записи-агрегата: имена метрик окна (задача 2.1).

    **Имена в тексте — ради поиска, а не ради чтения.** Полнотекстовый индекс
    стора (1.6) построен по ``message``/``module``/``process`` и НЕ смотрит в
    JSON-мешок ``extra``. Положи мы имена только в ``extra`` — снапшот нашёлся
    бы фильтром по виду записи и никогда по имени метрики, то есть ровно на тот
    вопрос, ради которого он и едет в стор («что было с `frames.dropped`?»),
    ответа бы не было.

    Числа сюда НЕ дублируются: значения, типы и теги лежат в ``extra``
    структурно (урок 3.2/3.4 — ``repr`` в строку читается глазами и не читается
    ничем больше). Текст — поисковый ключ, а не второй источник правды.

    Разность ``total_count − len(metrics)`` называется вслух: она станет
    ненулевой, когда 2.2 введёт потолок кардинальности, и «сколько метрик было
    в окне» не должно зависеть от того, сколько их доехало (тот же счёт, что у
    предела строки снапшота в ``LogStatsChannel``).
    """
    metrics = [m for m in (record.get(SNAPSHOT_METRICS_KEY) or []) if isinstance(m, dict)]
    total = record.get(SNAPSHOT_TOTAL_KEY, len(metrics))

    # Имена — БЕЗ повторов. Единица окна — серия (имя × теги), и одно имя даёт
    # столько серий, сколько у него сочетаний тегов. Живой замер стенда
    # 2026-08-13: у процесса `devices` 384 серии на 4 разных имени, и текст
    # записи весил 16 924 Б — 17 килобайт четырёх слов, повторённых сотнями.
    # Поиску повтор не добавляет ничего (FTS5 индексирует термы), а в стор он
    # едет каждым снапшотом.
    names, seen = [], set()
    for metric in metrics:
        name = str(metric.get("name", ""))
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    # Тот же зачин, что у строки снапшота в ``performance.log``
    # (``LogStatsChannel._format_snapshot``): оператор ищет одним словом в обоих
    # приёмниках одной плоскости. Знак ``×`` тут стоял и снят — консоль Windows
    # (cp1251/cp866) роняет на нём вывод, а зачин читают в том числе консолью.
    head = f"metrics snapshot (count={total})"
    if len(names) < len(metrics):
        # Иначе «count=384» рядом со списком из четырёх слов читалось бы как
        # «380 имён потерялись», а потерь тут нет — есть теги.
        head += f", имён {len(names)}"
    body = f": {', '.join(names)}" if names else ""

    # Опущенное считается по СЕРИЯМ, а не по именам: свернувшиеся в одно имя
    # серии никуда не делись, они в ``extra``. Разность станет ненулевой, когда
    # 2.2 введёт потолок кардинальности и часть серий не доедет.
    omitted = int(total) - len(metrics) if isinstance(total, int) else 0
    tail = f" … опущено {omitted} из {total}" if omitted > 0 else ""
    return f"{head}{body}{tail}"


def hub_record_to_display(record: Dict[str, Any], process: str = "") -> Dict[str, Any]:
    """Нормализовать hub-запись (drain log/stats) в display-вид.

    ЕДИНЫЙ нормализатор для live-хвоста И стора: ``extra`` здесь — dict (не
    JSON-строка), стор сериализует его в JSON только на границе БД.

    У ``stats`` веток ДВЕ, и назвать одну значило бы описать не ту, что едет:
      * агрегат окна (``aggregate=true``) → ``severity="snapshot"``,
        ``message`` — строка снапшота; так выглядят ВСЕ записи живого стенда
        (замер 2026-08-14: 112 строк вкладки, снапшоты раз в 10 с);
      * одиночная метрика → ``severity=metric_type``, ``message=metric``.

    Args:
        record: hub-запись (или tap-запись стора той же формы, с ключом ``context``).
        process: имя процесса-источника; пусто → ``record['process']`` → ``module``.
    """
    kind = record.get("kind", "")
    module = record.get("module", "")
    ts = float(record.get("ts", 0.0) or 0.0)
    proc = process or record.get("process") or module

    if kind == KIND_STATS and record.get(STATS_AGGREGATE_KEY):
        # Задача 2.1. Запись-АГРЕГАТ (снапшот окна) — не метрика, и «четыре
        # ключа» ниже её уничтожают: ни ``metric``, ни ``value`` у неё нет, и
        # в БД уехала бы строка `message="" extra={"value": null}` при зелёном
        # «kind=stats > 0». Дефект найден ревью №2 спеки ЧТЕНИЕМ КОДА — живой
        # прогон его бы не заметил: строка-то есть.
        severity = STATS_SNAPSHOT_SEVERITY
        message = snapshot_message(record)
        # То же правило конверта, что у лога: всё, что не конверт, — в extra.
        # Перечислять ключи агрегата поимённо значило бы завести второе место,
        # где описан его состав, и потерять поле 2.2 молча.
        extra: Dict[str, Any] = {k: v for k, v in record.items() if k not in _ENVELOPE_KEYS}
    elif kind == KIND_STATS:
        severity = str(record.get("metric_type", "")).lower()
        message = record.get("metric", "")
        extra = {"value": record.get("value"), "tags": record.get("tags", {})}
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


def kind_for_severity(severity_number: int) -> str:
    """Вид записи по её важности: ``error`` от ERROR и выше, иначе ``log`` (Б-4).

    **Вид считает ИСТОЧНИК записи, а не канал, который её везёт.** До Ф5.2 оба
    канала (стор-tap и live-форвардер) получали ``kind`` константой в конструкторе
    и висели ОБА на ``logger_manager`` — то есть любая запись, прошедшая порог
    tap'а, метилась ошибкой. Живьём это выглядело так: INFO-снимок метрик приехал
    в хвост как ``kind: "error"``, а в сторе все 303 016 строк оказались ошибками —
    вкладки «Логи» и «Статистика» были структурно пусты не потому, что записей
    нет, а потому что каждая называлась чужим именем.

    Порог — тот же ``ERROR_SEVERITY``, которым уже выражен инвариант «≥17 = ошибка»
    (Ф3.1). Второго определения аварийности не заводится: разойдясь однажды, они
    дали бы запись, которая для floor'а ошибка, а для вкладки — лог.

    Неопознанный уровень приходит сюда **числом** ``UNSPECIFIED = 0`` — не
    ``UNKNOWN_SEVERITY``: до этой функции строку уже прочёл
    :func:`severity_number_for`, и он переводит «имя не опознано» в «оси важности
    нет». Ноль ниже порога, поэтому такая запись становится ``log``, и это
    сознательно: опечатка в имени уровня не повод объявить запись аварией.
    Проверено инъекцией — первая её редакция целилась в ``-1`` и не убила ни
    одного теста, потому что до сюда ``-1`` не доходит вовсе.
    """
    return KIND_ERROR if severity_number >= ERROR_SEVERITY else KIND_LOG


def log_record_to_display(record_dict: Dict[str, Any], process: str = "") -> Dict[str, Any]:
    """Нормализовать LogRecord-dict (tap на менеджере) в display-вид.

    На вход — ``LogRecord.to_dict()``: {timestamp, level, scope, message, module, extra}.
    ``kind`` **выводится из важности самой записи** (:func:`kind_for_severity`), а не
    приходит параметром: параметр и был дефектом Б-4 — см. его докстринг.

    Args:
        process: имя процесса-источника (tap знает ``sender``); пусто → падаем на
            ``module`` LogRecord (подробное имя источника) — хуже, но не пусто.
    """
    module = record_dict.get("module", "")
    severity = str(record_dict.get("level", "")).lower()
    # Число считается ДО вида и одно на оба поля: вид, посчитанный по другому
    # прочтению уровня, чем число, дал бы строку, где `kind=error` соседствует с
    # `severity_number` ниже порога — и фильтр вкладки разошёлся бы с её колонкой.
    number = severity_number_for(KIND_LOG, severity)
    kind = kind_for_severity(number)
    return {
        "kind": kind,
        "process": process or module,
        "module": module,
        "ts": float(record_dict.get("timestamp", 0.0) or 0.0),
        "severity": severity,
        # Ф3.6: оба нормализатора дают ОДНУ форму — иначе пороговый фильтр
        # работал бы на половине данных (tap идёт этой дорогой). Число берётся
        # ПОСЧИТАННОЕ выше, а не пересчитывается: два вычисления одного поля —
        # это два места, где оно может разойтись.
        "severity_number": number,
        "message": record_dict.get("message", ""),
        # extra под ключом "context" — паритет с историей: StoreTapChannel кладёт
        # LogRecord.extra в "context", и стор сохраняет его как {"context": {...}}.
        # Плоский extra здесь давал бы РАЗНУЮ форму записи в live-хвосте и после
        # reload из стора (нарушение контракта record_display).
        "extra": {"context": record_dict.get("extra", {}) or {}},
    }
