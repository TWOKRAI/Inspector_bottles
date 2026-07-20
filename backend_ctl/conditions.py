# -*- coding: utf-8 -*-
"""conditions.py — await_condition: серверное ожидание вместо поллинга (B.2).

Один вызов «сделал → дождался → проверил» вместо 3–10 round-trip'ов агента.
Аналог ``kubectl wait`` / Playwright ``waitFor`` / своего же ``qt_wait_for``.

Три вида условий (``kind``):

  * ``state_path`` — ``spec={"path", "value"}``: точное значение пути в локальном
    telemetry read-model (проекция ``state.changed``-дельт);
  * ``event_matches`` — ``spec={"plane", "pattern"}``: в плоскости B.1 появилось
    событие, чей command или path матчится glob-паттерном (классификация — тот же
    :func:`~backend_ctl.events._classify`, что у колец: нет второго классификатора);
  * ``metric_threshold`` — ``spec={"path", "op", "value"}``: числовая метрика пути
    пересекла порог (``>``/``>=``/``<``/``<=``/``==``/``!=``).

Механика без поллинга: временный подписчик событийного канала + ``threading.Event``.
Порядок race-free: подписаться → проверить начальное состояние (read-model) →
ждать; событие между проверкой и подпиской потеряться не может. Колбэк исполняется
в reader-потоке и обязан быть лёгким (только сравнение + set()).

Ожидание блокирует ВЫЗЫВАЮЩИЙ поток driver'а (для MCP — поток tools/call);
жёсткий cap таймаута ставит MCP-слой (``MAX_EVENTS_TIMEOUT``). Таймаут возвращает
ДИАГНОЗ (что ждали, что видели последним, сколько событий пришло), не пустоту:
«ждал и не дождался» и «не туда смотрел» должны различаться с первого взгляда.

Дельты с маркером удаления узла (:data:`~backend_ctl.events.MISSING_MARKER`)
в сравнение значений/порогов не участвуют (удаление — не значение).
"""

from __future__ import annotations

import fnmatch
import operator
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .events import (
    ALL_PLANE,
    MISSING_MARKER,
    OBSERVABILITY_RECORD_COMMAND,
    PLANES,
    _classify,
    iter_state_deltas,
)

# Виды условий (валидация входа — обучающая ошибка, не таймаут).
KINDS: tuple[str, ...] = ("state_path", "event_matches", "metric_threshold")

