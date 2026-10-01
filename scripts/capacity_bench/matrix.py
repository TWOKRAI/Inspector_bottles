"""Матрица стенда: (высота, fps, секунды) по профилю."""

from __future__ import annotations

_SECS = 30


def cases(profile: str) -> list[tuple[int, int, int]]:
    if profile == "quick":
        return [(480, 25, _SECS), (1080, 100, _SECS)]
    if profile == "full":
        return [(h, fps, _SECS) for h in (480, 1080) for fps in (25, 60, 100)]
    raise ValueError(f"неизвестный профиль {profile!r}: quick | full")
