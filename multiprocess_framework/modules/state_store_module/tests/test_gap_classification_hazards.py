"""test_gap_classification_hazards.py — доводка R3c после ревью (автор кода).

Два дефекта, найденные ревью, и их регрессии:
  * M1: при неудаче первого ответа и при ``shutdown`` СОВМЕЩЁННЫЕ с ресинком разрывы
    оставались без классификации (догоняющего захода нет) — сумма исходов не сходилась
    с ``gap_detected_count``;
  * M2: numpy-скаляры в кэше давали ложный ``diverged`` на каждом ресинке
    (``np.float64(1.0) == np.float64(1.0)`` — ``np.bool_``, а не ``bool``).

Стенд A (``_Stand`` с настоящим ``RouterManager``), литералы вписаны руками.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

from .test_gap_classification import _answer_raw, _counts, _expect
from .test_resync_offthread_hazards import _d, _open_window, _Stand


def _coalesce_gaps(stand: _Stand, how_many: int) -> None:
    """Совместить с идущим ресинком ``how_many`` разрывов (пакеты rev 9, 13, …)."""
    first = 9
    for i in range(how_many):
        rev = first + 4 * i
        stand.deliver([_d("foo.bar", 3 + i, revision=rev, old=2 + i)], first_revision=rev, revision=rev)
    assert stand.proxy._resync_coalesced_count == how_many, "разрывы не совместились — сценарий не воспроизведён"
    assert len(stand.qr.resync_tickets()) == 1, "совмещённый разрыв отправил параллельный запрос"


def test_m1a_first_answer_refused_with_two_coalesced_gaps_classifies_all_three_unclassified():
    """Разрыв + 2 совмещённых, первый ответ ``status: error`` -> detected 3, unclassified 3 (сумма сходится)."""
    stand = _Stand("gc_h_refused")
    try:
        _open_window(stand)
        _coalesce_gaps(stand, 2)
        _answer_raw(stand, {"status": "error", "error": "boom"})
        tickets = len(stand.qr.resync_tickets())
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert tickets == 1, f"якорь: после неудачи ушёл догоняющий запрос (поведение должно остаться прежним): {tickets}"
    assert counts == _expect(detected=3, unclassified=3)


def test_m1b_first_answer_timeout_with_one_coalesced_gap_classifies_both_unclassified():
    """Разрыв + 1 совмещённый, первый ответ не пришёл (таймаут) -> detected 2, unclassified 2."""
    stand = _Stand("gc_h_timeout")
    stand.proxy._SYNC_REQUEST_TIMEOUT = 0.25  # параметр стенда, ДО первого запроса
    try:
        _open_window(stand)
        _coalesce_gaps(stand, 1)
        done = stand.spin(lambda: stand.proxy._resync_inflight_id is None, deadline_sec=5.0)
        assert done, "таймаут ресинка не наступил за 5 с — стенд неисправен"
        failed = stand.proxy._resync_failed_count
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert failed == 1, f"якорь: таймаут не засчитан как неудача ресинка ({failed})"
    assert counts == _expect(detected=2, unclassified=2)


def test_m1c_shutdown_in_flight_with_one_coalesced_gap_classifies_both_unclassified():
    """Разрыв + 1 совмещённый, ``shutdown``, поздний ответ -> detected 2, unclassified 2 (поздний ответ не считает)."""
    stand = _Stand("gc_h_shutdown")
    try:
        _open_window(stand)
        _coalesce_gaps(stand, 1)
        stand.proxy.shutdown()
        after_shutdown = _counts(stand.proxy)
        stand.answer_resync({"foo": {"bar": 2, "extra": 42}}, revision=5)  # поздний ответ
        stand.tick()
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert after_shutdown == _expect(detected=2, unclassified=2), f"shutdown не закрыл разрывы: {after_shutdown}"
    assert counts == _expect(detected=2, unclassified=2), f"поздний ответ изменил счётчики: {counts}"


@pytest.fixture
def numpy_module():
    return pytest.importorskip("numpy")


def test_m2_numpy_scalars_are_equal_and_arrays_differ(numpy_module):
    """Скаляры numpy равны по значению (иначе ложный diverged на каждом ресинке); массив — «отличается»."""
    np = numpy_module
    same = StateProxy._same_value
    assert same(np.float64(1.0), np.float64(1.0)) is True
    assert same(np.int64(3), 3) is True
    assert same(np.float64(1.0), np.float64(2.0)) is False
    assert same(np.array([1, 2]), np.array([1, 2])) is False, "массив (ndim >= 1) обязан считаться «отличается»"


def test_m2_numpy_scalar_in_cache_does_not_make_a_clean_gap_diverged(numpy_module):
    """Сквозь стенд: numpy-скаляр в кэше и тот же в снимке -> clean, не diverged."""
    np = numpy_module
    stand = _Stand("gc_h_numpy")
    try:
        stand.deliver(
            [_d("foo.x", np.float64(1.5), revision=1, old=MISSING), _d("foo.same", 0, revision=1, old=MISSING)],
            first_revision=1,
            revision=1,
        )
        stand.deliver([_d("foo.same", 0, revision=5, old=0)], first_revision=5, revision=5)
        assert stand.proxy._resync_inflight_id is not None, "разрыв не открыл ресинк — сценарий не воспроизведён"
        stand.answer_resync({"foo": {"x": np.float64(1.5), "same": 0}}, revision=5)
        counts = _counts(stand.proxy)
    finally:
        stand.close()

    assert counts == _expect(detected=1, clean=1)
