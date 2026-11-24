# T9a — бриф tester

Файл роли: спавн — `python scripts/plans_ledger.py brief T9a.tester --plan plans/2026-11-24_gui-frame-path`. Файлы tester-а вынесены из блока FILES основного брифа `tasks/T9a.md` по решению лида (в FILES основного брифа — только файлы developer-а).

TASK: T9a — blind acceptance tests for the TimeRing core (RED before code)   PLAN: plans/2026-11-24_gui-frame-path/plan.md
ROLE: tester
CHAIN: lead (brief, stage 0) -> tester -> developer (makes these tests green) -> lead (injections, review)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. Tests use ONLY the literals of the ACCEPTANCE block in `tasks/T9a.md` (periods in nanoseconds as integers, payload sizes, `max_bytes`, `pin_max_bytes`); expected values are literals, never derived from the code under test.
  2. The constructor is `TimeRing(buffer_seconds, max_bytes, pin_max_bytes)` without defaults; `append(capture_ns, capture_ts, payload, seq, device_frame_num=None, group_id=None, flags=0)`; `at(t_ns, mode)`; `range()`; counters `bytes_held`, `bytes_held_peak`, `span_s`, `rejected_order`, `rejected_oversize`; gaps via `range()["gaps"]`.
  3. Every new `.py` has `__all__` and a `Purpose:` line in its docstring; a test that can block runs in a daemon thread with a join deadline (the threaded tests belong to the developer, file `test_time_ring_hazards.py`).

FORBIDDEN PATHS (no edits): Services/frame_buffer/time_ring.py, Services/frame_buffer/__init__.py, Services/frame_buffer/DECISIONS.md, Services/frame_buffer/README.md, Services/frame_buffer/tests/test_time_ring_hazards.py
FILES (complete list — nothing else; need another file -> stop and report):
  1. Services/frame_buffer/tests/__init__.py — new
  2. Services/frame_buffer/tests/test_time_ring.py — new

REDS (expected RED before code):
  - Services/frame_buffer/tests/test_time_ring.py::test_evicts_older_than_buffer_seconds
  - Services/frame_buffer/tests/test_time_ring.py::test_low_fps_keeps_same_seconds
  - Services/frame_buffer/tests/test_time_ring.py::test_bytes_cap_evicts_oldest_and_span_reported
  - Services/frame_buffer/tests/test_time_ring.py::test_at_nearest_prev_next
  - Services/frame_buffer/tests/test_time_ring.py::test_seq_gap_recorded
  - Services/frame_buffer/tests/test_time_ring.py::test_range_empty
  - Services/frame_buffer/tests/test_time_ring.py::test_bytes_held_never_exceeds_max_bytes
  - Services/frame_buffer/tests/test_time_ring.py::test_rejected_order
  - Services/frame_buffer/tests/test_time_ring.py::test_rejected_oversize

TESTS: .venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py

OUT OF SCOPE: the implementation, threaded tests, T9b (pin, export, segment reader).
REPORT: STATUS (DONE|BLOCKED), files, collected and red counts, the reason each RED fails (ERROR on import before the code exists is expected).
