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

from ...observability_declarations import declare_metric
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
# Уровень плагина едет ТЕМ ЖЕ сборщиком тика; писатель — сегмент пути,
# а не претендент на имя (ADR-PM-038 + Ф1 «порт наблюдений»)
# ---------------------------------------------------------------------------

#: Имя порта на сервисах процесса. Публичный атрибут — как ``document_sink`` /
#: ``event_selector`` / ``flight_recorder``, и по той же причине: порт объявлен в
#: ``IProcessServices``, а объявление без атрибута ломает ``isinstance(process,
#: IProcessServices)`` на штатной конфигурации.
PLUGIN_LEVELS_ATTR = "plugin_levels"


class PluginLevels:
    """Текущие значения уровней, объявленных плагинами процесса (ADR-PM-038).

    **Что здесь лежит.** Ровно «сколько СЕЙЧАС» по каждому имени — одно значение
    на имя **в поддереве своего писателя**, перезапись, без истории и без
    агрегата. Историю и агрегат за окно даёт ДРУГАЯ плоскость (``ctx.gauge`` →
    ``StatsManager``); соседство имён ``record_metric`` / ``publish_metric``
    названо в ADR-PM-038 и в докстрингах обоих фасадов.

    **Ключ первого уровня — ПИСАТЕЛЬ, и это замена арбитражу, а не его
    аккуратная версия** (Ф1 плана «порт наблюдений», принцип «владение = путь»).
    Прежняя редакция ключевала парой ``(имя, публикатор)`` и разрешала спор двух
    писателей за ОДИН лист сверкой публикатора с объявленным владельцем имени —
    механизм, у которого был ``ValueError`` на объявлении, голос про самозванца,
    отсев с тройками и поимённое снятие с запасом. Спорить стало НЕ О ЧЕМ:
    писатель — сегмент пути (``state.plugins.<писатель>.<имя>``), и одинаковое
    имя у двух плагинов даёт два РАЗНЫХ листа. Арбитр удалён целиком, а не
    ослаблен: класс задач «кто хозяин имени» исчез структурно.

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
    в котором останавливают плагин, — и он под тем же локом. Довод пережил
    переезд в поддерево ДВАЖДЫ: копируется теперь ВЛОЖЕННЫЙ словарь, то есть
    гонка есть и на внешнем уровне (появился новый писатель), и на внутреннем
    (писатель завёл новое имя) — обе накрыты одним локом.
    """

    __slots__ = ("_values", "_lock")

    def __init__(self) -> None:
        #: писатель → {имя → значение}
        #:
        #: ponytail: предела нет — потолок |писателей × их имён|. Плагин,
        #: публикующий в СГЕНЕРИРОВАННЫЕ имена, растит его линейно (5000
        #: публикаций → 5000 записей, измерено ревью). Это runaway-плагин, а не
        #: режим работы: имя уровня пишут руками рядом с вычислением. Кап не
        #: заводится, пока такого писателя нет — завести его значило бы решать,
        #: КАКОЙ уровень выбросить, не имея ни одного случая для правила.
        self._values: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def publish(self, name: str, value: Any, writer: str) -> None:
        """Запомнить текущее значение уровня ``name`` от писателя ``writer``.

        Перезаписывается запись ТОГО ЖЕ писателя по тому же имени — и только она.
        Запись соседа под тем же именем живёт в СВОЁМ поддереве и этой публикацией
        не задета: одинаковое имя у двух плагинов — не конфликт, а два листа.

        Проверок владения здесь нет и быть не может: имя не принадлежит никому,
        принадлежит ПУТЬ, а путь писателю выдаёт не проверка, а построение ключа.
        Публикация «до объявления» тоже перестала быть случаем — объявление
        осталось каталогом имён для гейта и авто-строк GUI, а не правом на имя.
        """
        name = str(name)
        writer = str(writer)
        with self._lock:
            self._values.setdefault(writer, {})[name] = value

    def publications(self) -> dict[str, dict[str, Any]]:
        """Копия ``писатель → {имя → значение}`` — единственный вход сборщика.

        Копия ДВУХУРОВНЕВАЯ: отдай внутренние словари ссылкой — и читатель тика
        итерировал бы живой словарь, в который пишет поток воркера, то есть ровно
        ту гонку, ради которой здесь лок.
        """
        with self._lock:
            return {writer: dict(values) for writer, values in self._values.items()}

    def names(self) -> set[str]:
        """Имена листьев ВСЕХ писателей — кандидаты гейта на этом тике.

        Отдельно от :meth:`publications`, потому что спрашивают разные вопросы в
        разное время: гейту нужен СПИСОК ИМЁН до решения (какие правила резолвить
        на этом тике), сборщику — значения после. Значения сюда не копируются:
        имён на порядок меньше, а вызов идёт каждым тиком.

        Почему гейт вообще спрашивает хранилище. Каталог объявлений
        (:func:`gated_metrics`) знает только объявленные имена, а необъявленное
        имя обязано ехать легально — под ДЕФОЛТНЫМ правилом конфига, ровно как
        ``TelemetryPublishConfig.resolve`` тотальна. Не спроси гейт хранилище —
        необъявленное имя не попало бы в ``allowed`` никогда, и «легально едет»
        оказалось бы тихим отказом (та самая форма, которую Ф1 хоронит: голос
        про самозванца сняли, а отказ остался бы).
        """
        with self._lock:
            return {name for values in self._values.values() for name in values}

    def retract(self, writer: str) -> int:
        """Снять всё, что опубликовал ``writer``. Возвращает число снятых записей.

        Зовётся фреймворком при остановке плагина
        (``ProcessModulePlugin._do_shutdown``) — свежесть держится жизненным
        циклом, а не штампом времени на каждом листе. Прецедент — ``throttle.prune``
        при ``state.delete``.

        Автоматика, а не «каждый плагин зовёт сам»: свойство, которое держится на
        памяти автора плагина, свойством не является — забудут ровно один раз и
        молча, а симптом («камера остановлена, а частота идёт») будут искать в
        камере.

        С поддеревом писателя это ровно ``pop`` его ветки: соседи не задеваются
        по построению, а не по фильтру. Поимённой бухгалтерии снятия (``_retracted``,
        запас переутверждений, ``None``-надгробия) здесь больше нет: она стояла на
        каталоге владения, который Ф1 удалила, а во вложенной форме её страж
        «имени нет в payload» всегда истинен, и надгробие легло бы на ПЛОСКИЙ путь
        при живом писателе. Замена — удаление поддерева дорогой ``state.delete``
        (Ф2); между Ф1 и Ф2 механизма снятия из ДЕРЕВА нет вовсе, и пара фаз
        поставляется вместе (§11.7 плана).

        Число возвращается, чтобы вызывающий мог отличить «сняли N» от «снимать
        было нечего»: у плагина без уровней ноль — законный ответ, а не сбой.
        """
        writer = str(writer)
        with self._lock:
            gone = self._values.pop(writer, None)
        return 0 if gone is None else len(gone)


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


