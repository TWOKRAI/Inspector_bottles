"""telemetry_read_model.py — generic Qt-free ядро read-model телеметрии.

Принцип «запись — всегда, чтение — локально, история — по запросу». Backend
публикует телеметрию постоянно (троттлинг на стороне источника) в дерево
StateStore; потребитель держит ОДИН локальный read-model, наполняемый ОДНИМ
потоком дельт, и читает снимок/историю локально — без похода на сервер.

Ядро — чистое хранилище проекции состояния плюс кольцевые буферы истории. Оно
**не знает транспорта**: :meth:`ingest` принимает уже разобранную дельту
``(path, value, deleted)``. Обёртки над конкретным конвертом парсят своё
сообщение и вызывают ingest():

    * GUI (:class:`TelemetryViewModel`, Qt) — конверт ``state_delta`` +
      коалесинг сигнала обновления;
    * headless-драйвер диагностики (backend_ctl) — push ``state.changed`` из
      сокета.

Модуль generic: он не знает ни имён процессов, ни конкретного набора метрик
приложения. Набор путей, для которых копится история (``tracked_suffixes``), и
параметры окна — аргументы конструктора. Дефолт ``DEFAULT_TRACKED_SUFFIXES``
покрывает штатные gated-метрики фреймворка (см. ``process_module`` —
каталог метрик и форму дерева ``build_worker_telemetry``); приложение с
дополнительными метриками передаёт собственный набор суффиксов.

Инвариант: read-model НЕ создаёт серверных подписок и не делает блокирующий IPC.
Он не держит ссылки ни на router, ни на state-proxy — питается исключительно
входящими дельтами через :meth:`ingest`.

Dict-at-Boundary: ядро оперирует уже разобранными значениями (не live
SchemaBase) — граница процессов соблюдена на стороне обёртки.
"""

from __future__ import annotations

import collections
import math
import time
from typing import Any, Callable

from multiprocess_framework.modules.state_store_module.core.freshness import FRESH_KEY, read_value
from multiprocess_framework.modules.state_store_module.core.leaf_copy import LeafCopy

# Суффиксы путей телеметрии, для которых копится кольцевой буфер ИСТОРИИ (спарклайны).
# Это НАБОР ИСТОРИИ read-модели, а НЕ зеркало publish-gate (каталог метрик в
# ``process_module``): пересекается с ним, но намеренно отличается — ``.state.uptime``
# трекается для истории карточки процесса (в gate его нет, публикуется всегда), а
# транспортный счётчик ``shm`` в gate есть, но своей спарклайн-серии не имеет.
# Форма суффикса — по телеметрийному поддереву (``build_worker_telemetry``): агрегат
# ``processes.<P>.state.fps`` → ``.state.fps``, per-worker ``…workers.<w>.effective_hz``
# → ``.effective_hz`` (матч по СУФФИКСУ, независимо от имени процесса/воркера).
# Плагинная метрика Ф1 «порта наблюдений» лежит на ``…state.plugins.<писатель>.<имя>``
# и матчится ТЕМ ЖЕ набором — через каноническую свёртку пути, см. ``_is_tracked``.
# Потребитель задаёт свой набор истории через ``tracked_suffixes``.
DEFAULT_TRACKED_SUFFIXES: tuple[str, ...] = (
    ".state.fps",
    ".state.latency_ms",
    ".state.uptime",
    ".effective_hz",
    ".cycle_duration_ms",
)

# Поля метки писателя (``freshness.stamp``): ``read`` собирает их из текущего состояния.
# Форма метки живёт в ``state_store_module.core.freshness``; дрейф двух списков ловит
# ``test_read_model_freshness.py::test_mark_fields_match_the_writer_stamp``.
_MARK_FIELDS: tuple[str, ...] = ("seq", "src_ts", "incarnation", "tick_sec")

# Лист, появление которого «закрывает такт» писателя метки (M-16, довыставление хвоста).
_SRC_TS_SUFFIX = f".{FRESH_KEY}.src_ts"

# Точки этих путей ВСЕГДА держат время приёма, а не ``src_ts``: их пишет не писатель метки.
# ``.state.uptime`` публикует ``ProcessMonitor`` (~1 Гц) своим тактом; довыставление
# перекрасило бы последнюю точку кольца в более раннее время, и кольцо перестало бы быть
# хронологическим. Имена Task 1.8 (``rate_hz``, ``cycle_ms``) пишет тот же такт, что и метку,
# поэтому остаются на времени источника и сюда не входят. Константа модуля, не параметр
# конструктора: смена набора — решение модуля, а не потребителя.
_RECEIPT_TIME_SUFFIXES: tuple[str, ...] = (".state.uptime",)

