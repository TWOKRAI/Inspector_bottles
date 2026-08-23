"""test_resync_offthread_hazards.py — hazard-тесты окна неблокирующей ресинхронизации.

Автор реализации (не независимый tester). Приёмка (``test_resync_starvation_
acceptance.py``) проверяет, что приёмный поток больше не стоит; здесь —
опасности САМОГО механизма, которые появляются ровно потому, что он перестал
стоять: между отправкой запроса снимка и его приходом теперь ОТКРЫТО окно, в
котором живут дельты.

Что проверяется (ADR-SS-022):
  1. дельта окна СВЕЖЕЕ снимка — снимок её не откатывает;
  2. дельта окна СТАРШЕ снимка — побеждает снимок (иначе ресинк бессмыслен);
  3. дельты окна не «придерживаются» до ответа: кэш и callbacks получают их сразу;
  4. удаление в окне — снимок не воскрешает снятое поддерево;
  5. два разрыва подряд — один запрос в полёте и ровно один догоняющий;
  6. ответ, который не придёт НИКОГДА — состояние названо, механизм не залипает;
  7. переполнение журнала защиты — снимок не применяется вовсе (цена названа числом);
  8. GuiStateProxy (свой on_state_changed) защищён тем же механизмом.

Стенд — настоящие RouterManager + StateProxy, как в приёмочном файле: тест сам
играет роль сервера (кладёт ответ в системный канал), поэтому МОМЕНТ ответа
управляется точно, а окно воспроизводится, а не имитируется.

Все ожидания — с явным дедлайном; тест не имеет права повиснуть вместо падения.
Литералы вписаны руками и не выведены из кода под тестом; настоящее значение
``_SYNC_REQUEST_TIMEOUT`` проверяется отдельным тестом-константой.
"""

from __future__ import annotations

import threading
import time

import pytest
from queue import Queue
from types import SimpleNamespace

from ...router_module import QueueChannel, RouterManager
from ..core.delta import MISSING, Delta
from ..proxy.gui_state_proxy import GuiStateProxy
from ..proxy.state_proxy import StateProxy