_OPS: Dict[str, Callable[[Any, Any], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

#: Дефолт ожидания (сек); потолок для MCP ставит mcp_tools.MAX_EVENTS_TIMEOUT.
DEFAULT_AWAIT_TIMEOUT: float = 10.0

# Какие плоскости вообще возможны для данного wire-command — пре-фильтр предиката
# event_matches (зеркало веток _classify; команды вне карты попадают только в other).
_PLANE_CANDIDATES: Dict[Any, tuple[str, ...]] = {
    "state.changed": ("state", "telemetry"),
    "log.record": ("logs",),
    "ui.event": ("ui",),
    OBSERVABILITY_RECORD_COMMAND: ("logs", "errors", "stats", "other"),
}


def _error(text: str) -> Dict[str, Any]:
    return {"success": False, "error": text}


def _match_targets(view: Dict[str, Any]) -> List[str]:
    """Строки, по которым матчится glob event_matches: command + path'ы события."""
    targets: List[str] = []
    cmd = view.get("command")
    if isinstance(cmd, str):
        targets.append(cmd)
    data = view.get("data")
    if isinstance(data, dict):
        path = data.get("path")
        if isinstance(path, str):
            targets.append(path)
    targets.extend(delta["path"] for delta in iter_state_deltas(view))
    return targets


class _Waiter:
    """Состояние одного ожидания: предикат, диагностика, сигнал попадания.

    Колбэк (reader-поток) и вызывающий поток разделяют состояние под ``_lock``;
    первый сработавший источник (начальная проверка или событие) фиксирует
    ``matched`` — повторные срабатывания игнорируются.
    """

    def __init__(self, predicate: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]) -> None:
        self._predicate = predicate
        self._hit = threading.Event()
        self._lock = threading.Lock()
        self.matched: Optional[Dict[str, Any]] = None
        self.events_seen = 0
        self.last_seen: Optional[Dict[str, Any]] = None

    def offer(self, msg: Dict[str, Any]) -> None:
        """Колбэк событийного канала (reader-поток): лёгкая проверка + set()."""
        try:
            found = self._predicate(msg)
        except Exception:  # noqa: BLE001 — предикат не должен ронять reader
            return
        with self._lock:
            self.events_seen += 1
            if found is not None and self.matched is None:
                self.matched = found
                self._hit.set()

    def resolve_initial(self, found: Optional[Dict[str, Any]]) -> None:
        """Зачесть результат начальной проверки (read-model) как попадание."""
        if found is None:
            return
        with self._lock:
            if self.matched is None:
                self.matched = found
                self._hit.set()

    def note(self, observation: Dict[str, Any]) -> None:
        """Запомнить последнее релевантное наблюдение для таймаут-диагноза."""
        with self._lock:
            self.last_seen = observation

    def wait(self, timeout: float) -> bool:
        return self._hit.wait(timeout)


def await_condition(
    drv: Any,
    kind: str,
    spec: Optional[Dict[str, Any]],
    *,
    timeout: float = DEFAULT_AWAIT_TIMEOUT,
) -> Dict[str, Any]:
    """Дождаться условия на живом потоке событий driver'а (см. докстроку модуля).

    Returns:
        Успех: ``{"success": True, "kind", "matched": {...}, "elapsed_sec"}`` —
        ``matched`` несёт сработавшее значение/событие. Таймаут:
        ``{"success": False, "timed_out": True, "waited": spec, "elapsed_sec",
        "events_seen", "last_seen", "hint"?}`` — диагноз, не пустота. Невалидный
        вход → error-dict сразу (обучающий текст, без ожидания).
    """
    setup = setup_condition(drv, kind, spec)
    if isinstance(setup, dict):  # ошибка валидации kind/spec
        return setup
    waiter, initial_check = setup

    started = time.monotonic()
    # Порядок race-free: подписка ДО начальной проверки — событие в зазоре
    # не теряется (повторное срабатывание гасит _Waiter).
    listener = drv.subscribe(waiter.offer)
    try:
        waiter.resolve_initial(initial_check())
        waiter.wait(max(0.0, timeout))
    finally:
        drv.unsubscribe(listener)

    elapsed = round(time.monotonic() - started, 3)
    with waiter._lock:
        matched, events_seen, last_seen = waiter.matched, waiter.events_seen, waiter.last_seen
    if matched is not None:
        return {"success": True, "kind": kind, "matched": matched, "elapsed_sec": elapsed}

    out: Dict[str, Any] = {
        "success": False,
        "timed_out": True,
        "kind": kind,
        "waited": dict(spec),
        "elapsed_sec": elapsed,
        "events_seen": events_seen,
        "last_seen": last_seen,
    }
    # Подсказка — по отсутствию РЕЛЕВАНТНЫХ наблюдений (note), не любых событий:
    # фоновый трафик (log.record/ui.event при активном debug_session) не должен
    # гасить диагноз «нужные дельты/события так и не пришли».
    if last_seen is None:
        out["hint"] = (
            "за время ожидания не было ни одного релевантного наблюдения (дельты нужного "
            "пути / события плоскости) — активна ли подписка (watch_like_gui / "
            "state_subscribe на нужный паттерн)?"
        )
    return out


# ---- Настройка предикатов по kind: (waiter, initial_check) либо error-dict ----


def setup_condition(drv: Any, kind: str, spec: Optional[Dict[str, Any]], *, scan_history: bool = False):
    """Собрать ``(waiter, initial_check)`` по ``(kind, spec)`` либо вернуть error-dict.

    Публичная точка переиспользования предикатов: живой :func:`await_condition`
    и offline-реплей (``recorder.replay_await_condition``) строят один и тот же
    предикат из одних настройщиков — без второго парсера условий. Валидация
    ``kind``/``spec`` — обучающая ошибка (error-dict), не таймаут.

    Args:
        scan_history: искать совпадение ещё и в УЖЕ НАКОПЛЕННЫХ кольцах событий, а не
            только среди новых (Task 4.2). Ставит ТОЛЬКО replay-путь: над записью
            «будущего» нет, а при дефолтном ``position='end'`` playhead уже в конце —
            ``event_matches`` не мог совпасть в принципе и всегда отдавал
            ``end_of_recording``. Живой await семантику не меняет: там «ждём новое» —
            это ровно то, что просили, а прошлое читается через ``events_page``.
    """
    if kind not in KINDS:
        return _error(f"неизвестный kind {kind!r}: ожидаю один из {list(KINDS)}")
    if not isinstance(spec, dict):
        return _error(f"spec должен быть dict, получено {type(spec).__name__}")
    if kind == "state_path":
        return _setup_state_path(drv, spec)
    if kind == "metric_threshold":
        return _setup_metric_threshold(drv, spec)
    return _setup_event_matches(spec, drv=drv, scan_history=scan_history)


def _setup_state_path(drv: Any, spec: Dict[str, Any]):
    path, value = spec.get("path"), spec.get("value")
    if not isinstance(path, str) or not path:
        return _error("state_path требует spec.path (строка-путь state-дерева)")

    def predicate(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for delta in iter_state_deltas(msg):
            if delta.get("path") != path:
                continue
            new_value = delta.get("new_value")
            if new_value == MISSING_MARKER:
                # Удаление узла — не значение, но наблюдение релевантное: диагноз
                # «видел удаление» информативнее пустого last_seen.
                waiter.note({"path": path, "deleted": True, "source": "delta"})
                continue
            waiter.note({"path": path, "value": new_value, "source": "delta"})
            if new_value == value:
                return {"path": path, "value": new_value, "source": "delta"}
        return None

    def initial_check() -> Optional[Dict[str, Any]]:
        exists, current = _read_model_entry(drv, path)
        if not exists:
            return None  # отсутствие узла ≠ значение None — не матчим
        waiter.note({"path": path, "value": current, "source": "read-model"})
        return {"path": path, "value": current, "source": "read-model"} if current == value else None

    waiter = _Waiter(predicate)
    return waiter, initial_check


def _setup_metric_threshold(drv: Any, spec: Dict[str, Any]):
    path, op_name, value = spec.get("path"), spec.get("op"), spec.get("value")
    if not isinstance(path, str) or not path:
        return _error("metric_threshold требует spec.path (полный путь метрики)")
    op = _OPS.get(op_name or "")
    if op is None:
        return _error(f"неизвестный op {op_name!r}: ожидаю один из {sorted(_OPS)}")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return _error("metric_threshold требует числовой spec.value (порог)")

    def check(candidate: Any, source: str) -> Optional[Dict[str, Any]]:
        # note ДО численного гейта: нечисловое значение по нужному пути — важнейший
        # диагноз («ты смотришь не на метрику»), его нельзя терять из last_seen.
        waiter.note({"path": path, "value": candidate, "source": source})
        if not isinstance(candidate, (int, float)) or isinstance(candidate, bool):
            return None  # не-числа порог не пересекают
        if op(candidate, value):
            return {"path": path, "value": candidate, "op": op_name, "threshold": value, "source": source}
        return None

    def predicate(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for delta in iter_state_deltas(msg):
            if delta.get("path") != path:
                continue
            new_value = delta.get("new_value")
            if new_value == MISSING_MARKER:
                waiter.note({"path": path, "deleted": True, "source": "delta"})
                continue
            found = check(new_value, "delta")
            if found is not None:
                return found
        return None

    def initial_check() -> Optional[Dict[str, Any]]:
        exists, current = _read_model_entry(drv, path)
        return check(current, "read-model") if exists else None

    waiter = _Waiter(predicate)
    return waiter, initial_check


def _setup_event_matches(spec: Dict[str, Any], *, drv: Any = None, scan_history: bool = False):
    plane, pattern = spec.get("plane"), spec.get("pattern")
    if plane not in (ALL_PLANE, *PLANES):
        return _error(f"event_matches требует spec.plane из {[ALL_PLANE, *PLANES]}, получено {plane!r}")
    if not isinstance(pattern, str) or not pattern:
        return _error("event_matches требует spec.pattern (glob по command/path события)")

    def predicate(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Дешёвый пре-фильтр по command: не гонять полную классификацию (аллокации
        # на каждую дельту) для сообщений, которые в искомую плоскость не попадают, —
        # предикат живёт в reader-потоке и обязан быть лёгким.
        if plane != ALL_PLANE and plane not in _PLANE_CANDIDATES.get(msg.get("command"), ("other",)):
            return None
        # Тот же классификатор, что у колец B.1 — плоскость события едина всюду.
        views = [(ALL_PLANE, msg)] if plane == ALL_PLANE else _classify(msg)
        for view_plane, view in views:
            if view_plane != plane:
                continue
            targets = _match_targets(view)
            if targets:
                waiter.note({"plane": plane, "last_command": view.get("command"), "targets": targets[:3]})
            for target in targets:
                if fnmatch.fnmatchcase(target, pattern):
                    return {"plane": plane, "matched_target": target, "event": view}
        return None

    def initial_check() -> Optional[Dict[str, Any]]:
        # Live: прошлые события — через events_page; ждём только новые.
        if not scan_history or drv is None:
            return None
        # Replay (Task 4.2): «новых» событий не будет — при position='end' лента уже
        # прокручена. Ищем совпадение в уже наполненных кольцах ТЕМ ЖЕ предикатом:
        # второго парсера условий не появляется.
        return _scan_rings(drv, plane, predicate)

    waiter = _Waiter(predicate)
    return waiter, initial_check


def _scan_rings(drv: Any, plane: str, predicate: Any) -> Optional[Dict[str, Any]]:
    """Прогнать предикат по уже накопленным кольцам hub'а (для replay-инициализации).

    Читает недеструктивно и СВОИМ курсором с начала (``cursor=None``), страницами —
    чужие читатели плоскости не затрагиваются. Первое совпадение возвращается сразу.
    Kind ``event_matches`` работает над оригинальными сообщениями arrival-кольца,
    поэтому сканируем ``ALL_PLANE``: классификацию по плоскостям делает сам предикат.
    """
    cursor: Any = None
    while True:
        try:
            page = drv.events_page(ALL_PLANE, cursor=cursor, limit=500)
        except Exception:  # noqa: BLE001 — недоступные кольца не должны ронять await
            return None
        if not page.get("success", True):
            return None
        items = page.get("items") or []
        for item in items:
            event = item.get("event")
            if isinstance(event, dict):
                hit = predicate(event)
                if hit is not None:
                    return hit
        next_cursor = page.get("next_cursor")
        if not items or next_cursor == cursor:
            return None  # догнали хвост — совпадения в записи нет
        cursor = next_cursor


def _read_model_entry(drv: Any, path: str) -> tuple[bool, Any]:
    """(есть ли узел, значение) пути из telemetry read-model driver'а.

    Существование отдельно от значения: узел со значением ``None`` и отсутствие
    узла — разные состояния, «ждать value=None» не должно срабатывать на пустоте.
    """
    with drv._telemetry_lock:
        snap = drv._telemetry_model.snapshot(path)
    return (True, snap[path]) if path in snap else (False, None)


__all__ = ["await_condition", "setup_condition", "KINDS", "DEFAULT_AWAIT_TIMEOUT"]