#: Ключ поддерева писателей внутри секции ``state`` merge-payload'а.
#:
#: Константа, а не литерал: СЕГОДНЯ читатель ровно один — сборщик ниже (``:505``).
#: Константой заведена под будущих: правила гейта Ф4
#: (``processes.*.state.plugins.*.fps``) и мигрирующие читатели Task 1.4. Разойдись
#: они — метрика уехала бы под путь, которого никто не читает, и увидеть это можно
#: было бы только на стенде. Пока читатель один, это задел, а не факт.
PLUGINS_SUBTREE_KEY = "plugins"


def build_plugin_levels(
    levels: dict,
    allowed_metrics: Optional[Iterable[str]] = None,
) -> dict:
    """Спроецировать хранилище уровней в поддерево ``plugins.<писатель>.<имя>``.

    Тот же сборщик обслуживает push (тик heartbeat) и poll
    (``current_levels_snapshot``) — второго способа посчитать те же величины не
    заводится (ADR-PM-035). Разница между ними ровно одна и она уже существует у
    соседей: опрос зовётся с ``allowed_metrics=None`` (гейт про push, а не про
    то, что процесс знает о себе).

    **Проекция, а не отбор.** Владение здесь больше не решается: писатель — не
    претендент на имя, а СЕГМЕНТ ПУТИ. Прежняя редакция сверяла публикатора с
    объявленным владельцем имени, отбрасывала несовпавших и возвращала вторым
    элементом тройки для голоса; всё это удалено вместе с арбитражем (Ф1). Два
    плагина с именем ``fps`` дают ``plugins.a.fps`` и ``plugins.b.fps`` — спорить
    стало синтаксически не о чем, а значит и отсеивать нечего, и голосу нечего
    сказать.

    **Гейт матчит по ИМЕНИ ЛИСТА (суффиксу), а не по пути.** Правило конфига
    ``metrics.fps`` действует на ``plugins.<любой>.fps`` — так прод-конфиг
    работает без единой правки после переезда листьев в поддерево. Glob по пути
    (``processes.*.state.plugins.*.fps``) — язык Ф4, здесь его нет.

    Args:
        levels: снимок :meth:`PluginLevels.publications` — ``писатель → {имя →
            значение}``.
        allowed_metrics: разрешённые на этом тике ИМЕНА ЛИСТЬЕВ (``None`` → все,
            как у соседних сборщиков).

    Returns:
        ``{"plugins": {писатель: {имя: значение}}}`` — либо **пустой** dict, если
        не уцелело ни одного листа. Пустое поддерево не возвращается намеренно:
        ``{"plugins": {}}`` в merge-payload'е — это запись в дерево, которая
        ничего не сообщает, но создаёт узел и дельту на каждом тике.

    Post:
        - чистая функция: ``levels`` не мутируется;
        - писатель без уцелевших листьев в результат не попадает (пустая ветка —
          то же «ничего не сообщает» уровнем ниже);
        - округление до 1 знака — то же, что у ``build_worker_telemetry``.
          Нечисловое значение проходит как есть (``round`` на нём — падение
          сборщика телеметрии из-за прикладной опечатки).

          **Ф1 округления не вводила и не трогала** — оно тут с самого появления
          уровней (прежняя редакция, та же строка ``round(value, 1)``), и решение
          за ним своё: уровень — вид для глаз, а не измерительный прибор
          (``current_levels_snapshot``). Довод «иначе разойдутся push и poll»,
          которым его объясняли, не работает и НИКОГДА не работал: опрос шёл через
          эту же функцию и до Ф1 (прежний ``_collect_plugin_levels(None)``), так что
          разойтись дороги не могли ни тогда, ни сейчас. Довод «вид для глаз» —
          единственный живой.
          Практическое следствие, на которое уже споткнулась независимая приёмка:
          ``publish_metric("x", 111.25)`` даёт в дереве ``111.2`` — тест, ищущий
          в дереве ровно опубликованный литерал, обязан брать число, переживающее
          ``round(x, 1)``.
          **Цена снятия округления ИЗМЕРЕНА ревью Ф1 и сегодня равна нулю**, а не
          «не измерена», как здесь стояло: единственный боевой вызывающий
          ``publish_metric`` (``Plugins/sources/capture/plugin.py:359-361``)
          округляет сам, остальные два значения целые. Для гипотетического писателя
          с сырым float цена +7.3 % дельт (500 против 466 на 500 тиков) — не порядок.
          Округление оставлено потому, что его снятие меняет наблюдаемую форму
          дерева, а Ф1 меняет адрес, не форму значения; это граница фазы, а не
          цена.
    """
    allowed = None if allowed_metrics is None else set(allowed_metrics)

    subtree: dict[str, dict[str, Any]] = {}
    for writer, values in levels.items():
        branch: dict[str, Any] = {}
        for name, value in values.items():
            if allowed is not None and name not in allowed:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                branch[name] = round(value, 1)
            else:
                branch[name] = value
        if branch:
            subtree[str(writer)] = branch
    return {PLUGINS_SUBTREE_KEY: subtree} if subtree else {}


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

    def due_metrics(self, now: Optional[float] = None, *, extra: Iterable[str] = ()) -> set[str]:
        """Разрешённые к публикации на этом тике имена (enabled ∧ созрел интервал).

        Продвигает ``_next_due`` для выданных имён. ``now`` — для инъекции времени
        в тестах (по умолчанию ``clock()``).

        Args:
            now: момент решения; ``None`` → ``clock()``.
            extra: имена СВЕРХ каталога :func:`gated_metrics`, которые на этом
                тике тоже являются кандидатами, — листья, реально лежащие в
                хранилище уровней (:meth:`PluginLevels.names`).

        **Зачем ``extra`` и почему это не «дырка в каталоге»** (Ф1, шаг 5).
        Каталог объявлений отвечает на «что бывает», а гейт обязан ответить на
        «поедет ли ЭТО имя», и ответ у него тотальный по построению:
        ``TelemetryPublishConfig.resolve`` возвращает ``(default_enabled,
        default_interval_sec)`` для любого незнакомого ключа. Обходи гейт только
        каталог — необъявленное имя не попало бы в ``allowed`` НИКОГДА, то есть
        «публикуй без объявления» было бы тихим отказом. Ф1 сняла голос про
        необъявленное имя; оставить при этом отказ значило бы поменять громкий
        отказ на молчаливый — ровно тот класс, который фаза хоронит.

        Каталог из вычисления не убран: метрику фреймворка (``fps``, ``shm``)
        никто не «публикует в хранилище», её считает сам сборщик, и без каталога
        гейт про неё не узнал бы вовсе.
        """
        if now is None:
            now = self._clock()
        allowed: set[str] = set()
        for metric in set(gated_metrics()) | {str(name) for name in extra}:
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
    "PLUGINS_SUBTREE_KEY",
    "get_or_create_plugin_levels",
    "TelemetryGate",
    "gated_metrics",
    "capped_metrics",
]
