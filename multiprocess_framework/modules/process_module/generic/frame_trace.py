# -*- coding: utf-8 -*-
"""frame_trace — пер-сегментная трассировка кадра через пайплайн (in-band).

Идея: ``item["trace"]`` — список спанов, который едет вместе с кадром через всю
цепочку (в метаданных сообщения, рядом с ссылкой на frame). Каждый узел/плагин
дописывает свой спан → на выходе цепочки читаем полную историю: сколько ушло на
ПЕРЕДАЧУ между процессами (transport) и на ОБРАБОТКУ в каждом плагине (process).

Контракт спана (plain dict — Dict at Boundary, pickle-safe)::

    {"kind": "transport", "from": "camera_0", "to": "detector", "ms": 1.8}
    {"kind": "process",   "node": "detector", "plugin": "hsv_mask", "ms": 0.6}
    {"kind": "merge",     "node": "stitcher", "branches": 3, "chosen": "region_0", "ms": 0}

Спан ``merge`` добавляется fan-in плагином (stitcher) после наследования trace
ветви-победителя (critical path = ветвь с max суммой ``ms``). Поля:

- ``branches`` — число входных ветвей (фактическое, может быть < ожидаемого
  при timeout).
- ``chosen`` — имя ветви-победителя (``region_name`` из метаданных item).
- ``ms`` — время ожидания полной коллекции в fan-in буфере. ``0`` если не
  измеримо (InspectorManager не передаёт эту метрику).

Дополнительно merged-кадр может нести ``item["trace_branches"]`` — лёгкую
сводку по всем ветвям::

    [{"branch": "region_0", "total_ms": 12.5, "spans": 4},
     {"branch": "region_1", "total_ms":  8.3, "spans": 4},
     {"branch": "default",  "total_ms": 10.1, "spans": 4}]

``trace_branches`` содержит только агрегаты (без полных спанов), размер
O(число ветвей) — не растёт от глубины trace.

Служебные поля ``_t_send`` / ``_from`` ставятся перед отправкой и снимаются на
приёме (по ним считается transport-спан); они НЕ накапливаются.

Время — ``time.time()`` (wall): кросс-процессно сравнимо на одной машине
(monotonic у каждого процесса свой и несравним). Длительность ОБРАБОТКИ меряем
``perf_counter`` (high-res), длительность ПЕРЕДАЧИ — разностью wall-часов.

Гейтится ``INSPECTOR_FRAME_TRACE=1`` — в проде по умолчанию OFF: stamp/record
становятся no-op (один bool-чек на item на участок, нулевой overhead). Дочерние
процессы (spawn) наследуют env, если флаг выставлен до запуска ``run.py``.
"""

from __future__ import annotations

import functools
import os
import time

# Читается один раз при импорте. Дочерние spawn-процессы наследуют env.
# Тесты могут переопределить: frame_trace._ENABLED = True.
_ENABLED = os.environ.get("INSPECTOR_FRAME_TRACE", "").strip().lower() in ("1", "true", "yes")


def enabled() -> bool:
    """Включена ли трассировка кадра (по env INSPECTOR_FRAME_TRACE)."""
    return _ENABLED


def stamp_send(item: dict, node: str) -> None:
    """Перед отправкой item из узла: запомнить отправителя и wall-время.

    На приёме следующий узел вызовет ``record_transport`` и по ним вычислит
    время передачи. No-op если трассировка выключена.
    """
    if not _ENABLED or not isinstance(item, dict):
        return
    item["_t_send"] = time.time()
    item["_from"] = node


def record_transport(item: dict, node: str) -> None:
    """На приёме: добавить transport-спан ``from -> node`` по _t_send/_from.

    Снимает служебные поля (чтобы не уехали на следующий участок). No-op если
    трассировка выключена или item пришёл без отметки отправки.
    """
    if not _ENABLED or not isinstance(item, dict):
        return
    t_send = item.pop("_t_send", None)
    frm = item.pop("_from", None)
    if not isinstance(t_send, (int, float)):
        return
    item.setdefault("trace", []).append(
        {
            "kind": "transport",
            "from": frm,
            "to": node,
            "ms": round((time.time() - t_send) * 1000.0, 3),
        }
    )


