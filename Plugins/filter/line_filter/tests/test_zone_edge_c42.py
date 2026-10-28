"""Слепая приёмка C-42: `zone_edge` даёт одно событие на один проход диска.

Тесты написаны по строкам приёмки A1–A10 из `plans/word-layout/tasks/C-42.md`,
без чтения реализации. Только публичный путь: `configure` + `process(items)`;
выход — `counted_total` и `filtered`.

Геометрия: линия горизонтальна, зона `|y - 240| <= 125`; диск идёт по `y`
с шагом 6 px/кадр, `x = 320`. Пустой кадр — `None` в списке кадров.
"""

from unittest.mock import MagicMock

from Plugins.filter.line_filter.plugin import LineFilterPlugin

CFG = {
    "center_x": 320,
    "center_y": 240,
    "angle": 0,
    "zone_width": 250,
    "rearm_frames": 2,
    "max_match_distance": 60,
    "max_age": 30,
    "mode": "zone_edge",
}


def _make(**cfg):
    p = LineFilterPlugin()
    ctx = MagicMock()
    ctx.registers = None
    ctx.config = {**CFG, **cfg}
    p.configure(ctx)
    return p


def _run(frames):
    """Прогнать кадры; вернуть (плагин, выходы по кадрам, все события подряд).

    Элемент `frames`: `None` — пустой кадр, число — диск в `(320, y)`.
    """
    p = _make()
    outs = []
    events = []
    for n, y in enumerate(frames, start=1):
        dets = [] if y is None else [{"center": [320, y]}]
        out = p.process([{"detections": dets, "seq_id": n}])
        outs.append(out[0])
        events.extend(out[0]["filtered"])
    return p, outs, events


def _pass(y_from, y_to, skip=()):
    """Проход диска с шагом 6 px; кадры с y из `skip` — пустые."""
    return [None if y in skip else y for y in range(y_from, y_to + 1, 6)]


ARM = [None, None]  # взвод по О1: плагин видит пустую зону


def test_a1_loss_of_two_frames_inside_zone_one_event():
    """A1: проход y=103…373, детекции нет на y=235 и y=241 -> counted_total == 1."""
    p, outs, _ = _run(ARM + _pass(103, 373, skip={235, 241}))
    assert p._counted_total == 1
    assert outs[-1]["counted_total"] == 1


def test_a2_loss_of_five_frames_inside_zone_one_event():
    """A2: детекции нет на y=229…253 (5 кадров) -> counted_total == 1."""
    p, _, _ = _run(ARM + _pass(103, 373, skip={229, 235, 241, 247, 253}))
    assert p._counted_total == 1


def test_a3_loss_near_exit_edge_one_event():
    """A3: нет детекции на y=349 и y=355, на y=361 диск снова в зоне -> counted_total == 1."""
    p, _, _ = _run(ARM + _pass(103, 373, skip={349, 355}))
    assert p._counted_total == 1


def test_a4_two_passes_give_two_events_second_at_entry_edge():
    """A4: два прохода, между ними 3 пустых кадра -> counted_total == 2, у второго xy[1] в [115, 125]."""
    frames = ARM + _pass(103, 373) + [None] * 3 + _pass(115, 373)
    p, _, events = _run(frames)
    assert p._counted_total == 2
    assert len(events) == 2
    assert 115 <= events[1]["xy"][1] <= 125


def test_a5_new_disc_after_10_empty_frames_not_lost():
    """A5: первый диск пропал на y=241, 10 пустых кадров, второй входит с y=115 (126 px) -> 2."""
    frames = ARM + _pass(103, 241) + [None] * 10 + _pass(115, 373)
    p, _, _ = _run(frames)
    assert p._counted_total == 2


def test_a6_point_61px_away_after_2_empty_is_new_disc():
    """A6, половина 61 px: диск на y=241, 2 пустых, точка на y=302 -> counted_total == 2."""
    p, _, _ = _run(ARM + _pass(103, 241) + [None] * 2 + [302])
    assert p._counted_total == 2


def test_a6_point_60px_away_after_2_empty_is_same_disc():
    """A6, половина 60 px: диск на y=241, 2 пустых, точка на y=301 -> counted_total == 1 (граница включительна)."""
    p, _, _ = _run(ARM + _pass(103, 241) + [None] * 2 + [301])
    assert p._counted_total == 1


def test_a7_return_after_31_empty_frames_is_new_disc():
    """A7, половина 31 пустой: диск на y=241, 31 пустой кадр, точка на y=241 -> counted_total == 2."""
    p, _, _ = _run(ARM + _pass(103, 241) + [None] * 31 + [241])
    assert p._counted_total == 2


def test_a7_return_after_30_empty_frames_is_same_disc():
    """A7, половина 30 пустых: диск на y=241, 30 пустых, точка на y=241 -> 1 (граница max_age включительна)."""
    p, _, _ = _run(ARM + _pass(103, 241) + [None] * 30 + [241])
    assert p._counted_total == 1


def test_a8_start_with_occupied_zone_first_frame_not_counted():
    """A8: старт с занятой зоной (диск y=330…354), 2 пустых, новый диск на y=115 -> 1 событие xy == [320.0, 115.0]."""
    frames = [330, 336, 342, 348, 354] + [None, None] + [115]
    p, _, events = _run(frames)
    assert p._counted_total == 1
    assert len(events) == 1
    assert list(events[0]["xy"]) == [320.0, 115.0]


def test_a9_start_with_occupied_zone_and_loss_not_counted():
    """A9: старт с занятой зоной (y=200, 206, 212), 2 пустых, тот же диск на y=230 -> counted_total == 0."""
    frames = [200, 206, 212, None, None, 230]
    p, _, events = _run(frames)
    assert p._counted_total == 0
    assert events == []


def test_a10_filtered_empty_on_frames_without_event_and_counter_matches():
    """A10: на кадрах без события filtered пуст; counted_total в выходе == атрибуту плагина.

    Один проход y=103…373 после 2 пустых кадров: событие ровно одно, на входе
    в зону (кадр y=115 или y=121, индексы 4 или 5); до него счётчик 0, с него 1.
    """
    p = _make()
    frames = ARM + _pass(103, 373)
    nonempty = []
    for i, y in enumerate(frames):
        dets = [] if y is None else [{"center": [320, y]}]
        out = p.process([{"detections": dets, "seq_id": i + 1}])[0]
        assert out["counted_total"] == p._counted_total
        if out["filtered"]:
            nonempty.append(i)
    assert len(nonempty) == 1
    assert nonempty[0] in (4, 5)
    assert p._counted_total == 1