_MISSING: Any = object()


def _process_root(path: str) -> str | None:
    """``processes.<P>.<что-то>`` -> ``processes.<P>``; иначе ``None``.

    Корень записи процесса — адрес метки ``<root>._fresh`` и ключ хвоста довыставления.
    """
    parts = path.split(".", 2)
    if len(parts) < 3 or parts[0] != "processes" or not parts[1]:
        return None
    return f"processes.{parts[1]}"


def _canonical_plugin_path(path: str) -> str | None:
    """``…state.plugins.<писатель>.<имя>`` → ``…state.<имя>``; иначе ``None``.

    Единственная точка, знающая про раскладку поддерева писателя (Ф1 «порта
    наблюдений»). Свёртка НАРОЧНО узкая — ровно хвост из четырёх сегментов
    ``state.plugins.<писатель>.<имя>``.

    **Из двух половин проверки несущая ОДНА — про ``plugins``** (ревью Task 1.4,
    находка 1; прежний докстринг подавал их как необходимую пару, и это было
    неправдой). Она держит живой промах: ``processes.<P>.state.cam.actual.fps``
    пишет ``camera_service``, и без неё путь свернулся бы в
    ``processes.<P>.state.fps`` — то есть actual-параметр камеры начал бы копить
    кольцо истории под суффиксом АГРЕГАТА. Узлов ``plugins`` в дереве четыре
    (``config.plugins``, ``plugins.<плагин>.io_peek``, корневой каталог,
    ``state.plugins``), поэтому широкий матч по «есть сегмент plugins» тоже не
    годится — нужна именно позиция.

    Половина про ``state`` — **оборона в глубину, а не несущая проверка**:
    свёртка ``segments[:-3] + segments[-1:]`` делает хвост ``.state.<имя>``
    возможным ТОЛЬКО когда ``segments[-4] == "state"``, значит через
    :meth:`TelemetryReadModel._is_tracked` её снятие ненаблюдаемо. Оставлена,
    потому что функция обещает адрес ИМЕННО из ``state``, и без неё вернула бы
    свёртку для ``config.plugins.<x>.<y>`` — ложь про собственный контракт.
    Наблюдаема она только прямой проверкой этой функции, и такая проверка есть
    (``TestFoldingIsNarrow::test_config_plugins_returns_none_from_the_folder_itself``).

    Вложенных под писателем уровней свёртка не поддерживает намеренно:
    ``…plugins.<писатель>.workers.<w>.effective_hz`` останется несвёрнутым, и
    поймает его прямой суффикс ``.effective_hz`` — тот от раскладки не зависит.
    """
    segments = path.split(".")
    if len(segments) < 4:
        return None
    if segments[-3] != "plugins":  # несущая: держит state.cam.actual.<метрика>
        return None
    if segments[-4] != "state":  # оборона в глубину, см. докстроку
        return None
    return ".".join(segments[:-3] + segments[-1:])


