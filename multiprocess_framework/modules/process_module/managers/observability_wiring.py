# -*- coding: utf-8 -*-
"""
Wiring ObservabilityHub в composition root процесса (Ф5.16).

Композиция уровня 1 («рыба») поверх готовых примитивов уровня 0
(ObservabilityHub из channel_routing, ObservabilityDrainAdapter). Владелец
дренажа — ProcessModule (решение владельца 2026-07-09 §6.1, НЕ app_module).

Модель дренажа (§6.1, инвариант 3; **упрощена в 2.2, 2026-07-28**):
  - Один hub на процесс, тег = имя процесса.
  - Пилот — worker_module: его реестр слотов пуст (managers={}), поэтому
    подмена logger/stats на hub безопасна.
  - stats worker'а → hub (bounded-буфер) → drain по такту heartbeat в реальный
    StatsManager через ObservabilityDrainAdapter.
  - **logger-слот worker'а — РЕАЛЬНЫЙ logger_manager, целиком.** Лога в hub-буфере
    больше нет ни на одной severity.
  - error-слот worker'а (track_error) остаётся РЕАЛЬНЫМ error_manager —
    write-through: error/critical пишутся синхронно, минуя буфер, потому что
    auto-restart (Ф3.7) убивает процесс SIGKILL'ом, обходя finally/atexit.

**Почему лог-буфер снят (2.2 — «писателей в пределе один»).** До 2026-07-28 здесь
жил `_LoggerSlotSplitter` — per-severity маршрутизатор поверх слота: `error/critical`
write-through в реальный логгер, ниже — в hub-буфер. Он появился как ЛЕКАРСТВО от двух
воспроизведённых дефектов буферизации лога:

  * **R1 (дубль):** drain клал error-лог в стор как `kind='log'`, а `adapter.apply_log`
    переигрывал его в `logger_manager`, где tap (min ERROR) писал ВТОРУЮ запись
    `kind='error'` — дубль в сторе и в обеих вкладках GUI;
  * **R3 (потеря):** при SIGKILL недренированный буфер пропадал вместе с crash-логом.

Снят сам буфер лога — и оба дефекта исчезают **по построению**, а не по договорённости:
переигрывать нечего (`drained[KIND_LOG]` пуст всегда), терять при SIGKILL нечего
(запись уже у писателя). Расщепитель был вторым местом, где решалась судьба лог-записи,
то есть вторым маршрутизатором рядом с `LoggerCore`; после снятия точка одна.

**Что при этом НЕ потеряно — и почему это проверено, а не заявлено.** Живой хвост
sub-ERROR логов подписчикам (GUI, backend_ctl) раньше шёл пачкой из drain-петли. Ровно
ту же роль уже играет `log.tail.subscribe` — tap прямо на `logger_manager` с уровнем от
подписчика (`log_tail::{subscriber}`, Ф1.5). После снятия буфера записи доезжают до
логгера СРАЗУ, поэтому этот tap видит их живьём и на своём уровне; hub-форвардер несёт
теперь stats и error-хвост. Второй механизм доставки для лога был лишним.

Цена: sub-ERROR лог воркера пишется синхронно в момент эмиссии, а не пачкой по
heartbeat. Отклонённая гейтом запись стоит ~240 нс, вся плоскость на живой нагрузке
(8 процессов × 21 Гц) — 0.03 % ядра, поэтому отсрочка записи ценой второго
маршрутизатора не окупалась.

Хелпер намеренно тонкий и без импорта самого ProcessModule — тестируется в
изоляции (см. tests/test_observability_wiring.py).
"""

from __future__ import annotations

import importlib
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from ...channel_routing_module.levels import normalize_level_name
from ...channel_routing_module.observability import (
    KIND_LOG,
    KIND_STATS,
    ObservabilityDrainAdapter,
    ObservabilityHub,
    ObservabilityStore,
    RecordForwardChannel,
    StoreTapChannel,
    hub_record_to_display,
)

# Имена store-tap'ов (хэндлы для remove_tap на teardown). Вешаем на ОБА
# менеджера: error_manager (track_error/write-through) и logger_manager
# (logger.error/ctx.log_error) — приложение логирует ошибки и туда, и туда.
STORE_ERROR_TAP = "observability_store::error"
STORE_LOGGER_TAP = "observability_store::logger_error"

# Префикс forward-tap'ов live-хвоста hub→подписчик (Ф5.20b), симметрично store-tap'ам.
# F1: имена tap'ов KEYED по subscriber — несколько подписчиков (GUI + backend_ctl)
# держат независимые форвардеры на ОДНОМ процессе (раньше был единственный слот →
# второй подписчик угонял хвост у первого). Образец — log.tail (``log_tail::{subscriber}``).
FORWARD_TAP_PREFIX = "observability_forward"


def forward_tap_names(subscriber: str) -> Tuple[str, str, str]:
    """Детерминированные имена forward-tap'ов подписчика (F1: per-subscriber).

    Возвращает ``(batch, error, logger)`` — уникальные по подписчику имена каналов,
    чтобы форвардеры разных подписчиков не пересекались в реестре tap'ов менеджера.
    """
    base = f"{FORWARD_TAP_PREFIX}::{subscriber}"
    return f"{base}::batch", f"{base}::error", f"{base}::logger_error"


