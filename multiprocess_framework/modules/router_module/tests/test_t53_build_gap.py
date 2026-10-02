# -*- coding: utf-8 -*-
"""Task 5.3 — слепые приёмочные тесты ``build_gap`` и ``build_marker`` (запись о разрыве).

Независимый tester, от acceptance Task 5.3 (plans/transport-single-policy/phase-5.md, «### Task 5.3»),
без чтения реализации 5.3 (её в дереве нет). Ожидаемые значения — литералы, не пересчёт из кода.

Что пинится (чистая функция, без процессов):
  * запись ``count > 1``: ровно набор ключей из спеки; ``reason`` / ``trace_id`` / ``capture_ts`` / ``frame_id``
    в ней нет; ``source`` — только если источник один, ``camera_id`` — только если ключ у ВСЕХ входов и
    значение одно;
  * запись ``count == 1`` = ключи ``build_marker`` + ``count`` + ``trace_ids`` + ``first/last_capture_ts`` +
    ``reasons`` + ``sources``;
  * ``first/last_capture_ts`` — min/max по не-``None``; все ``None`` -> оба ``None``;
  * вход может быть записью (поля суммируются, ``trace_ids`` склеиваются в порядке входа);
  * чанк ``GAP_CHUNK = 1500``: вход неделим, упаковка жадная, следующий вход открывает новую запись;
  * пустой вход -> ``ValueError``; ``len(trace_ids) == count``;
  * ``build_marker`` = сегодняшние ключи + ``"count": 1``.

RED до реализации: символа ``build_gap`` / ``GAP_CHUNK`` нет, поэтому тесты падают ``AttributeError``
на обращении к модулю (не ``ImportError`` на сборке файла). Тесты ``build_marker`` падают ``AssertionError``
(в литерале нет ``count``). Зелёных контролей в файле нет.
"""

from __future__ import annotations

import copy
import pickle
import uuid

import pytest

from multiprocess_framework.modules.router_module.middleware import not_inspected_marker as nim

TS1, TS2, TS3 = 10.0, 11.5, 12.25
CAM = "cam0"
SRC = "processor"


def _m(trace_id: str, *, reason: str = "lag", ts: float | None = TS1, source: str = SRC, camera="cam0", **extra):
    """Маркер через боевой конструктор. ``camera=None`` — ключа ``camera_id`` нет вовсе."""
    meta: dict = {"trace_id": trace_id, "capture_ts": ts}
    if camera is not None:
        meta["camera_id"] = camera
    meta.update(extra)
    return nim.build_marker(meta, reason=reason, source=source)


def _markers(n: int, *, prefix: str = "t", reason: str = "lag") -> list[dict]:
    return [_m(f"{prefix}{i}", reason=reason, ts=float(i)) for i in range(n)]


def _rec(n: int, *, prefix: str = "t", reason: str = "lag") -> dict:
    """Запись ровно из n маркеров (n <= 1500) — вход для «вход может быть записью»."""
    out = nim.build_gap(_markers(n, prefix=prefix, reason=reason))
    assert len(out) == 1, "стенд неисправен: n маркеров дали не одну запись"
    return out[0]


# =============================================================================== константа
def test_gap_chunk_is_1500():
    assert nim.GAP_CHUNK == 1500


# ======================================================================== форма записи count > 1
def test_three_markers_give_exact_record_literal():
    """Три маркера одного узла-источника и одной камеры: ровно одна запись, ключи и значения — литерал спеки."""
    items = [
        _m("t1", reason="lag", ts=TS1),
        _m("t2", reason="lag", ts=TS2),
        _m("t3", reason="stale_restore", ts=TS3),
    ]

    assert nim.build_gap(items) == [
        {
            "inspection_status": "not_inspected",
            "overflow_marker": True,
            "count": 3,
            "trace_ids": ["t1", "t2", "t3"],
            "first_capture_ts": TS1,
            "last_capture_ts": TS3,
            "reasons": {"lag": 2, "stale_restore": 1},
            "sources": {SRC: 3},
            "source": SRC,
            "camera_id": CAM,
        }
    ]