def record_process(item: dict, node: str, plugin: str, ms: float) -> None:
    """Добавить process-спан: обработка ``plugin`` в ``node`` заняла ``ms``."""
    if not _ENABLED or not isinstance(item, dict):
        return
    item.setdefault("trace", []).append({"kind": "process", "node": node, "plugin": plugin, "ms": round(ms, 3)})


def record_merge(
    item: dict,
    node: str,
    branches: int,
    chosen: str,
    ms: float | None = None,
) -> None:
    """Добавить merge-спан: fan-in (N→1) в ``node``, выбрана ветвь ``chosen``.

    Вызывается stitcher'ом (или аналогичным fan-in плагином) ПОСЛЕ наследования
    trace от ветви-победителя (critical path). Спан дописывается в конец
    наследованного trace.

    Args:
        item: merged-кадр (dict), уже содержащий наследованный trace.
        node: имя узла (trace_node) — обычно имя процесса stitcher'а.
        branches: число входных ветвей (фактическое).
        chosen: имя ветви-победителя (region_name).
        ms: время ожидания коллекции в fan-in буфере (мс). ``None`` / ``0``
            если не измеримо.
    """
    if not _ENABLED or not isinstance(item, dict):
        return
    span: dict = {
        "kind": "merge",
        "node": node,
        "branches": branches,
        "chosen": chosen,
    }
    if ms is not None:
        span["ms"] = round(ms, 3)
    else:
        span["ms"] = 0
    item.setdefault("trace", []).append(span)


def fork_trace(item: dict) -> dict:
    """Вернуть dict с независимой копией trace для одного fan-out-выхода.

    Предназначен для плагинов типа region_split (1→N fan-out): каждый
    выходной item должен нести независимый список спанов, чтобы декоратор
    ``traced`` мутировал только свой item, а не общий родительский list.

    Использование::

        out_item = {**item, "frame": crop, ..., **frame_trace.fork_trace(item)}

    При включённой трассировке возвращает ``{"trace": list(item.get("trace", []))}``.
    Без флага — пустой dict ``{}`` (нет аллокаций, нет overhead).

    Args:
        item: входной item (родительский кадр перед fan-out).

    Returns:
        dict с ключом ``"trace"`` при ``_ENABLED``, иначе ``{}``.
    """
    if not _ENABLED:
        return {}
    return {"trace": list(item.get("trace", []))}


def merge_trace(items: list[dict]) -> tuple[list, list, str]:
    """Выбрать critical-path ветвь и собрать сводку по всем ветвям (fan-in).

    Реализует семантику «Вариант A» из плана frame-trace-fanin.md:
    merged-кадр наследует trace ветви с максимальной суммой ``ms``
    (critical path — самый медленный путь, он же end-to-end латентность).
    Дополнительно возвращает лёгкую сводку ``trace_branches`` по всем ветвям.

    Использование в fan-in плагине::

        trace, branches, chosen = frame_trace.merge_trace(items)
        merged["trace"] = trace
        merged["trace_branches"] = branches
        frame_trace.record_merge(merged, node=node, branches=len(items), chosen=chosen, ms=0)

    Без флага возвращает ``([], [], "")`` — нулевой overhead, нет аллокаций.

    Args:
        items: коллекция входных item'ов (уже собранная fan-in буфером).
               Может быть пустой (вернёт ``([], [], "")``).

    Returns:
        Тройка ``(critical_path_trace, trace_branches, chosen_name)``:

        - ``critical_path_trace`` — копия trace ветви-победителя (list).
        - ``trace_branches`` — список dict'ов
          ``[{"branch": str, "total_ms": float, "spans": int}]``.
        - ``chosen_name`` — имя ветви-победителя (``region_name`` из метаданных
          или ``"branch_<idx>"`` если поля нет).

    Notes:
        - Edge case: пустой ``items`` → ``([], [], "")``.
        - Edge case: все trace пусты (флаг включён, но spans=0) → winner = items[0].
        - ``ms`` в спанах меряется ``time.time()`` (wall); critical-path по сумме
          корректен только на одной машине (monotonic у разных процессов несравним).
        - Clock skew между процессами на одном хосте пренебрежимо мал.
    """
    if not _ENABLED or not items:
        return [], [], ""

    # Вычислить суммарную длительность trace каждой ветви
    branch_stats: list[tuple[int, float, int, str]] = []  # (idx, total_ms, spans, name)
    for idx, it in enumerate(items):
        tr = it.get("trace", [])
        total_ms = sum(s.get("ms", 0) for s in tr)
        branch_name = it.get("region_name", f"branch_{idx}")
        branch_stats.append((idx, total_ms, len(tr), branch_name))

    # Выбрать ветвь-победителя: max суммы ms (critical path).
    # Edge case: все trace пусты (spans=0) → winner = items[0].
    winner_idx = max(branch_stats, key=lambda x: x[1])[0]
    winner = items[winner_idx]
    winner_name = winner.get("region_name", f"branch_{winner_idx}")

    # Наследовать trace (копию) от ветви-победителя
    critical_path_trace: list = list(winner.get("trace", []))

    # trace_branches — лёгкая сводка по ВСЕМ ветвям (агрегаты, без спанов)
    trace_branches: list = [
        {"branch": name, "total_ms": round(total_ms, 3), "spans": spans} for _, total_ms, spans, name in branch_stats
    ]

    return critical_path_trace, trace_branches, winner_name