def wire_process_observability(
    process_name: str,
    worker_manager: Optional[Any],
    logger: Optional[Any],
    stats: Optional[Any],
    error: Optional[Any],
) -> Tuple[Optional[ObservabilityHub], Optional[ObservabilityDrainAdapter]]:
    """Создать hub процесса и инъектировать его в слоты пилота (worker_module).

    Args:
        process_name:   Тег hub'а (== имя процесса).
        worker_manager: Пилотный ObservableMixin (слоты подменяются). None →
                        no-op (процесс без воркеров: нечего пилотировать).
        logger/stats/error: Реальные sink-менеджеры для drain-адаптера.

    Returns:
        (hub, adapter) или (None, None) если worker_manager отсутствует.

    Post:
        - worker.get_manager('logger') is logger  (write-through на ВСЕХ severity);
        - worker.get_manager('stats') is hub  (чистый буфер);
        - worker.get_manager('error') is error  (write-through, НЕ hub);
        - adapter сконфигурирован на реальные logger/stats/error;
        - у stats-менеджера поднят канал hub_stats (2.1): снапшот окна едет в
          stats-слот hub'а, а оттуда дренажом в стор и живые хвосты.
    """
    if worker_manager is None:
        return None, None

    hub = ObservabilityHub(process_name)
    adapter = ObservabilityDrainAdapter(logger=logger, stats=stats, error=error)

    # stats worker'а → hub (буфер, drain по heartbeat).
    # logger-слот → РЕАЛЬНЫЙ logger_manager целиком (2.2): лог-буфера больше нет,
    # поэтому R1 (дубль через переигрывание) и R3 (потеря при SIGKILL) невозможны
    # по построению — переигрывать и терять нечего. См. шапку модуля.
    # Вырожденный случай logger=None: слотом остаётся hub — записи не исчезают
    # молча, а копятся в bounded-канале со счётчиком потерь.
    worker_manager.register_manager("logger", logger if logger is not None else hub)
    worker_manager.register_manager("stats", hub)
    # Write-through путь: error/critical (track_error) → реальный error_manager напрямую.
    if error is not None:
        worker_manager.register_manager("error", error)

    # Задача 2.1: обратная дорога — снапшот окна StatsManager'а в stats-слот
    # hub'а, откуда drain доносит его до стора и живых хвостов. Регистрирует
    # канал САМ менеджер (его ``_setup_channels``), а не мы: канал, поставленный
    # снаружи, не пережил бы ``config.reload`` — базовый ``reconfigure`` чистит
    # реестр каналов и собирает его заново из конфига.
    #
    # ``getattr`` не ради вежливости к отсутствию метода, а ради того, что
    # ``stats`` здесь duck-typed и в тестах бывает дублем: настоящий
    # ``StatsManager`` метод несёт всегда (контракт-тест
    # ``test_hub_stats_channel``), поэтому молчаливого no-op на боевом пути тут
    # нет — есть отсутствие требования к чужим дублям.
    attach = getattr(stats, "attach_observability_hub", None)
    if callable(attach):
        attach(hub)

    return hub, adapter


def drain_process_observability(
    hub: Optional[ObservabilityHub],
    adapter: Optional[ObservabilityDrainAdapter],
    store: Optional[ObservabilityStore] = None,
    forwarders: Union[Callable[[List[dict]], None], Iterable[Callable[[List[dict]], None]], None] = None,
    stats_to_flush: Optional[Any] = None,
) -> None:
    """Слить буфер hub'а (log/stats) в реальные менеджеры, стор и live-хвосты.

    Зовётся по такту heartbeat и финально на graceful-teardown. `drain_all()`
    осушает каналы — вызываем ОДИН раз и разветвляем: adapter → sink-менеджеры,
    store → персистентная история (Ф5.20a), forwarders → live-хвосты hub→подписчики
    (Ф5.20b). F1: ``forwarders`` — итерабл форвардеров (по одному на подписчика,
    фан-аут одной и той же пачки записей каждому) ИЛИ единственный callable
    (back-compat). Буфер дренируется РОВНО один раз независимо от числа подписчиков.

    **После 2.2 у пилота в hub'е нет ЛОГА вообще** — ни одной severity: logger-слот
    write-through в реальный менеджер, поэтому `drained[KIND_LOG]` пуст, а
    `adapter.apply_log` для пилота не срабатывает. Ключ остаётся в контракте: hub —
    примитив уровня 0, и лог в него может положить другой владелец. Ошибки попадают
    в стор и в GUI отдельными tap'ами на error/logger-менеджерах, лог — tap'ом
    `log.tail` на logger_manager, НЕ отсюда.
    Исключения глушим: дренаж телеметрии не должен ронять такт heartbeat
    (урок 2.1 — health self-publish не критичен).
    """
    if hub is None:
        return
    # Задача 2.1, ФИНАЛЬНЫЙ дренаж: закрыть окно агрегации ДО того, как забирать
    # буфер. Порядок останова — `stop_all_workers` → этот дренаж → `shutdown()`
    # менеджеров, а последний снапшот `StatsManager` рождается в его
    # ``shutdown()``, то есть ПОСЛЕ. Без этого шага он ложился бы в hub, из
    # которого уже никто не читает (стор к тому моменту закрыт), и последнее
    # окно смены пропадало бы молча — на каждом процессе, каждый останов.
    # На такте heartbeat параметр не передаётся: там окно закрывает свой таймер,
    # а принудительный сброс сбивал бы темп агрегации.
    if stats_to_flush is not None:
        try:
            stats_to_flush.flush()
        except Exception:  # nosec B110 — сбой сброса не должен сорвать teardown
            pass
    drained = hub.drain_all()
    if adapter is not None:
        adapter.apply_drained(drained)
    # stats из hub'а — общий срез для стора и live-хвоста. KIND_LOG у пилота пуст
    # (logger-слот write-through), но ключ читаем: hub — примитив уровня 0, и лог
    # в него вправе положить другой владелец. Пустой список безвреден.
    records = drained.get(KIND_LOG, []) + drained.get(KIND_STATS, [])
    if store is not None and records:
        try:
            store.append_records(records)
        except Exception:  # nosec B110 — сбой стора не критичен для heartbeat
            pass
    # F1: фан-аут пачки каждому подписчику. Один callable → back-compat (обернём).
    if records and forwarders is not None:
        fwds: Iterable[Callable[[List[dict]], None]] = (forwarders,) if callable(forwarders) else forwarders
        for fwd in fwds:
            try:
                fwd(records)
            except Exception:  # nosec B110 — сбой доставки одному хвосту не рушит остальные
                pass