def test_legacy_markers_without_count_key_count_as_one_each():
    """Вход — маркер из литерала БЕЗ ключа ``count`` (как до 5.3): читатель берёт ``count = item.get("count", 1)``."""
    legacy = [
        {
            "inspection_status": "not_inspected",
            "overflow_marker": True,
            "reason": "lag",
            "source": SRC,
            "trace_id": f"t{i}",
            "capture_ts": float(i),
        }
        for i in (1, 2)
    ]

    (record,) = nim.build_gap(legacy)

    assert record["count"] == 2
    assert record["trace_ids"] == ["t1", "t2"]
    assert record["reasons"] == {"lag": 2}


def test_two_sources_record_has_no_source_key_but_counts_both():
    items = [_m("t1", source="proc_a"), _m("t2", source="proc_b"), _m("t3", source="proc_a")]

    (record,) = nim.build_gap(items)

    assert "source" not in record
    assert record["sources"] == {"proc_a": 2, "proc_b": 1}


def test_camera_id_absent_when_one_input_lacks_the_key():
    items = [_m("t1", camera="cam0"), _m("t2", camera=None), _m("t3", camera="cam0")]

    (record,) = nim.build_gap(items)

    assert "camera_id" not in record
    assert record["count"] == 3


def test_camera_id_absent_when_values_differ():
    items = [_m("t1", camera="cam0"), _m("t2", camera="cam1")]

    (record,) = nim.build_gap(items)

    assert "camera_id" not in record


def test_camera_id_zero_value_is_kept_when_all_inputs_agree():
    """Значение 0 — не «нет ключа» (``build_marker`` сохраняет 0, запись тоже)."""
    items = [_m("t1", camera=0), _m("t2", camera=0)]

    (record,) = nim.build_gap(items)

    assert record["camera_id"] == 0


def test_all_four_reasons_aggregated_by_name():
    items = [
        _m("t1", reason="lag"),
        _m("t2", reason="stale_restore"),
        _m("t3", reason="stale_exec"),
        _m("t4", reason="door"),
        _m("t5", reason="lag"),
    ]

    (record,) = nim.build_gap(items)

    assert record["reasons"] == {"lag": 2, "stale_restore": 1, "stale_exec": 1, "door": 1}


def test_trace_ids_keep_input_order_not_sorted_order():
    items = [_m("t9"), _m("t1"), _m("t5")]

    (record,) = nim.build_gap(items)

    assert record["trace_ids"] == ["t9", "t1", "t5"]


def test_empty_trace_id_is_kept_so_that_len_trace_ids_equals_count():
    """``build_marker`` пишет ``trace_id = ""`` при его отсутствии; запись не выбрасывает пустые id."""
    items = [_m("t1"), nim.build_marker({"capture_ts": TS2}, reason="lag", source=SRC), _m("t3")]

    (record,) = nim.build_gap(items)

    assert record["trace_ids"] == ["t1", "", "t3"]
    assert record["count"] == 3


def test_record_has_no_per_frame_keys():
    (record,) = nim.build_gap(_markers(3))

    leaked = [k for k in ("reason", "trace_id", "capture_ts", "frame_id") if k in record]
    assert leaked == []


# ============================================================================ запись count == 1
def test_single_marker_gives_exact_count_one_record_literal():
    marker = _m("t1", reason="lag", ts=TS1, frame_id=7)

    assert nim.build_gap([marker]) == [
        {
            "inspection_status": "not_inspected",
            "overflow_marker": True,
            "reason": "lag",
            "source": SRC,
            "trace_id": "t1",
            "capture_ts": TS1,
            "frame_id": 7,
            "camera_id": CAM,
            "count": 1,
            "trace_ids": ["t1"],
            "first_capture_ts": TS1,
            "last_capture_ts": TS1,
            "reasons": {"lag": 1},
            "sources": {SRC: 1},
        }
    ]


def test_single_marker_without_optional_keys_gives_record_without_them():
    marker = nim.build_marker({"trace_id": "t1", "capture_ts": TS1}, reason="door", source="B")

    assert nim.build_gap([marker]) == [
        {
            "inspection_status": "not_inspected",
            "overflow_marker": True,
            "reason": "door",
            "source": "B",
            "trace_id": "t1",
            "capture_ts": TS1,
            "count": 1,
            "trace_ids": ["t1"],
            "first_capture_ts": TS1,
            "last_capture_ts": TS1,
            "reasons": {"door": 1},
            "sources": {"B": 1},
        }
    ]


