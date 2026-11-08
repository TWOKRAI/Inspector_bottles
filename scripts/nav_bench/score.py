"""Разбор ответов агента и подсчёт попаданий. Чистые функции: без ввода-вывода и без запуска процессов.

Формат ответа агента — по одному JSON-объекту на вопрос::

    {"id": "Q1", "answer": "...", "locations": ["path/file.py:123"], "confidence": "sure"}

Оценка вопроса по адресам (``expected``):
  hit   — адреса агента закрывают эталон: ``require: "all"`` — каждую запись, ``"any"`` (по умолчанию) — хотя бы одну.
          Запись закрыта, если есть адрес с тем же posix-путём и строкой (или диапазоном строк ``a-b``), которая
          пересекает окно ``line ± tolerance`` (``tolerance`` записи, по умолчанию 3; у эталона ``line: null`` —
          достаточно пути). Учитываются только первые ``len(expected)+1`` адресов: остальные — лишние, и их наличие
          лишает hit (при ``sure`` ответ — ``false``, иначе ``miss``).
  false — уверенность ``sure`` и (адрес, не совпавший ни с одной записью, или лишние адреса сверх потолка), при этом
          нет чистого попадания: лишние адреса сверх потолка делают ответ ложным даже при закрытом эталоне;
  miss  — всё остальное: нет ответа, «malformed», ``sure`` без адресов, неуверенный промах, неполное совпадение.
  n/a   — у вопроса нет ``expected`` (только факты).

Оценка по фактам (``expected_facts``): каждый факт ``{"any_of": ["literal", "synonym"]}`` найден, если в поле
``answer`` ответа есть любая из строк целым словом (границы слова, без учёта регистра); ``facts_require`` —
``"all"`` (по умолчанию) или ``"any"`` по фактам. Факты считаются отдельно от адресов (``facts_hit``).

Уверенность: ``.strip().casefold()`` из ``sure|unsure|unknown``; любое другое значение (``high`` и т.п.) — ``unknown``.
"""

from __future__ import annotations

import json
import re
import statistics
from typing import Any

TOLERANCE_LINES = 3
CONFIDENCES = ("sure", "unsure", "unknown")
REQUIRES = ("all", "any")

# Пороги по умолчанию; набор вопросов и условие переопределяют любой ключ в своём "thresholds"
# (порядок: умолчания < условие < набор). Остальные ключи проверяются, только если заданы:
#   facts_hit_min — фактов на оцениваемых вопросах; calls_median_max / tokens_median_max — абсолютные пределы
#   (tokens — final_context_tokens); calls_ratio_max / tokens_ratio_max — доля от базовой записи ``baseline``.
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "hits_min": 8,  # попаданий по адресам на оцениваемых вопросах — худший из повторов
    "false_max": 1,  # ложных адресов на оцениваемых вопросах — худший из повторов
    "facts_hit_min": 0,  # 0 — не проверять
}

# Полосы вердикта: PASS — все пороги; FIX — главная метрика на 1-2 ниже порога; FAIL — ниже; UNMEASURED — порог
# задан, а метрики нет; TAINTED — нарушен доступ.
FIX_WIDTH = 2

# «путь:строка», допускает «путь:10-20», «путь:10:5», «путь:10,12» — первая строка, диапазон «a-b» целиком.
_LOCATION_RE = re.compile(r"^(?P<path>.+?):(?P<start>\d+)(?:[-–](?P<end>\d+))?(?:[:,]\d+)*(?:[-–]\d+)?$")


def _key(question_id: Any) -> str:
    """Ключ вопроса: «Q1», « q1 » и 1 не должны расходиться из-за регистра и пробелов."""
    return str(question_id).strip().casefold()


def normalize_path(path: str, prefixes: tuple[str, ...] = ()) -> str:
    """Posix-вид пути; срезает ``./`` и абсолютные префиксы корня репозитория."""
    posix = path.strip().strip("`'\"").replace("\\", "/")
    for prefix in prefixes:
        head = prefix.replace("\\", "/").rstrip("/") + "/"
        if posix.casefold().startswith(head.casefold()):
            posix = posix[len(head) :]
            break
    while posix.startswith("./"):
        posix = posix[2:]
    return posix


def parse_location_range(text: str, prefixes: tuple[str, ...] = ()) -> tuple[str, int | None, int | None]:
    """``"a/b.py:12-20"`` -> ``("a/b.py", 12, 20)``; ``"a/b.py:12"`` -> ``(.., 12, 12)``; без строки — ``None``."""
    raw = text.strip().strip("`'\"")
    found = _LOCATION_RE.match(raw)
    if found is None:
        return normalize_path(raw, prefixes), None, None
    start = int(found.group("start"))
    end = int(found.group("end")) if found.group("end") else start
    return normalize_path(found.group("path"), prefixes), min(start, end), max(start, end)