class TelemetryReadModel:
    """Read-model телеметрии: снимок ``path → value`` + кольцевые буферы истории.

    Питается потоком уже разобранных дельт (:meth:`ingest`). НЕ создаёт серверных
    подписок и не держит транспорт. Late-binding: читатель, обратившийся ПОСЛЕ
    публикации, видит актуальный снимок сразу.

    Что умеет:
        * ingest(path, value, deleted)  — внести одну разобранную дельту.
        * ingest_poll_snapshot(values, requested_at_seq) — влить ответ ОПРОСА,
          отбросив пути, перезаписанные push'ем уже после отправки запроса.
        * get(path) / snapshot(prefix)  — чтение текущего снимка.
        * history(path, since)          — кольцевой буфер последних ~N минут по
          ключевым метрикам для мгновенных спарклайнов без похода в БД. ``ts``
          точки — время ИСТОЧНИКА (``src_ts`` метки писателя того же такта), а
          если метки нет — время приёма (``clock``); см. :meth:`_apply_put`.
        * read(path, key, alive_incarnation) — значение листа вместе с классом
          свежести (``no_data``/``fresh``/``stale``/``writer_gone``) и возрастом.

    **Инвариантов у read-model ДВА, и второй появился позже первого.**

    1. *Кольцо истории пишет только поток.* Опрос отдаёт УРОВЕНЬ, а не точку
       потока, и вливается с ``record_history=False`` (ADR-139): второй писатель
       в ``deque`` фиксированной длины молча сокращал бы окно спарклайна.
    2. *Порядок записи судится номером, а не временем* (S-1, нога B). У
       read-model ДВА входа — push и ответ опроса, — и они приходят по разным
       дорогам с разной задержкой. Ответ опроса, отправленный ДО push'а и
       пришедший ПОСЛЕ него, воскрешал снятое значение (замер: оборот запроса
       7.5–10 с; ``t2 push -> None``, ``t3 poll -> 12.5``). Сторожем служит
       :attr:`write_seq` — счётчик ПРИНЯТЫХ push-записей: каждый путь помнит
       номер своей последней push-записи, и ответ опроса, чей номер отправки
       старше, по этому пути отбрасывается.

    **Почему номер, а не часы.** На Windows разрешение ``time.monotonic`` — 15.6
    мс, и две записи одного оборота цикла получают ОДНУ метку: часы не отличили
    бы «push раньше» от «push позже». Судится не «когда», а «кто раньше записал»,
    и на это отвечает монотонный счётчик без единицы измерения.
    """

    def __init__(
        self,
        *,
        initial_cache: dict[str, Any] | None = None,
        tracked_suffixes: tuple[str, ...] | None = None,
        window_sec: float = 600.0,
        sample_hz: float = 1.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Инициализировать read-model.

        Args:
            initial_cache: опциональный первичный снимок ``{path: value}``
                (обычно кэш state-proxy). Заливается сразу — snapshot() работает
                ещё до первой дельты. None/пустой → стартуем пустыми.
            tracked_suffixes: набор суффиксов путей для кольцевых буферов истории.
                None → DEFAULT_TRACKED_SUFFIXES. Пустой кортеж → история не
                копится (только snapshot/get).
            window_sec: длительность окна истории в секундах (~10 мин = 600).
            sample_hz: ожидаемая частота семплов метрики (троттлинг источника).
                maxlen буфера = ceil(window_sec * sample_hz) ≈ 600 точек.
            clock: источник wall-clock: время ПРИЁМА точки истории (если метки
                писателя нет) и «сейчас» для :meth:`read`. Дефолт ``time.time``
                (бит-в-бит прежнее поведение). Инъекция нужна offline-реплею
                (backend_ctl flight recorder): точки истории при прокрутке записи
                должны нести ЗАПИСАННЫЕ ts (playhead-часы), а не время загрузки.
                На live-путь не влияет — дефолт остаётся ``time.time``.
        """
        # Проекция состояния: путь ЛИСТА → последнее значение (копия хранит листья,
        # dict-дельта заменяет поддерево — ADR-SS-024 A3). Пишется в ingest,
        # читается get()/snapshot() (late-binding).
        self._state = LeafCopy()

        # Кольцевые буферы истории: путь → deque[(ts_wall, число)].
        self._history: dict[str, collections.deque[tuple[float, float]]] = {}
        self._tracked: tuple[str, ...] = (
            tuple(tracked_suffixes) if tracked_suffixes is not None else DEFAULT_TRACKED_SUFFIXES
        )
        # maxlen из окна и ожидаемого троттлинга: 600 с × 1 Гц = 600 точек.
        self._maxlen: int = max(1, int(round(window_sec * sample_hz)))

        # Источник ts точек истории. Дефолт time.time (live-путь бит-в-бит);
        # инъекция — только для offline-реплея (см. докстроку конструктора).
        self._clock: Callable[[], float] = clock

        # Сторож порядка push/poll (S-1, нога B). Счётчик ПРИНЯТЫХ записей
        # push-дороги (ingest/prime); ответ опроса его НЕ двигает — иначе опрос
        # объявлял бы устаревшим сам себя.
        self._write_seq: int = 0
        # путь → номер его последней push-записи. Растёт только вместе с
        # _write_seq и чистится ТАМ ЖЕ, где путь уходит из снимка
        # (:meth:`_purge_subtree`): иначе словарь копил бы номера путей, которых
        # в дереве уже нет, — медленная утечка, которую никто не замечает.
        self._push_seq: dict[str, int] = {}

        # Хвост довыставления (M-16): корень ``processes.<P>`` -> пути колец, в которые
        # писали с прошлого прихода ``<root>._fresh.src_ts``. Значения идут РАНЬШЕ метки
        # такта, поэтому точка пишется с временем приёма, а при приходе ``src_ts`` последняя
        # точка каждого кольца хвоста получает его (:meth:`_restamp_tail`). Пополняется
        # только внутри ``if record_history:`` в :meth:`_apply_put`; чистится там же, где
        # уходит кольцо (``removed`` и :meth:`_purge_subtree`) — иначе писатель, никогда не
        # шлющий метку, держал бы пути мёртвых колец (тот же класс утечки, что у ``_push_seq``).
        self._stamp_tail: dict[str, set[str]] = {}

        if initial_cache:
            self.prime(initial_cache)

    # ------------------------------------------------------------------
    # Первичное наполнение
    # ------------------------------------------------------------------

    def prime(self, cache: dict[str, Any]) -> None:
        """Залить первичный снимок кэша (нечисловые пути игнорируют историю).

        Считается push-дорогой и двигает :attr:`write_seq` по каждому пути.
        Не декоративно: ``prime`` — публичный метод, и повторный залив кэша
        (переподключение, загрузка записи) обязан обесценить ответы опроса,
        улетевшие ДО него, ровно так же, как это делает обычная push-дельта.
        """
        for path, value in cache.items():
            if not isinstance(path, str):
                continue
            self._apply_put(path, value, True)

    # ------------------------------------------------------------------
    # Приём дельт (envelope-agnostic)
    # ------------------------------------------------------------------

    def ingest(self, path: str, value: Any, *, deleted: bool = False, record_history: bool = True) -> None:
        """Внести одну уже разобранную дельту в снимок (+историю числовых точек).

        Args:
            path: полный путь узла (``processes.cam.state.fps``).
            value: новое значение (для ``deleted=True`` игнорируется).
            deleted: True → узел удалён, убрать из снимка (в историю не пишем).
            record_history: False → обновить ТОЛЬКО снимок, кольцо истории не
                трогать. Нужно источникам, которые дают текущий УРОВЕНЬ, а не
                точку потока (опрос уровней, ADR-139): кольцо имеет фиксированный
                ``maxlen``, и второй писатель в тот же путь сокращает окно
                графика пропорционально своей частоте, ничего об этом не сообщая.

        Пишет СИНХРОННО: snapshot/get/history актуальны сразу после вызова.
        """
        if deleted:
            # tree_store.delete() шлёт ОДНУ дельту на корень поддерева, поэтому
            # чистим и сам путь, и всё поддерево под ним. Граница — точка-разделитель
            # (как в snapshot): удаление ``processes.cam`` не заденет ``processes.cam2``.
            self._purge_subtree(path)
            # Удаление — тоже ПРИНЯТАЯ запись push-дороги, и счётчик её считает.
            # Номер самому удалённому пути не присваивается: путь ушёл из снимка,
            # и запись о нём стала бы вечной строкой словаря (узел удаляют один
            # раз, а обратно он может не вернуться никогда).
            self._write_seq += 1
            return
        # История — по каждой дельте ПОТОКА (все точки важны для графика).
        # Источник уровней (record_history=False) в кольцо не пишет: см. Args.
        self._apply_put(path, value, record_history)

    def _apply_put(self, path: str, value: Any, record_history: bool) -> None:
        """Принять запись push-дороги: заменить поддерево, сдвинуть счётчик, записать историю.

        Единственное место смысловой записи push-дороги (``ingest`` и ``prime``).
        dict-дельта заменяет поддерево ``path`` листьями (:meth:`LeafCopy.put`);
        снятым листьям чистятся история и номер записи.

        Одна принятая дельта двигает ``write_seq`` на 1, все её листья получают
        этот номер. Счётчик двигается ПОСЛЕ применения записи в ``_state`` — от
        этого зависит граница ``==`` в :meth:`ingest_poll_snapshot`, см. её докстроку.

        **Довыставление хвоста (M-16).** Точка истории несёт ``src_ts`` метки писателя
        своего такта, а не время приёма. Порядок дельт живого тика — значения РАНЬШЕ
        метки (тик 1: dict ``workers``, ``state``, затем dict ``_fresh``; тик 2+: листья
        значений, затем ``_fresh.seq``, ``_fresh.src_ts``), поэтому метку нельзя прочесть
        в момент записи точки: она отстала бы на такт. Точка пишется с временем приёма и
        запоминается в хвосте корня ``processes.<P>``; когда в ``written`` появляется
        ``<root>._fresh.src_ts`` (лист, dict ``_fresh`` или корень с меткой внутри),
        последняя точка каждого кольца хвоста заменяется на ``(src_ts, значение)``, и хвост
        очищается. Это идёт ПОСЛЕ цикла ``written``, меняет только ``self._history[p][-1]``,
        не зовёт ``_apply_put`` и не двигает ``_write_seq`` и ``_push_seq`` (инвариант 2).
        Метки нет — остаётся время приёма. Только поток: при ``record_history=False``
        (источник уровней) хвост не пополняется и не довыставляется (инвариант 1).
        """
        if not path:
            # Пустой путь копия-листьев отвергает (``LeafCopy.put`` бросает ValueError), а
            # ingest("") исторически не бросает (test_short_paths_do_not_raise): запись
            # игнорируется. Хранилище такой путь не отдаёт.
            return
        written, removed = self._state.put(path, value)
        for p in removed:
            self._history.pop(p, None)
            self._push_seq.pop(p, None)
            self._forget_in_tail(p)
        self._write_seq += 1
        stamped: list[str] = []  # корни, чей src_ts пришёл с этой записью
        for p in written:
            self._push_seq[p] = self._write_seq
            if record_history:
                if self._record_history(p, self._state[p]) and not p.endswith(_RECEIPT_TIME_SUFFIXES):
                    root = _process_root(p)
                    if root is not None:
                        self._stamp_tail.setdefault(root, set()).add(p)
                if p.endswith(_SRC_TS_SUFFIX):
                    stamped.append(p)
        for p in stamped:
            self._restamp_tail(p[: -len(_SRC_TS_SUFFIX)], self._state[p])

    def _restamp_tail(self, root: str, src_ts: Any) -> None:
        """Последняя точка каждого кольца хвоста ``root`` -> ``(src_ts, значение)``; хвост очищается.

        ``src_ts`` — не конечное число (``None``, строка, ``nan``, ``inf``) -> ничего не меняется:
        точки остаются на времени приёма, хвост ждёт следующую метку (он ограничен числом
        путей колец, растёт не может). Кольцо, которого нет (путь снят) или которое пусто,
        терпится. ``write_seq`` и ``_push_seq`` не трогаются.
        """
        paths = self._stamp_tail.get(root)
        if not paths:
            return
        ts = self._as_number(src_ts)
        if ts is None or not math.isfinite(ts):
            return
        del self._stamp_tail[root]
        for p in paths:
            buf = self._history.get(p)
            if buf:
                buf[-1] = (ts, buf[-1][1])

    def _forget_in_tail(self, path: str) -> None:
        """Убрать путь из хвоста довыставления: кольцо пути ушло, ждать нечего."""
        root = _process_root(path)
        paths = self._stamp_tail.get(root) if root is not None else None
        if paths is None:
            return
        paths.discard(path)
        if not paths:
            del self._stamp_tail[root]

    def _purge_subtree(self, path: str) -> None:
        """Убрать путь и всё поддерево под ним из снимка, истории и номеров.

        Граница — точка-разделитель: удаляются ``path`` и ключи с префиксом
        ``path + "."`` (сосед с общим строковым префиксом не затрагивается).

        ``_push_seq`` чистится ЗДЕСЬ ЖЕ и по той же границе — это единственное
        место, где путь уходит из read-model. Не чистить его значило бы копить
        номера мёртвых путей: узлы приходят и уходят (пересборка топологии,
        ``deleted=True``), словарь рос бы линейно по числу когда-либо виденных
        путей, и заметить это было бы нечем.

        **Цена названа:** вместе с номером теряется и знание «этот путь недавно
        писал push», поэтому ответ опроса, улетевший ДО удаления узла и
        пришедший ПОСЛЕ, путь восстановит (сторожу нечем его отбраковать).
        Окно — оборот запроса опроса (замер 7.5–10 с) и только для явного
        удаления узла, а не для снятия уровня (снятие едет значением ``None`` и
        номер себе как раз проставляет). Обмен сознательный: вечно растущий
        словарь против узкого окна на редком событии.
        """
        gone = self._state.drop(path)  # по индексу: цена — размер поддерева
        for p in gone:
            self._push_seq.pop(p, None)
            self._forget_in_tail(p)
        # В кольцах истории бывают пути только от import_history (их нет в _state),
        # поэтому история чистится сканом по границе-точке; она мала (только
        # отслеживаемые суффиксы).
        dotted = path + "."
        for p in [p for p in self._history if p == path or p.startswith(dotted)]:
            del self._history[p]

    # ------------------------------------------------------------------
    # Порядок записи: push против ответа опроса (S-1, нога B)
    # ------------------------------------------------------------------

    @property
    def write_seq(self) -> int:
        """Сколько записей PUSH-дороги принято. Строго растёт, не убывает.

        Снимается опрашивающим В МОМЕНТ ОТПРАВКИ запроса и возвращается сюда
        аргументом ``requested_at_seq`` вместе с ответом. Ответ опроса счётчик НЕ
        двигает: иначе первый же влив объявил бы устаревшими все запросы, ещё
        находящиеся в полёте.

        Не время и не измеряется в секундах: сравнивать можно только с другим
        значением ЭТОГО ЖЕ экземпляра. Пересоздание read-model обнуляет счётчик —
        последствия названы в :meth:`ingest_poll_snapshot`.
        """
        return self._write_seq

    def ingest_poll_snapshot(self, values: dict[str, Any], *, requested_at_seq: int) -> list[str]:
        """Влить ответ ОПРОСА, отбросив пути, перебитые push'ем после отправки.

        Правило — по каждому пути отдельно: путь отбрасывается, если
        ``push_seq[path] > requested_at_seq``, то есть его последняя push-запись
        принята ПОЗЖЕ, чем опрашивающий снял номер и отправил запрос. Прочие
        пути того же ответа вливаются: один ответ несёт несколько путей и терять
        может часть, а не «ответ целиком».

        **Граница ``==`` принимается, и это доказуемо, а не вкус.**
        :attr:`write_seq` увеличивается ПОСЛЕ применения записи
        (:meth:`_apply_put` двигает его следом за записью в снимок), и
        путь получает номер, равный уже увеличенному счётчику. Значит равенство
        ``push_seq[path] == requested_at_seq`` означает: эта push-запись была УЖЕ
        учтена в снимке, против которого опрашивающий снимал номер, — то есть
        ответ опроса не старше её, а свежее. Отсюда строгое ``>``. Строгость
        проверяется отдельным тестом на границу (``==`` вливается, ``+1``
        отбрасывается) — иначе ``>`` и ``>=`` неразличимы, и правка на ``>=``
        прошла бы молча.

        История НЕ пишется (инвариант 1, ADR-139): опрос отдаёт уровень, а не
        точку потока.

        **Пересоздание read-model.** Счётчик живёт в экземпляре и начинается с
        нуля; ``requested_at_seq``, снятый с ПРЕЖНЕГО экземпляра, для нового —
        число из чужой шкалы. Сторож при этом не ломается опасным образом, а
        вырождается: у свежего экземпляра ``_push_seq`` пуст, поэтому висящие в
        полёте ответы применяются целиком, как и до починки. Живого пути к этому
        нет — опрашивающий держит ссылку на конкретный экземпляр и пересоздаётся
        вместе с ним, — но если он появится, сторож не защитит, а не соврёт.

        Args:
            values: плоское ``{path: value}`` уже разложенного снимка опроса.
            requested_at_seq: :attr:`write_seq` на момент ОТПРАВКИ запроса.
                Обязателен и без умолчания намеренно: умолчание позволило бы
                обойти сторожа молча, просто не передав аргумент.

        Returns:
            Список РЕАЛЬНО применённых путей (порядок ``values``). Число
            отброшенных — ``len(values) - len(applied)``; считать их обязан
            вызывающий, ядро счётчиков наблюдаемости не ведёт.
        """
        applied: list[str] = []
        for path, value in values.items():
            if not path:
                continue  # пустой путь копия не хранит; как в _apply_put — игнор
            # Порог по умолчанию −1, а не 0: путь без единой push-записи не имеет
            # номера вовсе, и любой ответ по нему свежий (0 > 0 было бы ложью
            # только случайно, −1 — по построению).
            if self._push_seq.get(path, -1) > requested_at_seq:
                continue
            self._state[path] = value
            applied.append(path)
        return applied

    # ------------------------------------------------------------------
    # Чтение снимка (late-binding)
    # ------------------------------------------------------------------

    def get(self, path: str, default: Any = None) -> Any:
        """Текущее значение по пути (или default, если пути нет)."""
        return self._state.get(path, default)

    def snapshot(self, prefix: str) -> dict[str, Any]:
        """Снимок поддерева: все пути == prefix или начинающиеся с ``prefix.``.

        Границей служит точка-разделитель — ``snapshot("processes.cam")`` берёт
        поддерево процесса ``cam`` и НЕ захватывает ``processes.cam2.*`` (иначе
        соседний процесс с общим строковым префиксом протёк бы в снимок). Пустой
        prefix → полный снимок read-model.
        """
        if not prefix:
            return self._state.copy()  # одна C-копия: dict(LeafCopy) не атомарна
        dotted = prefix + "."
        return {p: v for p, v in self._state.items() if p == prefix or p.startswith(dotted)}

    def read(self, path: str, key: str, alive_incarnation: str | None = None) -> dict[str, Any]:
        """Значение листа процесса вместе с классом свежести и возрастом (M-6).

        Pre:
            ``path`` — корень записи процесса ``processes.<name>``, под которым писатель
            держит метку ``_fresh``; ``key`` — имя листа или путь через точку от ``path``
            (``"state.lat"``); ``alive_incarnation`` — воплощение писателя, которое
            читатель считает живым (из супервизии), или ``None`` («не задано»).
        Post:
            Всюду определена, исключений не бросает. Возвращает ``{"class", "value",
            "age_s"}``, ровно как :func:`read_value` над полным поддеревом процесса, с
            ``now = self._clock()``:
            ``no_data`` — ``{"class": "no_data", "value": None, "age_s": None}`` — если
            ``path`` не корень процесса с меткой (листьев ``<path>._fresh.*`` нет),
            метка неполна или негодна, ``key`` не строка, не указывает на лист или лист
            равен ``None``; ``fresh`` / ``stale`` / ``writer_gone`` с последним значением и
            ``age_s = now - src_ts`` — иначе. Ноль — значение (``fps: 0`` -> ``fresh``).
            Снимок и ``history`` не меняются.

        Метка читается ИЗ ТЕКУЩЕГО состояния на каждый вызов, не кэшируется: ``seq`` и
        ``src_ts`` приходят отдельными листьями, и кэш с первой dict-дельты дал бы ложный
        ``stale`` у писателя, который публикует исправно. Между дельтой значения и дельтами
        метки читатель видит новое значение со старой меткой: возраст завышен не более чем
        на такт — безопасное направление, и это не «чинится» кэшем. Сборка O(1): минимальное
        поддерево из четырёх листьев метки и цепочки ``key``, а не скан снимка. Лока нет:
        вызывающий держит тот же лок, что для ``get``/``snapshot``/``history``.
        """
        if not isinstance(key, str):
            return read_value(None, key, None, None)  # тот же ответ no_data, без дублирования литерала
        mark = {
            field: value
            for field in _MARK_FIELDS
            if (value := self._state.get(f"{path}.{FRESH_KEY}.{field}", _MISSING)) is not _MISSING
        }
        subtree: dict[str, Any] = {FRESH_KEY: mark}
        node = subtree
        *parents, leaf = key.split(".")
        for segment in parents:
            child = node.setdefault(segment, {})
            if not isinstance(child, dict):  # ключ идёт сквозь лист метки: «посреди пути не dict»
                return read_value(None, key, None, None)
            node = child
        node[leaf] = self._state.get(f"{path}.{key}")
        return read_value(subtree, key, self._clock(), alive_incarnation)

    # ------------------------------------------------------------------
    # Кольцевые буферы истории
    # ------------------------------------------------------------------

    def _is_tracked(self, path: str) -> bool:
        """Отслеживается ли путь для истории (совпадение по суффиксу).

        Две формы адреса, ОДИН набор суффиксов. Плагинная метрика с Ф1 «порта
        наблюдений» живёт в поддереве писателя
        (``processes.<P>.state.plugins.<писатель>.<имя>``), и голый ``endswith``
        по ``.state.<имя>`` её не ловит: между ``state`` и листом появились два
        сегмента. Поэтому у пути такой формы дополнительно проверяется его
        КАНОНИЧЕСКИЙ вид — тот же путь без пары ``plugins.<писатель>``
        (:func:`_canonical_plugin_path`). Так набор суффиксов остаётся про ИМЯ
        МЕТРИКИ, а не про раскладку дерева, и потребителю не приходится
        перечислять писателей, которых он не знает.

        Ключ кольца при этом остаётся ПОЛНЫМ путём — с сегментом писателя. Два
        писателя с одноимённой метрикой получают ДВА независимых кольца, и в
        выдаче ``history``/``snapshot`` видно, ЧЕЙ это лист.
        """
        if any(path.endswith(suffix) for suffix in self._tracked):
            return True
        canonical = _canonical_plugin_path(path)
        return canonical is not None and any(canonical.endswith(s) for s in self._tracked)

    @staticmethod
    def _as_number(value: Any) -> float | None:
        """Привести к float; не-число (в т.ч. bool/str/None) → None."""
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _record_history(self, path: str, value: Any) -> bool:
        """Добавить числовую точку в кольцевой буфер отслеживаемого пути (O(1)); True — точка добавлена."""
        if not self._is_tracked(path):
            return False
        num = self._as_number(value)
        if num is None:
            return False
        buf = self._history.get(path)
        if buf is None:
            buf = collections.deque(maxlen=self._maxlen)
            self._history[path] = buf
        # ts ПРИЁМА: wall-clock (Unix-epoch) через self._clock(). Это временное
        # значение: пока метка такта не пришла, точка держит время приёма, а
        # ``_apply_put`` довыставляет ей ``src_ts`` метки (M-16, ``_restamp_tail``);
        # без метки (и у ``.state.uptime``) время приёма остаётся окончательным.
        # Ring — только для отображения (спарклайн/дашборд), длительности/Hz по
        # нему не считаются, поэтому monotonic здесь не нужен. Дефолт
        # clock=time.time; инъекция — offline-реплей (записанные ts вместо
        # времени загрузки).
        buf.append((self._clock(), num))
        return True

    def history(self, path: str, since: float | None = None) -> list[tuple[float, Any]]:
        """Выборка (ts, value) буфера для спарклайна.

        Args:
            path: полный путь метрики (например ``processes.cam.state.fps``).
            since: нижняя граница ts (wall-clock, Unix-epoch); None → весь буфер.

        Returns:
            Список ``(ts, value)`` в хронологическом порядке (O(k) по буферу). Нет
            буфера → пустой список. ``ts`` — время ИСТОЧНИКА: ``src_ts`` метки
            писателя того же такта; метки нет (и всегда у ``.state.uptime``) — время
            приёма (``clock``). Принятые пределы: скачок ``src_ts`` назад (шаг часов
            писателя) может нарушить хронологию кольца; две записи одного пути за один
            такт довыставляются только последней (``DECISIONS.md``).
        """
        buf = self._history.get(path)
        if buf is None:
            return []
        if since is None:
            return list(buf)
        return [(ts, val) for ts, val in buf if ts >= since]

    # ------------------------------------------------------------------
    # Экспорт / импорт истории (сериализация колец для flight recorder)
    # ------------------------------------------------------------------

    def export_history(self) -> dict[str, list[tuple[float, float]]]:
        """Снимок всех кольцевых буферов истории: ``path → [(ts, value), ...]``.

        JSON-safe (числа + списки) — граница процессов/файла соблюдена. Порядок
        точек хронологический (как в буфере). Пустые буферы не включаются.
        Используется recorder'ом для сохранения истории в header записи.
        """
        return {path: list(buf) for path, buf in self._history.items() if buf}

    def import_history(self, data: dict[str, list[tuple[float, float]]]) -> None:
        """Восстановить кольцевые буферы истории из :meth:`export_history`-снимка.

        Точки несут ЗАПИСАННЫЕ ts (не «сейчас») — это ключ честного offline-реплея.
        maxlen соблюдается: если серия длиннее окна, остаётся хвост (последние
        ``maxlen`` точек, как при живом накоплении). Существующие буферы этих
        путей заменяются. Нечисловые/битые точки пропускаются best-effort.

        Args:
            data: ``{path: [(ts, value), ...]}`` — обычно из header записи.
        """
        for path, points in data.items():
            if not isinstance(path, str) or not points:
                continue
            buf: collections.deque[tuple[float, float]] = collections.deque(maxlen=self._maxlen)
            for point in points:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    continue
                ts, value = point
                num = self._as_number(value)
                ts_num = self._as_number(ts)
                if num is None or ts_num is None:
                    continue
                buf.append((ts_num, num))
            if buf:
                self._history[path] = buf


__all__ = ["TelemetryReadModel", "DEFAULT_TRACKED_SUFFIXES"]
