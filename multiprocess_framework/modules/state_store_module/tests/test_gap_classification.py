"""test_gap_classification.py — слепые acceptance-тесты R3c: классификация разрывов revision.

Независимый tester, стадия 1 (ДО реализации; на базе ожидаются красные).

ЧТО МЕНЯЕТСЯ. ``StateProxy`` на разрыве revision (``first_revision > _last_revision + 1``)
запускает ресинк и пишет WARNING «разрыв revision». Узкая подписка при чужих записях
видит такие «разрывы» ~4/с без потери данных — это шум. Нужно: строка обнаружения
уходит в DEBUG; считаются разрывы и исходы ресинка; WARNING остаётся только для
реально разошедшегося кэша и троттлится. Протокол и поведение кэша/ресинка НЕ меняются.

ТАБЛИЦА (из требований):
  * ресинк ушёл, ответ ok, снимок применён, изменённых путей 0     -> gap_clean_count
  * то же, изменённых >= 1                                         -> gap_diverged_count
  * status != ok / таймаут / отправка не удалась / request_async
    бросил / overflow (снимок не применён) / value не dict /
    shutdown в полёте                                              -> gap_unclassified_count
  * ресинк не стартовал (нет роутера / пустые patterns)            -> только gap_detected_count
  * разрыв во время идущего ресинка (совмещение): detected +1 за
    КАЖДЫЙ разрыв, классифицируется ОДИН раз исходом ДОГОНЯЮЩЕГО
    ресинка (разрыв-инициатор — исходом первого ответа)
  * прямой ``proxy._resync(patterns)`` не от разрыва               -> счётчики +0

«Снимок изменил кэш» = путь ДОБАВЛЕН, УДАЛЁН (стёрт как устаревший) или значение
ОТЛИЧАЕТСЯ — по путям, которые снимку вправе писать (пути, защищённые окном ресинка,
не считаются); NaN равен NaN; контейнер с NaN внутри — «отличается».

СТЕНДЫ. F (fallback) — ``MockRouter`` без ``request_async`` (ресинк синхронный).
A (async) — ``_Stand`` с настоящим ``RouterManager`` (ресинк через ``request_async``).
Тест ``test_1…``/``test_2…`` и др. «F и A» параметризованы ``rig``-фикстурой.

ЛОГГЕР/СТАТИСТИКА. ``_make_mock_logger`` из ``test_state_proxy`` выбрасывает DEBUG, а
отложенное сообщение (``lambda:``) надо разворачивать — поэтому здесь свой двойник
``_Cap``, подключаемый через ``proxy.register_manager("logger", cap)``.

Литералы ожидаемых значений вписаны руками, из кода под тестом не выводятся.
Ожидаемые красные на базе: поведенческие (лог до счётчика) в №1/№2/№10, остальные —
``AttributeError`` на ``gap_*_count``.
"""

from __future__ import annotations

import re
import time
from collections import Counter

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

from ._deterministic_delivery import apply_deterministic_delivery
from .test_resync_offthread_hazards import _d, _open_window, _Stand
from .test_state_proxy import MockRouter
from .test_watch_from_revision import _RelayRouter

_PAT = "foo.**"
_COUNTERS = ("detected", "clean", "diverged", "unclassified")


# ===========================================================================
# Двойники логгера и статистики
# ===========================================================================


class _Cap:
    """Логгер-двойник: пишет (УРОВЕНЬ, текст), разворачивая отложенные ``lambda:``.

    Поддержка отложенного сообщения обязательна: после R3c строка обнаружения
    передаётся в ``_log_debug(lambda: ...)``, и двойник, который не зовёт
    ``callable``, записал бы репр лямбды.
    """

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def _put(self, level: str, message: object, **_kw: object) -> None:
        text = message() if callable(message) else message
        self.lines.append((level, str(text)))

    def debug(self, message: object, **kw: object) -> None:
        self._put("DEBUG", message, **kw)

    def info(self, message: object, **kw: object) -> None:
        self._put("INFO", message, **kw)

    def warning(self, message: object, **kw: object) -> None:
        self._put("WARNING", message, **kw)

    def error(self, message: object, **kw: object) -> None:
        self._put("ERROR", message, **kw)

    def critical(self, message: object, **kw: object) -> None:
        self._put("CRITICAL", message, **kw)

    def at(self, level: str) -> list[str]:
        return [text for lvl, text in self.lines if lvl == level]

    def gap_warnings(self) -> list[str]:
        """WARNING со словом «разрыв» — «семья» строк про разрыв revision."""
        return [t for t in self.at("WARNING") if "разрыв" in t]

    def gap_debugs(self) -> list[str]:
        return [t for t in self.at("DEBUG") if "разрыв" in t]


