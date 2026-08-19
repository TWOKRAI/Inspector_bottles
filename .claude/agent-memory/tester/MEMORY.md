# MEMORY.md — индекс памяти tester

- [config.reload ttl-addressing guard](feedback_config_reload_ttl_addressing_guard.md) — throttle-only+ttl refuses for an unrelated reason; don't mistake it for the receiver check
- [observability provenance witness keys](feedback_observability_provenance_witness_keys.md) — pick scalar schema leaves, not containers; base.yaml is a safe minimal hot-rebuild fixture
- [Pydantic extra=ignore hides RED](feedback_pydantic_extra_ignore_hides_red.md) — assert the new attribute directly, a dropped kwarg alone won't fail today
- [live telemetry gate without full boot](feedback_test_live_telemetry_gate_without_full_boot.md) — ProcessHeartbeat._build_telemetry_gate() + minimal services fake, pair with a green control
- [framework tests can't import prototype](feedback_framework_tests_cannot_import_prototype.md) — sentrux boundary has no tests/ exception; split into a companion file under multiprocess_prototype/backend/tests/
- [freeform brief without MODE header](feedback_freeform_brief_without_mode_header.md) — explicit forbidden-paths + red/green framing = RED-equivalent, don't force MODE:regression's git-diff step
- [negative wording assertion needs an existence anchor](feedback_negative_wording_assertion_needs_an_existence_anchor.md) — "must not falsely claim X" is vacuous if nothing was logged; pair with `assert logs` in the same test
- [addressing fake needs general dot-notation](feedback_addressing_fake_needs_general_dot_notation.md) — flat dict.get fake proves its own shape, not a nested-key property; copy the real Config._traverse contract + add one real-object test
- [ownership test needs silent-owner case](feedback_ownership_test_needs_silent_owner_case.md) — live-owner-vs-impostor alone stays green under pure overlay order; add the "owner declared but didn't publish" case to actually test ownership