def parse_location(text: str, prefixes: tuple[str, ...] = ()) -> tuple[str, int | None]:
    """``"a/b.py:12"`` -> ``("a/b.py", 12)``; без номера строки — ``("a/b.py", None)``."""
    path, start, _ = parse_location_range(text, prefixes)
    return path, start


def location_matches(
    location: str,
    expected: dict[str, Any],
    tolerance: int | None = None,
    prefixes: tuple[str, ...] = (),
) -> bool:
    """Совпадает ли адрес агента с одной записью эталона ``{"path","line","symbol","tolerance"}``.

    Допуск: аргумент ``tolerance``, иначе ``expected["tolerance"]``, иначе ``TOLERANCE_LINES``.
    Диапазон строк агента совпадает, если пересекает окно ``[line - tol, line + tol]``.
    """
    path, start, end = parse_location_range(location, prefixes)
    if path != normalize_path(str(expected["path"])):
        return False
    expected_line = expected.get("line")
    if expected_line is None:
        return True
    if tolerance is None:
        tolerance = int(expected.get("tolerance", TOLERANCE_LINES))
    if start is None or end is None:
        return False
    return start <= int(expected_line) + tolerance and end >= int(expected_line) - tolerance


def _normalize_answer(obj: Any) -> dict[str, Any] | None:
    """Приводит разобранный объект к ответу; без ``id`` это не ответ."""
    if not isinstance(obj, dict) or "id" not in obj:
        return None
    locations = obj.get("locations")
    if not isinstance(locations, list):
        locations = []
    confidence = str(obj.get("confidence", "")).strip().casefold()
    return {
        "id": str(obj["id"]).strip(),
        "answer": str(obj.get("answer", "")),
        "locations": [loc for loc in locations if isinstance(loc, str)],
        "confidence": confidence if confidence in CONFIDENCES else "unknown",
    }


def parse_answers(text: str) -> dict[str, dict[str, Any]]:
    """Достаёт ответы из произвольного текста: проза, ```-ограждения, многострочные объекты.

    Ключ результата — ``_key(id)``. Битый объект (обрыв, запятая в конце) пропускается:
    вопрос остаётся без ответа и считается ``unknown``. При повторе id побеждает последний.
    """
    decoder = json.JSONDecoder()
    found: dict[str, dict[str, Any]] = {}
    pos = 0
    while True:
        start = text.find("{", pos)
        if start < 0:
            return found
        try:
            obj, end = decoder.raw_decode(text, start)
        except ValueError:
            pos = start + 1
            continue
        answer = _normalize_answer(obj)
        if answer is None:
            pos = start + 1  # обёртка без id: ответы могут лежать внутри
            continue
        found[_key(answer["id"])] = answer
        pos = end


def classify(
    question: dict[str, Any],
    answer: dict[str, Any] | None,
    prefixes: tuple[str, ...] = (),
) -> str:
    """``hit`` | ``false`` | ``miss`` | ``n/a`` по адресам одного вопроса."""
    expected = question.get("expected") or []
    if not expected:
        return "n/a"
    if answer is None:
        return "miss"
    cap = len(expected) + 1
    locations = answer["locations"]
    kept = locations[:cap]
    over = len(locations) > cap
    covered = [any(location_matches(loc, exp, prefixes=prefixes) for loc in kept) for exp in expected]
    need_all = question.get("require", "any") == "all"
    if (all(covered) if need_all else any(covered)) and not over:
        return "hit"
    stray = over or any(not any(location_matches(loc, exp, prefixes=prefixes) for exp in expected) for loc in kept)
    return "false" if answer["confidence"] == "sure" and stray else "miss"


def _word_in(option: str, text: str) -> bool:
    """Опция найдена в тексте целым словом: ``processor`` не лежит внутри ``preprocessor``."""
    return re.search(r"(?<!\w)" + re.escape(option) + r"(?!\w)", text, re.IGNORECASE) is not None


def classify_facts(question: dict[str, Any], answer: dict[str, Any] | None) -> str | None:
    """``hit`` | ``miss`` по фактам; ``None`` — у вопроса нет ``expected_facts``."""
    facts = question.get("expected_facts") or []
    if not facts:
        return None
    if answer is None:
        return "miss"
    text = answer["answer"]
    found = [any(_word_in(str(option), text) for option in fact["any_of"]) for fact in facts]
    need_all = question.get("facts_require", "all") == "all"
    return "hit" if (all(found) if need_all else any(found)) else "miss"