def wire_observability_forward(
    router: Any,
    subscriber: str,
    sender: str,
    logger_manager: Optional[Any] = None,
    error_manager: Optional[Any] = None,
    min_level: str = "ERROR",
) -> Tuple[Callable[[List[dict]], None], list]:
    """Собрать live-форвардер hub→подписчик и повесить error-tap'ы (Ф5.20b).

    Симметрично ``wire_observability_store`` (Ф5.20a), но записи не в SQLite, а
    адресным router-пушем ``command="observability.record"`` на подписчика:
      - log/stats — пачкой из drain-петли: возвращаемый ``forwarder(hub_records)``
        нормализует hub-записи в display-вид и пушит одним сообщением;
      - error/critical — по одной у tap'а на logger+error менеджерах (min ERROR),
        те же write-through записи, что ловит store-tap.

    F1: имена tap'ов и канала — per-subscriber (``observability_forward::{subscriber}::…``),
    поэтому форвардеры разных подписчиков (GUI + backend_ctl) сосуществуют на одном
    процессе и не перетирают друг друга (раньше был единственный слот на процесс).

    Ф6.х.5 (корневая причина З-1): порог tap'ов был захардкожен ``"ERROR"`` без
    ручки — аудит-записи (INFO) не проходили никогда, а batch-путь структурно
    пуст (см. ниже), то есть подписка «успешна», а событий ноль. Уровень теперь
    задаёт подписчик — тем же правом, что у ``log.tail.subscribe``.

    **Batch-половина ЖИВА с задачи 2.1.** Раньше здесь стояло «forwarder не
    вызывается ни разу, stats-плоскость хвоста пуста»: слот stats принадлежал
    одному владельцу (``WorkerManager``), а метрик он не шлёт. Теперь второй
    владелец — канал ``hub_stats`` ``StatsManager``'а: он кладёт в слот снапшот
    окна, и подписчик получает записи ``kind="stats"`` пачкой из drain-петли
    (ADR-SM-010 / ADR-CRM-015). Проверено живым хвостом на стенде.

    Args:
        router: живой RouterManager процесса (``send_async``). None → forwarder-no-op.
        subscriber: адрес GUI-процесса (``targets=[subscriber]``).
        sender: имя процесса-источника.
        logger_manager/error_manager: менеджеры с ``add_tap`` (error-хвост).
        min_level: порог tap'ов на logger/error менеджерах (дефолт ERROR —
            прежнее поведение; INFO/DEBUG открывает живой хвост).

    Returns:
        (forwarder, taps) — forwarder: Callable для drain-петли; taps: список
        (manager, tap_name) для unwire.
    """
    batch_name, error_name, logger_name = forward_tap_names(subscriber)
    batch_channel = RecordForwardChannel(router=router, subscriber=subscriber, sender=sender, name=batch_name)

    def forwarder(hub_records: List[dict]) -> None:
        # process=sender (5.21 (c)): каждая live-запись несёт имя процесса-источника.
        batch_channel.push_batch([hub_record_to_display(r, process=sender) for r in hub_records])

    taps: list[Tuple[Any, str]] = []
    for mgr, tap_name in ((error_manager, error_name), (logger_manager, logger_name)):
        if mgr is None or not hasattr(mgr, "add_tap"):
            continue
        channel = RecordForwardChannel(router=router, subscriber=subscriber, sender=sender, name=tap_name)
        mgr.add_tap(channel, min_level=min_level, name=tap_name)
        taps.append((mgr, tap_name))
    return forwarder, taps


def unwire_observability_forward(taps: Optional[list]) -> None:
    """Снять forward-tap'ы live-хвоста с их менеджеров (unsubscribe/teardown)."""
    for mgr, tap_name in taps or []:
        if mgr is not None and hasattr(mgr, "remove_tap"):
            try:
                mgr.remove_tap(tap_name)
            except Exception:  # nosec B110 — teardown best-effort
                pass


# ---------------------------------------------------------------------------
# Ф8.5 — плоскость документов: второе правило допуска
# ---------------------------------------------------------------------------

#: Адрес ключа в конфиге — он же то, что печатается в WARNING'е. Константа, а не
#: строка по месту: оператор получает адрес, по которому можно ГРЕПНУТЬ конфиг, и
#: этот адрес обязан совпадать с тем, что читает код.
DOCUMENTS_CONFIG_ADDRESS = "observability.documents"

#: Атрибуты процесса, на которых живёт плоскость. Публикация стока (``document_sink``)
#: — не удобство, а условие того, что клиентов у плоскости может быть двое: аудит
#: (пишет фреймворк) и вердикты (пишет приложение) идут в ОДИН экземпляр, то есть в
#: одно соединение и один файл. Заведи приложение свой стор — writer'ов на файл стало
#: бы вдвое больше, а «один писатель на процесс» перестало бы быть правдой.
DOCUMENT_SINK_ATTR = "document_sink"
_PURGE_DEADLINE_ATTR = "_document_purge_at"
_PURGE_INTERVAL_ATTR = "_document_purge_interval"

#: Период уборки по умолчанию, сек. Час — потому что срок хранения документа
#: измеряется сутками и годами: точность уборки в пределах часа не наблюдаема.
DEFAULT_PURGE_INTERVAL_SEC = 3600.0

