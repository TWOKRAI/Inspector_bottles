# multiprocess_prototype_v3/frontend/coordinators/recipe_slot.py
"""Pure helpers for recipe slot index UI (shared by register and app recipe panels)."""

from __future__ import annotations


def parse_clamped_recipe_slot_text(
    text: str,
    *,
    min_index: int,
    max_index: int,
    fallback_on_invalid: int,
) -> int:
    """
    Parse slot line-edit text into an int clamped to [min_index, max_index].

    On empty or non-numeric input, returns fallback_on_invalid (typically schema min).
    """
    try:
        v = int(text.strip())
    except (TypeError, ValueError):
        v = fallback_on_invalid
    return max(min_index, min(max_index, v))