def score_run(
    questions: list[dict[str, Any]],
    final_text: str,
    prefixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Оценка одного прогона.

    ``hits`` / ``false`` — только оцениваемые вопросы (``scored: true``) с адресами: по ним пороги.
    ``facts_hit`` — оцениваемые вопросы с фактами, где факты найдены. ``total_*`` — по всем вопросам набора.
    """
    answers = parse_answers(final_text)
    per_question: list[dict[str, Any]] = []
    for question in questions:
        answer = answers.get(_key(question["id"]))
        per_question.append(
            {
                "id": question["id"],
                "scored": bool(question.get("scored", True)),
                "verdict": classify(question, answer, prefixes),
                "facts": classify_facts(question, answer),
                "confidence": answer["confidence"] if answer else "unknown",
                "locations": answer["locations"] if answer else [],
            }
        )
    scored = [row for row in per_question if row["scored"]]
    located = [row for row in scored if row["verdict"] != "n/a"]
    with_facts = [row for row in scored if row["facts"] is not None]
    return {
        "per_question": per_question,
        "hits": sum(row["verdict"] == "hit" for row in scored),
        "false": sum(row["verdict"] == "false" for row in scored),
        "scored": len(located),
        "facts_hit": sum(row["facts"] == "hit" for row in with_facts),
        "facts_scored": len(with_facts),
        "total_hits": sum(row["verdict"] == "hit" for row in per_question),
        "total_false": sum(row["verdict"] == "false" for row in per_question),
        "total": len(per_question),
    }


METRICS = (
    "hits",
    "false",
    "facts_hit",
    "tool_calls",
    "final_context_tokens",
    "cumulative_tokens",
    "cache_read_tokens",
    "wall_s",
)


def _spread(values: list[float | int | None]) -> dict[str, float | None]:
    """min / median / max без пропусков (``None`` — не измерено)."""
    known = [value for value in values if value is not None]
    if not known:
        return {"min": None, "median": None, "max": None}
    return {"min": min(known), "median": statistics.median(known), "max": max(known)}


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводка по повторам. Каждый прогон: поля из METRICS (любое может быть None — не измерено)."""
    result: dict[str, Any] = {"repeats": len(runs)}
    for name in METRICS:
        result[name] = _spread([run.get(name) for run in runs])
    return result


def verdict(
    agg: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
    *,
    baseline: dict[str, Any] | None = None,
    tainted: bool = False,
) -> dict[str, Any]:
    """Сверка сводки с порогами. Полоса ``band``: PASS | FIX | FAIL | UNMEASURED | TAINTED.

    hits / facts_hit — по худшему повтору (min), false — по худшему (max), вызовы и токены — по медиане.
    ``baseline`` — сводка базовой записи: относительные пороги ``calls_ratio_max`` / ``tokens_ratio_max``
    (медиана вызовов и ``final_context_tokens`` к медиане базы). Не измеренное значение (``None``) не проходит
    молча: попадает в ``unmeasured``, и тогда ``pass`` ложно, а полоса — ``UNMEASURED``. ``tainted`` (нарушение
    доступа в любом повторе) перекрывает всё, в том числе ``UNMEASURED``.
    """
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    checks: dict[str, tuple[Any, Any, Any]] = {}
    if limits.get("hits_min"):
        checks["hits"] = (agg["hits"]["min"], limits["hits_min"], lambda v, lim: v >= lim)
    if limits.get("facts_hit_min"):
        checks["facts_hit"] = (agg["facts_hit"]["min"], limits["facts_hit_min"], lambda v, lim: v >= lim)
    checks["false"] = (agg["false"]["max"], limits["false_max"], lambda v, lim: v <= lim)
    if "calls_median_max" in limits:
        checks["tool_calls"] = (agg["tool_calls"]["median"], limits["calls_median_max"], lambda v, lim: v <= lim)
    if "tokens_median_max" in limits:
        checks["tokens"] = (
            agg["final_context_tokens"]["median"],
            limits["tokens_median_max"],
            lambda v, lim: v <= lim,
        )
    for name, ratio_key, metric in (
        ("calls_ratio", "calls_ratio_max", "tool_calls"),
        ("tokens_ratio", "tokens_ratio_max", "final_context_tokens"),
    ):
        if ratio_key not in limits:
            continue
        base = ((baseline or {}).get(metric) or {}).get("median")
        value = agg[metric]["median"]
        ratio = value / base if value is not None and base else None
        checks[name] = (ratio, limits[ratio_key], lambda v, lim: v <= lim)
    detail: dict[str, dict[str, Any]] = {}
    unmeasured: list[str] = []
    for name, (value, limit, ok_fn) in checks.items():
        if value is None:
            unmeasured.append(name)
            detail[name] = {"value": None, "limit": limit, "ok": None}
        else:
            detail[name] = {"value": value, "limit": limit, "ok": bool(ok_fn(value, limit))}
    passed = all(row["ok"] is not False for row in detail.values())
    # главная метрика полосы: факты, если порог по фактам задан, иначе попадания по адресам
    primary_name, primary_limit = (
        ("facts_hit", limits["facts_hit_min"]) if limits.get("facts_hit_min") else ("hits", limits["hits_min"])
    )
    primary = agg[primary_name]["min"]
    if tainted:
        band = "TAINTED"
    elif unmeasured:
        band = "UNMEASURED"
    elif passed:
        band = "PASS"
    elif primary is not None and primary >= primary_limit - FIX_WIDTH:
        band = "FIX"
    else:
        band = "FAIL"
    return {"pass": band == "PASS", "band": band, "checks": detail, "unmeasured": unmeasured}