# ============================================================================== capture_ts
def test_capture_ts_none_in_the_middle_is_skipped():
    items = [_m("t1", ts=TS1), _m("t2", ts=None), _m("t3", ts=TS3)]

    (record,) = nim.build_gap(items)

    assert (record["first_capture_ts"], record["last_capture_ts"]) == (TS1, TS3)


def test_capture_ts_none_first_does_not_break_min_max():
    items = [_m("t1", ts=None), _m("t2", ts=2.0), _m("t3", ts=1.0)]

    (record,) = nim.build_gap(items)

    assert (record["first_capture_ts"], record["last_capture_ts"]) == (1.0, 2.0)


def test_capture_ts_out_of_order_first_is_min_last_is_max():
    """Не первый/последний по порядку входа, а min/max по значению."""
    items = [_m("t1", ts=3.0), _m("t2", ts=1.0), _m("t3", ts=2.0)]

    (record,) = nim.build_gap(items)

    assert (record["first_capture_ts"], record["last_capture_ts"]) == (1.0, 3.0)


def test_capture_ts_all_none_gives_none_none():
    items = [_m("t1", ts=None), _m("t2", ts=None)]

    (record,) = nim.build_gap(items)

    assert (record["first_capture_ts"], record["last_capture_ts"]) == (None, None)


def test_single_marker_with_none_capture_ts_gives_none_none():
    (record,) = nim.build_gap([_m("t1", ts=None)])

    assert (record["first_capture_ts"], record["last_capture_ts"]) == (None, None)


# ====================================================================== вход — запись
def test_record_inputs_are_summed_and_trace_ids_concatenated_in_input_order():
    a = nim.build_gap(
        [_m("a1", reason="lag", ts=5.0), _m("a2", reason="lag", ts=6.0), _m("a3", reason="door", ts=7.0)]
    )[0]
    b = nim.build_gap([_m("b1", reason="lag", ts=1.0), _m("b2", reason="stale_exec", ts=2.0)])[0]

    (record,) = nim.build_gap([a, b])

    assert record["count"] == 5
    assert record["trace_ids"] == ["a1", "a2", "a3", "b1", "b2"]
    assert record["reasons"] == {"lag": 3, "door": 1, "stale_exec": 1}
    assert record["sources"] == {SRC: 5}
    assert (record["first_capture_ts"], record["last_capture_ts"]) == (1.0, 7.0)


def test_marker_and_record_inputs_mixed_are_summed():
    rec = nim.build_gap([_m("r1", ts=2.0), _m("r2", ts=3.0)])[0]

    (record,) = nim.build_gap([_m("m1", ts=9.0), rec])

    assert record["count"] == 3
    assert record["trace_ids"] == ["m1", "r1", "r2"]
    assert record["reasons"] == {"lag": 3}
    assert (record["first_capture_ts"], record["last_capture_ts"]) == (2.0, 9.0)


def test_single_record_input_is_returned_unchanged():
    rec = nim.build_gap(_markers(4))[0]

    assert nim.build_gap([rec]) == [rec]


# =================================================================================== чанк
def test_chunk_full_record_then_marker_gives_1500_and_1():
    rec = _rec(nim.GAP_CHUNK)
    marker = _m("tail", ts=99.0, frame_id=3)

    records = nim.build_gap([rec, marker])

    assert [r["count"] for r in records] == [1500, 1]
    assert records[0]["trace_ids"] == rec["trace_ids"]
    assert records[1] == {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "reason": "lag",
        "source": SRC,
        "trace_id": "tail",
        "capture_ts": 99.0,
        "frame_id": 3,
        "camera_id": CAM,
        "count": 1,
        "trace_ids": ["tail"],
        "first_capture_ts": 99.0,
        "last_capture_ts": 99.0,
        "reasons": {"lag": 1},
        "sources": {SRC: 1},
    }


def test_chunk_greedy_marker_then_full_record_opens_new_record():
    """Жадная упаковка неделимых входов: 1 + 1500 > 1500, поэтому запись на 1500 открывает новую. Решение тестера."""
    rec = _rec(nim.GAP_CHUNK)

    records = nim.build_gap([_m("head", ts=-1.0), rec])

    assert [r["count"] for r in records] == [1, 1500]


