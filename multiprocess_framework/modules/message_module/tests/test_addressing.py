# -*- coding: utf-8 -*-
"""
Contract-тесты иерархической адресации (P0.2 transport-router-hub).

Покрывают: парсинг/валидацию dotted-адреса, prefix-правило (воркер без процесса —
ошибка), backward-совместимость плоского ``"proc"``, нормализацию ``target``/``targets``.
"""

import pytest

from ..addressing import (
    depth,
    is_broadcast,
    join_address,
    normalize_targets,
    process_of,
    split_address,
    subpath_of,
    validate_address,
    worker_of,
)
from ..types import AddressValidationError


class TestSplitAddress:
    """Разбор dotted-адреса в список уровней."""

    def test_flat_process_backward_compat(self):
        # Плоское имя (как сегодня — targets нигде не dotted) == один уровень.
        assert split_address("ProcessManager") == ["ProcessManager"]

    def test_process_worker(self):
        assert split_address("proc.worker") == ["proc", "worker"]

    def test_deep_address(self):
        assert split_address("proc.worker.sub") == ["proc", "worker", "sub"]

    def test_broadcast_is_single_level(self):
        assert split_address("all") == ["all"]
        assert split_address("broadcast") == ["broadcast"]


class TestAccessors:
    """process_of / worker_of / subpath_of / depth."""

    def test_process_of(self):
        assert process_of("proc.worker") == "proc"
        assert process_of("proc") == "proc"

    def test_worker_of(self):
        assert worker_of("proc.worker") == "worker"
        assert worker_of("proc") is None

    def test_subpath_of(self):
        assert subpath_of("proc") == []
        assert subpath_of("proc.worker") == ["worker"]
        assert subpath_of("proc.worker.sub") == ["worker", "sub"]

    def test_depth(self):
        assert depth("proc") == 1
        assert depth("proc.worker") == 2
        assert depth("proc.worker.sub") == 3


class TestValidation:
    """Prefix-правило и форма адреса."""

    def test_valid_addresses_pass(self):
        validate_address("proc")
        validate_address("proc.worker")
        validate_address("proc.worker.deep")

    @pytest.mark.parametrize("bad", ["", ".", ".worker", "proc.", "a..b", "proc..", "..x"])
    def test_empty_segment_rejected(self, bad):
        # ".worker" == воркер без процесса (нарушение prefix); "proc." / "a..b" — висячие точки.
        with pytest.raises(AddressValidationError):
            validate_address(bad)

    @pytest.mark.parametrize("bad", [None, 123, [], {}])
    def test_non_string_rejected(self, bad):
        with pytest.raises(AddressValidationError):
            validate_address(bad)

    def test_split_propagates_validation(self):
        with pytest.raises(AddressValidationError):
            split_address(".worker")


class TestBroadcast:
    def test_is_broadcast(self):
        assert is_broadcast("all")
        assert is_broadcast("broadcast")
        assert not is_broadcast("proc")
        assert not is_broadcast("proc.worker")

    def test_broadcast_skips_dotted_validation(self):
        # Спец-адреса не иерархические — валидируются как есть, не падают.
        validate_address("all")
        validate_address("broadcast")


class TestJoinAddress:
    def test_join(self):
        assert join_address(["proc", "worker"]) == "proc.worker"
        assert join_address(["proc"]) == "proc"

    def test_roundtrip(self):
        for addr in ("proc", "proc.worker", "proc.worker.sub"):
            assert join_address(split_address(addr)) == addr

    @pytest.mark.parametrize("bad", [[], ["proc", ""], ["", "worker"]])
    def test_join_rejects_empty(self, bad):
        with pytest.raises(AddressValidationError):
            join_address(bad)


class TestNormalizeTargets:
    """recon #2: скаляр target + список targets → единый list[str]."""

    def test_list_only(self):
        assert normalize_targets(targets=["a", "b"]) == ["a", "b"]

    def test_scalar_target_only(self):
        assert normalize_targets(target="proc") == ["proc"]

    def test_string_targets_coerced_to_list(self):
        assert normalize_targets(targets="proc") == ["proc"]

    def test_both_dedup_preserves_order(self):
        # data-plane кладёт и target, и тот же в targets-fallback — без дублей.
        assert normalize_targets(targets=["proc"], target="proc") == ["proc"]

    def test_both_distinct(self):
        assert normalize_targets(targets=["a"], target="b") == ["a", "b"]

    def test_empty(self):
        assert normalize_targets() == []
        assert normalize_targets(targets=[], target=None) == []
