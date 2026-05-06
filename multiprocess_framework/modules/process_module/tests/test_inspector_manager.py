"""Тесты InspectorManager — буферизация items для fan-in."""

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.inspector_manager import (
    InspectorManager,
)


class TestPassThrough:
    """Без fan-in — немедленный pass-through."""

    def test_no_total_regions(self):
        """Item без total_regions → сразу on_ready([item])."""
        results = []
        mgr = InspectorManager(on_ready=results.append)

        item = {"frame": "data", "camera_id": 0, "seq_id": 1}
        mgr.on_item(item)

        assert len(results) == 1
        assert results[0] == [item]

    def test_total_regions_zero(self):
        """total_regions=0 → pass-through."""
        results = []
        mgr = InspectorManager(on_ready=results.append)

        item = {"frame": "data", "total_regions": 0, "camera_id": 0, "seq_id": 1}
        mgr.on_item(item)

        assert len(results) == 1
        assert results[0] == [item]

    def test_total_regions_one(self):
        """total_regions=1 → pass-through (один item = готово)."""
        results = []
        mgr = InspectorManager(on_ready=results.append)

        item = {"frame": "data", "total_regions": 1, "camera_id": 0, "seq_id": 1}
        mgr.on_item(item)

        assert len(results) == 1
        assert results[0] == [item]


class TestFanIn:
    """Fan-in — буферизация по (camera_id, seq_id)."""

    def test_collect_all_regions(self):
        """3 items с total_regions=3 → on_ready вызван 1 раз с 3 items."""
        results = []
        mgr = InspectorManager(on_ready=results.append)

        for i in range(3):
            mgr.on_item({
                "frame": f"region_{i}",
                "camera_id": 0,
                "seq_id": 5,
                "total_regions": 3,
                "region_name": f"r{i}",
            })

        assert len(results) == 1
        assert len(results[0]) == 3
        assert mgr.pending_count == 0

    def test_not_ready_until_complete(self):
        """2 из 3 items → on_ready НЕ вызван, pending_count == 1."""
        results = []
        mgr = InspectorManager(on_ready=results.append)

        for i in range(2):
            mgr.on_item({
                "frame": f"region_{i}",
                "camera_id": 0,
                "seq_id": 5,
                "total_regions": 3,
                "region_name": f"r{i}",
            })

        assert len(results) == 0
        assert mgr.pending_count == 1

    def test_multi_camera_isolation(self):
        """Items с (cam=0, seq=5) и (cam=1, seq=5) буферизуются раздельно."""
        results = []
        mgr = InspectorManager(on_ready=results.append)

        # Камера 0: 2 региона
        for i in range(2):
            mgr.on_item({
                "frame": f"cam0_r{i}",
                "camera_id": 0,
                "seq_id": 5,
                "total_regions": 2,
                "region_name": f"r{i}",
            })

        # Камера 1: 2 региона
        for i in range(2):
            mgr.on_item({
                "frame": f"cam1_r{i}",
                "camera_id": 1,
                "seq_id": 5,
                "total_regions": 2,
                "region_name": f"r{i}",
            })

        assert len(results) == 2
        # Первая коллекция — камера 0
        assert all("cam0" in item["frame"] for item in results[0])
        # Вторая коллекция — камера 1
        assert all("cam1" in item["frame"] for item in results[1])

    def test_default_camera_id(self):
        """Item без camera_id → camera_id=0 по умолчанию."""
        results = []
        mgr = InspectorManager(on_ready=results.append)

        for i in range(2):
            mgr.on_item({
                "frame": f"r{i}",
                "seq_id": 1,
                "total_regions": 2,
                "region_name": f"r{i}",
            })

        assert len(results) == 1
        assert len(results[0]) == 2


class TestTimeout:
    """Timeout — flush неполных коллекций."""

    def test_timeout_flush(self):
        """2/3 items + timeout → flush неполной коллекции."""
        results = []
        mgr = InspectorManager(timeout_sec=0.05, on_ready=results.append)

        # Добавляем 2 из 3
        for i in range(2):
            mgr.on_item({
                "frame": f"r{i}",
                "camera_id": 0,
                "seq_id": 5,
                "total_regions": 3,
                "region_name": f"r{i}",
            })

        assert len(results) == 0

        # Ждём timeout
        time.sleep(0.08)
        mgr.check_timeouts()

        assert len(results) == 1
        assert len(results[0]) == 2
        assert mgr.pending_count == 0

    def test_no_timeout_before_threshold(self):
        """До timeout → check_timeouts не flush'ит."""
        results = []
        mgr = InspectorManager(timeout_sec=1.0, on_ready=results.append)

        mgr.on_item({
            "frame": "r0",
            "camera_id": 0,
            "seq_id": 5,
            "total_regions": 3,
            "region_name": "r0",
        })

        mgr.check_timeouts()
        assert len(results) == 0
        assert mgr.pending_count == 1


class TestEdgeCases:
    """Edge cases и дубликаты."""

    def test_duplicate_region_name(self):
        """Дубликат region_name → перезапись с warning."""
        results = []
        warnings = []
        mgr = InspectorManager(
            on_ready=results.append,
            log_error=warnings.append,
        )

        # Два item с одинаковым region_name
        mgr.on_item({
            "frame": "first",
            "camera_id": 0,
            "seq_id": 1,
            "total_regions": 2,
            "region_name": "r0",
        })
        mgr.on_item({
            "frame": "duplicate",
            "camera_id": 0,
            "seq_id": 1,
            "total_regions": 2,
            "region_name": "r0",
        })

        # Warning залогирован
        assert len(warnings) == 1
        assert "дубликат" in warnings[0]

        # В буфере осталась перезаписанная версия
        assert mgr.pending_count == 1


class TestThreadSafety:
    """Thread-safety: concurrent on_item."""

    def test_concurrent_on_item(self):
        """Параллельный on_item из нескольких потоков без race condition."""
        results = []
        lock = threading.Lock()

        def safe_on_ready(items):
            with lock:
                results.append(items)

        mgr = InspectorManager(on_ready=safe_on_ready)

        num_collections = 50
        regions_per_collection = 3

        def worker(start_seq):
            for seq in range(start_seq, start_seq + num_collections):
                for r in range(regions_per_collection):
                    mgr.on_item({
                        "frame": f"seq{seq}_r{r}",
                        "camera_id": 0,
                        "seq_id": seq,
                        "total_regions": regions_per_collection,
                        "region_name": f"r{r}",
                    })

        # Два потока с разными seq_id диапазонами
        t1 = threading.Thread(target=worker, args=(0,))
        t2 = threading.Thread(target=worker, args=(1000,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Все коллекции должны быть доставлены
        assert len(results) == num_collections * 2
        # Каждая коллекция — 3 items
        for collection in results:
            assert len(collection) == regions_per_collection
        assert mgr.pending_count == 0