class _Stats:
    """Приёмник метрик: имя каждого ``record_metric`` в порядке прихода."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def record_metric(self, name: str, value: object = 1, tags: object = None) -> None:
        self.calls.append((name, value))

    def __getattr__(self, name: str):  # record_timing и пр. — не предмет теста
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: None

    def gap_names(self) -> Counter:
        return Counter(n for n, _v in self.calls if n.startswith("state_proxy.gap_"))


def _counts(proxy: StateProxy) -> dict[str, int]:
    return {
        "detected": proxy.gap_detected_count,
        "clean": proxy.gap_clean_count,
        "diverged": proxy.gap_diverged_count,
        "unclassified": proxy.gap_unclassified_count,
    }


def _num_in(text: str, n: int) -> bool:
    """Число ``n`` встречается в тексте отдельным токеном (не частью другого числа)."""
    return re.search(rf"(?<!\d){n}(?!\d)", text) is not None


# ===========================================================================
# Низкоуровневые помощники стендов
# ===========================================================================


def _answer_raw(stand: _Stand, result: dict) -> str:
    """Ответить на ПОСЛЕДНИЙ неотвеченный запрос снимка произвольным ``result``.

    Копия логики ``_Stand.answer_resync`` с одним отличием: ``result`` задаёт тест
    (``status != ok``, ``value`` не dict и т.п.), а не фиксированный ``ok``.
    """
    pending = [t for t in stand.qr.resync_tickets() if t.get("request_id") not in stand.answered]
    assert pending, "нет неотвеченного запроса снимка — сценарий не воспроизведён"
    cid = pending[-1]["request_id"]
    stand.answered.add(cid)
    stand.q_system.put(
        {
            "type": "response",
            "command": "command.response",
            "request_id": cid,
            "success": True,
            "result": result,
        }
    )
    stand.tick()
    return cid


def _ok(snapshot: dict, revision: object) -> dict:
    return {"status": "ok", "value": snapshot, "revision": revision}


def _f_msg(deltas: list, first: int, last: int) -> dict:
    return {
        "command": "state.changed",
        "data": {"deltas": [d.to_dict() for d in deltas], "revision": last, "first_revision": first},
    }


def _f_requests(router: MockRouter) -> list[dict]:
    return [m for m in router.sent if m.get("command") == "state.get_subtree"]


class _Rig:
    """Единый интерфейс над стендами F и A для тестов «F и A».

    ``feed`` — доставить пакет (базу или разрыв); ``gap`` — доставить пакет-разрыв
    и довести ресинк до исхода (F: ответ задаётся ДО пакета, ресинк синхронный;
    A: ответ кладётся в системный канал ПОСЛЕ пакета, исход — на следующем такте).
    """

    _seq = 0

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.log = _Cap()
        self.stats = _Stats()
        self.rev = 0
        _Rig._seq += 1
        if kind == "F":
            self.router = MockRouter()
            self.proxy = StateProxy("cam", router=self.router)
            self.proxy.subscribe(_PAT, lambda _d_: None, exclude_self=False)
            self.stand = None
        else:
            self.stand = _Stand(f"gc_rig_{_Rig._seq}")
            self.proxy = self.stand.proxy
        # Логгер/статистика — ПОСЛЕ подписки: её собственные строки не наши.
        self.proxy.register_manager("logger", self.log)
        self.proxy.register_manager("stats", self.stats)

    def close(self) -> None:
        if self.stand is not None:
            self.stand.close()

    def request_count(self) -> int:
        if self.kind == "F":
            return len(_f_requests(self.router))
        return len(self.stand.qr.resync_tickets())

    def feed(self, items: dict[str, object], gap: int = 0) -> int:
        """Доставить ОДИН пакет с дельтами ``items`` (путь -> значение).

        ``gap`` — сколько revision пропущено перед пакетом (0 — непрерывно).
        Возвращает revision пакета.
        """
        new = self.rev + 1 + gap
        deltas = [_d(p, v, revision=new, old=MISSING) for p, v in items.items()]
        if self.kind == "F":
            self.proxy.on_state_changed(_f_msg(deltas, first=new, last=new))
        else:
            self.stand.deliver(deltas, first_revision=new, revision=new)
        self.rev = new
        return new

    def gap(
        self,
        items: dict[str, object],
        *,
        snapshot: dict | None = None,
        result: dict | None = None,
        shift: int = 3,
    ) -> None:
        """Пакет-разрыв + исход ресинка.

        ``snapshot`` — ответ ``ok`` с этим снимком (revision = revision пакета);
        ``result`` — произвольный ответ обработчика (перекрывает ``snapshot``);
        оба None — ответа нет (F: ``send`` вернул None; A: таймаут стенда).
        """
        expected_rev = self.rev + 1 + shift
        if snapshot is not None and result is None:
            result = _ok(snapshot, expected_rev)
        if self.kind == "F":
            self.router.set_sync_response("state.get_subtree", result)
            self.feed(items, gap=shift)
            return
        if result is None:
            self.proxy._SYNC_REQUEST_TIMEOUT = 0.25  # параметр стенда
        self.feed(items, gap=shift)
        assert self.proxy._resync_inflight_id is not None, "разрыв не открыл ресинк — сценарий не воспроизведён"
        if result is None:
            done = self.stand.spin(lambda: self.proxy._resync_inflight_id is None, deadline_sec=5.0)
            assert done, "таймаут ресинка не наступил за 5 с — стенд неисправен"
        else:
            _answer_raw(self.stand, result)

    def direct_resync(self, result: dict) -> None:
        """Прямой ``proxy._resync`` НЕ от разрыва, с ответом (читать счётчики — только после ответа)."""
        if self.kind == "F":
            self.router.set_sync_response("state.get_subtree", result)
            self.proxy._resync([_PAT])
            return
        self.proxy._resync([_PAT])
        assert self.proxy._resync_inflight_id is not None, "прямой _resync не ушёл — стенд неисправен"
        _answer_raw(self.stand, result)

    def counts(self) -> dict[str, int]:
        return _counts(self.proxy)


@pytest.fixture(params=["F", "A"])
def rig(request):
    r = _Rig(request.param)
    try:
        yield r
    finally:
        r.close()


@pytest.fixture
def rig_f():
    r = _Rig("F")
    try:
        yield r
    finally:
        r.close()


@pytest.fixture
def rig_a():
    r = _Rig("A")
    try:
        yield r
    finally:
        r.close()


def _expect(**kw: int) -> dict[str, int]:
    out = dict.fromkeys(_COUNTERS, 0)
    out.update(kw)
    return out


# ===========================================================================
# 1 (F и A). Дыра по ревизии, снимок равен кэшу -> clean; шума в WARNING нет
# ===========================================================================


def test_1_revision_hole_with_snapshot_equal_to_cache_is_clean_and_not_a_warning(rig):
    """Снимок == кэшу: WARNING про «разрыв» нет, обнаружение — DEBUG, clean == 1.

    Ассерт на лог стоит ДО чтения счётчиков: на базе красный по поведению
    (там обнаружение — WARNING «разрыв revision (ожидалось …)»).
    """
    rig.feed({"foo.bar": 1, "foo.same": 0})
    rig.gap({"foo.bar": 2}, snapshot={"foo": {"bar": 2, "same": 0}})

    assert rig.log.gap_warnings() == [], f"clean-разрыв шумит в WARNING: {rig.log.gap_warnings()!r}"
    assert rig.log.gap_debugs(), "строка обнаружения разрыва должна быть (в DEBUG); DEBUG-строк с «разрыв» нет"
    assert rig.counts() == _expect(detected=1, clean=1)


# ===========================================================================
# 2 (F и A). Снимок изменил кэш -> diverged; ровно один WARNING с числом путей
# ===========================================================================

_CHANGED_PATHS = ("foo.alpha", "foo.beta", "foo.gamma")

# (id, кэш до разрыва, снимок, кэш после ресинка по изменяемым путям)
_DIVERGE_CASES = {
    "value_differs": (
        {"foo.alpha": 1, "foo.beta": 1, "foo.gamma": 1, "foo.same": 0},
        {"foo": {"alpha": 11, "beta": 12, "gamma": 13, "same": 0}},
        {"foo.alpha": 11, "foo.beta": 12, "foo.gamma": 13},
    ),
    "path_added_lost_create": (
        {"foo.same": 0},
        {"foo": {"alpha": 1, "beta": 2, "gamma": 3, "same": 0}},
        {"foo.alpha": 1, "foo.beta": 2, "foo.gamma": 3},
    ),
    "path_removed_on_server": (
        {"foo.alpha": 1, "foo.beta": 1, "foo.gamma": 1, "foo.same": 0},
        {"foo": {"same": 0}},
        {},
    ),
}


@pytest.mark.parametrize("case", list(_DIVERGE_CASES))
def test_2_snapshot_that_changed_the_cache_is_diverged_with_one_informative_warning(rig, case):
    """(а) значение отличается, (б) путь добавлен, (в) путь удалён на сервере -> diverged == 1.

    Три изменённых пути в каждом случае: число 3 отличается от revision/ожиданий,
    поэтому «называет число путей» не выполнится случайно. WARNING ровно один и
    называет ВСЕ три пути (<= 5). Лог — до счётчиков (на базе красный по поведению:
    там WARNING — обнаружение, без имён путей).
    """
    before, snapshot, expected_cache = _DIVERGE_CASES[case]
    rig.feed(before)
    rig.gap({"foo.same": 0}, snapshot=snapshot)

    warns = rig.log.gap_warnings()
    assert len(warns) == 1, f"ожидался ровно один WARNING про разрыв, получено {len(warns)}: {warns!r}"
    assert _num_in(warns[0], 3), f"WARNING не называет число изменённых путей (3): {warns[0]!r}"
    for path in _CHANGED_PATHS:
        assert path in warns[0], f"WARNING не называет путь {path!r}: {warns[0]!r}"

    cache = rig.proxy.cache
    for path, value in expected_cache.items():
        assert cache.get(path) == value, f"кэш не исправлен: {path}={cache.get(path)!r}, ожидалось {value!r}"
    if case == "path_removed_on_server":
        for path in _CHANGED_PATHS:
            assert path not in cache, f"устаревший путь {path} остался в кэше"

    assert rig.counts() == _expect(detected=1, diverged=1)


def test_2d_warning_names_at_most_five_paths_and_never_prints_values(rig_f):
    """Изменено 7 путей: в строке число 7, имён <= 5; значения (старые и новые) не печатаются."""
    names = ["p_aa", "p_bb", "p_cc", "p_dd", "p_ee", "p_ff", "p_gg"]
    rig_f.feed({**{f"foo.{n}": "OLD_VALUE_XYZ" for n in names}, "foo.same": 0})
    rig_f.gap({"foo.same": 0}, snapshot={"foo": {**{n: "NEW_VALUE_XYZ" for n in names}, "same": 0}})

    warns = rig_f.log.gap_warnings()
    assert len(warns) == 1, f"ожидался один WARNING про разрыв: {warns!r}"
    text = warns[0]
    assert _num_in(text, 7), f"WARNING не называет число изменённых путей (7): {text!r}"
    named = [n for n in names if n in text]
    assert 1 <= len(named) <= 5, f"имён путей в строке {len(named)} (ожидалось от 1 до 5): {text!r}"
    for secret in ("OLD_VALUE_XYZ", "NEW_VALUE_XYZ"):
        assert secret not in text, f"значение напечатано в WARNING: {text!r}"
    assert rig_f.counts() == _expect(detected=1, diverged=1)


# ===========================================================================
# 3. Ресинк без применимого снимка -> unclassified
# ===========================================================================


def test_3a_status_not_ok_is_unclassified(rig):
    """Ответ ``status != ok`` -> unclassified == 1, остальные классификации 0 (F и A)."""
    rig.feed({"foo.bar": 1})
    rig.gap({"foo.bar": 2}, result={"status": "error", "error": "boom"})

    assert rig.counts() == _expect(detected=1, unclassified=1)


def test_3a2_no_answer_at_all_is_unclassified_f(rig_f):
    """F: ``router.send`` вернул None («ответа нет») -> unclassified == 1."""
    rig_f.feed({"foo.bar": 1})
    rig_f.gap({"foo.bar": 2})  # snapshot/result не заданы -> None

    assert rig_f.counts() == _expect(detected=1, unclassified=1)


def test_3b_timeout_is_unclassified_a(rig_a):
    """A: ответ не пришёл, ресинк закрыт по таймауту -> unclassified == 1."""
    rig_a.feed({"foo.bar": 1})
    rig_a.gap({"foo.bar": 2})  # result None -> таймаут 0.25 с стенда

    assert rig_a.proxy._resync_failed_count == 1, "якорь: таймаут не засчитан как неудача ресинка"
    assert rig_a.counts() == _expect(detected=1, unclassified=1)


def test_3c_overflow_snapshot_not_applied_is_unclassified_a():
    """A: журнал защиты переполнен -> снимок не применён -> unclassified == 1."""
    stand = _Stand("gc_overflow")
    stand.proxy._RESYNC_DIRTY_MAX = 2  # параметр стенда
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
        overflow = stand.proxy._resync_overflow_count
        completed = stand.proxy._resync_completed_count
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert overflow == 1 and completed == 0, f"якорь: снимок не пропущен (overflow={overflow}, completed={completed})"
    assert counts == _expect(detected=1, unclassified=1)


def test_3d_value_not_a_dict_is_unclassified_a(rig_a):
    """A: ``value`` не dict -> unclassified == 1 (не clean и не diverged)."""
    rig_a.feed({"foo.bar": 1})
    rig_a.gap({"foo.bar": 2}, result={"status": "ok", "value": "junk", "revision": 5})

    assert rig_a.counts() == _expect(detected=1, unclassified=1)


def test_3e_request_async_raises_is_unclassified_a():
    """A: ``request_async`` бросает исключение (колбэка не будет) -> unclassified == 1."""
    stand = _Stand("gc_raises")

    def _boom(*_a, **_k):
        raise RuntimeError("request_async сломан")

    stand.router.request_async = _boom  # type: ignore[method-assign]
    try:
        stand.deliver([_d("foo.bar", 1, revision=1, old=MISSING)], first_revision=1, revision=1)
        stand.deliver([_d("foo.bar", 2, revision=5, old=1)], first_revision=5, revision=5)
        inflight = stand.proxy._resync_inflight_id
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert inflight is None, "якорь: окно ресинка осталось открытым после исключения"
    assert counts == _expect(detected=1, unclassified=1)


def test_3f_send_failure_with_synchronous_callback_is_unclassified_a():
    """A: отправка не удалась, роутер зовёт колбэк синхронно, ещё изнутри ``request_async``."""
    stand = _Stand("gc_sendfail")
    try:
        stand.deliver([_d("foo.bar", 1, revision=1, old=MISSING)], first_revision=1, revision=1)
        stand.qr.send_to_queue = lambda *a, **k: False  # type: ignore[method-assign]
        stand.deliver([_d("foo.bar", 2, revision=5, old=1)], first_revision=5, revision=5)
        failed = stand.proxy._resync_failed_count
        inflight = stand.proxy._resync_inflight_id
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert failed == 1 and inflight is None, (
        f"якорь: провал отправки не дошёл до колбэка синхронно (failed={failed}, inflight={inflight!r})"
    )
    assert counts == _expect(detected=1, unclassified=1)


# ===========================================================================
# 4. Совмещение: классифицируется ОДИН раз исходом догоняющего ресинка (A)
# ===========================================================================


def _second_gap_in_window(stand: _Stand) -> None:
    """Второй разрыв ПОКА первый ресинк в полёте: пакет rev 9 (ожидалось 6), путь ``foo.bar``."""
    stand.deliver([_d("foo.bar", 3, revision=9, old=2)], first_revision=9, revision=9)
    assert stand.proxy._resync_coalesced_count == 1, "второй разрыв не совместился — сценарий не воспроизведён"


@pytest.mark.parametrize("catchup", ["status_error", "timeout"])
def test_4_coalesced_gaps_with_different_outcomes_diverged_then_unclassified(catchup):
    """Первый ответ меняет кэш (diverged), догоняющий — провал (unclassified).

    detected == 2 (по разрыву), diverged == 1 (инициатор), unclassified == 1
    (совмещённый, исход догоняющего), clean == 0; параллельного запроса нет.
    """
    stand = _Stand(f"gc_coal_{catchup}")
    try:
        _open_window(stand)
        _second_gap_in_window(stand)
        assert len(stand.qr.resync_tickets()) == 1, "второй разрыв отправил параллельный запрос"
        if catchup == "timeout":
            # Первый запрос уже ушёл с дедлайном 5 с; догоняющий возьмёт этот таймаут.
            stand.proxy._SYNC_REQUEST_TIMEOUT = 0.25
        # Первый ответ: foo.bar защищён (дельта окна rev 9 >= 5), foo.extra ДОБАВЛЕН -> diverged.
        stand.answer_resync({"foo": {"bar": 2, "extra": 42}}, revision=5)
        assert len(stand.qr.resync_tickets()) == 2, "догоняющий запрос не ушёл — сценарий не воспроизведён"
        if catchup == "status_error":
            _answer_raw(stand, {"status": "error", "error": "boom"})
        else:
            done = stand.spin(lambda: stand.proxy._resync_inflight_id is None, deadline_sec=5.0)
            assert done, "таймаут догоняющего ресинка не наступил за 5 с"
        tickets = len(stand.qr.resync_tickets())
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert tickets == 2, f"параллельный/лишний запрос снимка: {tickets}"
    assert counts == _expect(detected=2, diverged=1, unclassified=1)


def test_4_control_coalesced_gaps_both_clean():
    """Контроль формы ``test_second_gap_during_the_window_does_not_start_a_parallel_resync``.

    Первый ответ ``{"foo":{"bar":2}}`` rev 5 (foo.bar защищён дельтой окна) -> clean;
    ответ догоняющего ``{"foo":{"bar":3}}`` rev 9 -> clean; clean == 2, detected == 2.
    """
    stand = _Stand("gc_coal_clean")
    try:
        _open_window(stand)
        _second_gap_in_window(stand)
        stand.answer_resync({"foo": {"bar": 2}}, revision=5)
        stand.answer_resync({"foo": {"bar": 3}}, revision=9)
        counts = _counts(stand.proxy)
        tickets = len(stand.qr.resync_tickets())
    finally:
        stand.close()

    assert tickets == 2, f"лишний запрос снимка: {tickets}"
    assert counts == _expect(detected=2, clean=2)


def test_4b_two_coalesced_gaps_are_classified_by_the_catch_up_outcome_twice():
    """Два совмещённых разрыва за окно: догоняющий классифицирует ОБА (всего 3 = первый + 2).

    Исход догоняющего — diverged (добавлен ``foo.extra``) -> diverged == 2, clean == 1
    (инициатор, исход первого ответа). detected == 3. Одним запросом больше не станет.
    """
    stand = _Stand("gc_coal_two")
    try:
        _open_window(stand)
        stand.deliver([_d("foo.bar", 3, revision=9, old=2)], first_revision=9, revision=9)
        stand.deliver([_d("foo.bar", 4, revision=13, old=3)], first_revision=13, revision=13)
        assert stand.proxy._resync_coalesced_count == 2, "два совмещённых разрыва не воспроизведены"
        assert len(stand.qr.resync_tickets()) == 1
        stand.answer_resync({"foo": {"bar": 2}}, revision=5)  # bar защищён -> clean (инициатор)
        assert len(stand.qr.resync_tickets()) == 2, "догоняющий запрос не ушёл"
        stand.answer_resync({"foo": {"bar": 4, "extra": 42}}, revision=13)  # extra добавлен -> diverged
        counts = _counts(stand.proxy)
        tickets = len(stand.qr.resync_tickets())
    finally:
        stand.close()

    assert tickets == 2, f"лишний запрос снимка: {tickets}"
    assert counts == _expect(detected=3, clean=1, diverged=2)


# ===========================================================================
# 5 (A). Путь, изменённый ДЕЛЬТОЙ в окне, защищён и не считается
# ===========================================================================


def test_5_path_changed_by_a_window_delta_is_protected_and_does_not_count_as_divergence():
    """Окно: дельта foo.bar=99 (rev 6 >= 5) защищена; остальное снимка совпадает -> clean == 1.

    Якорь ``_resync_completed_count == 1``: снимок РЕАЛЬНО применён (а не отброшен),
    иначе «не diverged» ничего бы не значило. Добавленный путь здесь нельзя —
    он считался бы изменением.
    """
    stand = _Stand("gc_protected")
    try:
        stand.deliver(
            [_d("foo.bar", 1, revision=1, old=MISSING), _d("foo.keep", 5, revision=1, old=MISSING)],
            first_revision=1,
            revision=1,
        )
        stand.deliver([_d("foo.bar", 2, revision=5, old=1)], first_revision=5, revision=5)
        assert stand.proxy._resync_inflight_id is not None, "окно не открылось — сценарий не воспроизведён"
        stand.deliver([_d("foo.bar", 99, revision=6, old=2)], first_revision=6, revision=6)
        stand.answer_resync({"foo": {"bar": 2, "keep": 5}}, revision=5)
        completed = stand.proxy._resync_completed_count
        cache = stand.proxy.cache
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert completed == 1, f"якорь: снимок не применён (completed={completed})"
    assert cache.get("foo.bar") == 99, f"якорь: защита окна не сработала: foo.bar={cache.get('foo.bar')!r}"
    assert counts == _expect(detected=1, clean=1)


def test_5b_subtree_deleted_by_a_window_delta_is_protected_and_does_not_count_as_divergence():
    """Окно: дельта-удаление корня foo.bar защищает поддерево; снимок «воскресил» бы лист — не считается."""
    stand = _Stand("gc_protected_del")
    try:
        stand.deliver([_d("foo.bar.deep", 7, revision=1, old=MISSING)], first_revision=1, revision=1)
        stand.deliver([_d("foo.other", 3, revision=5, old=MISSING)], first_revision=5, revision=5)
        assert stand.proxy._resync_inflight_id is not None, "окно не открылось — сценарий не воспроизведён"
        stand.deliver([_d("foo.bar", MISSING, revision=6, old=None)], first_revision=6, revision=6)
        assert "foo.bar.deep" not in stand.proxy.cache, "удаление в окне не применилось — сценарий не воспроизведён"
        stand.answer_resync({"foo": {"bar": {"deep": 7}, "other": 3}}, revision=5)
        completed = stand.proxy._resync_completed_count
        cache = stand.proxy.cache
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert completed == 1, f"якорь: снимок не применён (completed={completed})"
    assert "foo.bar.deep" not in cache, "якорь: снимок воскресил защищённое поддерево"
    assert counts == _expect(detected=1, clean=1)


# ===========================================================================
# 6 (F и A). Не от разрыва / разрыв без старта ресинка -> классификации +0
# ===========================================================================


def test_6_direct_resync_not_from_a_gap_does_not_touch_any_gap_counter(rig):
    """Прямой ``proxy._resync(patterns)`` с ОТВЕТОМ (снимок отличается от кэша): все четыре счётчика +0.

    Тест отвечает на запрос и только потом читает счётчики; якорь —
    ``_resync_completed_count == 1`` (снимок применён, различие реально было).
    """
    rig.feed({"foo.bar": 1})
    rig.direct_resync(_ok({"foo": {"bar": 999}}, revision=1))

    assert rig.proxy._resync_completed_count == 1, "якорь: прямой ресинк не применил снимок"
    assert rig.proxy.cache.get("foo.bar") == 999, "якорь: снимок не изменил кэш — различие не воспроизведено"
    assert rig.counts() == _expect()


def test_6b_gap_without_router_counts_detection_only_and_does_not_raise():
    """Нет роутера: ресинк не стартует -> только detected == 1 (образец ``..._no_router_is_safe``)."""
    proxy = StateProxy("cam", router=None)
    proxy.subscribe(_PAT, lambda _d_: None)
    log = _Cap()
    proxy.register_manager("logger", log)
    proxy.on_state_changed(_f_msg([_d("foo.bar", 10, 1)], first=1, last=1))
    proxy.on_state_changed(_f_msg([_d("foo.bar", 50, 5)], first=5, last=5))

    assert proxy.cache.get("foo.bar") == 50, "якорь: пакет разрыва не применён"
    assert log.gap_warnings() == [], f"разрыв без ресинка шумит в WARNING: {log.gap_warnings()!r}"
    assert _counts(proxy) == _expect(detected=1)


def test_6c_gap_with_empty_patterns_counts_detection_only_f():
    """F: подписок нет (patterns пуст), роутер есть -> ресинк не стартует, только detected == 1."""
    router = MockRouter()
    proxy = StateProxy("cam", router=router)
    proxy.on_state_changed(_f_msg([_d("foo.bar", 10, 1)], first=1, last=1))
    proxy.on_state_changed(_f_msg([_d("foo.bar", 50, 5)], first=5, last=5))

    assert _f_requests(router) == [], "якорь: при пустых patterns ушёл запрос снимка"
    assert _counts(proxy) == _expect(detected=1)


def test_6c_gap_with_empty_patterns_counts_detection_only_a():
    """A: настоящий роутер, подписок нет -> запрос снимка не уходит, только detected == 1."""
    stand = _Stand("gc_empty_patterns")
    try:
        bare = StateProxy("gc_bare", router=stand.router, server_target="ProcessManager")
        bare.on_state_changed(_f_msg([_d("foo.bar", 10, 1)], first=1, last=1))
        bare.on_state_changed(_f_msg([_d("foo.bar", 50, 5)], first=5, last=5))
        tickets = len(stand.qr.resync_tickets())
        counts = _counts(bare)
    finally:
        stand.close()

    assert tickets == 0, "якорь: при пустых patterns ушёл запрос снимка"
    assert counts == _expect(detected=1)


# ===========================================================================
# 7 (F и A). Контроли поведения: ЗЕЛЁНЫЕ и на базе
# ===========================================================================


def test_7_every_gap_starts_a_resync_and_revision_advances_as_before(rig):
    """Контроль: ресинк на каждом разрыве, ``_last_revision`` продвигается, число запросов то же."""
    rig.feed({"foo.bar": 1})
    rig.gap({"foo.bar": 2}, snapshot={"foo": {"bar": 2}})  # разрыв 1 (rev 5)
    assert rig.proxy._last_revision == 5, f"_last_revision после первого разрыва: {rig.proxy._last_revision!r}"
    rig.gap({"foo.bar": 3}, snapshot={"foo": {"bar": 3}})  # разрыв 2 (rev 9)
    assert rig.proxy._last_revision == 9, f"_last_revision после второго разрыва: {rig.proxy._last_revision!r}"
    rig.feed({"foo.bar": 4})  # непрерывно (rev 10) — не разрыв
    assert rig.proxy._last_revision == 10

    assert rig.request_count() == 2, f"запросов state.get_subtree {rig.request_count()}, ожидалось 2 (по разрыву)"
    assert rig.proxy.cache.get("foo.bar") == 4


def test_7a_coalesced_gap_sends_no_parallel_request_and_one_catch_up():
    """Контроль (A): второй разрыв в окне — запросов 1; после ответа — догоняющий (2); после его ответа — 2."""
    stand = _Stand("gc_ctl_coalesce")
    try:
        _open_window(stand)
        after_first = len(stand.qr.resync_tickets())
        stand.deliver([_d("foo.bar", 3, revision=9, old=2)], first_revision=9, revision=9)
        after_second_gap = len(stand.qr.resync_tickets())
        stand.answer_resync({"foo": {"bar": 2}}, revision=5)
        after_first_answer = len(stand.qr.resync_tickets())
        stand.answer_resync({"foo": {"bar": 3}}, revision=9)
        final = len(stand.qr.resync_tickets())
        last_revision = stand.proxy._last_revision
        started = stand.proxy._resync_started_count
    finally:
        stand.close()

    assert (after_first, after_second_gap, after_first_answer, final) == (1, 1, 2, 2)
    assert started == 2
    assert last_revision == 9


def test_7b_existing_resync_failed_warning_remains(rig):
    """Контроль: WARNING «resync не удался» (status != ok) остаётся — это настоящий отказ."""
    rig.feed({"foo.bar": 1})
    rig.gap({"foo.bar": 2}, result={"status": "error", "error": "boom"})

    assert any("resync не удался" in w for w in rig.log.at("WARNING")), (
        f"WARNING «resync не удался» пропал: {rig.log.at('WARNING')!r}"
    )


def test_7c_existing_overflow_warning_remains():
    """Контроль (A): WARNING про переполнение журнала защиты остаётся."""
    stand = _Stand("gc_ctl_overflow")
    log = _Cap()
    stand.proxy.register_manager("logger", log)
    stand.proxy._RESYNC_DIRTY_MAX = 2
    try:
        _open_window(stand)
        stand.deliver(
            [_d(f"foo.{n}", 1, revision=6, old=MISSING) for n in ("a", "b", "c")],
            first_revision=6,
            revision=6,
        )
        stand.answer_resync({"foo": {"bar": 2}}, revision=5)
    finally:
        stand.close()

    assert any("снимок НЕ применён" in w for w in log.at("WARNING")), (
        f"WARNING про переполнение пропал: {log.at('WARNING')!r}"
    )


# ===========================================================================
# 8. Характеризации: известное ограничение клиента
# ===========================================================================


class _ServerRouter:
    """Роутер ``StateStoreManager`` на стенде A: ``state.changed`` кладёт в state-канал стенда."""

    def __init__(self, stand: _Stand) -> None:
        self._stand = stand

    def send_async(self, message: dict, priority: str = "normal") -> None:
        self._stand.q_state.put(message)


def test_8b_write_between_flush_and_snapshot_is_diverged_known_limitation():
    """(B) Запись в подписанный путь МЕЖДУ flush и снимком: клиент не отличает её от потери -> diverged.

    Настоящий ``StateStoreManager`` (flusher не запущен — flush вручную), настоящий
    ``RouterManager`` клиента. Ход: rev 1 доставлен; rev 2 вне подписки (клиент его
    не видит — штатная «дыра»); rev 3 доставлен и открывает окно; запись rev 4 в
    ПОДПИСАННЫЙ путь лежит в буфере диспетчера (клиенту не доехала), снимок берётся
    после неё. Данные не потеряны (дельта приедет), но клиент считает расхождение.
    """
    stand = _Stand("gc_charB")
    log = _Cap()
    stand.proxy.register_manager("logger", log)
    mgr = StateStoreManager(router=_ServerRouter(stand), initial_state={})
    try:
        mgr.handle_state_subscribe({"data": {"pattern": _PAT, "subscriber": stand.name}})

        def _set(path: str, value: object) -> None:
            mgr.handle_state_set({"data": {"path": path, "value": value, "source": "other"}})

        def _flush() -> None:
            mgr.dispatcher._flush_once()
            stand.tick()

        _set("foo.bar", 1)
        _flush()
        _set("other.x", 0)  # rev 2, вне подписки
        _set("foo.bar", 2)  # rev 3
        _flush()
        assert stand.proxy._resync_inflight_id is not None, "разрыв не открыл ресинк — сценарий не воспроизведён"
        assert stand.proxy.cache.get("foo.bar") == 2

        _set("foo.bar", 3)  # (B): после flush, до снимка; в буфере диспетчера
        ticket = stand.qr.resync_tickets()[-1]
        reply = mgr.handle_state_get_subtree(
            {"data": {"paths": ticket["data"]["paths"], "request_id": ticket["request_id"]}}
        )
        _answer_raw(stand, reply)
        completed = stand.proxy._resync_completed_count
        cache = stand.proxy.cache
        counts = _counts(stand.proxy)
    finally:
        mgr.shutdown()
        stand.close()

    assert completed == 1 and cache.get("foo.bar") == 3, (
        f"якорь: снимок не применён или не содержит записи (completed={completed}, bar={cache.get('foo.bar')!r})"
    )
    assert counts == _expect(detected=1, diverged=1)


@pytest.fixture
def _deterministic_delivery(monkeypatch):
    apply_deterministic_delivery(monkeypatch)


def test_8e_own_write_with_exclude_self_is_diverged_known_limitation(_deterministic_delivery):
    """(E) Собственная ``proxy.set`` под своим паттерном при ``exclude_self=True`` -> diverged.

    Сервер не шлёт автору его собственную запись (exclude_sources), но revision она
    двигает: следующий чужой пакет выглядит разрывом, а снимок содержит путь, которого
    у клиента нет. Потери пакета не было — клиент отличить не может.
    """
    router = _RelayRouter()
    mgr = StateStoreManager(router=router, initial_state={})
    mgr.initialize()
    proxy = StateProxy("gui", router=router, server_target="ProcessManager")
    router.register_message_handler("state.changed", proxy.on_state_changed)
    try:
        proxy.subscribe(_PAT, lambda _d_: None)  # exclude_self=True по умолчанию
        log = _Cap()
        proxy.register_manager("logger", log)

        mgr.handle_state_set({"data": {"path": "foo.bar", "value": 1, "source": "other"}})  # rev 1
        proxy.set("foo.own", 7)  # rev 2: автору не доставляется
        assert proxy.cache.get("foo.own") is None, "якорь: собственная запись дошла до кэша без ресинка"
        mgr.handle_state_set({"data": {"path": "foo.bar", "value": 2, "source": "other"}})  # rev 3 -> «разрыв»

        requests = len(router.resync_requests())
        own = proxy.cache.get("foo.own")
        counts = _counts(proxy)
    finally:
        mgr.shutdown()

    assert requests == 1 and own == 7, f"якорь: ресинк не воспроизведён (запросов={requests}, foo.own={own!r})"
    assert counts == _expect(detected=1, diverged=1)


def test_8c_equal_nan_leaf_is_clean(rig):
    """(C) Лист NaN в кэше и NaN в снимке (РАЗНЫЕ объекты float) — «равны» -> clean."""
    rig.feed({"foo.x": float("nan"), "foo.same": 0})
    rig.gap({"foo.same": 0}, snapshot={"foo": {"x": float("nan"), "same": 0}})

    assert rig.counts() == _expect(detected=1, clean=1)


def test_13_container_with_nan_inside_is_diverged(rig):
    """Контейнер с NaN внутри (``[nan]``, разные объекты) — «отличается» (``[nan] != [nan]``) -> diverged."""
    rig.feed({"foo.vec": [float("nan")], "foo.same": 0})
    rig.gap({"foo.same": 0}, snapshot={"foo": {"vec": [float("nan")], "same": 0}})

    assert rig.counts() == _expect(detected=1, diverged=1)


# ===========================================================================
# 9. Публичные счётчики и метрики
# ===========================================================================


@pytest.mark.parametrize("name", [f"gap_{n}_count" for n in _COUNTERS])
def test_9a_counters_are_read_only_ints(name):
    """Счётчик — property без setter: присвоение -> AttributeError; значение int, 0 на новом прокси."""
    proxy = StateProxy("cam", router=MockRouter())
    assert isinstance(getattr(StateProxy, name, None), property), f"{name} должен быть property"
    with pytest.raises(AttributeError):
        setattr(proxy, name, 5)
    value = getattr(proxy, name)
    assert type(value) is int and value == 0, f"{name}={value!r} на новом прокси, ожидалось int 0"


_METRIC_CASES = {
    "clean": (
        {"foo": {"bar": 2}},
        None,
        {"state_proxy.gap_detected": 1, "state_proxy.gap_clean": 1},
    ),
    "diverged": (
        {"foo": {"bar": 777}},
        None,
        {"state_proxy.gap_detected": 1, "state_proxy.gap_diverged": 1},
    ),
    "unclassified": (
        None,
        {"status": "error", "error": "boom"},
        {"state_proxy.gap_detected": 1, "state_proxy.gap_unclassified": 1},
    ),
}


@pytest.mark.parametrize("case", list(_METRIC_CASES))
def test_9b_metrics_arrive_in_captured_stats(rig_f, case):
    """Метрики ``state_proxy.gap_detected/…`` приходят в захваченный stats — по одной на событие."""
    snapshot, result, expected = _METRIC_CASES[case]
    rig_f.feed({"foo.bar": 1})
    rig_f.gap({"foo.bar": 2}, snapshot=snapshot, result=result)

    assert rig_f.stats.gap_names() == Counter(expected)


def test_9b_detected_only_metric_when_resync_does_not_start():
    """Разрыв без роутера: из метрик gap_* приходит только ``state_proxy.gap_detected``."""
    proxy = StateProxy("cam", router=None)
    proxy.subscribe(_PAT, lambda _d_: None)
    stats = _Stats()
    proxy.register_manager("stats", stats)
    proxy.on_state_changed(_f_msg([_d("foo.bar", 10, 1)], first=1, last=1))
    proxy.on_state_changed(_f_msg([_d("foo.bar", 50, 5)], first=5, last=5))

    assert stats.gap_names() == Counter({"state_proxy.gap_detected": 1})


# ===========================================================================
# 10 (F). Троттлинг WARNING diverged
# ===========================================================================


@pytest.fixture
def clock(monkeypatch):
    """Подменяемые часы троттлинга — ЕДИНСТВЕННОЕ место, зависящее от имени часов.

    Имя часов в реализации тестеру неизвестно (слепой тест). Подменяется
    ``time.monotonic`` глобально — ``real() + сдвиг``, поэтому реальное время идёт,
    ничто не зависает; тест двигает сдвиг ``advance(сек)``. Дополнительно, если в
    модуле ``state_proxy`` или классе ``StateProxy`` уже лежит ПСЕВДОНИМ исходной
    ``time.monotonic`` (``from time import monotonic`` / атрибут класса), он
    подменяется тоже. Если реализация берёт часы иначе (аргумент по умолчанию
    с захватом на этапе определения) — эта фикстура её не покроет, правка здесь
    (и только здесь).
    """
    from multiprocess_framework.modules.state_store_module.proxy import state_proxy as sp_module

    real = time.monotonic
    shift = [0.0]

    def fake() -> float:
        return real() + shift[0]

    monkeypatch.setattr(time, "monotonic", fake)
    for owner in (sp_module, StateProxy):
        for attr, value in list(vars(owner).items()):
            if value is real:
                monkeypatch.setattr(owner, attr, staticmethod(fake) if owner is StateProxy else fake)

    def advance(seconds: float) -> None:
        shift[0] += seconds

    return advance


_NAMES = ["aa", "bb", "cc", "dd"]


def _diverge(rig: _Rig, k: int, tag: int) -> None:
    """Один diverged-разрыв, меняющий ровно ``k`` путей (k не убывает от вызова к вызову).

    Пакет разрыва пишет ``foo.tick`` = tag (в снимке то же значение — не изменение);
    снимок кладёт ``tag`` в первые ``k`` путей из ``_NAMES`` — каждый ДОБАВЛЕН либо
    отличается от значения прошлого события.
    """
    snap = {"tick": tag, **{n: tag for n in _NAMES[:k]}}
    rig.gap({"foo.tick": tag}, snapshot={"foo": snap})


def test_10_diverged_warning_is_throttled_to_one_per_30_seconds(rig_f, clock):
    """Три diverged подряд в пределах 30 с -> один WARNING (накопленное 1); четвёртый после 30 с ->
    второй WARNING с накопленным 3. diverged == 4; обнаружение — только DEBUG.

    Изменённых путей 2, 2, 2, 4 — отличаются от накопленных 1 и 3, чтобы число
    накопленного в тексте не совпало с числом путей случайно.
    """
    rig_f.feed({"foo.tick": 0})
    _diverge(rig_f, 2, 1)
    _diverge(rig_f, 2, 2)
    _diverge(rig_f, 2, 3)
    after_three = list(rig_f.log.gap_warnings())
    clock(31.0)
    _diverge(rig_f, 4, 4)
    after_four = list(rig_f.log.gap_warnings())

    assert len(after_three) == 1, f"три diverged за 30 с дали {len(after_three)} WARNING вместо одного: {after_three!r}"
    assert _num_in(after_three[0], 1), f"первая строка не называет накопленное (1): {after_three[0]!r}"
    assert _num_in(after_three[0], 2), f"первая строка не называет число путей (2): {after_three[0]!r}"
    assert len(after_four) == 2, f"после 30 с ожидался второй WARNING: {after_four!r}"
    assert _num_in(after_four[1], 3), f"вторая строка не называет накопленное с прошлой строки (3): {after_four[1]!r}"
    assert _num_in(after_four[1], 4), f"вторая строка не называет число путей (4): {after_four[1]!r}"
    assert len(rig_f.log.gap_debugs()) >= 4, "обнаружение каждого из 4 разрывов должно остаться в DEBUG"
    assert StateProxy._GAP_WARN_INTERVAL_S == 30.0, "интервал троттлинга обязан быть классовым атрибутом 30.0"
    assert rig_f.counts() == _expect(detected=4, diverged=4)


def test_10b_throttle_boundary_is_between_29_and_31_seconds(rig_f, clock):
    """Граница окна: через 29 с после строки — тихо, ещё через 2 с (31) — новая строка с накопленным 2."""
    rig_f.feed({"foo.tick": 0})
    _diverge(rig_f, 2, 1)
    assert len(rig_f.log.gap_warnings()) == 1
    clock(29.0)
    _diverge(rig_f, 2, 2)
    at_29 = len(rig_f.log.gap_warnings())
    clock(2.0)
    _diverge(rig_f, 3, 3)
    warns = list(rig_f.log.gap_warnings())

    assert at_29 == 1, f"через 29 с строка не должна повторяться: {at_29} WARNING"
    assert len(warns) == 2, f"через 31 с ожидалась вторая строка: {warns!r}"
    assert _num_in(warns[1], 2), f"вторая строка не называет накопленное (2): {warns[1]!r}"
    assert _num_in(warns[1], 3), f"вторая строка не называет число путей (3): {warns[1]!r}"


# ===========================================================================
# 11 (A). GuiStateProxy — тот же механизм
# ===========================================================================


def test_11_gui_state_proxy_classifies_clean_gap():
    """``_Stand(gui=True)``: разрыв со снимком == кэшу -> clean == 1; в WARNING про разрыв нет."""
    stand = _Stand("gc_gui", gui=True)
    log = _Cap()
    stand.proxy.register_manager("logger", log)
    try:
        _open_window(stand)
        stand.answer_resync({"foo": {"bar": 2}}, revision=5)
        warns = log.gap_warnings()
        counts = _counts(stand.proxy)
        is_gui = type(stand.proxy).__name__ == "GuiStateProxy"
    finally:
        stand.close()

    assert is_gui, "стенд собрал не GUI-прокси"
    assert warns == [], f"GUI-прокси: clean-разрыв шумит в WARNING: {warns!r}"
    assert counts == _expect(detected=1, clean=1)


# ===========================================================================
# 12 (A). shutdown посреди полёта
# ===========================================================================


def test_12_shutdown_in_flight_then_late_answer_is_unclassified_not_a_false_clean():
    """Ресинк в полёте, ``shutdown`` прокси, поздний ответ -> unclassified == 1 (не ложный clean).

    Подписок после shutdown нет, снимок применять не к чему: «изменённых 0» было бы
    ложным clean. Принимается и вариант «посчитано при shutdown», и «при позднем
    ответе» — важен итог: unclassified == 1, clean == diverged == 0.
    """
    stand = _Stand("gc_shutdown")
    try:
        _open_window(stand)
        stand.proxy.shutdown()
        stand.answer_resync({"foo": {"bar": 2, "extra": 42}}, revision=5)  # поздний ответ
        stand.tick()
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert counts == _expect(detected=1, unclassified=1)
