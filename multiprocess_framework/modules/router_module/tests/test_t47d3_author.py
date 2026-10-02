# -*- coding: utf-8 -*-
"""Task 4.7d-3 — авторские hazard-тесты двери отправителя (маркер ``reason="door"``).

Что может сломаться именно в ЭТОМ механизме (замена содержимого общего ``data``-dict + счётчики):
  * fan-out: цели делят ОДИН dict; если замена не на месте или рождение считается в send-middleware,
    маркер рождается/считается по разу на цель;
  * счётчик ``door_drops`` в ``strip_data_frame_on_send`` (зовётся на цель) вместо ``strip_and_write`` (на item);
  * маркер несёт хвост исходного item'а: кадр, ссылки, билеты, метку дропа или полезную нагрузку;
  * замена трогает адресную часть сообщения (target/type/channel и прочие ключи msg);
  * исчерпание займа ошибочно превращается в маркер под every (рождённый маркер на вход, который можно повторить);
  * ``latest`` случайно что-то эмитит или мутирует item.

Стенд (писатель A, отправитель B, view, перезапись кольца) — из слепого ``test_t47d3_door.py``; вызовы двери идут
в daemon-потоке с дедлайном на join. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import is_marker
from multiprocess_framework.modules.router_module.tests import test_t47d3_door as _door
from multiprocess_framework.modules.router_module.tests.test_t47d3_door import (
    EVERY,
    LATEST_DEFAULT,
    MARKER,
    _arr,
    _bounded,
    _door_drop_item,
    _exhausted_sender,
    _msg,
    _overwrite_input,
    _received,
    _send,
)

# Фикстуры слепого файла (настоящее SHM-кольцо, чистка FW_SHM_*): присваивание, а не import-имя — pytest видит их
# как атрибуты модуля.
made = _door.made
_clean_shm_flags = _door._clean_shm_flags

MARKER_KEYS = set(MARKER)  # ровно эти ключи, ничего сверх


def _door_dropped_item(made, **kw):
    writer, sender, received = _received(made, **kw)
    item = _door_drop_item(received)
    item["payload"] = {"count": 3}  # полезная нагрузка алгоритма: маркер её нести не должен
    _overwrite_input(writer)
    return sender, item


def test_fanout_three_targets_same_dict_one_birth_one_door_drop(made):
    """3 цели делят один dict под every: 3 сообщения, один и тот же объект data (замена на месте), маркер равен
    литералу, ``not_inspected_door == 1``, ``door_drops == 1`` (не 3)."""
    sender, item = _door_dropped_item(made, **EVERY)
    msgs = [_msg(item, target=f"t{i}") for i in range(3)]

    outs = [_bounded(lambda m=m: sender.strip_data_frame_on_send(m)) for m in msgs]

    assert all(o is not None for o in outs)
    assert all(o["data"] is item for o in outs), "замена не на месте: цели получили разные dict"
    assert all(o["data"] == MARKER for o in outs)
    assert (sender.not_inspected_door, sender.door_drops) == (1, 1)


def test_door_drops_counts_per_item_not_per_send_under_latest_and_every(made):
    """Счётчик в ``strip_and_write``, а не в middleware-send: 3 цели одного item'а -> ``door_drops == 1``
    в обоих режимах (``send`` зовётся на цель, ``strip_and_write`` первым вызовом ставит метку)."""
    for kw in (LATEST_DEFAULT, EVERY):
        sender, item = _door_dropped_item(made, **kw)
        for i in range(3):
            _bounded(lambda i=i: sender.strip_data_frame_on_send(_msg(item, target=f"t{i}")))
        assert sender.door_drops == 1, f"{kw}: door_drops={sender.door_drops}"


def test_marker_has_exactly_marker_keys_nothing_leaks(made):
    """В ``msg["data"]`` ровно ключи маркера: ни ``frame``/``_shm_refs``/``_shm_views``/``_shm_dropped``, ни
    ``payload``/``crop``/``n`` исходного item'а."""
    sender, item = _door_dropped_item(made, **EVERY)

    out = _send(sender, item)

    assert set(out["data"]) == MARKER_KEYS, sorted(set(out["data"]) ^ MARKER_KEYS)


def test_message_envelope_untouched_by_replacement(made):
    """Конверт сообщения цел: тот же набор ключей msg, ``target``/``type``/``channel``/``sender`` — как были."""
    sender, item = _door_dropped_item(made, **EVERY)
    msg = {"target": "line_9", "type": "data", "channel": "data_ch", "sender": "B", "data": item}

    out = _bounded(lambda: sender.strip_data_frame_on_send(msg))

    assert out is msg
    assert set(out) == {"target", "type", "channel", "sender", "data"}
    assert (out["target"], out["type"], out["channel"], out["sender"]) == (
        "line_9",
        "data",
        "data_ch",
        "B",
    )


def test_loan_exhaustion_under_every_is_none_and_item_not_turned_into_marker(made):
    """Исчерпание займа при every: ``None``, item НЕ заменён маркером (ждёт повторной попытки), счётчики двери 0."""
    sender = _exhausted_sender(made, **EVERY)
    item = {"frame": _arr(9), "trace_id": "tr-9"}

    out = _send(sender, item)

    assert out is None
    assert not is_marker(item) and item["trace_id"] == "tr-9"
    assert (sender.door_drops, sender.not_inspected_door) == (0, 0)


def test_latest_door_drop_returns_none_and_emits_nothing(made):
    """latest: ``None``, item не стал маркером (метка дропа на месте, нагрузка цела), ``not_inspected_door == 0``."""
    sender, item = _door_dropped_item(made, **LATEST_DEFAULT)

    out = _send(sender, item)

    assert out is None
    assert not is_marker(item)
    assert item["_shm_dropped"] is True and item["payload"] == {"count": 3}
    assert sender.not_inspected_door == 0


def test_resend_of_already_born_marker_does_not_birth_again(made):
    """Повторная отправка того же dict ПОСЛЕ рождения (ретрай/третья цель позже) — маркер уходит как есть,
    счётчики не растут."""
    sender, item = _door_dropped_item(made, **EVERY)
    _send(sender, item)

    out = _send(sender, item, target="late")

    assert out is not None and out["data"] == MARKER
    assert (sender.not_inspected_door, sender.door_drops) == (1, 1)


def test_constructor_rejects_unknown_overflow():
    """``overflow`` вне latest|every -> ValueError (как у приёмника и исполнителя)."""
    with pytest.raises(ValueError):
        FrameShmMiddleware(None, owner="B", overflow="Every")
