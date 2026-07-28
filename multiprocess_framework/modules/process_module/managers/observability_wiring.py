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

from typing import Any, Callable, Iterable, List, Optional, Tuple, Union

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
        - adapter сконфигурирован на реальные logger/stats/error.
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

    return hub, adapter


def drain_process_observability(
    hub: Optional[ObservabilityHub],
    adapter: Optional[ObservabilityDrainAdapter],
    store: Optional[ObservabilityStore] = None,
    forwarders: Union[Callable[[List[dict]], None], Iterable[Callable[[List[dict]], None]], None] = None,
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

    Args:
        router: живой RouterManager процесса (``send_async``). None → forwarder-no-op.
        subscriber: адрес GUI-процесса (``targets=[subscriber]``).
        sender: имя процесса-источника.
        logger_manager/error_manager: менеджеры с ``add_tap`` (error-хвост).

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
        mgr.add_tap(channel, min_level="ERROR", name=tap_name)
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


def wire_observability_store(
    error_manager: Optional[Any],
    logger_manager: Optional[Any] = None,
    db_path: Optional[str] = None,
    process: str = "",
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
            ``process`` в стор-записи (иначе виден только scope логгера).

    Returns:
        (store, taps) — taps: список (manager, tap_name) для unwire.
    """
    store = ObservabilityStore(db_path)
    taps: list[Tuple[Any, str]] = []
    for mgr, tap_name in ((error_manager, STORE_ERROR_TAP), (logger_manager, STORE_LOGGER_TAP)):
        if mgr is None or not hasattr(mgr, "add_tap"):
            continue
        # min_level=ERROR → ловим error + critical, ниже не пишем (вкладка «Ошибки»).
        mgr.add_tap(StoreTapChannel(store, name=tap_name, process=process), min_level="ERROR", name=tap_name)
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