def test_chunk_record_input_is_not_split():
    """Две записи по 1000: 1000 + 1000 > 1500, каждая уходит целой, ``trace_ids`` входа не режутся."""
    a, b = _rec(1000, prefix="a"), _rec(1000, prefix="b")

    records = nim.build_gap([a, b])

    assert [r["count"] for r in records] == [1000, 1000]
    assert records[0]["trace_ids"] == a["trace_ids"]
    assert records[1]["trace_ids"] == b["trace_ids"]
    assert records[0]["reasons"] == {"lag": 1000}


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1499, [1499]), (1500, [1500]), (1501, [1500, 1]), (3000, [1500, 1500]), (3008, [1500, 1500, 8])],
)
def test_chunk_counts_around_the_boundary(n, expected):
    records = nim.build_gap(_markers(n))

    assert [r["count"] for r in records] == expected


@pytest.mark.parametrize("n", [1, 2, 7, 1500, 1501, 3008])
def test_chunk_invariants_sum_len_order_and_message_count(n):
    """Σ count == n; ``len(trace_ids) == count``; склейка ``trace_ids`` по записям = порядок входа;
    записей ⌈n/1500⌉; ни одна запись не больше 1500."""
    items = _markers(n)

    records = nim.build_gap(items)

    expected_records = -(-n // 1500)
    assert len(records) == expected_records
    assert sum(r["count"] for r in records) == n
    assert all(len(r["trace_ids"]) == r["count"] for r in records)
    assert all(r["count"] <= 1500 for r in records)
    assert [t for r in records for t in r["trace_ids"]] == [it["trace_id"] for it in items]


def test_chunked_records_keep_per_record_aggregates():
    """Агрегаты считаются по каждой записи отдельно, а не по всему входу."""
    items = [_m(f"t{i}", reason="lag" if i < 1500 else "door", ts=float(i)) for i in range(1503)]

    first, second = nim.build_gap(items)

    assert first["reasons"] == {"lag": 1500}
    assert (first["first_capture_ts"], first["last_capture_ts"]) == (0.0, 1499.0)
    assert second["reasons"] == {"door": 3}
    assert (second["first_capture_ts"], second["last_capture_ts"]) == (1500.0, 1502.0)


# ======================================================================== пустой вход, чистота
def test_empty_input_raises_value_error():
    with pytest.raises(ValueError):
        nim.build_gap([])


def test_inputs_are_not_mutated():
    items = [_m("t1"), _m("t2", reason="door")]
    rec = nim.build_gap([_m("r1"), _m("r2")])[0]
    before = copy.deepcopy([*items, rec])

    nim.build_gap([*items, rec])

    assert [*items, rec] == before


# ==================================================================== запись остаётся маркером
def test_record_is_marker_and_collection_of_records_is_marker_collection():
    multi = nim.build_gap(_markers(3))[0]
    single = nim.build_gap(_markers(1))[0]

    assert nim.is_marker(multi) is True
    assert nim.is_marker(single) is True
    assert nim.is_marker_collection([multi, single]) is True


# ================================================================================== размер
def test_pickle_size_of_1078_ids_record_is_within_64_kib():
    """32-символьные trace_id (uuid4 hex), 1078 штук — число в отчёт (``pytest -s``), потолок 64 КиБ."""
    items = [
        nim.build_marker(
            {"trace_id": uuid.uuid4().hex, "capture_ts": 1000.0 + i, "camera_id": CAM}, reason="lag", source=SRC
        )
        for i in range(1078)
    ]

    (record,) = nim.build_gap(items)
    size = len(pickle.dumps(record))
    print(f"\nPICKLE_SIZE_1078_IDS={size} bytes")

    assert record["count"] == 1078
    assert all(len(t) == 32 for t in record["trace_ids"])
    assert size <= 64 * 1024


# ============================================================================ build_marker
def test_build_marker_has_count_one_in_exact_literal():
    marker = nim.build_marker(
        {"trace_id": "t7", "capture_ts": 9.25, "frame_id": 12, "camera_id": "cam0"}, reason="lag", source="up"
    )

    assert marker == {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "reason": "lag",
        "source": "up",
        "trace_id": "t7",
        "capture_ts": 9.25,
        "frame_id": 12,
        "camera_id": "cam0",
        "count": 1,
    }


def test_build_marker_without_optional_keys_has_count_one():
    marker = nim.build_marker({}, reason="door", source="B")

    assert marker == {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "reason": "door",
        "source": "B",
        "trace_id": "",
        "capture_ts": None,
        "count": 1,
    }