#: C3 (major-10): документы, которые писали в НЕОБЪЯВЛЕННУЮ плоскость. Симметрия с
#: четвёртым классом потери записей (``records_without_channels``): «приёмника нет
#: вовсе» — отдельный диагноз, и лечится он конфигом, а не базой.
#: Счётчик живёт на ПРОЦЕССЕ, а не на ``PluginContext``: контекстов у процесса
#: столько же, сколько плагинов (плюс клоны ``with_config``), и счётчик на
#: контексте показывал бы каждому свою правду.
_DOCS_WITHOUT_SINK_ATTR = "_documents_without_sink"
#: «Уже сказали» — по одному флагу на КЛАСС отказа, а не один на оба: голос про
#: отсутствие плоскости не имеет права заглушить голос про отказ стока.
_DOCS_WARNED_NO_SINK_ATTR = "_documents_warned_no_sink"
_DOCS_WARNED_REFUSED_ATTR = "_documents_warned_refused"

#: Этап 6, задача 1.1: адрес плоскости stats в конфиге — тот же приём, что у
#: ``DOCUMENTS_CONFIG_ADDRESS``: оператор получает то, что можно грепнуть.
STATS_CONFIG_ADDRESS = "statistics"

#: Метрики, которые писали в процесс БЕЗ ``StatsManager``. Симметрия с
#: ``_DOCS_WITHOUT_SINK_ATTR``: «менеджера нет вовсе» — диагноз конфига, не базы.
#: Счётчик на ПРОЦЕССЕ, а не на контексте: контекстов у процесса столько же,
#: сколько плагинов, и счётчик на контексте показывал бы каждому свою правду.
_STATS_WITHOUT_PLANE_ATTR = "_stats_without_plane"
_STATS_WARNED_NO_PLANE_ATTR = "_stats_warned_no_plane"


def note_metric_without_plane(svc: Any, metric: str, source: str) -> None:
    """Учесть метрику, которой некуда ехать, и сказать это ОДИН раз (этап 6, 1.1).

    Форма — дословно ``note_document_without_sink``: первый случай WARNING'ом с
    адресом, дальше молча счётчиком. Довод тот же и проверен на документах:
    метрика пишется на такте, и голос на каждую превратил бы ненастроенную
    плоскость в поток, к которому перестают прислушиваться.

    Возврата у метрик нет (``record_metric -> None``, сигнатура дословна
    ``StatsManager``), поэтому счётчик и голос — ЕДИНСТВЕННЫЙ канал, которым
    ненастроенная плоскость наблюдаема. У документов рядом есть ``False``, и
    там же — соблазн счесть этот путь тихим: здесь тихим он быть не может.
    """
    try:
        setattr(svc, _STATS_WITHOUT_PLANE_ATTR, int(getattr(svc, _STATS_WITHOUT_PLANE_ATTR, 0) or 0) + 1)
    except Exception:  # noqa: BLE001 — иммутабельный дубль в тесте не должен ронять линию
        return
    if getattr(svc, _STATS_WARNED_NO_PLANE_ATTR, False):
        return
    try:
        setattr(svc, _STATS_WARNED_NO_PLANE_ATTR, True)
    except Exception:  # noqa: BLE001
        pass
    _process_warn(
        svc,
        f"[stats] метрика {metric!r} от {source!r} писать некуда: у процесса нет StatsManager "
        f"({STATS_CONFIG_ADDRESS}) — дальше считаем молча, "
        f"счётчик в introspect.observability -> stats.without_plane",
    )


def stats_plane_report(svc: Any) -> Dict[str, Any]:
    """Секция ``stats`` для ``introspect.observability`` (этап 6, 1.1).

    Два числа отвечают на разные вопросы, и слить их нельзя:

    * ``declared`` — менеджер поднят, метрике есть куда ехать;
    * ``without_plane`` — сколько метрик написали, когда менеджера нет. Лечится
      конфигом, а не базой.

    Отказов у самого ``StatsManager`` на этом пути не бывает (запись в окно —
    операция в памяти), поэтому третьего числа, симметричного ``dropped``
    документов, здесь нет — пустая графа «не измерено» врала бы о наличии
    механизма отказа.
    """
    stats = getattr(svc, "stats_manager", None)
    return {
        "stats": {
            "declared": callable(getattr(stats, "record_metric", None)),
            "without_plane": int(getattr(svc, _STATS_WITHOUT_PLANE_ATTR, 0) or 0),
        }
    }


def note_document_without_sink(svc: Any, kind: str, source: str) -> None:
    """Учесть документ, которому некуда ехать, и сказать это ОДИН раз (C3).

    Первый случай — WARNING с адресом: род документа, его источник и ключ
    конфига, по которому плоскость поднимают. Дальше — молча, счётчиком:
    вердикт на каждую деталь превратил бы ненастроенную плоскость в поток
    предупреждений, а к потоку перестают прислушиваться. Число при этом не
    теряется — его отдаёт :func:`document_plane_report`.
    """
    try:
        setattr(svc, _DOCS_WITHOUT_SINK_ATTR, int(getattr(svc, _DOCS_WITHOUT_SINK_ATTR, 0) or 0) + 1)
    except Exception:  # noqa: BLE001 — иммутабельный дубль в тесте не должен ронять запись
        return
    if getattr(svc, _DOCS_WARNED_NO_SINK_ATTR, False):
        return
    try:
        setattr(svc, _DOCS_WARNED_NO_SINK_ATTR, True)
    except Exception:  # noqa: BLE001
        pass
    _process_warn(
        svc,
        f"[documents] документ рода {kind!r} от {source!r} писать некуда: плоскость не объявлена "
        f"({DOCUMENTS_CONFIG_ADDRESS}.factory) — дальше считаем молча, "
        f"счётчик в introspect.observability -> documents.without_sink",
    )


