"""Конверт свежести: метка писателя и классификатор читателя; сюда — судить, жив ли писатель значения

freshness.py — метка писателя на корне записи и классификатор читателя.

Значение, пришедшее через границу процесса, должно нести ответ на вопрос «писатель
ещё публикует?». Писатель кладёт метку ``_fresh`` в ``data`` последней и шлёт одно
слияние на корень процесса: ``processes.<name>`` -> ``{"state": {...}, "workers":
{...}, "_fresh": S}``. Читатель получает поддерево процесса и ключ (имя листа или
путь через точку от поддерева, ``"state.fps"``) и получает один из четырёх ответов.

Purpose:
    Единственный источник правды о форме метки и пороге «2 такта»: писатель
    (``stamp``) и читатели (``classify``, ``read_value``) импортируют отсюда;
    зеркала в ``backend_ctl`` нет. Чистые функции над ``dict``, только stdlib;
    ``now`` передаёт читатель (его часы — ``time.time``, сравнимые между процессами).

Public API:
    - FRESH_KEY  — имя ключа метки на корне записи (``"_fresh"``)
    - stamp      — собрать метку из четырёх полей
    - classify   — класс поддерева: no_data / fresh / stale / writer_gone
    - read_value — {"class", "value", "age_s"} для листа поддерева

Stability: lite

Decisions: ADR-SS-025 (метка писателя против ``TreeStore.revision``, ``Delta.timestamp``
    и времени приёма; смысл метки — «писатель публиковал такт N в момент T», а не
    «лист обновлён в T»).
"""

from __future__ import annotations

import math
from typing import Any, Literal

FRESH_KEY = "_fresh"

type FreshClass = Literal["no_data", "fresh", "stale", "writer_gone"]

_MARK_KEYS = ("seq", "src_ts", "incarnation", "tick_sec")
_NO_DATA: dict[str, Any] = {"class": "no_data", "value": None, "age_s": None}


def _is_finite_number(x: Any) -> bool:
    """int/float без bool, nan и inf."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def stamp(seq: int, src_ts: float, incarnation: str, tick_sec: float) -> dict[str, Any]:
    """Собрать метку свежести. Значения кладутся как переданы, без проверки и округления.

    Pre:
        ``src_ts`` — ``time.time()`` писателя (``time.monotonic`` между процессами
        несравним: у каждого свой ноль); ``tick_sec`` — период публикации писателя, с.
    Post:
        Возвращает ``dict`` ровно с четырьмя ключами ``seq``, ``src_ts``,
        ``incarnation``, ``tick_sec``. Не бросает.
        ``stamp(3, 100.0, "a", 5.0) == {"seq": 3, "src_ts": 100.0,
        "incarnation": "a", "tick_sec": 5.0}``.
        Писатель кладёт метку в ``data`` последней (порядок ключей ``data`` — порядок
        дельт); это делает публикатор, не эта функция.
    """
    return {"seq": seq, "src_ts": src_ts, "incarnation": incarnation, "tick_sec": tick_sec}


def classify(subtree: Any, now: Any, alive_incarnation: str | None) -> FreshClass:
    """Класс свежести поддерева процесса по метке ``subtree["_fresh"]``.

    Pre:
        ``subtree`` — поддерево ``processes.<name>`` (``dict``) с меткой ``_fresh``;
        ``now`` — ``time.time()`` читателя; ``alive_incarnation`` — воплощение писателя,
        которое читатель считает живым, или ``None`` («не задано», проверка пропускается).
    Post:
        Всюду определена, исключений не бросает (исключение в потоке приёма уронило бы
        весь снимок). Правила строго по порядку:
        (1) ``subtree`` не ``dict`` -> ``no_data``;
        (2) ``subtree.get("_fresh")`` не ``dict`` -> ``no_data``;
        (3) в метке нет любого из ``seq``, ``src_ts``, ``incarnation``, ``tick_sec`` -> ``no_data``;
        (4) ``src_ts``, ``tick_sec`` или ``now`` не число (``int``/``float``), либо ``bool``,
            ``nan``, ``inf``, либо ``tick_sec <= 0`` -> ``no_data``;
        (5) ``alive_incarnation is not None`` и ``!= incarnation`` -> ``writer_gone``
            (раньше ``stale``: ответ «ушёл» полезнее «давно не писал»);
        (6) ``now - src_ts > 2 * tick_sec`` -> ``stale`` (строго ``>``: ровно два такта —
            ещё ``fresh``);
        (7) иначе ``fresh`` (отрицательный возраст — часы писателя впереди — тоже ``fresh``).
    """
    if not isinstance(subtree, dict):
        return "no_data"
    mark = subtree.get(FRESH_KEY)
    if not isinstance(mark, dict):
        return "no_data"
    if any(k not in mark for k in _MARK_KEYS):
        return "no_data"
    src_ts, tick_sec, incarnation = mark["src_ts"], mark["tick_sec"], mark["incarnation"]
    if not (_is_finite_number(src_ts) and _is_finite_number(tick_sec) and _is_finite_number(now)):
        return "no_data"
    if tick_sec <= 0:
        return "no_data"
    if alive_incarnation is not None and alive_incarnation != incarnation:
        return "writer_gone"
    if now - src_ts > 2 * tick_sec:
        return "stale"
    return "fresh"


def read_value(subtree: Any, key: Any, now: Any, alive_incarnation: str | None) -> dict[str, Any]:
    """Значение листа поддерева процесса вместе с классом свежести и возрастом.

    Pre:
        ``subtree`` — поддерево ``processes.<name>`` с меткой ``_fresh`` на корне;
        ``key`` — имя листа или путь через точку от ``subtree`` (``"state.fps"``,
        ``"workers.w.effective_hz"``); ``now``, ``alive_incarnation`` — как у ``classify``.
    Post:
        Всюду определена, исключений не бросает. Возвращает ``dict`` с ключами
        ``class``, ``value``, ``age_s``:
        (1) ``classify(...) == "no_data"`` -> ``{"class": "no_data", "value": None, "age_s": None}``;
        (2) ``key`` не строка, нет сегмента пути, посреди пути не ``dict``, значение
            ``None`` -> тот же ответ;
        (3) иначе ``{"class": <класс>, "value": <значение>, "age_s": now - src_ts}``
            без округления; ``age_s`` одна формула для ``fresh``, ``stale``,
            ``writer_gone``, отрицательный возраст отдаётся как есть.
        Ноль — значение (``fps: 0`` -> ``fresh``, ``0``), ``None`` — отсутствие. Четыре
        ответа — разные пары (класс, значение): нет данных (``no_data``, ``None``);
        ноль (``fresh``, ``0``); устарело (``stale``, последнее значение); писатель
        ушёл (``writer_gone``, последнее значение).
    """
    cls = classify(subtree, now, alive_incarnation)
    if cls == "no_data" or not isinstance(key, str):
        return dict(_NO_DATA)
    value: Any = subtree
    for segment in key.split("."):
        if not isinstance(value, dict) or segment not in value:
            return dict(_NO_DATA)
        value = value[segment]
    if value is None:
        return dict(_NO_DATA)
    return {"class": cls, "value": value, "age_s": now - subtree[FRESH_KEY]["src_ts"]}
