"""Тесты CentroidTracker — ассоциация, hits/age, новые треки."""

from Plugins.filter.line_filter.tracker import CentroidTracker


class TestAssociation:
    def test_jitter_same_track(self):
        """Дрожащая точка (±5px) ассоциируется с тем же треком."""
        tr = CentroidTracker(max_match_distance=20, max_age=30)
        t1 = tr.update([(100.0, 100.0)])[0]
        t2 = tr.update([(103.0, 98.0)])[0]
        assert t1.id == t2.id
        assert t2.hits == 2

    def test_far_point_new_track(self):
        """Точка дальше max_match_distance → новый трек."""
        tr = CentroidTracker(max_match_distance=20, max_age=30)
        a = tr.update([(100.0, 100.0)])[0]
        b = tr.update([(300.0, 300.0)])[0]
        assert a.id != b.id

    def test_two_objects_keep_ids(self):
        tr = CentroidTracker(max_match_distance=20, max_age=30)
        tr.update([(100.0, 100.0), (400.0, 400.0)])
        res = tr.update([(105.0, 100.0), (398.0, 402.0)])
        ids = sorted(t.id for t in res)
        assert ids == [0, 1]
        assert all(t.hits == 2 for t in res)


class TestAging:
    def test_track_removed_after_max_age(self):
        tr = CentroidTracker(max_match_distance=20, max_age=2)
        tr.update([(100.0, 100.0)])  # id 0 created
        assert 0 in tr.tracks
        # Несколько кадров без этой точки → misses растут.
        tr.update([])  # misses=1
        tr.update([])  # misses=2
        assert 0 in tr.tracks  # ещё жив (misses == max_age)
        tr.update([])  # misses=3 > max_age → удалён
        assert 0 not in tr.tracks
