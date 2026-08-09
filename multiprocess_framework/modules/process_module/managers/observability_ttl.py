# -*- coding: utf-8 -*-
"""Авто-возврат рантайм-правок наблюдаемости по истечении срока (Task 5.8).

Закрывает резидуал R1 задачи 5.12, названный в плане явно: до слоёв «включил
DEBUG и забыл» стиралось любым ``config.reload``; после 5.12 ручка переживает
reload, а через ``observability.persist`` становится вечной — то есть живой
инцидент «messages.log 645 МБ за прогон» стал ВЕРОЯТНЕЕ, чем был.

Модель одна: **L3 временный по построению**. Срок несёт каждая запись сессии
(:meth:`ObservabilityLayers.session_set`), а исполняет возврат такт heartbeat.
Постоянной правку делает ровно один путь — ``observability.persist``, то есть
переезд в L2, где вечность обеспечена файлом, а не забывчивостью.

Почему heartbeat, а не свой таймер
----------------------------------
Такт liveness уже идёт в КАЖДОМ процессе, включая оркестратор
(``ProcessManagerProcess`` не переопределяет ``run``), останавливается вместе с
процессом и уже несёт три таких же хозяйственных дела — дренаж hub'а, публикацию
health и pump GC. Свой поток означал бы четвёртый способ жить и четвёртую
процедуру остановки ради операции, которая случается раз в пять минут.

Цена решения названа честно: **срок — это срок, а не таймер**. Возврат наступает
на первом такте liveness ПОСЛЕ истечения, то есть не позже ``ttl +
heartbeat_interval`` (по умолчанию +5с). Для защиты от забытого DEBUG это
безразлично, но обещать секундную точность нельзя.

Где гарантии нет — сказано вслух
--------------------------------
Процесс без heartbeat (``heartbeat_interval <= 0``, нет ``worker_manager``)
подметальщика не имеет. Срок в таком процессе ставится, но не исполняется —
и команда обязана ответить ``ttl_enforced: false``. Молчаливое «срок принят»
там, где возврата не будет, — ровно тот класс ложного сигнала, который на этом
проекте уже стоил дня разбирательств.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..configs.observability_layers import LAYERS_ATTR, ObservabilityLayers

#: Механизм смены для аудита (Task 5.9). Такт подметальщика — единственный
#: источник смен, за которым не стоит человек, и в разборе инцидента отличить
#: «вернулось само по сроку» от «кто-то откатил» нужно первым делом.
AUDIT_ORIGIN = "ttl-sweeper"


def ttl_enforced(svc: Any) -> bool:
    """Есть ли у процесса живой подметальщик сроков (такт heartbeat)."""
    heartbeat = getattr(svc, "_heartbeat", None)
    is_running = getattr(heartbeat, "is_running", None)
    if not callable(is_running):
        return False
    try:
        return bool(is_running())
    except Exception:  # noqa: BLE001 — «не знаю» = «не гарантирую»
        return False


def ttl_report(svc: Any, layers: ObservabilityLayers) -> Dict[str, Any]:
    """Блок про сроки для ответов команд и ``introspect.observability``.

    Единая форма у всех четырёх мест, где про сроки спрашивают: иначе оператор
    сверяет разные поля разных команд и делает вывод из их расхождения.
    """
    return {
        "ttl": layers.session_ttl_view(),
        "ttl_default_sec": layers.effective_session_ttl(),
        "ttl_enforced": ttl_enforced(svc),
        "reverts": list(layers.session_reverts),
    }


def sweep_session_ttl(svc: Any) -> Optional[Dict[str, Any]]:
    """Один проход подметальщика: снять просроченное и пересобрать конфиг.

    Возвращает отчёт (что снято, чем закончилась пересборка) либо ``None``, если
    делать было нечего. ``None`` — самый частый ответ и он не стоит ничего:
    процесс, к ручкам которого не прикасались, стека слоёв вообще не имеет, и
    подметальщик выходит на первой строке.

    Исключений не бросает: отказ пересборки — это отчёт со ``success: False``,
    повторная попытка на следующем такте и громкая запись. Проглотить его нельзя
    — ключ из L3 уже удалён, и молчание оставило бы менеджеры на конфиге правки,
    которой больше нет.
    """
    layers = getattr(svc, LAYERS_ATTR, None)
    if not isinstance(layers, ObservabilityLayers):
        return None

    expired = list(layers.expire_due())
    if not expired and not layers.rebuild_pending:
        return None

    from .observability_reload import apply_observability_layers, telemetry_targets

    entry: Dict[str, Any] = {
        # Своей отметки времени тут нет намеренно (A-A6-1): аудит ставит `ts` сам,
        # а второй timestamp в теле записи делал бы КАЖДЫЙ такт повтора уникальным
        # — схлопывание залипшего отказа не сработало бы ни разу. Читателей у
        # прежнего поля `at` не было ни одного (проверено grep'ом), так что это
        # снятие дубля, а не потеря.
        "keys": expired,
        # Повтор после неудачи отличается от свежего истечения: без причины в
        # записи «ключей ноль, а возврат был» читается как сбой учёта.
        "reason": "ttl" if expired else "retry",
        "success": True,
    }
    try:
        applied = apply_observability_layers(
            layers,
            logger=getattr(svc, "logger_manager", None),
            error=getattr(svc, "error_manager", None),
            stats=getattr(svc, "stats_manager", None),
            log_info=None,  # своё сообщение ниже — оно про возврат, а не про пересборку
            # Task 5.10.f: истечь может и ключ телеметрии. Не передай мы её
            # получателей — возврат объявлялся бы, а гейт оставался на истёкшей
            # правке: следствие без причины, худший из возможных исходов.
            **telemetry_targets(svc),
            origin=AUDIT_ORIGIN,
            # Запись за такт кладёт `note_revert` ниже: она несёт и снятые ключи,
            # и исход пересборки. Generic-запись была бы вторым описанием того же
            # факта — см. `record_rebuild` (замечание 4 ревью 5.9).
            record_rebuild=False,
        )
    except Exception as exc:  # noqa: BLE001 — отчёт, а не падение такта
        layers.rebuild_pending = True
        entry["success"] = False
        entry["error"] = repr(exc)
        layers.note_revert(entry, origin=AUDIT_ORIGIN)
        _announce_failure(svc, expired, exc)
        return entry

    layers.rebuild_pending = False
    entry["log_level"] = applied["logger"].get("default_level")
    entry["session_keys"] = list(layers.session_keys())
    layers.note_revert(entry, origin=AUDIT_ORIGIN)
    if expired:
        _announce_revert(svc, expired, entry["log_level"], layers)
    return entry


def _announce_revert(svc: Any, keys: List[str], level: Any, layers: ObservabilityLayers) -> None:
    """Долговечная запись об авто-возврате — строка в журнале процесса.

    Уровень WARNING, а не INFO, и это выбор: возврат сам по себе штатен, но он
    означает, что правка оператора БОЛЬШЕ НЕ ДЕЙСТВУЕТ. Найти это по молчанию
    можно только через час недоумения «почему пропали мои DEBUG-записи».

    Кольцо ``session_reverts`` (readback ``introspect.observability``) журнал не
    заменяет: оно живёт в памяти процесса и умирает вместе с ним, а вопрос
    «когда это вернулось» задают обычно уже после рестарта.
    """
    held = ", ".join(layers.session_keys()) or "—"
    message = (
        f"[observability] TTL истёк — рантайм-правки возвращены к нижнему слою: "
        f"{', '.join(keys)}; действующий log_level={level}; ещё держится сессией: {held}. "
        f"Чтобы правка жила дольше — ttl=<сек> при смене или observability.persist в рецепт"
    )
    log = getattr(svc, "_log_warning", None) or getattr(svc, "log_warning", None)
    if not callable(log):
        log = getattr(svc, "_log_info", None) or getattr(svc, "log_info", None)
    if callable(log):
        try:
            log(message, module="observability")
        except TypeError:  # логгер без kwarg `module` — сообщение важнее формы
            log(message)


def _announce_failure(svc: Any, keys: List[str], exc: BaseException) -> None:
    """Пересборка после истечения срока не удалась — это ошибка, а не debug-шум."""
    message = (
        f"[observability] TTL истёк ({', '.join(keys) or 'повтор'}), но пересобрать конфиг из слоёв "
        f"не удалось: {exc!r}. Менеджеры остались на прежнем конфиге; повтор на следующем такте"
    )
    log = getattr(svc, "_log_error", None) or getattr(svc, "log_error", None)
    if not callable(log):
        log = getattr(svc, "_log_info", None) or getattr(svc, "log_info", None)
    if callable(log):
        try:
            log(message, module="observability")
        except TypeError:
            log(message)
