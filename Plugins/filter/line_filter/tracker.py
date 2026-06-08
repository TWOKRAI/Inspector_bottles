"""CentroidTracker — лёгкий трекинг центроидов между кадрами (SORT-lite).

Жадная ассоциация ближайшего соседа в радиусе max_match_distance. Даёт стабильную
идентичность объекта между кадрами — основа для temporal confirmation, гистерезиса
(enter_zone) и детекции пересечения (cross_line). Точки без id на входе получают id
трека; повторное дрожание ±N px ассоциируется с тем же треком.
"""

from __future__ import annotations

import math

Point = tuple[float, float]


class Track:
    """Один трек: позиция, счётчики, и место для line-специфичного состояния."""

    __slots__ = ("id", "x", "y", "hits", "misses", "meta")

    def __init__(self, track_id: int, x: float, y: float) -> None:
        self.id = track_id
        self.x = x
        self.y = y
        self.hits = 1
        self.misses = 0
        # Состояние, которым управляет плагин (prev_sign, armed, counted, ...).
        self.meta: dict = {}

    @property
    def pos(self) -> Point:
        return (self.x, self.y)


class CentroidTracker:
    """Ассоциация точек с треками по ближайшему соседу.

    Args:
        max_match_distance: радиус ассоциации точки к существующему треку (px).
        max_age: трек удаляется после стольких подряд кадров без совпадения.
    """

    def __init__(self, max_match_distance: float = 20.0, max_age: int = 30) -> None:
        self._max_dist = max_match_distance
        self._max_age = max_age
        self._next_id = 0
        self._tracks: dict[int, Track] = {}

    @property
    def tracks(self) -> dict[int, Track]:
        return self._tracks

    def update(self, points: list[Point]) -> list[Track]:
        """Обновить треки точками текущего кадра. Возвращает треки, совпавшие в этом кадре.

        Жадная ассоциация: перебираем все пары (точка, трек) по возрастанию дистанции,
        связываем ближайшие в пределах max_match_distance. Несвязанные точки → новые
        треки. Несвязанные треки → misses++ (удаляются по max_age).
        """
        track_ids = list(self._tracks.keys())
        unmatched_points = set(range(len(points)))
        unmatched_tracks = set(track_ids)

        # Все пары в радиусе, отсортированные по дистанции (жадно — ближайшие первыми).
        pairs: list[tuple[float, int, int]] = []
        for pi, p in enumerate(points):
            for tid in track_ids:
                t = self._tracks[tid]
                d = math.hypot(p[0] - t.x, p[1] - t.y)
                if d <= self._max_dist:
                    pairs.append((d, pi, tid))
        pairs.sort(key=lambda x: x[0])

        matched: list[Track] = []
        for _d, pi, tid in pairs:
            if pi not in unmatched_points or tid not in unmatched_tracks:
                continue
            t = self._tracks[tid]
            t.x, t.y = points[pi]
            t.hits += 1
            t.misses = 0
            unmatched_points.discard(pi)
            unmatched_tracks.discard(tid)
            matched.append(t)

        # Новые треки для несвязанных точек.
        for pi in unmatched_points:
            t = Track(self._next_id, points[pi][0], points[pi][1])
            self._tracks[self._next_id] = t
            self._next_id += 1
            matched.append(t)

        # Старение несвязанных треков.
        for tid in unmatched_tracks:
            t = self._tracks[tid]
            t.misses += 1
            if t.misses > self._max_age:
                del self._tracks[tid]

        return matched