class _FakeQueueRegistry:
    """Фиксирует исходящие билеты; ничего не резолвит взаправду."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def send_to_queue(self, target: str, qtype: str, msg: dict) -> bool:
        self.sent.append((target, qtype, msg))
        return True

    def resync_tickets(self) -> list[dict]:
        return [m for (_t, _q, m) in self.sent if m.get("command") == "state.get_subtree"]


class _Stand:
    """Процесс-подписчик целиком: роутер с system/state каналами + StateProxy.

    Тест держит роль сервера: ``deliver()`` кладёт пакет ``state.changed`` в
    state-канал, ``answer_resync()`` — ответ на снимок в system-канал, ``tick()``
    прокручивает приёмный такт (как один оборот ``message_processor``).
    """

    def __init__(self, name: str, *, gui: bool = False) -> None:
        self.qr = _FakeQueueRegistry()
        self.router = RouterManager(
            manager_name=name,
            process=SimpleNamespace(name=name),
            queue_registry=self.qr,
        )
        self.q_system: Queue = Queue()
        self.q_state: Queue = Queue()
        self.router.register_channel(QueueChannel(f"{name}_system", self.q_system))
        self.router.register_channel(QueueChannel(f"{name}_state", self.q_state))
        self.router.initialize()
        self.name = name
        self.received: list[Delta] = []
        if gui:
            self.proxy: StateProxy = GuiStateProxy(
                process_name=name,
                router=self.router,
                delta_sink=self.received.extend,
                server_target="ProcessManager",
            )
        else:
            self.proxy = StateProxy(name, router=self.router, server_target="ProcessManager")
        self.router.register_message_handler("state.changed", self.proxy.on_state_changed)
        self.proxy.subscribe("foo.**", self.received.extend, sync=False)
        self.answered: set[str] = set()

    def deliver(self, deltas: list[Delta], first_revision: int, revision: int) -> None:
        """Пакет state.changed → state-канал → разбор приёмным тактом."""
        self.q_state.put(
            {
                "type": "event",
                "command": "state.changed",
                "sender": "ProcessManager",
                "targets": [self.name],
                "queue_type": "state",
                "data": {
                    "deltas": [d.to_dict() for d in deltas],
                    "revision": revision,
                    "first_revision": first_revision,
                },
            }
        )
        self.tick()

    def answer_resync(self, snapshot: dict, revision: object) -> str:
        """Ответить на ПОСЛЕДНИЙ неотвеченный запрос снимка (роль StateStoreManager)."""
        pending = [t for t in self.qr.resync_tickets() if t.get("request_id") not in self.answered]
        assert pending, "нет неотвеченного запроса снимка — сценарий не воспроизведён"
        cid = pending[-1]["request_id"]
        self.answered.add(cid)
        self.q_system.put(
            {
                "type": "response",
                "command": "command.response",
                "request_id": cid,
                "success": True,
                "result": {"status": "ok", "value": snapshot, "revision": revision},
            }
        )
        self.tick()
        return cid

    def tick(self) -> None:
        self.router.receive(timeout=0.0, channel_types=["system", "state", "observability"])

    def spin(self, predicate, deadline_sec: float) -> bool:
        """Крутить приёмные такты до выполнения условия, но не дольше дедлайна."""
        deadline = time.monotonic() + deadline_sec
        while time.monotonic() < deadline:
            if predicate():
                return True
            self.tick()
            time.sleep(0.01)
        return predicate()

    def close(self) -> None:
        self.router.shutdown()


def _d(path: str, value: object, revision: int, old: object = None) -> Delta:
    return Delta(path=path, old_value=old, new_value=value, source="ProcessManager", revision=revision)


def _open_window(stand: _Stand) -> None:
    """Довести стенд до состояния «ресинк в полёте»: база, затем разрыв revision.

    База: revision=1. Разрыв: пакет начинается с 5 при ожидаемых 2 → resync.
    """
    stand.deliver([_d("foo.bar", 1, revision=1, old=MISSING)], first_revision=1, revision=1)
    assert stand.proxy.cache.get("foo.bar") == 1, "базовая дельта не применена — стенд неисправен"
    stand.deliver([_d("foo.bar", 2, revision=5, old=1)], first_revision=5, revision=5)
    assert stand.proxy._resync_inflight_id is not None, (
        "разрыв revision не открыл окно ресинхронизации — сценарий не воспроизведён"
    )


# ===========================================================================
# 1. Дельта окна СВЕЖЕЕ снимка — снимок её не откатывает
# ===========================================================================


def test_delta_arrived_during_resync_is_not_overwritten_by_an_older_snapshot():
    """Значение, изменённое ЖИВОЙ дельтой в окне, снимок постарше не откатывает.

    Именно этот класс регресса появился вместе с неблокирующим ресинком: раньше
    приёмный поток стоял внутри запроса, и дельт в окне быть не могло вовсе.
    """
    stand = _Stand("hz_newer")
    try:
        _open_window(stand)
        # Дельта окна: revision=6 (свежее снимка, который сервер снял на 5).
        stand.deliver([_d("foo.bar", 99, revision=6, old=2)], first_revision=6, revision=6)
        assert stand.proxy.cache.get("foo.bar") == 99, "дельта окна не применена — сценарий не воспроизведён"

        stand.answer_resync({"foo": {"bar": 2, "extra": 42}}, revision=5)
        cache = stand.proxy.cache
    finally:
        stand.close()

    # Якорь существования: снимок РЕАЛЬНО применён (иначе «не откатило» ничего
    # не значит — снимок мог быть просто выброшен целиком).
    assert cache.get("foo.extra") == 42, (
        f"снимок не применён вовсе (foo.extra отсутствует, кэш={cache!r}) — "
        "проверка «свежее не откатили» была бы пустой"
    )
    assert cache.get("foo.bar") == 99, (
        f"снимок (revision=5) откатил значение живой дельты (revision=6): "
        f"foo.bar={cache.get('foo.bar')!r}, ожидалось 99"
    )


# ===========================================================================
# 2. Дельта окна СТАРШЕ снимка — побеждает снимок
# ===========================================================================


def test_snapshot_wins_over_a_delta_that_is_older_than_the_snapshot():
    """Пара-контроль к предыдущему: старую дельту снимок обязан перекрыть.

    Без этого «защита свежего» выродилась бы в «снимок не применяется никогда»,
    и ресинк перестал бы чинить то, ради чего он есть.
    """
    stand = _Stand("hz_older")
    try:
        _open_window(stand)
        stand.deliver([_d("foo.bar", 99, revision=6, old=2)], first_revision=6, revision=6)
        # Снимок снят ПОЗЖЕ (revision=9): сервер уже знает более новое значение.
        stand.answer_resync({"foo": {"bar": 555, "extra": 42}}, revision=9)
        cache = stand.proxy.cache
        last_revision = stand.proxy._last_revision
    finally:
        stand.close()

    assert cache.get("foo.bar") == 555, (
        f"снимок (revision=9) не перекрыл более старую дельту (revision=6): foo.bar={cache.get('foo.bar')!r}"
    )
    assert cache.get("foo.extra") == 42
    assert last_revision == 9, f"_last_revision не продвинут до серверного 9: {last_revision!r}"


def test_delta_without_revision_loses_to_the_snapshot():
    """Названная цена №1: дельта с revision=0 считается СТАРОЙ, снимок её перекрывает.

    ``Delta.revision`` по умолчанию 0 (отправитель, не знающий про revision, —
    обратная совместимость ADR-SS-014). Сравнивать такую дельту со снимком не с
    чем, и выбран перекос в сторону снимка. Тест фиксирует именно это решение,
    чтобы «цена» не осталась абзацем в ADR.
    """
    stand = _Stand("hz_rev0")
    try:
        _open_window(stand)
        # Конверт с revision=6 (иначе пакет отбросится как устаревший), но САМА
        # дельта без revision — ровно то, что шлёт старый отправитель.
        stand.deliver([_d("foo.bar", 99, revision=0, old=2)], first_revision=6, revision=6)
        assert stand.proxy.cache.get("foo.bar") == 99, "дельта окна не применена — сценарий не воспроизведён"
        stand.answer_resync({"foo": {"bar": 777, "extra": 42}}, revision=5)
        cache = stand.proxy.cache
    finally:
        stand.close()

    assert cache.get("foo.extra") == 42, f"снимок не применён вовсе (кэш={cache!r}) — проверка была бы пустой"
    assert cache.get("foo.bar") == 777, (
        f"дельта без revision победила снимок: foo.bar={cache.get('foo.bar')!r}, ожидалось 777 "
        "(названная цена: revision=0 трактуется как СТАРАЯ)"
    )


def test_snapshot_without_a_revision_protects_every_path_touched_in_the_window():
    """Названная цена №2: сервер не вернул revision → защищаются ВСЕ пути окна.

    Сравнивать не с чем, и перекос выбран в сторону «не откатить живое». Пути,
    которых окно не касалось, снимок при этом применяет как обычно — иначе
    «защита» означала бы «снимок игнорируется целиком».
    """
    stand = _Stand("hz_no_rev")
    try:
        _open_window(stand)
        stand.deliver([_d("foo.bar", 99, revision=6, old=2)], first_revision=6, revision=6)
        # Ответ БЕЗ revision (сервер старой версии / поле потерялось).
        stand.answer_resync({"foo": {"bar": 2, "extra": 42}}, revision=None)
        cache = stand.proxy.cache
        last_revision = stand.proxy._last_revision
    finally:
        stand.close()

    assert cache.get("foo.extra") == 42, (
        f"снимок без revision выброшен целиком (foo.extra отсутствует, кэш={cache!r}) — "
        "нетронутые окном пути обязаны восстанавливаться"
    )
    assert cache.get("foo.bar") == 99, (
        f"снимок без revision откатил живое значение: foo.bar={cache.get('foo.bar')!r}, ожидалось 99"
    )
    assert last_revision == 6, (
        f"_last_revision сдвинут ответом без revision: {last_revision!r}, ожидалось 6 (по последней дельте)"
    )


# ===========================================================================
# 3. Дельты окна не придерживаются до ответа
# ===========================================================================


def test_deltas_during_the_window_reach_the_cache_and_callbacks_immediately():
    """Дельты окна доставляются СРАЗУ, а не после прихода снимка.

    Проверяется прямо ВНУТРИ окна (ответ ещё не отправлен): и кэш, и callbacks
    уже видят значение. Если бы дельты копились «до ресинка», подписчик снова
    получал бы данные пачками раз в таймаут — то есть дефект вернулся бы в
    другой форме.
    """
    stand = _Stand("hz_not_deferred")
    try:
        _open_window(stand)
        before = len(stand.received)
        stand.deliver([_d("foo.live", 7, revision=6, old=MISSING)], first_revision=6, revision=6)

        in_window = stand.proxy._resync_inflight_id is not None
        cached_now = stand.proxy.cache.get("foo.live")
        delivered_now = [d for d in stand.received[before:] if d.path == "foo.live"]
    finally:
        stand.close()

    assert in_window, "окно ресинхронизации закрылось раньше времени — сценарий не воспроизведён"
    assert cached_now == 7, f"дельта окна не попала в кэш до прихода снимка: {cached_now!r}"
    assert len(delivered_now) == 1, (
        f"дельта окна не доставлена подписчику до прихода снимка (получено {len(delivered_now)}) — "
        "поток дельт снова придерживается до ресинка"
    )


# ===========================================================================
# 4. Удаление в окне — снимок не воскрешает поддерево
# ===========================================================================


def test_deletion_during_the_window_is_not_resurrected_by_the_snapshot():
    """Снятие писателя в окне: снимок постарше не возвращает его листья.

    Удаление приходит ОДНОЙ дельтой на корень (TreeStore.delete), а кэш держит
    ЛИСТЬЯ — защищать надо префикс, иначе снимок вернёт показания писателя,
    которого в дереве уже нет (тот же класс, что чинил _update_cache).
    """
    stand = _Stand("hz_delete")
    try:
        stand.deliver(
            [_d("foo.bar.deep", 7, revision=1, old=MISSING)],
            first_revision=1,
            revision=1,
        )
        assert stand.proxy.cache.get("foo.bar.deep") == 7, "стенд неисправен: лист не закэширован"
        stand.deliver([_d("foo.other", 3, revision=5, old=MISSING)], first_revision=5, revision=5)
        assert stand.proxy._resync_inflight_id is not None, "окно не открылось — сценарий не воспроизведён"

        # Удаление поддерева в окне (revision=6, свежее снимка).
        stand.deliver([_d("foo.bar", MISSING, revision=6, old=None)], first_revision=6, revision=6)
        assert "foo.bar.deep" not in stand.proxy.cache, "удаление не применилось — сценарий не воспроизведён"

        stand.answer_resync({"foo": {"bar": {"deep": 7}, "other": 3, "extra": 42}}, revision=5)
        cache = stand.proxy.cache
    finally:
        stand.close()

    assert cache.get("foo.extra") == 42, (
        f"снимок не применён вовсе (кэш={cache!r}) — проверка «не воскресил» была бы пустой"
    )
    assert "foo.bar.deep" not in cache, (
        f"снимок воскресил лист удалённого поддерева: foo.bar.deep={cache.get('foo.bar.deep')!r}"
    )


# ===========================================================================
# 5. Два разрыва подряд — один запрос в полёте, ровно один догоняющий
# ===========================================================================


def test_second_gap_during_the_window_does_not_start_a_parallel_resync():
    """Разрыв, случившийся в окне, не шлёт второго снимка — только догоняющий, один.

    Без совмещения шторм разрывов (а он и есть штатная картина: очередь
    drop_oldest вытесняет 90%+ дельт) породил бы снимок всего поддерева на
    каждый разрыв — и утопил бы IPC ровно там, где его и так не хватает.
    """
    stand = _Stand("hz_coalesce")
    try:
        _open_window(stand)
        assert len(stand.qr.resync_tickets()) == 1, "первый разрыв не отправил ровно один запрос снимка"

        # Второй разрыв ПОКА снимок в полёте: ожидалось 6, пакет с 9.
        stand.deliver([_d("foo.bar", 3, revision=9, old=2)], first_revision=9, revision=9)
        in_flight_tickets = len(stand.qr.resync_tickets())
        coalesced = stand.proxy._resync_coalesced_count

        # Ответ на первый снимок → ровно один догоняющий запрос.
        stand.answer_resync({"foo": {"bar": 2}}, revision=5)
        after_answer = len(stand.qr.resync_tickets())

        # Ответ на догоняющий → новых запросов больше нет.
        stand.answer_resync({"foo": {"bar": 3}}, revision=9)
        stand.tick()
        final_tickets = len(stand.qr.resync_tickets())
        started = stand.proxy._resync_started_count
        inflight = stand.proxy._resync_inflight_id
    finally:
        stand.close()

    assert in_flight_tickets == 1, f"второй разрыв отправил параллельный снимок: запросов={in_flight_tickets}"
    assert coalesced == 1, f"совмещение не зафиксировано счётчиком: {coalesced}"
    assert after_answer == 2, f"догоняющий заход не сделан или сделан не один раз: запросов={after_answer}"
    assert final_tickets == 2, f"появились лишние запросы снимка: {final_tickets}"
    assert started == 2, f"_resync_started_count={started}, ожидалось 2 (первый + догоняющий)"
    assert inflight is None, "окно осталось открытым после последнего ответа"


# ===========================================================================
# 6. Ответ, который не придёт никогда
# ===========================================================================


def test_resync_whose_answer_never_arrives_releases_the_window_and_is_counted():
    """Названо тестом: ответа нет → окно закрывается по таймауту, кэш не тронут,
    следующий разрыв снова может ресинкаться.

    Опасность механизма: отметка «ресинк идёт» — это ещё и глушилка новых
    запросов. Если бы она не снималась, ОДИН потерянный ответ навсегда лишил бы
    процесс ресинхронизации, причём молча.
    """
    stand = _Stand("hz_lost_answer")
    # Литерал 0.25 — параметр стенда, а не ожидаемое значение: настоящий таймаут
    # проверяется отдельным тестом-константой ниже.
    stand.proxy._SYNC_REQUEST_TIMEOUT = 0.25
    try:
        _open_window(stand)
        assert len(stand.qr.resync_tickets()) == 1, "запрос снимка не ушёл — сценарий не воспроизведён"

        released = stand.spin(lambda: stand.proxy._resync_inflight_id is None, deadline_sec=5.0)
        failed = stand.proxy._resync_failed_count
        cache_after = stand.proxy.cache

        # Механизм не залип: новый разрыв снова шлёт снимок.
        stand.deliver([_d("foo.bar", 4, revision=20, old=2)], first_revision=20, revision=20)
        tickets_after = len(stand.qr.resync_tickets())
    finally:
        stand.close()

    assert released, "окно ресинхронизации не закрылось за 5 с после потери ответа — механизм залип"
    assert failed == 1, f"неудача не зафиксирована счётчиком: _resync_failed_count={failed}"
    assert cache_after.get("foo.bar") == 2, (
        f"кэш пострадал от неудавшегося ресинка: foo.bar={cache_after.get('foo.bar')!r}, ожидалось 2 "
        "(значение последней применённой дельты)"
    )
    assert tickets_after == 2, f"после потерянного ответа новый разрыв не запустил ресинк: запросов={tickets_after}"


def test_sync_request_timeout_constant_is_five_seconds():
    """Константа проверяется отдельно от поведения (иначе тест согласится с любым числом)."""
    assert StateProxy._SYNC_REQUEST_TIMEOUT == 5.0


# ===========================================================================
# 7. Переполнение журнала защиты — цена названа числом
# ===========================================================================


def test_snapshot_is_skipped_entirely_when_the_protection_journal_overflows():
    """Путей в окне больше потолка → снимок НЕ применяется, и это сосчитано.

    Цена названа явно: восстановление откладывается до следующего разрыва.
    Альтернатива (применить снимок наполовину) откатила бы часть путей к
    устаревшим значениям — молча и выборочно.
    """
    stand = _Stand("hz_overflow")
    stand.proxy._RESYNC_DIRTY_MAX = 2  # параметр стенда, не ожидаемое значение
    try:
        _open_window(stand)
        stand.deliver(
            [
                _d("foo.a", 1, revision=6, old=MISSING),
                _d("foo.b", 2, revision=6, old=MISSING),
                _d("foo.c", 3, revision=6, old=MISSING),
            ],
            first_revision=6,
            revision=6,
        )
        assert stand.proxy._resync_dirty_overflow, "потолок журнала не сработал — сценарий не воспроизведён"

        stand.answer_resync({"foo": {"bar": 2, "extra": 42}}, revision=5)
        cache = stand.proxy.cache
        overflow_count = stand.proxy._resync_overflow_count
        completed = stand.proxy._resync_completed_count
    finally:
        stand.close()

    assert overflow_count == 1, f"переполнение не сосчитано: {overflow_count}"
    assert completed == 0, f"ресинк засчитан выполненным, хотя снимок не применялся: {completed}"
    assert "foo.extra" not in cache, (
        f"снимок всё-таки применён при переполненном журнале: foo.extra={cache.get('foo.extra')!r}"
    )
    # Живые значения на месте — именно их и защищали.
    assert cache.get("foo.a") == 1 and cache.get("foo.c") == 3, f"живые дельты потеряны: {cache!r}"


# ===========================================================================
# 8. GuiStateProxy — тот же механизм, свой on_state_changed
# ===========================================================================


def test_gui_proxy_window_protection_works_through_its_own_on_state_changed():
    """У GuiStateProxy СВОЙ on_state_changed — защита окна обязана работать и там.

    Опасность механизма: пометка «путь изменён в окне» стоит в общем
    ``_update_cache``. Если бы её поставили в ``on_state_changed`` базового
    класса, GUI-прокси (единственный подписчик, ради которого всё и делается)
    остался бы без защиты — и снимок откатывал бы ему живые показания.
    """
    stand = _Stand("hz_gui", gui=True)
    try:
        _open_window(stand)
        stand.deliver([_d("foo.bar", 99, revision=6, old=2)], first_revision=6, revision=6)
        stand.answer_resync({"foo": {"bar": 2, "extra": 42}}, revision=5)
        cache = stand.proxy.cache
        delivered = [d.path for d in stand.received]
    finally:
        stand.close()

    assert isinstance(stand.proxy, GuiStateProxy), "стенд собрал не GUI-прокси"
    assert "foo.bar" in delivered, "дельты не доехали до delta_sink — стенд неисправен"
    assert cache.get("foo.extra") == 42, f"снимок не применён вовсе (кэш={cache!r}) — проверка была бы пустой"
    assert cache.get("foo.bar") == 99, (
        f"снимок откатил живое значение в GUI-прокси: foo.bar={cache.get('foo.bar')!r}, ожидалось 99"
    )


# ===========================================================================
# 9. Приёмный такт не блокируется самим ресинком (замер на стенде hazard'ов)
# ===========================================================================


def test_the_receive_tick_that_starts_a_resync_returns_immediately():
    """Такт, запускающий ресинк, стоит не дольше 0.5 с (при внутреннем таймауте 5 с).

    Дубль приёмочного C1 на ЭТОМ стенде — намеренно: остальные тесты файла
    измеряют содержимое кэша и молчаливо предполагают, что такт не блокируется;
    без этой проверки они остались бы зелёными и на блокирующем ресинке, просто
    медленно.
    """
    stand = _Stand("hz_tick")
    try:
        stand.deliver([_d("foo.bar", 1, revision=1, old=MISSING)], first_revision=1, revision=1)
        stand.q_state.put(
            {
                "type": "event",
                "command": "state.changed",
                "sender": "ProcessManager",
                "targets": [stand.name],
                "queue_type": "state",
                "data": {
                    "deltas": [_d("foo.bar", 2, revision=5, old=1).to_dict()],
                    "revision": 5,
                    "first_revision": 5,
                },
            }
        )
        t0 = time.monotonic()
        stand.tick()
        elapsed = time.monotonic() - t0
        started = len(stand.qr.resync_tickets())
    finally:
        stand.close()

    assert started == 1, "ресинк не запускался — замер длительности ничего не доказывает"
    assert elapsed < 0.5, f"приёмный такт с ресинком занял {elapsed:.3f} с — поток снова блокируется"


def test_resync_response_callback_runs_on_the_thread_that_pumps_receive():
    """Снимок применяется ПРИЁМНЫМ потоком — от этого зависит отсутствие локов на кэше.

    Если бы ответ разбирал отдельный поток, кэш StateProxy стал бы разделяемым
    состоянием без синхронизации (дельты пишет приёмный поток, снимок — чужой),
    и «не откатили живое» превратилось бы в гонку.
    """
    stand = _Stand("hz_thread")
    seen_threads: list[str] = []
    original = stand.proxy._on_resync_response

    def _spy(envelope: dict) -> None:
        seen_threads.append(threading.current_thread().name)
        original(envelope)

    stand.proxy._on_resync_response = _spy  # type: ignore[method-assign]
    try:
        _open_window(stand)
        pump_name = "hz-pump"
        answered: dict = {}

        def _pump_once() -> None:
            answered["thread"] = threading.current_thread().name
            stand.tick()

        # Ответ кладём из ТЕКУЩЕГО потока, а разбираем — в отдельном именованном:
        # имя потока в seen_threads должно совпасть с тем, кто крутил receive().
        pending = [t for t in stand.qr.resync_tickets() if t.get("request_id") not in stand.answered]
        cid = pending[-1]["request_id"]
        stand.answered.add(cid)
        stand.q_system.put(
            {
                "type": "response",
                "command": "command.response",
                "request_id": cid,
                "success": True,
                "result": {"status": "ok", "value": {"foo": {"extra": 42}}, "revision": 5},
            }
        )
        t = threading.Thread(target=_pump_once, name=pump_name, daemon=True)
        t.start()
        t.join(timeout=5.0)
        alive = t.is_alive()
    finally:
        stand.close()

    assert not alive, "приёмный поток не завершил такт за 5 с"
    assert seen_threads == ["hz-pump"], (
        f"обработчик снимка исполнен не приёмным потоком, а {seen_threads!r} — кэш стал бы разделяемым без лока"
    )


class TestContractViolationIsNotFailOpen:
    """Нарушение контракта не имеет права стать тихим no-op.

    Политики противоположны и это НЕ вкусовщина: отказ транспорта (таймаут,
    нет маршрута) — штатная жизнь распределённой системы, там fail-open верен.
    Вызов с приёмного потока — ошибка программиста, и её проглатывание
    превращает громкий отказ роутера в пустой снимок, с которым вызывающий
    поедет дальше. Инъекция INJ-9 при починке 2026-08-23 показала это
    буквально: откат ухода resync с приёмного потока ПРИ живой проверке
    контракта дал не простой на 5 с, а МОЛЧА отключённый resync.

    Логом такое не закрывается, и это измерено: за 22-минутный прогон стенда
    StateProxy обязан был написать ~260 предупреждений о таймаутах, а в 60
    файлах логов нет ни одного упоминания 'StateProxy' (WARNING других
    источников при этом есть в 17 файлах).
    """

    @staticmethod
    def _proxy_with_router(router):
        from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

        return StateProxy("camera_0", router=router, server_target="ProcessManager")

    def test_reentrant_error_propagates_instead_of_returning_none(self):
        """Исключение контракта проходит наружу, а не превращается в None."""
        from multiprocess_framework.modules.router_module.core.router_manager import (
            RouterReentrantRequestError,
        )

        class _ReentrantRouter:
            def request(self, msg, timeout=None):
                raise RouterReentrantRequestError("INJECT: вызов с приёмного потока")

            def register_message_handler(self, *a, **k):
                return True

        proxy = self._proxy_with_router(_ReentrantRouter())

        with pytest.raises(RouterReentrantRequestError):
            proxy._send_sync({"command": "state.get_subtree", "data": {}})

    def test_transport_failure_still_fails_open_with_none(self):
        """Пара-контроль: отказ ТРАНСПОРТА по-прежнему fail-open.

        Без него предыдущий тест доказывал бы лишь «перестали ловить всё
        подряд», а не «отличаем ошибку программиста от отказа транспорта».
        """

        class _BrokenTransportRouter:
            def request(self, msg, timeout=None):
                raise ConnectionError("INJECT: транспорт лёг")

            def register_message_handler(self, *a, **k):
                return True

        proxy = self._proxy_with_router(_BrokenTransportRouter())

        assert proxy._send_sync({"command": "state.get_subtree", "data": {}}) is None
