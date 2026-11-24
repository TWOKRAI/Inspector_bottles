# T9b — бриф tester

Файл роли: спавн — `python scripts/plans_ledger.py brief T9b.tester --plan plans/2026-11-24_gui-frame-path`. Файлы tester-а вынесены из блока FILES основного брифа `tasks/T9b.md` по решению лида. Эти файлы переносятся в основное дерево при СТАРТЕ T9b, не при слиянии T9a.

TASK: T9b — blind acceptance tests for the segment format, pins and export (RED before code)   PLAN: plans/2026-11-24_gui-frame-path/plan.md
ROLE: tester
CHAIN: lead (brief, stage 0) -> tester -> developer (makes these tests green) -> lead (injections, review)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. Tests use ONLY the literals of the ACCEPTANCE block in `tasks/T9b.md`; expected values are literals, never derived from the code under test; export is compared by content (`blob[off:off+len] == payload_i`), never by length alone.
  2. API: `pin(t0_ns, t1_ns, tag)` (inclusive interval), `unpin(tag)`, `find_group(group_id)`, `export(t0_ns, t1_ns) -> {"blob", "index"}`, `segment.read_segment(blob, index) -> list[dict]`; the index record is `struct "<QIqdqqqI"`, 56 bytes.
  3. Every new `.py` has `__all__` and a `Purpose:` line in its docstring; the pin literal of `test_pin_budget_exceeded_oldest_pin_released_and_counted` uses two pins of 2000 bytes (see open question 6 of the main brief).

FORBIDDEN PATHS (no edits): Services/frame_buffer/time_ring.py, Services/frame_buffer/segment.py, Services/frame_buffer/__init__.py, Services/frame_buffer/DECISIONS.md, Services/frame_buffer/tests/test_time_ring_hazards.py, Services/frame_buffer/tests/test_time_ring.py
FILES (complete list — nothing else; need another file -> stop and report):
  1. Services/frame_buffer/tests/test_segment.py — new
  2. Services/frame_buffer/tests/test_time_ring_pin_export.py — new

REDS (expected RED before code):
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_pinned_range_survives_eviction
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_pin_budget_exceeded_oldest_pin_released_and_counted
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_find_group_returns_frames_of_group
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_export_bytes_identical_to_appended
  - Services/frame_buffer/tests/test_segment.py::test_reader_drops_only_last_record_on_truncated_tail
  - Services/frame_buffer/tests/test_segment.py::test_reader_keeps_all_when_not_truncated
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_unpin_releases_range
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_two_overlapping_pins_unpin_one_keeps_other
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_pin_covers_future_frames
  - Services/frame_buffer/tests/test_segment.py::test_fixed_record_length

TESTS: .venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_segment.py Services/frame_buffer/tests/test_time_ring_pin_export.py

OUT OF SCOPE: the implementation, threaded tests, the T9a core tests.
REPORT: STATUS (DONE|BLOCKED), files, collected and red counts, the reason each RED fails (ERROR on import before the code exists is expected).