def traced(fn):
    """Декоратор: измерить вызов плагинного ``process``/``produce`` и записать
    process-спан в КАЖДЫЙ выходной item.

    Универсален: меряет строго вокруг тела метода (start→end через perf_counter),
    делит длительность на размер батча → честное per-item время (а не общий батч
    на каждый item). Узел берёт из ``self._trace_node`` (ставит оркестратор),
    имя — из ``self.name``. No-op при выключенной трассировке (нулевой overhead,
    кроме одного bool-чека).

    Применяется автоматически в ``PluginOrchestrator.boot()`` ко всем забученным
    плагинам (C6 рычаг 2 — см. ``install_tracing``) — отдельно вешать не нужно.
    """

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if not _ENABLED:
            return fn(self, *args, **kwargs)
        t0 = time.perf_counter()
        result = fn(self, *args, **kwargs)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        out = result if isinstance(result, list) else ([] if result is None else [result])
        node = getattr(self, "_trace_node", "")
        name = getattr(self, "name", "?")
        per = dt_ms / len(out) if out else dt_ms
        for it in out:
            record_process(it, node, name, per)
        return result

    wrapper._traced = True  # type: ignore[attr-defined]
    return wrapper


def install_tracing(cls) -> None:
    """Обернуть ``process``/``produce`` класса плагина в ``traced`` (idempotent).

    C6 рычаг 2: раньше обёртка стояла в ``ProcessModulePlugin.__init_subclass__`` (база
    плагина импортировала ``generic.frame_trace`` на этапе ОБЪЯВЛЕНИЯ класса — жёсткая
    связь фундамент-плагина → inspection-домен). Теперь установку делает
    ``PluginOrchestrator.boot()`` (и sub-plugin-исполнители chain/worker_pool) на бутe —
    база плагина больше не знает про ``generic``.

    Fable MED-3: обход ``__mro__`` до ``ProcessModulePlugin`` — метод оборачивается на
    классе-ВЛАДЕЛЬЦЕ (том, что его определил в ``__dict__``), а не только на ``cls``.
    Наследник плагина, не переопределивший ``process()``, всё равно получает трассировку
    (обёрнут метод родителя). Дефолтные ``process``/``produce`` самого ``ProcessModulePlugin``
    НЕ оборачиваются (граница обхода). Guard ``_traced`` — idempotency при повторном бутe.
    """
    # Lazy: plugins.base больше не импортирует generic (C6 рычаг 2), цикла нет.
    from ..plugins.base import ProcessModulePlugin

    for _method in ("process", "produce"):
        for owner in cls.__mro__:
            if owner is ProcessModulePlugin or owner is object:
                break  # дошли до базы — метод не переопределён пользователем, дефолт не трогаем
            fn = owner.__dict__.get(_method)
            if fn is None:
                continue
            if callable(fn) and not getattr(fn, "_traced", False):
                setattr(owner, _method, traced(fn))
            break  # нашли класс-владелец — дальше по mro не идём