def note_document_refused(svc: Any, kind: str, source: str) -> None:
    """Сказать ОДИН раз, что настроенный сток отказал (C3).

    Своего счётчика здесь нет намеренно: отказы считает сам сток
    (``DocumentStore.dropped``), и второй счётчик того же события разошёлся бы
    с первым. Наружу число отдаёт :func:`document_plane_report`, читая сток.
    """
    if getattr(svc, _DOCS_WARNED_REFUSED_ATTR, False):
        return
    try:
        setattr(svc, _DOCS_WARNED_REFUSED_ATTR, True)
    except Exception:  # noqa: BLE001
        pass
    _process_warn(
        svc,
        f"[documents] документ рода {kind!r} от {source!r} НЕ записан: сток отказал "
        f"— дальше считаем молча, счётчик в introspect.observability -> documents.dropped",
    )


def document_plane_report(svc: Any) -> Dict[str, Any]:
    """Секция ``documents`` для ``introspect.observability`` (C3).

    Три числа, и каждое отвечает на свой вопрос:

    * ``declared`` — плоскость объявлена конфигом и сток поднялся;
    * ``without_sink`` — сколько документов писали, когда плоскости нет. Лечится
      конфигом (``observability.documents``);
    * ``dropped`` — сколько отказал сам сток. Лечится базой. ``None`` — сток не
      ведёт счётчика: «не измерено» обязано отличаться от «ноль потерь», иначе
      слепота читается как здоровье.

    Слить два первых числа в одно нельзя: диагнозы разные, и общий счётчик
    отправил бы искать поломку не туда.
    """
    sink = getattr(svc, DOCUMENT_SINK_ATTR, None)
    dropped = getattr(sink, "dropped", None) if sink is not None else 0
    return {
        "documents": {
            "declared": bool(getattr(sink, "append", None)),
            "without_sink": int(getattr(svc, _DOCS_WITHOUT_SINK_ATTR, 0) or 0),
            "dropped": int(dropped) if isinstance(dropped, int) else None,
        }
    }


def _process_warn(svc: Any, message: str) -> None:
    """Сказать вслух. Форма повторяет ``make_audit_log``: логгер бывает разный, а
    молчание недопустимо ни при каком."""
    warn = (
        getattr(svc, "_log_warning", None)
        or getattr(svc, "log_warning", None)
        or getattr(svc, "_log_info", None)
        or getattr(svc, "log_info", None)
    )
    if not callable(warn):
        return
    try:
        warn(message, module="observability")
    except TypeError:  # логгер без kwarg `module` — сообщение важнее формы
        warn(message)


def resolve_factory(path: str) -> Callable[..., Any]:
    """``"пакет.модуль:атрибут"`` (или ``"пакет.модуль.атрибут"``) → вызываемый объект.

    Обе формы приняты сознательно. Двоеточие однозначно (``class_loader`` его не знает,
    но ``register_sink_factory`` и точки входа setuptools — знают) и не заставляет
    гадать, где кончается пакет; точка привычна и уже используется для класса процесса.
    Отказ громкий: неизвестный модуль/атрибут — исключение, а не ``None``.
    """
    text = str(path).strip()
    if ":" in text:
        module_name, _, attr = text.partition(":")
    else:
        module_name, _, attr = text.rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"{path!r} — не import-path вида 'модуль:атрибут'")
    obj = getattr(importlib.import_module(module_name), attr)
    if not callable(obj):
        raise TypeError(f"{path!r} — не вызываемый объект ({type(obj).__name__})")
    return obj


