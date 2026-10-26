"""LineFilterPlugin — фильтр виртуальной линии (virtual tripwire / line-crossing).

Вход: detections/points со списком координат объектов. На каждый кадр:
  трекинг центроидов → знаковое расстояние до линии → режим (enter_zone/cross_line)
  с temporal confirmation, гистерезисом и дедупом → накопление уникальных объектов.

Выход (НЕ трогает кадр): один item с data_type="overlay" (для Join+overlay_draw),
несущий overlay (семантика линии + отмеченные точки), filtered и counted_total.
seq_id наследуется от входа — для корреляции кадр↔overlay в JoinInspectorManager.

Stateful (трекер/накопитель) → thread_safe=False.
"""

from __future__ import annotations

import math

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    Port,
    register_plugin,
)

from .geometry import signed_distance
from .registers import LineFilterRegisters
from .tracker import CentroidTracker


@register_plugin("line_filter", category="filter", description="Фильтр виртуальной линии (вход в зону / пересечение)")
class LineFilterPlugin(ProcessModulePlugin):
    """detections → фильтр виртуальной линии → overlay + filtered."""

    name = "line_filter"
    category = "filter"
    thread_safe = False  # stateful: трекер + накопитель

    inputs = [
        Port(name="detections", dtype="list[dict]", shape="N", description="Детекции с center [x,y] (или points)"),
    ]
    outputs = [
        Port(name="overlay", dtype="dict", shape="-", description="Draw-params (линия + отмеченные точки)"),
        Port(name="filtered", dtype="list[dict]", shape="N", description="Сработавшие объекты"),
    ]

    register_class = LineFilterRegisters

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: LineFilterRegisters = self._init_register(ctx)
        self._tracker = CentroidTracker(
            max_match_distance=self._reg.max_match_distance,
            max_age=self._reg.max_age,
        )
        self._frame = 0
        # zone_edge: latch занятости зоны (rising-edge) + счётчик пустых кадров для пере-взвода.
        # Защёлка стартует закрытой (решение владельца О1): если при старте/рестарте плагина зона
        # занята, первый кадр не засчитывается — триггер взводится только после rearm_frames
        # пустых кадров подряд. Диск, вошедший за время рестарта, теряется (дубль хуже потери).
        self._zone_occupied = True
        self._empty_streak = 0
        # zone_edge: где и когда плагин последний раз видел объект в зоне — (номер кадра, позиция).
        # По нему повторное появление после пустых кадров опознаётся как тот же объект.
        self._last_seen: tuple[int, tuple[float, float]] | None = None
        # Недавно зачтённые позиции для дедупа: list[(frame_idx, (x, y))].
        self._recent: list[tuple[int, tuple[float, float]]] = []
        # Накопленные события (emit_mode=accumulated): list[dict].
        self._accumulated: list[dict] = []
        self._counted_total = 0
        ctx.log_info(
            f"LineFilterPlugin: mode={self._reg.mode}, center=({self._reg.center_x},{self._reg.center_y}), "
            f"angle={self._reg.angle}°, zone={self._reg.zone_width}px, dedup={self._reg.dedup_radius}px"
        )

    # --- Извлечение точек (толерантно к формату входа) ---

    @staticmethod
    def _extract_points(item: dict) -> list[tuple[float, float]]:
        pts: list[tuple[float, float]] = []
        dets = item.get("detections")
        if isinstance(dets, list):
            for d in dets:
                if isinstance(d, dict) and "center" in d:
                    c = d["center"]
                    if len(c) >= 2:
                        pts.append((float(c[0]), float(c[1])))
        raw = item.get("points")
        if isinstance(raw, list):
            for p in raw:
                if len(p) >= 2:
                    pts.append((float(p[0]), float(p[1])))
        return pts

    # --- Дедуп: точка считается тем же объектом, если рядом недавно зачтённая ---

    def _is_duplicate(self, pos: tuple[float, float]) -> bool:
        r = self._reg.dedup_radius
        for _f, (x, y) in self._recent:
            if math.hypot(pos[0] - x, pos[1] - y) <= r:
                return True
        return False

    def _record(self, track, direction: str | None) -> dict:
        self._counted_total += 1
        self._recent.append((self._frame, track.pos))
        event = {
            "id": track.id,
            "xy": [round(track.x, 1), round(track.y, 1)],
            "frame": self._frame,
        }
        if direction:
            event["direction"] = direction
        self._accumulated.append(event)
        return event

    # --- Логика фильтра на одном кадре ---

    def _record_pos(self, pos: tuple[float, float]) -> dict:
        """Зачесть событие по позиции (zone_edge — без Track-объекта)."""
        self._counted_total += 1
        self._recent.append((self._frame, pos))
        event = {
            "id": self._counted_total,
            "xy": [round(pos[0], 1), round(pos[1], 1)],
            "frame": self._frame,
        }
        self._accumulated.append(event)
        return event

    def _is_same_object(self, pos: tuple[float, float], prev: tuple[int, tuple[float, float]]) -> bool:
        """zone_edge: точка — повторное появление того же объекта, что видели в зоне в ``prev``?

        Та же ассоциация, что у трекера в других режимах: расстояние ≤ ``max_match_distance``
        и не больше ``max_age`` кадров без точки в зоне между ``prev`` и текущим кадром.
        """
        last_frame, (lx, ly) = prev
        r = self._reg
        gap = self._frame - last_frame - 1  # кадров без точки в зоне между прежним и текущим
        return gap <= r.max_age and math.hypot(pos[0] - lx, pos[1] - ly) <= r.max_match_distance

    def _apply_zone_edge(
        self, points: list[tuple[float, float]], center: tuple[float, float], half: float
    ) -> list[dict]:
        """Rising-edge по занятости зоны — одно событие на один проход диска.

        Триггер на переходе «зона пуста → есть круг». Пере-взвод после ``rearm_frames``
        пустых кадров (гасит мерцание детекции). Ассоциацию центров между соседними кадрами
        не требует → стабильно на любой скорости ленты, лишь бы круг попал в зону хотя бы
        1 кадр (``zone_width`` ≥ смещения за кадр).

        Память последнего места (``_last_seen``): если детекция пропала внутри зоны дольше
        ``rearm_frames`` и защёлка снялась, то точка, снова появившаяся не дальше
        ``max_match_distance`` от места пропажи и не позднее чем через ``max_age`` пустых кадров,
        — тот же диск, события нет. Защёлка стартует закрытой (О1): занятая зона при старте
        не засчитывается.
        Допущение: в зоне один объект за раз (однополосный конвейер); несколько точек рядом
        с местом пропажи дают одно «тот же объект» на все.
        """
        r = self._reg
        in_zone = [(p, abs(signed_distance(p, center, r.angle))) for p in points]
        in_zone = [(p, sd) for p, sd in in_zone if sd <= half]
        in_zone.sort(key=lambda x: x[1])  # ближайший к линии первым
        passed: list[dict] = []

        if in_zone:
            self._empty_streak = 0
            # Сравнение — с ПРЕЖНИМ _last_seen: запись этого кадра идёт ниже.
            prev = self._last_seen
            self._last_seen = (self._frame, in_zone[0][0])
            if not self._zone_occupied:  # rising edge → один триггер до освобождения зоны
                self._zone_occupied = True
                for p, _sd in in_zone:
                    if prev is not None and self._is_same_object(p, prev):
                        gap = self._frame - prev[0] - 1
                        dist = math.hypot(p[0] - prev[1][0], p[1] - prev[1][1])
                        self._ctx.log_info(
                            f"LineFilterPlugin: zone_edge — тот же объект, события нет: "
                            f"({p[0]:.1f},{p[1]:.1f}), {dist:.1f}px от места пропажи, "
                            f"пропуск {gap} кадр."
                        )
                    else:
                        passed.append(self._record_pos(p))
        else:
            self._empty_streak += 1
            if self._empty_streak >= max(1, r.rearm_frames):
                self._zone_occupied = False
        return passed

    def _apply(self, points: list[tuple[float, float]]) -> list[dict]:
        r = self._reg
        center = (float(r.center_x), float(r.center_y))
        half = r.zone_width / 2.0
        passed: list[dict] = []

        if r.mode == "zone_edge":
            return self._apply_zone_edge(points, center, half)
        # Переключение режима на лету: вернувшись в zone_edge при диске в зоне, плагин ведёт себя
        # как при старте (О1) — защёлка закрыта, счёт пустых кадров с нуля, занятая зона не засчитывается.
        self._zone_occupied = True
        self._empty_streak = 0

        for t in self._tracker.update(points):
            sd = signed_distance(t.pos, center, r.angle)
            confirmed = t.hits >= r.min_hits

            if r.mode == "enter_zone":
                in_zone = abs(sd) <= half
                armed = t.meta.get("armed", True)
                if confirmed and in_zone and armed:
                    if not self._is_duplicate(t.pos):
                        passed.append(self._record(t, None))
                    t.meta["armed"] = False
                elif abs(sd) > half + r.hysteresis_margin:
                    t.meta["armed"] = True  # вышел из зоны → можно зачесть снова
            else:  # cross_line
                sign = 1 if sd >= 0 else -1
                prev = t.meta.get("prev_sign")
                if confirmed and prev is not None and sign != prev:
                    if not self._is_duplicate(t.pos):
                        direction = "enter" if sign > 0 else "exit"
                        passed.append(self._record(t, direction))
                t.meta["prev_sign"] = sign

        return passed

    # --- Сборка overlay (семантика линии + точки; кадр развернёт overlay_draw) ---

    def _build_overlay(self, passed: list[dict]) -> dict:
        r = self._reg
        group = self.name
        points = [{"xy": ev["xy"], "type": "point", "group": group, "label": f"#{ev['id']}"} for ev in passed]
        return {
            "vlines": [
                {
                    "cx": r.center_x,
                    "cy": r.center_y,
                    "angle": r.angle,
                    "zone_width": r.zone_width,
                    "type": "line",
                    "group": group,
                }
            ],
            "points": points,
        }

    # --- Обработка ---

    def process(self, items: list[dict]) -> list[dict]:
        r = self._reg
        out: list[dict] = []
        for item in items:
            self._frame += 1
            # Прунинг недавних зачётов старше max_age кадров.
            cutoff = self._frame - r.max_age
            if self._recent and self._recent[0][0] < cutoff:
                self._recent = [(f, p) for f, p in self._recent if f >= cutoff]

            points = self._extract_points(item)
            passed = self._apply(points)
            overlay = self._build_overlay(passed)

            result: dict = {
                "data_type": "overlay",
                "overlay": overlay,
                "filtered": list(self._accumulated) if r.emit_mode == "accumulated" else passed,
                "counted_total": self._counted_total,
            }
            # Перенос корреляционных/мета-ключей (seq_id обязателен для Join).
            for k in ("seq_id", "camera_id", "frame_id", "timestamp"):
                if k in item:
                    result[k] = item[k]
            out.append(result)
        return out
