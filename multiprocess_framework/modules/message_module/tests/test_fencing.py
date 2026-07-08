# -*- coding: utf-8 -*-
"""Тесты fencing-token (Ф4.2): штамп конверта + drop билета от устаревшего инстанса.

Чистые фабрики middleware — без роутера/процесса. Ключ дропа — per-sender
``incarnation`` (НЕ глобальный epoch): дропается только билет от СТАРОГО инстанса
отправителя (заменённого новым), текущий инстанс проходит даже при epoch-лаге.
Инварианты: только control-plane, fail-open при неизвестном incarnation,
обратная совместимость для сообщений без штампа.
"""
from multiprocess_framework.modules.message_module import (
    FENCE_KEY,
    make_fence_filter_middleware,
    make_fence_stamp_middleware,
    read_fence,
)
from multiprocess_framework.modules.message_module.fencing import is_data_plane


# --------------------------------------------------------------------------- #
# Штамп (send-middleware) — гейт на известность СВОЕГО incarnation
# --------------------------------------------------------------------------- #

def test_stamp_control_plane_adds_fence():
    stamp = make_fence_stamp_middleware("camera_0", lambda: (2, 5))
    msg = stamp({"type": "command", "command": "start"})
    assert read_fence(msg) == {"sender": "camera_0", "inc": 2, "epoch": 5}


def test_stamp_unknown_incarnation_is_fail_open():
    """incarnation None → не штампуем (получатель не сможет решить про stale)."""
    stamp = make_fence_stamp_middleware("camera_0", lambda: (None, 5))
    assert FENCE_KEY not in stamp({"type": "command", "command": "start"})


def test_stamp_epoch_may_be_none_but_incarnation_known():
    """epoch — диагностический, может быть None; штамп ставится по incarnation."""
    stamp = make_fence_stamp_middleware("camera_0", lambda: (3, None))
    assert read_fence(stamp({"type": "command"})) == {"sender": "camera_0", "inc": 3, "epoch": None}


def test_stamp_skips_data_plane_frame():
    stamp = make_fence_stamp_middleware("camera_0", lambda: (2, 5))
    assert FENCE_KEY not in stamp({"type": "data", "data_type": "frame"})
    assert FENCE_KEY not in stamp({"type": "command", "use_shared_memory": True})


def test_stamp_provider_error_does_not_break_send():
    def _boom():
        raise RuntimeError("psr down")

    stamp = make_fence_stamp_middleware("camera_0", _boom)
    assert FENCE_KEY not in stamp({"type": "command", "command": "start"})


# --------------------------------------------------------------------------- #
# Фильтр (receive-middleware) — per-sender incarnation
# --------------------------------------------------------------------------- #

def test_filter_passes_message_without_fence():
    filt = make_fence_filter_middleware(lambda s: 5)
    msg = {"type": "command", "command": "start"}
    assert filt(msg) is msg  # легаси-совместимость


def test_filter_passes_current_incarnation():
    filt = make_fence_filter_middleware(lambda s: 3)
    msg = {"type": "command", "_fence": {"sender": "peer", "inc": 3, "epoch": 1}}
    assert filt(msg) is msg  # inc == expected → проходит
    newer = {"type": "command", "_fence": {"sender": "peer", "inc": 4, "epoch": 1}}
    assert filt(newer) is newer  # inc > expected (получатель отстал) → проходит


def test_filter_drops_stale_instance_and_calls_on_drop():
    dropped = []
    filt = make_fence_filter_middleware(lambda s: 3, on_drop=lambda m: dropped.append(m))
    msg = {"type": "command", "command": "x", "_fence": {"sender": "old", "inc": 2, "epoch": 9}}
    assert filt(msg) is None  # inc 2 < expected 3 → DROP (несмотря на большой epoch)
    assert dropped == [msg]


def test_filter_fail_open_when_sender_unknown():
    filt = make_fence_filter_middleware(lambda s: None)  # неизвестный процесс
    msg = {"type": "command", "_fence": {"sender": "ghost", "inc": 0, "epoch": 0}}
    assert filt(msg) is msg


def test_filter_ignores_incomplete_stamp():
    filt = make_fence_filter_middleware(lambda s: 5)
    assert filt({"type": "command", "_fence": {"inc": 1}}) is not None  # нет sender
    assert filt({"type": "command", "_fence": {"sender": "p"}}) is not None  # нет inc


def test_filter_does_not_touch_data_plane():
    filt = make_fence_filter_middleware(lambda s: 99)
    frame = {"type": "data", "_fence": {"sender": "old", "inc": 0}}
    assert filt(frame) is frame  # горячий путь не фильтруется


# --------------------------------------------------------------------------- #
# Round-trip: штамп → фильтр
# --------------------------------------------------------------------------- #

def test_roundtrip_current_instance_survives_epoch_lag():
    # Отправитель отстал по epoch (0), но его incarnation текущий (1) → проходит.
    stamp = make_fence_stamp_middleware("camera_0", lambda: (1, 0))
    filt = make_fence_filter_middleware(lambda s: 1)  # получатель знает inc(camera_0)=1
    assert filt(stamp({"type": "command", "command": "ping"})) is not None


def test_roundtrip_replaced_instance_dropped():
    # Старый инстанс (inc=0) шлёт; его заменили — получатель знает inc=1 → дроп.
    stamp = make_fence_stamp_middleware("old_child", lambda: (0, 4))
    filt = make_fence_filter_middleware(lambda s: 1)
    assert filt(stamp({"type": "command", "command": "ping"})) is None


def test_is_data_plane_helper():
    assert is_data_plane({"type": "data"})
    assert is_data_plane({"use_shared_memory": True})
    assert not is_data_plane({"type": "command"})