def wire_document_sink(svc: Any) -> Optional[Any]:
    """Ф8.5: собрать сток документов процесса и подключить его к аудиту.

    Возвращает объект стока (для teardown и для второго клиента) либо ``None`` —
    плоскость не объявлена ЛИБО объявлена и не собралась. Разница между этими двумя
    случаями не теряется: во втором в журнал уходит WARNING с адресом ключа и
    причиной. Молчаливый ``None`` был бы неотличим от «не настроено» — тот самый
    класс «проглоченный сбой», ради которого фаза и затевалась.

    **Зовётся у КАЖДОГО процесса, а не только у пилота hub'а** (Р-8.5-А): аудит смен
    наблюдаемости есть везде, потому что команда смены приходит куда угодно. Ключа в
    конфиге нет — выходим на второй строке, поведение прежнее.

    **Почему ключ читается из разрешённых слоёв, а не отдельным полем proc_dict.**
    Секция ``observability`` уже едет к процессу целиком (L1 ``observability_app`` +
    L2 ``observability_override``) обеими дорогами сборки — и boot, и switch. Заведи
    мы свой плоский ключ, его пришлось бы класть в ДВУХ конструкторах ассемблера, и
    забытый второй дал бы ровно «дефект на одном пути из трёх»: после горячей смены
    рецепта плоскость молча исчезала бы. Здесь класть нечего — ключ доезжает тем же
    механизмом, что и уровень логирования, и настраивается рецептом наравне с ним.
    """
    from ..configs.observability_layers import process_observability_layers

    try:
        layers = process_observability_layers(svc)
        section = layers.resolve().get("documents") or {}
    except Exception as exc:  # noqa: BLE001 — процесс без конфига живёт без плоскости
        _process_warn(svc, f"[observability] секция {DOCUMENTS_CONFIG_ADDRESS} не прочитана: {exc!r}")
        return None

    if not isinstance(section, dict):
        _process_warn(
            svc,
            f"[observability] {DOCUMENTS_CONFIG_ADDRESS} не словарь "
            f"({type(section).__name__}) — плоскость документов не поднята",
        )
        return None
    factory_path = str(section.get("factory") or "").strip()
    if not factory_path:
        return None

    config = section.get("config")
    try:
        sink = resolve_factory(factory_path)(dict(config) if isinstance(config, dict) else {})
    except Exception as exc:  # noqa: BLE001 — отказ фабрики громкий, но не фатальный
        _process_warn(
            svc,
            f"[observability] плоскость документов НЕ поднята: фабрика "
            f"{DOCUMENTS_CONFIG_ADDRESS}.factory={factory_path!r} отказала ({exc!r}). "
            "Аудит остаётся кольцом в памяти и строками журнала; документы не пишутся",
        )
        return None

    append = getattr(sink, "append", None)
    if not callable(append):
        # Проверка СТРУКТУРНАЯ, а не isinstance протокола: импортировать протокол
        # значило бы импортировать Services, то есть отменить всю развилку.
        #
        # Адрес ключа тут обязателен ровно так же, как в ветке выше. Найдено
        # независимым tester'ом: правило «называй адрес» было применено к ОДНОЙ из
        # двух точек отказа, и оператор, попавший во вторую, получал сообщение без
        # места, куда идти править. Тот же класс, что «инъекция покрывает не все
        # точки правила», только со стороны исполнения.
        _process_warn(
            svc,
            f"[observability] плоскость документов НЕ поднята: "
            f"{DOCUMENTS_CONFIG_ADDRESS}.factory={factory_path!r} вернула "
            f"{type(sink).__name__} без метода append(dict)",
        )
        return None

    layers.audit.sink = append
    # Имя процесса в документе: плоскость одна на систему, и без него восемь
    # писателей неразличимы — «когда включили DEBUG» отвечалось бы без «где».
    layers.audit.source = str(getattr(svc, "name", "") or "")
    try:
        setattr(svc, DOCUMENT_SINK_ATTR, sink)
        setattr(svc, _PURGE_INTERVAL_ATTR, _purge_interval(config))
        # Срок здесь НЕ ставится: первая уборка идёт на первом же такте. Иначе
        # пришлось бы засеять дедлайн показанием часов, которых сшивка не видит —
        # ``sweep_process_documents`` принимает ``now`` параметром, и смешивать его
        # с монотоникой, снятой в другом месте, значит сравнивать разные шкалы.
        # Побочная польза: процесс, поднятый после долгого простоя, подметает сразу,
        # а не через час после старта.
        setattr(svc, _PURGE_DEADLINE_ATTR, None)
    except Exception:  # noqa: BLE001 — объект без сеттеров: аудит пишет, уборки нет
        pass
    return sink


def _purge_interval(config: Any) -> float:
    """Период уборки из словаря фабрики. Мусор и ноль → дефолт, а не «никогда»."""
    raw = config.get("purge_interval_sec") if isinstance(config, dict) else None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_PURGE_INTERVAL_SEC
    return value if value > 0 else DEFAULT_PURGE_INTERVAL_SEC


def sweep_process_documents(svc: Any, now: Optional[float] = None) -> Optional[int]:
    """Р-8.5-В: удалить протухшие документы — не чаще ``purge_interval_sec``.

    Возвращает число удалённых, либо ``None``, если такт пропущен (плоскости нет или
    срок следующей уборки не наступил).

    **Свой поток не заводится.** Такт heartbeat уже идёт в каждом процессе, уже
    дренирует hub и уже снимает просроченные правки L3 — четвёртое хозяйственное дело
    в нём стоит одного ``if``, а поток стоил бы ещё одной процедуры остановки ради
    операции раз в час.

    **Отказ БД такт не роняет** (Р-8.5-Г). Симметрично ``append``: уборка — это
    хозяйство, а heartbeat — liveness, и потеря первого не имеет права стоить второго.
    Но глушение именное: отказ уходит в журнал WARNING'ом.
    """
    store = getattr(svc, DOCUMENT_SINK_ATTR, None)
    purge = getattr(store, "purge_expired", None)
    if not callable(purge):
        return None
    moment = time.monotonic() if now is None else float(now)
    deadline = getattr(svc, _PURGE_DEADLINE_ATTR, None)
    if deadline is not None and moment < float(deadline):
        return None
    interval = float(getattr(svc, _PURGE_INTERVAL_ATTR, DEFAULT_PURGE_INTERVAL_SEC) or DEFAULT_PURGE_INTERVAL_SEC)
    # Срок следующей уборки ставится ДО самой уборки: упади она — такт всё равно
    # не превратится в попытку каждый heartbeat, то есть отказ БД не станет ещё и
    # источником нагрузки на неё же.
    try:
        setattr(svc, _PURGE_DEADLINE_ATTR, moment + interval)
    except Exception:  # noqa: BLE001
        pass
    try:
        return int(purge() or 0)
    except Exception as exc:  # noqa: BLE001 — см. докстринг
        _process_warn(svc, f"[observability] уборка плоскости документов не удалась: {exc!r}")
        return None


