"""Сборка телеметрии процесса в один merge-payload (E6/Task 5.7) + publisher-gate (PC 1.2).

Раньше публикатор heartbeat слал **3W+2** отдельных
``proxy.set`` (по 3 на воркер + 2 агрегатных) — каждый ``set`` = отдельное
IPC-сообщение в StateStoreManager. Этот helper собирает те же листья в один
вложенный dict под общим префиксом ``processes.<name>`` → публикатор шлёт **один**
``proxy.merge`` (глубокий merge сохраняет сиблинги ``health.*`` и пр.), снижая
число телеметрийных сообщений ~в W раз.

PC 1.2 (publisher-gate): ``build_worker_telemetry`` принимает ``allowed_metrics`` —
множество суффиксов метрик, которым РАЗРЕШЕНО попасть в payload на этом тике
(вкл/выкл из ``TelemetryPublishConfig`` ∧ «созрел» интервал). ``None`` → всё
разрешено (обратная совместимость: нет конфига → поведение как раньше). Решение
«вкл/выкл + созрел ли интервал» принимает ``TelemetryGate`` (per-метрика rate-limit
по паттерну ``plugins/io_peek.py`` — ``_next_due``). ``status`` воркеров вне гейта —
публикуется всегда (инвариант плана «errors/status always-on»).

Чистые функции + тонкий gate (не mixin — сегодня единственный потребитель heartbeat):
тестируется без Qt/IPC, публикатор остаётся тонким.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Iterable, Optional

from ...observability_declarations import declare_metric, metric_owners
from ..configs.telemetry_publish_config import gated_metrics

# Ф8.1: метрика объявляется ТАМ, ГДЕ СЧИТАЕТСЯ, а не перечисляется кортежем в
# configs/. Четыре ниже собирает `build_worker_telemetry` в этом же файле; `shm`
# считает `ProcessHeartbeat` и объявляет у себя. Прежний кортеж-литерал жил на два
# слоя ниже вычисления, и связь «строка каталога ↔ величина» держалась только
# совпадением имени.
#
# На уровне модуля, а не внутри функции: каталог обязан быть полон к моменту, когда
# `ProcessHeartbeat` спросит `unknown_metrics()`, а не к моменту первой публикации.
METRIC_FPS = declare_metric("fps", owner=__name__)
METRIC_LATENCY_MS = declare_metric("latency_ms", owner=__name__)
METRIC_EFFECTIVE_HZ = declare_metric("effective_hz", owner=__name__)
METRIC_CYCLE_DURATION_MS = declare_metric("cycle_duration_ms", owner=__name__)


def build_worker_telemetry(
    workers: dict,
    name: str,
    allowed_metrics: Optional[Iterable[str]] = None,
    *,
    include_cycles: bool = False,
) -> tuple[str, dict] | None:
    """Собрать (path, merge_data) телеметрии процесса из снимка воркеров.

    Формирует те же листья, что раньше писались россыпью ``proxy.set``, но как
    один вложенный dict для ``proxy.merge(path, data)``:

        path = f"processes.{name}"
        data = {
            "workers": {wname: {"status", "effective_hz"?, "cycle_duration_ms"?}, ...},
            "state":   {"fps"?, "latency_ms"?},   # агрегат
        }

    Правила (паритет с прежней логикой при ``allowed_metrics=None``):
      - per-worker: ``status`` — всегда (если не None, вне гейта); ``effective_hz`` —
        при hz>0 И если метрика разрешена; ``cycle_duration_ms`` — при lat>0 И если
        разрешена; воркер без единого поля не попадает в payload;
      - агрегат ``state``: ``fps`` = max(hz) по running-воркерам с hz>0 (если ``fps``
        разрешён); ``latency_ms`` = max(cycle_duration_ms) среди них (если ``latency_ms``
        разрешён); нет hz>0 → без агрегата;
      - округление до 1 знака сохранено (fps/hz/latency).

    Publisher-gate (PC 1.2): ``allowed_metrics`` — множество суффиксов, которым
    разрешено попасть в payload на этом тике. Выключенная/зажатая частотой метрика
    в него не входит → НЕ кладётся в merge (не грузим дерево/IPC/GUI) и по возможности
    НЕ считается в источнике (агрегат fps/latency пропускается целиком, если обе
    его метрики запрещены). Тайминг цикла воркера (``cycle_metrics``) считается
    независимо от этого гейта — его не трогаем.

    Args:
        workers: снимок ``get_all_workers_status()`` (dict wname -> статус-dict).
        name:    имя процесса-владельца (префикс пути в дереве).
        allowed_metrics: разрешённые суффиксы метрик (``None`` → все разрешены,
            обратная совместимость).
        include_cycles: положить в статус воркера счётчик завершённых циклов
            ``cycles`` (``CycleMetricsRecorder``, уже лежит в снимке —
            ``WorkerManager.get_worker_status`` подмешивает его наверх). Только для
            ОПРОСА уровней и намеренно НЕ для push'а: ``cycles`` — не уровень «для
            глаз», а **признак движения**, по которому опрашивающий отличает «числа
            свежие» от «числа стоят, потому что воркер встал» (``snapshot_ts`` этого
            не даёт — он про возраст ОТВЕТА, ревью-блокер 2, ADR-PM-035). В push он
            не идёт, чтобы не добавлять лист в дерево каждому воркеру на каждый тик
            ради того, что нужно только опрашивающему. Асимметрия названа и
            односторонняя: push остаётся ПОДМНОЖЕСТВОМ опроса, поэтому свойство
            «числа опроса совпадают с числами push» не нарушено.

    Returns:
        ``(path, data)`` для ``proxy.merge`` — ЛИБО ``None``, если публиковать нечего
        (пустой снимок / ни одного воркера с полями и без агрегата).

    Pre:
        - ``workers`` — mapping; нестандартные значения (не dict) пропускаются.
    Post:
        - чистая функция: ``workers`` не мутируется;
        - если результат не None — ``data`` непустой (нет пустого merge-сообщения).
    """
    # None → всё разрешено (нет конфига → как раньше). Иначе — членство в множестве.
    allowed = None if allowed_metrics is None else set(allowed_metrics)

    def _ok(metric: str) -> bool:
        return allowed is None or metric in allowed

    hz_ok = _ok("effective_hz")
    lat_ok = _ok("cycle_duration_ms")
    fps_ok = _ok("fps")
    plat_ok = _ok("latency_ms")
    # Считать агрегат вообще, только если хоть одна из его метрик разрешена — иначе
    # не грузим источник лишним проходом (max по списку).
    collect_aggregate = fps_ok or plat_ok

    workers_payload: dict[str, dict] = {}
    hz_values: list[float] = []
    latency_values: list[float] = []

    for wname, w in workers.items():
        if not isinstance(w, dict):
            continue
        status = w.get("status")
        hz = w.get("effective_hz")
        lat = w.get("cycle_duration_ms")

        # Per-worker: status — всегда (вне гейта); частоту/цикл — при измерении И если разрешено.
        wp: dict = {}
        if status is not None:
            wp["status"] = status
        if hz_ok and isinstance(hz, (int, float)) and hz > 0:
            wp["effective_hz"] = round(hz, 1)
        if lat_ok and isinstance(lat, (int, float)) and lat > 0:
            wp["cycle_duration_ms"] = round(lat, 1)
        # Признак движения для опроса (см. include_cycles). Вне гейта: это не метрика
        # «сколько сейчас», а счётчик, по которому судят о свежести самих метрик.
        # Читается из УЖЕ снятого статуса — ни второго обхода, ни нового механизма.
        if include_cycles:
            cycles = w.get("cycles")
            if isinstance(cycles, int) and not isinstance(cycles, bool):
                wp["cycles"] = cycles
        if wp:
            workers_payload[wname] = wp

        # Агрегат процесса: только running-воркеры с реальной частотой (и только если
        # агрегатные метрики вообще нужны — иначе не считаем).
        if collect_aggregate and status == "running" and isinstance(hz, (int, float)) and hz > 0:
            hz_values.append(float(hz))
            if isinstance(lat, (int, float)) and lat > 0:
                latency_values.append(float(lat))

    data: dict = {}
    if workers_payload:
        data["workers"] = workers_payload
    if hz_values:
        state: dict = {}
        if fps_ok:
            state["fps"] = round(max(hz_values), 1)
        if plat_ok and latency_values:
            state["latency_ms"] = round(max(latency_values), 1)
        if state:
            data["state"] = state

    if not data:
        return None
    return f"processes.{name}", data


def build_router_shm_telemetry(router: Any) -> dict:
    """Собрать счётчики кадрового транспорта router'а — те же листья, что уходят в
    ``processes.<name>.state.shm`` на тике публикации.

    Выделена из прежнего shm-публикатора heartbeat (Task 3.2), где
    жила инлайном вместе с merge'ем. Причина выделения — не красота: у группы ``shm``
    появился ВТОРОЙ потребитель (опрос уровней, :meth:`ProcessHeartbeat.current_levels_snapshot`),
    и держать список из тринадцати имён в двух местах значило бы завести две дороги к
    одной величине — добавленный счётчик появлялся бы у push и молча отсутствовал у
    опроса (или наоборот).

    **Чистая функция:** ``router.get_stats()`` — только чтение, ничего не мутирует;
    решение «публиковать ли» (все нули → не грузить дерево) остаётся у ПУБЛИКАТОРА, а
    не здесь: для опроса «все нули» — это показание «кадрового пути нет / всё чисто»,
    а не отсутствие данных.

    **Цена названа и измерена.** Предпочитается узкий ``router.get_shm_stats()``: полный
    ``get_stats()`` ради этих тринадцати int'ов строит ``channel_routes`` /
    ``message_handler_list`` / ``channels`` и стоил на живом стенде ~45 мс сверх пола
    транспорта — их платил и опрос уровней, и КАЖДЫЙ push-тик heartbeat'а (ADR-PM-035,
    ревью-блокер 1). Полный ``get_stats()`` остаётся фолбэком для router'ов без узкого
    аксессора (duck-typing: фейки тестов, сторонние реализации) — числа те же, дороже
    только путь.

    Args:
        router: ``RouterManager`` процесса (duck-typed по ``get_shm_stats()`` либо,
            фолбэком, по ``get_stats()``).

    Returns:
        dict ``{счётчик: int}`` — всегда ПОЛНЫЙ набор ключей (нули включительно).

    Raises:
        Пробрасывает исключения аксессора router'а — оба вызывающих ловят сами
        (публикатор логирует и пропускает тик; опрос отдаёт секцию ``None``).
    """
    narrow = getattr(router, "get_shm_stats", None)
    if callable(narrow):
        rs = narrow()
    else:
        stats = router.get_stats()
        rs = stats.get("router", stats) if isinstance(stats, dict) else {}

    def _n(key: str) -> int:
        return int(rs.get(key, 0) or 0)

    return {
        "pickle_fallbacks": _n("frame_pickle_fallbacks"),
        "torn_reads": _n("frame_torn_reads"),
        "boundary_crossings": _n("frame_boundary_crossings"),
        "queue_data_evicted": _n("queue_data_evicted"),
        # Ф7 G.4.a: system-backpressure тоже виден (блокировки вытеснения из полной
        # system-очереди — control-plane терять нельзя; ревью 2026-07-14: раньше
        # surface был, но публикации не было — асимметрия с data_evicted).
        "queue_system_evict_blocked": _n("queue_system_evict_blocked"),
        # Ф7.3: потери ХВОСТА наблюдаемости. Публикация обязательна, а не «для
        # симметрии»: пути потери хвоста молчат в логах сознательно (запись о
        # потерянной записи усиливала бы шторм), поэтому дерево — единственное
        # место, где оператор эту потерю увидит.
        "queue_observability_evicted": _n("queue_observability_evicted"),
        "queue_observability_send_failed": _n("queue_observability_send_failed"),
        # Ф7.х M-2: ТРЕТЬЯ форма потери хвоста — билет не доехал ни одним из путей
        # доставки роутера (targets, relay через хаб, канал). Счётчик завела Ф7.3 и
        # не вывела наружу НИ ОДНИМ путём — класс «проглоченный сбой» внутри починки
        # того же класса. Проверено живьём: в ``state.shm`` были только evicted и
        # send_failed.
        "observability_delivery_failed": _n("observability_delivery_failed"),
        # Ф7 G.5.c: дроп по post-use re-check zero-copy view (слот перезаписан под
        # живым view — consumer отстал > глубины кольца).
        "stale_drops": _n("frame_stale_drops"),
        # Ф7 G.5.d (В3): исчерпание free-list → drop-на-источнике (back-pressure).
        "loan_exhausted": _n("frame_loan_exhausted"),
        # Ф7 G.5 ревью-фикс 15: здоровье loan-цикла (released/reclaimed) — не потери,
        # но обязательный сигнал: exhausted растёт при released на нуле = release-контур
        # не замкнут (ревью поймало именно это через отсутствие сигнала).
        "slots_released": _n("frame_slots_released"),
        "slots_reclaimed": _n("frame_slots_reclaimed"),
        # Ф7 G.7 (0.5): размер reader-кэша SHM-handle. НЕ потеря, а health-сигнал:
        # под zero-copy эвикция отключена → рост на инкарнацию = утечка handle.
        "cache_size": _n("frame_handle_cache_size"),
    }


# ---------------------------------------------------------------------------
# Уровень плагина едет ТЕМ ЖЕ сборщиком тика; владение стережётся при
# публикации (ADR-PM-038)
# ---------------------------------------------------------------------------

#: Имя порта на сервисах процесса. Публичный атрибут — как ``document_sink`` /
#: ``event_selector`` / ``flight_recorder``, и по той же причине: порт объявлен в
#: ``IProcessServices``, а объявление без атрибута ломает ``isinstance(process,
#: IProcessServices)`` на штатной конфигурации.
PLUGIN_LEVELS_ATTR = "plugin_levels"


class PluginLevels:
    """Текущие значения уровней, объявленных плагинами процесса (ADR-PM-038).

    **Что здесь лежит.** Ровно «сколько СЕЙЧАС» по каждому имени — одно значение
    на имя, перезапись, без истории и без агрегата, **и рядом с ним имя того, кто
    его положил**. Историю и агрегат за окно даёт ДРУГАЯ плоскость (``ctx.gauge``
    → ``StatsManager``); соседство имён ``record_metric`` / ``publish_metric``
    названо в ADR-PM-038 и в докстрингах обоих фасадов, потому что именно на нём
    §Ф1 уже обжигался.

    **Публикатор хранится не для отчётности, а потому что без него инвариант
    «один лист — одно значение — один владелец» кончался на объявлении.** Первая
    редакция помнила только значение; сборщик сверял имя с ПЛОСКИМ каталогом
    («такое имя кем-то объявлено») и потому пропускал уровень, положенный в чужое
    имя. Воспроизведено 2026-08-16: плагин публиковал в ``fps`` (имя фреймворка),
    и дальше спор двух писателей за один лист разрешал транспорт — порядком
    прибытия и окном троттла. Теперь публикатор едет вместе со значением, и
    :func:`build_plugin_levels` сверяет его с владельцем имени.

    **Почему хранилище, а не прямая запись в дерево.** Прямую запись плагины уже
    умеют (``state_proxy.merge``) — и ровно она едет мимо publisher-гейта, мимо
    сборщика тика и мимо опроса. Хранилище разрывает «кто посчитал» и «кто
    публикует»: считает плагин на своём такте, публикует — сборщик тика процесса,
    один на всех и уже под гейтом.

    **Блокировка нужна, и не ради атомарности присваивания.** Присваивание в dict
    под GIL атомарно, а вот ``dict(self._values)`` в момент вставки из другого
    потока — нет: копирование словаря, растущего одновременно, поднимает
    ``RuntimeError: dictionary changed size during iteration``. Писатель — поток
    воркера плагина (``produce``), читатель — поток heartbeat; это разные потоки
    всегда, а не «в теории». :meth:`retract` добавляет третьего писателя — поток,
    в котором останавливают плагин, — и он под тем же локом.
    """

    __slots__ = ("_values", "_lock")

    def __init__(self) -> None:
        #: имя → (значение, публикатор)
        self._values: dict[str, tuple[Any, str]] = {}
        self._lock = threading.Lock()

    def publish(self, name: str, value: Any, owner: str) -> None:
        """Запомнить текущее значение уровня ``name`` от публикатора ``owner``.

        Перезапись предыдущего значения ТОГО ЖЕ имени — включая случай, когда
        предыдущее положил другой публикатор. Спорить здесь не о чем: спор
        решается позже и по владению именем (:func:`build_plugin_levels`), а
        отказ на записи означал бы, что порядок вызовов на такте плагина влияет
        на то, чей уровень вообще доедет до проверки.
        """
        with self._lock:
            self._values[str(name)] = (value, str(owner))

    def publications(self) -> dict[str, tuple[Any, str]]:
        """Копия пар ``имя → (значение, публикатор)`` — вход сборщика.

        Единственный вход :func:`build_plugin_levels`: без публикатора сборщик не
        может сверить владение и вырождается обратно в проверку «имя кем-то
        объявлено», которую задача и снимает.
        """
        with self._lock:
            return dict(self._values)

    def snapshot(self) -> dict[str, Any]:
        """Проекция «имя → значение» без публикаторов — для диагностики и тестов.

        Не второе хранилище и не второй источник правды: считается из
        :meth:`publications` в момент вызова. Отвечает на «какие сейчас
        значения», когда вопрос «чьи они» не задаётся, — сборщик им НЕ
        пользуется, потому что ему нужен ровно второй элемент пары.
        """
        return {name: value for name, (value, _owner) in self.publications().items()}

    def retract(self, owner: str) -> int:
        """Снять всё, что опубликовал ``owner``. Возвращает число снятых имён.

        Зовётся фреймворком при остановке плагина
        (``ProcessModulePlugin._do_shutdown``) — свежесть держится жизненным
        циклом, а не штампом времени на каждом листе. Прецедент — ``throttle.prune``
        при ``state.delete``.

        Автоматика, а не «каждый плагин зовёт сам»: свойство, которое держится на
        памяти автора плагина, свойством не является — забудут ровно один раз и
        молча, а симптом («камера остановлена, а частота идёт») будут искать в
        камере.

        Число возвращается, чтобы вызывающий мог отличить «сняли N» от «снимать
        было нечего»: у плагина без уровней ноль — законный ответ, а не сбой.
        Объявление имени при этом ОСТАЁТСЯ в реестре: плагин, поднятый заново,
        объявится тем же владельцем (это не конфликт), а вот забытое объявление
        пришлось бы восстанавливать некому.
        """
        owner = str(owner)
        with self._lock:
            gone = [name for name, (_value, who) in self._values.items() if who == owner]
            for name in gone:
                del self._values[name]
            return len(gone)


def get_or_create_plugin_levels(services: Any) -> Optional[PluginLevels]:
    """Вернуть (создав при необходимости) единое хранилище уровней процесса.

    Форма — дословно :func:`~..health.get_or_create_health_state`, и по той же
    причине: и ``PluginContext.publish_metric``, и ``ProcessHeartbeat`` обязаны
    достать ОДИН И ТОТ ЖЕ экземпляр, а единственное, что у них общего, — объект
    сервисов процесса.

    Ленивое создание, а не отдельный шаг сшивки, — тоже осознанно: плагин может
    опубликовать уровень раньше, чем поднимется heartbeat (``configure`` идёт до
    ``start``), и шаг сшивки пришлось бы ставить в порядок загрузки, где его
    забудут ровно один раз и молча.

    Returns:
        Хранилище — либо ``None``, если сервисы не принимают атрибут
        (иммутабельный дубль, ``__slots__``). ``None`` = названный no-op у
        вызывающего, а не исключение: уровень не имеет права ронять линию.
    """
    existing = getattr(services, PLUGIN_LEVELS_ATTR, None)
    if isinstance(existing, PluginLevels):
        return existing
    store = PluginLevels()
    try:
        setattr(services, PLUGIN_LEVELS_ATTR, store)
    except Exception:  # noqa: BLE001 — иммутабельные services (дубль/слоты)
        return None
    return store


def build_plugin_levels(
    levels: dict,
    allowed_metrics: Optional[Iterable[str]] = None,
) -> tuple[dict, tuple[tuple[str, str, Optional[str]], ...]]:
    """Отобрать уровни плагинов, которым разрешено уехать на этом тике.

    Тот же сборщик обслуживает push (тик heartbeat) и poll
    (``current_levels_snapshot``) — второго способа посчитать те же величины не
    заводится. Разница между ними ровно одна и она уже существует у соседей:
    опрос зовётся с ``allowed_metrics=None`` (гейт про push, а не про то, что
    процесс знает о себе — ADR-PM-035).

    **Отбор идёт по ВЛАДЕНИЮ ИМЕНЕМ, а не по членству в общем каталоге**
    (Р3.5-11, замена прежнему правилу, а не дополнение к нему). Лист берётся,
    только если объявленный владелец имени совпадает с публикатором. Прежнее
    правило («имя есть в :func:`declared_metrics`») отвечало на вопрос «такое имя
    кто-нибудь объявлял», и этого достаточно ровно до появления второго писателя:
    плагин, не объявлявший ``fps``, публиковал в него значение, отбор пропускал
    его как «объявленное», и дальше спор двух писателей за один лист разрешал
    транспорт — порядком прибытия двух merge и окном троттла. Проверка владельца
    отвечает на вопрос «твоё ли это имя» и потому закрывает спор до транспорта.

    Гейтируемость при этом сохраняется даром: ``TelemetryGate.due_metrics()``
    обходит :func:`gated_metrics` — тот же каталог объявлений, — а лист, чей
    владелец совпал с публикатором, объявлен по построению проверки.

    **Отсев обязан иметь голос.** Отброшенное возвращается вторым элементом:
    молчаливый отсев неотличим от опечатки в имени, а обратной связи у
    ``publish_metric`` нет по построению (возврата, как у stats, у него тоже
    нет). В тройке названы все три участника — иначе оператор видит «уровень не
    едет» и не может отличить «я опечатался в имени» от «это имя не моё».

    Args:
        levels: пары :meth:`PluginLevels.publications` — ``имя → (значение,
            публикатор)``.
        allowed_metrics: разрешённые на этом тике суффиксы (``None`` → все,
            как у соседних сборщиков).

    Returns:
        ``(payload, rejected)`` — листья под ``processes.<name>.state`` и
        отсортированный кортеж троек ``(имя, публикатор, владелец)``, где
        владелец — ``None``, если имя не объявлено НИКЕМ.

    Post:
        - чистая функция: ``levels`` не мутируется;
        - округление до 1 знака — то же, что у ``build_worker_telemetry``:
          расхождение push/poll в последнем знаке было бы дороже точности.
          Нечисловое значение проходит как есть (``round`` на нём — падение
          сборщика телеметрии из-за прикладной опечатки).
    """
    owners = metric_owners()
    allowed = None if allowed_metrics is None else set(allowed_metrics)

    payload: dict[str, Any] = {}
    rejected: list[tuple[str, str, Optional[str]]] = []
    for name, (value, publisher) in levels.items():
        owner = owners.get(name)
        if owner is None or owner != publisher:
            rejected.append((name, publisher, owner))
            continue
        if allowed is not None and name not in allowed:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            payload[name] = round(value, 1)
        else:
            payload[name] = value
    # Ключ сортировки — только имя: имя уникально (ключ dict'а), поэтому до
    # сравнения третьего элемента дело не доходит, а он бывает None и с str
    # не сравнивается.
    return payload, tuple(sorted(rejected, key=lambda item: item[0]))


def capped_metrics(config: Any, effective_tick: float) -> list[tuple[str, float]]:
    """Метрики, чей per-метрика ``interval_sec`` МЕНЬШЕ эффективного телеметрийного тика.

    Task 1.2: телеметрийный тик (``min(heartbeat_interval, tick_sec)``) — верхняя
    ступень частотной лестницы. Метрика не может публиковаться чаще этого тика, поэтому
    метрика с ``interval_sec < effective_tick`` «ограничена тиком»: её настроенный интервал
    не достижим (публикация на КАЖДОМ тике, но не чаще). Раньше это был тихий no-op
    (finding D) — теперь вызывающий (``ProcessHeartbeat``) логирует WARNING по этому списку.

    Чистая функция (тестируется без Qt/IPC): принимает уже вычисленный ``effective_tick``
    (``ProcessHeartbeat`` знает ``heartbeat_interval``, config — только ``tick_sec``).

    Args:
        config: объект с ``resolve(metric) -> (enabled, interval_sec)``
            (``TelemetryPublishConfig``).
        effective_tick: эффективный тик публикации, сек (``min(heartbeat_interval, tick_sec)``).

    Returns:
        Список ``(metric, interval_sec)`` включённых метрик с ``interval_sec < effective_tick``
        (пустой — ни одна метрика тиком не ограничена).
    """
    out: list[tuple[str, float]] = []
    for metric in gated_metrics():
        # config — валидированный TelemetryPublishConfig; resolve() тотальна для суффиксов
        # каталога (возвращает (enabled, interval) даже для отсутствующих правил).
        enabled, interval = config.resolve(metric)
        if enabled and interval < effective_tick:
            out.append((metric, interval))
    return out


class TelemetryGate:
    """Publisher-side гейт публикации метрик: вкл/выкл + per-метрика rate-limit.

    Держит ``TelemetryPublishConfig`` (duck-typed по ``.resolve(metric) -> (enabled,
    interval)``) и ``_next_due`` по суффиксу метрики — тот же паттерн, что
    ``IoPeekPublisher`` (``plugins/io_peek.py``). На каждый тик heartbeat метод
    ``due_metrics(now)`` возвращает подмножество каталога :func:`gated_metrics`, которые
    (а) ``enabled`` по конфигу И (б) «созрели» (прошёл ``interval_sec`` с прошлой
    выдачи), и продвигает их ``_next_due``. Выключенные метрики не возвращаются
    никогда → не считаются и не публикуются.

    ``status`` воркеров и health/errors через гейт НЕ проходят (публикуются всегда,
    инвариант плана). Даже если heartbeat тикает чаще ``interval_sec``, метрика
    выходит не чаще своего интервала.

    Продвижение ``_next_due`` происходит в момент ВЫДАЧИ разрешения (grant), а не
    факта наличия данных: если на «созревшем» тике у метрики не оказалось данных,
    следующая публикация подождёт интервал. Для телеметрии (данные на каждом тике
    активного процесса) это несущественно и держит gate чистым/тестируемым.

    Args:
        config: объект с методом ``resolve(metric_name) -> (enabled, interval_sec)``.
        clock:  источник монотонного времени (для тестов с фейк-часами).
    """

    def __init__(self, config: Any, clock: Callable[[], float] = time.monotonic) -> None:
        self._config = config
        self._clock = clock
        self._next_due: dict[str, float] = {}

    @property
    def config(self) -> Any:
        """Текущий ``TelemetryPublishConfig`` gate (Task 1.1).

        Публичный источник эффективной секции для дельта-переконфигурации
        (``mode="merge"``): ``ProcessHeartbeat.current_telemetry_publish`` сериализует
        его в dict-базу, поверх которой мержится дельта. Раньше состояние читалось
        только через приватное ``_config``.
        """
        return self._config

    def due_metrics(self, now: Optional[float] = None) -> set[str]:
        """Разрешённые к публикации на этом тике метрики (enabled ∧ созрел интервал).

        Продвигает ``_next_due`` для выданных метрик. ``now`` — для инъекции времени
        в тестах (по умолчанию ``clock()``).
        """
        if now is None:
            now = self._clock()
        allowed: set[str] = set()
        for metric in gated_metrics():
            enabled, interval = self._config.resolve(metric)
            if not enabled:
                continue
            if now < self._next_due.get(metric, 0.0):
                continue
            allowed.add(metric)
            self._next_due[metric] = now + interval
        return allowed


__all__ = [
    "build_worker_telemetry",
    "build_router_shm_telemetry",
    "build_plugin_levels",
    "PluginLevels",
    "PLUGIN_LEVELS_ATTR",
    "get_or_create_plugin_levels",
    "TelemetryGate",
    "gated_metrics",
    "capped_metrics",
]