def unwire_document_sink(svc: Any) -> None:
    """Отцепить сток от аудита и закрыть его (graceful teardown).

    Порядок обратный сшивке: сперва аудит перестаёт писать, потом закрывается БД.
    Наоборот — и запись, пришедшая между двумя строками, ушла бы в закрытое
    соединение, то есть отказ появился бы ровно на остановке, где его труднее всего
    объяснить.
    """
    from ..configs.observability_layers import LAYERS_ATTR

    layers = getattr(svc, LAYERS_ATTR, None)
    audit = getattr(layers, "audit", None)
    if audit is not None:
        try:
            audit.sink = None
        except Exception:  # noqa: BLE001 — teardown best-effort
            pass
    store = getattr(svc, DOCUMENT_SINK_ATTR, None)
    close = getattr(store, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # nosec B110 — teardown best-effort
            pass
    try:
        setattr(svc, DOCUMENT_SINK_ATTR, None)
    except Exception:  # noqa: BLE001
        pass


#: Адрес секции истории в конфиге наблюдаемости (Ф5.2). Константа, а не строка по
#: месту: этот адрес печатается в readback и в предупреждениях, и он обязан
#: совпадать с тем, по которому оператор грепает конфиг.
HISTORY_CONFIG_ADDRESS = "observability.history"

#: Порог записи в историю по умолчанию. **INFO, а не ERROR**, и это решение задачи,
#: а не унаследованное число: вкладка «Логи» с порогом ERROR пуста по построению —
#: ровно та находка (Б-8), ради которой задача и заведена. Безопасным INFO делает
#: не скромность, а предел: :data:`DEFAULT_HISTORY_MAX_ROWS` ограничивает таблицу
#: сверху независимо от темпа записи.
DEFAULT_HISTORY_LEVEL = "INFO"

#: Потолок истории по числу строк.
#:
#: **Число потолка измерено, а не оценено** (живой прогон `webcam_sketch`,
#: 2026-08-09): 1369 строк заняли 0.707 МиБ = **542 Б на строку** — это строка
#: стора с JSON-полем ``extra`` и двумя индексами, а не голая строка лога.
#: Первая редакция этого комментария брала 108 Б из замера Ф6 (длина строки в
#: ФАЙЛЕ журнала) и обещала 60–80 МБ — ошибка впятеро, ровно класс «уверенное
#: неверное число».
#:
#: Отсюда честный потолок: 200 000 × 542 Б ≈ **110 МБ** на стенд. Темп того же
#: прогона — 5040 строк/час, то есть предел по числу строк наступает примерно
#: через 40 часов и связывает раньше недельного возраста (7 сут × 5040 ≈ 847 000
#: строк). Оператору, которому 110 МБ много, ручка — ``max_rows`` в секции.
DEFAULT_HISTORY_MAX_ROWS = 200_000

#: Возраст, старше которого запись уходит: неделя. Столько живёт вопрос «что было
#: в прошлый вторник» на этом стенде; больше хранит файловый журнал, у него своя
#: ротация и свой объём.
DEFAULT_HISTORY_MAX_AGE_SEC = 7 * 24 * 3600.0

#: Период уборки истории. Реже документов (там срок в сутках, здесь строки копятся
#: минутами), но не на каждый такт: уборка — хозяйство, а не горячий путь.
DEFAULT_HISTORY_PURGE_INTERVAL_SEC = 300.0

_HISTORY_POLICY_ATTR = "_observability_history_policy"
_HISTORY_PURGE_DEADLINE_ATTR = "_observability_history_purge_at"


def resolve_history_policy(svc: Any) -> Dict[str, Any]:
    """Политика истории из слоёв конфига — с дефолтами и без тихого мусора (Ф5.2).

    Читается из ``observability.history`` теми же слоями, что и всё остальное
    (L0→L3): отдельного плоского ключа не заводится по той же причине, что у
    плоскости документов — его пришлось бы класть в ДВУХ конструкторах ассемблера,
    и забытый второй дал бы «дефект на одном пути из трёх».

    Мусор в значении **не молчит**: ключ падает на дефолт, и об этом говорится
    вслух. Тихое приведение к дефолту здесь опаснее обычного — оператор,
    опечатавшийся в ``max_rows``, ушёл бы уверенным, что поставил предел.
    """
    section: Any = {}
    try:
        from ..configs.observability_layers import process_observability_layers

        section = process_observability_layers(svc).resolve().get("history") or {}
    except Exception as exc:  # noqa: BLE001 — процесс без конфига живёт на дефолтах
        _process_warn(svc, f"[observability] секция {HISTORY_CONFIG_ADDRESS} не прочитана: {exc!r}")
        section = {}
    if not isinstance(section, dict):
        _process_warn(
            svc,
            f"[observability] {HISTORY_CONFIG_ADDRESS} не словарь ({type(section).__name__}) — история на дефолтах",
        )
        section = {}

    def _number(key: str, default: float, *, integer: bool) -> Any:
        raw = section.get(key)
        if raw is None:
            return int(default) if integer else float(default)
        try:
            value = int(raw) if integer else float(raw)
        except (TypeError, ValueError):
            _process_warn(
                svc,
                f"[observability] {HISTORY_CONFIG_ADDRESS}.{key}={raw!r} — не число, взят дефолт {default}",
            )
            return int(default) if integer else float(default)
        # Ноль и отрицательное = «предела нет». Это ОБЪЯВЛЕННЫЙ отказ от защиты, и
        # он проходит как есть — но громко, потому что молчаливая безлимитность и
        # была исходным состоянием, которое задача чинит.
        if value <= 0:
            _process_warn(
                svc,
                f"[observability] {HISTORY_CONFIG_ADDRESS}.{key}={value} — предел СНЯТ, история растёт без ограничения",
            )
        return value

    level = str(section.get("level") or DEFAULT_HISTORY_LEVEL).upper()
    if normalize_level_name(level) is None:
        _process_warn(
            svc,
            f"[observability] {HISTORY_CONFIG_ADDRESS}.level={level!r} — неизвестный уровень, "
            f"взят дефолт {DEFAULT_HISTORY_LEVEL}",
        )
        level = DEFAULT_HISTORY_LEVEL
    return {
        "level": level,
        "max_rows": _number("max_rows", DEFAULT_HISTORY_MAX_ROWS, integer=True),
        "max_age_sec": _number("max_age_sec", DEFAULT_HISTORY_MAX_AGE_SEC, integer=False),
        "purge_interval_sec": _number("purge_interval_sec", DEFAULT_HISTORY_PURGE_INTERVAL_SEC, integer=False),
    }


def sweep_observability_history(svc: Any, now: Optional[float] = None) -> Optional[Dict[str, int]]:
    """Уборка истории по такту heartbeat — не чаще ``purge_interval_sec`` (Ф5.2).

    Форма повторяет :func:`sweep_process_documents` дословно, и это намеренно:
    второй способ делать хозяйственное дело в такте означал бы вторую процедуру
    остановки и второе место, где его забудут.

    Возвращает отчёт :meth:`ObservabilityStore.purge` либо ``None`` — такт пропущен
    (стора нет или срок не наступил).
    """
    store = getattr(svc, "_observability_store", None)
    purge = getattr(store, "purge", None)
    if not callable(purge):
        return None
    policy = getattr(svc, _HISTORY_POLICY_ATTR, None) or {}
    moment = time.monotonic() if now is None else float(now)
    deadline = getattr(svc, _HISTORY_PURGE_DEADLINE_ATTR, None)
    if deadline is not None and moment < float(deadline):
        return None
    interval = float(policy.get("purge_interval_sec") or DEFAULT_HISTORY_PURGE_INTERVAL_SEC)
    if interval <= 0:
        interval = DEFAULT_HISTORY_PURGE_INTERVAL_SEC
    # Срок ставится ДО уборки: упади она — такт не превратится в попытку каждый
    # heartbeat, то есть отказ БД не станет ещё и источником нагрузки на неё же.
    try:
        setattr(svc, _HISTORY_PURGE_DEADLINE_ATTR, moment + interval)
    except Exception:  # noqa: BLE001
        pass
    try:
        return purge(max_rows=policy.get("max_rows"), max_age_sec=policy.get("max_age_sec"))
    except Exception as exc:  # noqa: BLE001 — хозяйство не имеет права ронять liveness
        _process_warn(svc, f"[observability] уборка истории не удалась: {exc!r}")
        return None


def wire_observability_store(
    error_manager: Optional[Any],
    logger_manager: Optional[Any] = None,
    db_path: Optional[str] = None,
    process: str = "",
    min_level: str = "ERROR",
) -> Tuple[ObservabilityStore, list]:
    """Создать персистентный стор и повесить store-tap на менеджеры ошибок (Ф5.20a).

    error/critical идут write-through в реальные менеджеры (Ф5.16 + R1/R3): через
    error_manager (track_error) И через logger_manager (logger-слот пилота — сам
    реальный logger_manager, 2.2). tap ловит их у реального sink'а и кладёт в стор
    (так вкладка «Ошибки» получает историю). stats пишутся в стор из drain-петли
    (см. drain_process_observability); лог в стор из drain-петли больше не приходит.

    **Live-урок (2026-07-09):** ошибки приложения (напр. CapturePlugin через
    `ctx.log_error`) идут в logger_manager, НЕ в error_manager — tap только на
    error_manager видит ~0 ошибок. Поэтому store-tap вешаем НА ОБА менеджера на
    уровне ERROR: и error_manager (write-through track_error/log_exception), и
    logger_manager (`logger.error`/`ctx.log_error`, а также error/critical
    logger-слота пилота). Оба пишут kind='error'; это разные менеджеры-инстансы.
    **Ключ к отсутствию дублей (R1):** лог пилота приходит в logger_manager РОВНО
    один раз — hub-буфера для лога больше нет вообще (2.2), поэтому drain-адаптеру
    нечего переигрывать (раньше переигрывал → tap срабатывал дважды). Одна эмиссия →
    одна запись у одного tap'а, и это свойство теперь структурное, а не соглашение
    о severity.

    Args:
        error_manager: реальный ErrorManager (LoggerCore с add_tap).
        logger_manager: реальный LoggerManager (LoggerCore с add_tap).
        db_path: путь к SQLite-файлу стора. None → resolve_default_db_path().
        process: имя процесса-источника (5.21 (c)) — tap проставит колонку
            ``process`` в стор-записи (иначе виден только ``module`` — имя
            источника внутри процесса).
        min_level: порог записи в историю (Ф5.2). Прежнее ``ERROR`` оставляло
            вкладку «Логи» пустой ПО ПОСТРОЕНИЮ — это и была находка Б-8. Теперь
            порог задаёт ``observability.history.level`` (дефолт INFO), а от роста
            таблицы защищает ретеншен (:func:`sweep_observability_history`), а не
            высокий порог.

    Returns:
        (store, taps) — taps: список (manager, tap_name) для unwire.
    """
    store = ObservabilityStore(db_path)
    taps: list[Tuple[Any, str]] = []
    for mgr, tap_name in ((error_manager, STORE_ERROR_TAP), (logger_manager, STORE_LOGGER_TAP)):
        if mgr is None or not hasattr(mgr, "add_tap"):
            continue
        # Вид записи (log/error) считает её важность — tap'у он не задаётся (Б-4).
        mgr.add_tap(StoreTapChannel(store, name=tap_name, process=process), min_level=min_level, name=tap_name)
        taps.append((mgr, tap_name))
    return store, taps


def unwire_observability_store(
    store: Optional[ObservabilityStore],
    taps: Optional[list],
) -> None:
    """Снять store-tap'ы с их менеджеров и закрыть стор (graceful teardown)."""
    for mgr, tap_name in taps or []:
        if mgr is not None and hasattr(mgr, "remove_tap"):
            try:
                mgr.remove_tap(tap_name)
            except Exception:  # nosec B110 — teardown best-effort
                pass
    if store is not None:
        try:
            store.close()
        except Exception:  # nosec B110
            pass
