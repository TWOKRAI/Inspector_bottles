"""Наборы вопросов-отношений (ответ — МНОЖЕСТВО адресов): линтер набора и оценка записей прогона.

Отдельно от ``bench.py`` намеренно: обязательные поля этого линтера (``kind``, ``expected_winner``, ``source``…)
у старых наборов (``k0``, ``r1``, ``fw1``, ``fw2``) отсутствуют — встроенные в ``verify-set`` они сделали бы старые
наборы красными (смена контракта). Бенч и ``score.py`` не меняются; отсюда только импорт их функций.

    python scripts/nav_bench/relset.py lint  --questions Q.json [--root .] [--truth T.json]
    python scripts/nav_bench/relset.py score --questions Q.json REC.json [REC.json ...] [--replay-atlas]

Сопоставление адресов (``match``): адрес агента закрывает запись эталона, если путь тот же и строка (или диапазон
``a-b``) пересекает окно ``line ± tolerance`` (``score.location_matches``; у ``line: null`` — любой адрес файла);
каждый адрес агента закрывает НЕ БОЛЬШЕ ОДНОЙ записи и наоборот (паросочетание максимального размера), поэтому
соседние вызовы на строках 417 и 418 одним адресом не закрываются. recall = закрыто / записей; precision = адресов,
участвующих в паре / всех различных адресов ответа (без потолка ``len(expected)+1``: у отношений длина ответа —
часть метрики). Пустой ответ: recall 0, precision ``None`` (не определена; в медиану не входит).
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.nav_bench import score  # noqa: E402

KINDS = ("a-callers", "b-implementations", "c-importers", "d-paraphrase", "e-known-gap")
WINNERS = ("grep", "atlas", "tie")
SOURCES = ("ast", "manual")
TRIVIAL_RECALL = 0.8  # один grep отдаёт >= 80 % множества ...
TRIVIAL_PRECISION = 0.5  # ... и хотя бы каждая вторая строка вывода — ответ: такой вопрос решает копирование
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
STOP = set(
    """about above after also among another answer anything apart back based because before being below between both
    called calls code count counts defined define defines directly does doing done each either every exact except
    files file from function functions give given have here inside into itself just kind line lines list listed more
    most must name named names need none only other others outside over part place places plus production project
    question rather reads same should since some such tell than that their them then there these they this those
    through under until used uses using what when where whether which while whose will with within without would your
    count class classes method methods module modules package packages tests test directory directories path paths
    repository report include including included exclude excluding excluded""".split()
)


# --- сопоставление ---------------------------------------------------------------------------
def match(
    expected: list[dict[str, Any]], locations: list[str], prefixes: tuple[str, ...] = ()
) -> list[tuple[int, int]]:
    """Пары (индекс адреса, индекс записи) максимального паросочетания; адреса — различные, порядок сохранён."""
    locs = list(dict.fromkeys(locations))
    adj = [[j for j, exp in enumerate(expected) if score.location_matches(loc, exp, prefixes=prefixes)] for loc in locs]
    owner: dict[int, int] = {}

    def augment(i: int, seen: set[int]) -> bool:
        for j in adj[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owner or augment(owner[j], seen):
                owner[j] = i
                return True
        return False

    for i in range(len(locs)):
        augment(i, set())
    return sorted((i, j) for j, i in owner.items())


def score_set(expected: list[dict[str, Any]], locations: list[str], prefixes: tuple[str, ...] = ()) -> dict[str, Any]:
    locs = list(dict.fromkeys(locations))
    pairs = match(expected, locs, prefixes)
    tp = len(pairs)
    return {
        "tp": tp,
        "fp": len(locs) - tp,
        "fn": len(expected) - tp,
        "recall": tp / len(expected) if expected else None,
        "precision": tp / len(locs) if locs else None,
    }


# --- линтер набора -----------------------------------------------------------------------------
GrepFn = Callable[[str, bool], list[str]]


def git_grep_fn(root: Path, sha: str, exclude: list[str]) -> GrepFn:
    """``(слово, без_регистра) -> ["путь:строка", ...]`` по дереву ``sha`` (как увидит агент копии: без ``exclude``)."""

    def run(word: str, ignore_case: bool) -> list[str]:
        cmd = ["git", "-C", str(root), "grep", "-n", "-I", "-w", "-F"]
        cmd += ["-i"] if ignore_case else []
        cmd += ["-e", word, sha, "--", "."] + [f":(exclude){e}" for e in exclude]
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        hits = []
        for row in out.stdout.splitlines():
            parts = row.split(":", 3)  # sha:путь:строка:текст
            if len(parts) == 4 and parts[2].isdigit():
                hits.append(f"{parts[1]}:{parts[2]}")
        return hits

    return run


def question_words(text: str) -> list[str]:
    return [w for w in dict.fromkeys(WORD_RE.findall(text)) if w.casefold() not in STOP]


def one_grep(question: dict[str, Any], grep: GrepFn) -> dict[str, Any]:
    """Лучшее слово вопроса: максимум recall, при равенстве — precision."""
    best = {"word": None, "recall": 0.0, "precision": 0.0, "hits": 0, "ignore_case": False}
    expected = question.get("expected") or []
    for word in question_words(str(question.get("question", ""))):
        for ignore_case in (False, True):
            hits = grep(word, ignore_case)
            if not hits:
                continue
            row = score_set(expected, hits)
            recall, precision = row["recall"] or 0.0, row["precision"] or 0.0
            # ближе всех к порогу «тривиален» по ОБОИМ числам: слово с recall 1.0 и precision 0.01 не заслоняет
            # слово с recall 0.9 и precision 0.6
            closeness = min(recall / TRIVIAL_RECALL, precision / TRIVIAL_PRECISION)
            if closeness > best.get("closeness", -1.0):
                best = {
                    "word": word,
                    "recall": recall,
                    "precision": precision,
                    "hits": len(set(hits)),
                    "ignore_case": ignore_case,
                    "closeness": closeness,
                }
    best["trivial"] = best["recall"] >= TRIVIAL_RECALL and best["precision"] >= TRIVIAL_PRECISION
    return best


def leaked_names(question: dict[str, Any]) -> list[str]:
    """Имена эталона (части ``symbol`` через точку, имя файла без ``.py``) в тексте вопроса целым словом сверх
    ``allowed_names``."""
    allowed = set(question.get("allowed_names") or [])
    names: set[str] = set()
    for exp in question.get("expected") or []:
        names |= {part for part in str(exp.get("symbol") or "").split(".") if part}
        stem = str(exp["path"]).rsplit("/", 1)[-1].removesuffix(".py")
        if stem != "__init__":
            names.add(stem)
    text = str(question.get("question", ""))
    return sorted(
        n for n in names if len(n) >= 3 and n not in allowed and re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", text)
    )


def lint(qset: dict[str, Any], grep: GrepFn | None, truth: dict[str, Any] | None = None) -> tuple[list[str], list[str]]:
    """(проблемы, справка). Проблема — красный код. ``grep=None`` — проверка (а) пропущена (это проблема)."""
    problems: list[str] = []
    info: list[str] = []
    if grep is None:
        problems.append("проверка «один grep» не выполнена (нет git)")
    for q in qset["questions"]:
        qid = q["id"]
        if q.get("kind") not in KINDS:
            problems.append(f"{qid}: kind {q.get('kind')!r} не из {KINDS}")
        if q.get("expected_winner") not in WINNERS:
            problems.append(f"{qid}: expected_winner {q.get('expected_winner')!r} не из {WINNERS}")
        if not str(q.get("winner_reason") or "").strip():
            problems.append(f"{qid}: нет winner_reason (почему ожидаем этого победителя — до замера)")
        if not isinstance(q.get("allowed_names"), list):
            problems.append(f"{qid}: нет списка allowed_names (пустой список — тоже явное решение)")
        for k, exp in enumerate(q.get("expected") or []):
            if exp.get("source") not in SOURCES:
                problems.append(f"{qid}: expected[{k}] без source из {SOURCES}")
            if exp.get("manual_check") is not True:
                problems.append(f"{qid}: expected[{k}] не сверен чтением (manual_check != true)")
        for name in leaked_names(q):
            problems.append(f"{qid}: имя эталона {name!r} в тексте вопроса, нет в allowed_names")
        if grep is not None:
            best = one_grep(q, grep)
            info.append(
                f"{qid}: один grep — лучшее слово {best['word']!r}{' (-i)' if best['ignore_case'] else ''}: "
                f"recall {best['recall']:.2f}, precision {best['precision']:.2f}, строк {best['hits']}"
            )
            if best["trivial"]:
                problems.append(
                    f"{qid}: тривиален — `git grep -w {best['word']}` даёт recall {best['recall']:.2f} "
                    f">= {TRIVIAL_RECALL} при precision {best['precision']:.2f} >= {TRIVIAL_PRECISION}"
                )
        if truth is not None:
            want = {(e["path"], e["line"]) for e in truth["questions"].get(qid, {}).get("entries", [])}
            have = {(e["path"], e["line"]) for e in q.get("expected") or []}
            if want != have:
                problems.append(
                    f"{qid}: expected не равен эталону скрипта: +{sorted(have - want)} -{sorted(want - have)}"
                )
    return problems, info


# --- оценка записей прогона ----------------------------------------------------------------------
def _atlas_uses(repeat: dict[str, Any], marker: str) -> list[dict[str, Any]]:
    return [
        u
        for u in repeat.get("tool_uses", [])
        if str(u.get("name")).casefold() == "bash" and marker in str(u.get("target"))
    ]


def _replay(use: dict[str, Any]) -> str:
    done = subprocess.run(
        shlex.split(use["target"]), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600
    )
    return done.stdout


def score_record(
    qset: dict[str, Any], record: dict[str, Any], marker: str = "atlas", replay: bool = False
) -> dict[str, Any]:
    """Строки ``(вопрос, повтор)`` и сводка повторов. ``replay`` — воспроизвести вызовы atlas трассы (тёплый кэш,
    без модели) и посчитать «доставлен» (адрес эталона есть в выводе atlas повтора) и «доставлен и назван»."""
    from scripts.nav_bench import bench  # только для разбора текста паспортов

    prefixes = tuple(record.get("prefixes") or ())
    rows = []
    reps = []
    for rep in record["repeats"]:
        answers = score.parse_answers(rep.get("final_text") or "")
        uses = _atlas_uses(rep, marker)
        delivered_addr: set[tuple[str, int | None]] = set()
        if replay:
            for use in uses:
                if not use.get("denied"):
                    delivered_addr |= bench.text_addresses(_replay(use))
        delivered_locs = [f"{p}:{n}" if n is not None else p for p, n in delivered_addr]
        for q in qset["questions"]:
            exp = q.get("expected") or []
            ans = answers.get(score._key(q["id"]))
            locs = ans["locations"] if ans else []
            row = {"id": q["id"], "repeat": rep.get("index"), **score_set(exp, locs, prefixes)}
            if replay:
                got = {j for _, j in match(exp, delivered_locs, prefixes)}
                named = {j for _, j in match(exp, locs, prefixes)}
                row["delivered"] = len(got)
                row["delivered_named"] = len(got & named)
            rows.append(row)
        reps.append(
            {
                "repeat": rep.get("index"),
                "tool_calls": rep.get("tool_calls"),
                "final_context_tokens": rep.get("final_context_tokens"),
                "cumulative_tokens": rep.get("cumulative_tokens"),
                "atlas_calls": len(uses),
                "atlas_errors": sum(bool(u.get("denied")) for u in uses),
                "violations": len(rep.get("violations") or []),
                "subtype": rep.get("subtype"),
            }
        )
    return {"rows": rows, "repeats": reps}


def _med_min(values: list[float | None]) -> str:
    known = [v for v in values if v is not None]
    if not known:
        return "н/д"
    return f"{statistics.median(known):.2f} / {min(known):.2f}"


def render(qset: dict[str, Any], name: str, result: dict[str, Any]) -> str:
    out = [
        f"## {name}",
        "",
        "| вопрос | recall мед/мин | precision мед/мин | доставлен (сумма) | доставлен и назван |",
        "|---|---|---|---|---|",
    ]
    for q in qset["questions"]:
        rows = [r for r in result["rows"] if r["id"] == q["id"]]
        deliv = sum(r.get("delivered", 0) for r in rows) if rows and "delivered" in rows[0] else "—"
        named = sum(r.get("delivered_named", 0) for r in rows) if rows and "delivered_named" in rows[0] else "—"
        recall = _med_min([r["recall"] for r in rows])
        precision = _med_min([r["precision"] for r in rows])
        out.append(f"| {q['id']} | {recall} | {precision} | {deliv} | {named} |")
    tp = {}
    for r in result["rows"]:
        tp.setdefault(r["repeat"], [0, 0, 0])
        tp[r["repeat"]][0] += r["tp"]
        tp[r["repeat"]][1] += r["fp"]
        tp[r["repeat"]][2] += r["fn"]
    out += [
        "",
        "| повтор | macro recall | macro precision | адресов верных | ложных | пропущено | вызовов | ctx токенов "
        "| накоп. токенов | atlas вызовов | atlas ошибок | нарушений | subtype |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rep in result["repeats"]:
        t = tp.get(rep["repeat"], [0, 0, 0])
        mr, mp = macro(result["rows"], rep["repeat"])
        rep["macro_recall"], rep["macro_precision"] = mr, mp
        out.append(
            f"| {rep['repeat']} | {mr:.2f} | {mp:.2f} | {t[0]} | {t[1]} | {t[2]} | {rep['tool_calls']} "
            f"| {rep['final_context_tokens']} | {rep['cumulative_tokens']} | {rep['atlas_calls']} "
            f"| {rep['atlas_errors']} | {rep['violations']} | {rep['subtype']} |"
        )
    keys = ("macro_recall", "macro_precision", "tool_calls", "cumulative_tokens", "final_context_tokens")
    summary = ", ".join(f"{k} {_med_min([r.get(k) for r in result['repeats']])}" for k in keys)
    out += ["", f"СВОДКА {name} (медиана / мин по повторам): {summary}"]
    return "\n".join(out)


def macro(rows: list[dict[str, Any]], repeat: Any) -> tuple[float, float]:
    """Среднее по вопросам повтора (каждый вопрос — вес 1): recall; precision — у вопросов с непустым ответом
    (пустой ответ precision не имеет; он уже стоит recall), 0.0 — если непустых ответов нет ни одного."""
    mine = [r for r in rows if r["repeat"] == repeat]
    recalls = [r["recall"] for r in mine if r["recall"] is not None]
    precisions = [r["precision"] for r in mine if r["precision"] is not None]
    return (statistics.fmean(recalls) if recalls else 0.0, statistics.fmean(precisions) if precisions else 0.0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    pl = sub.add_parser("lint", help="проверить набор: поля, утечки имён, «один grep», эталон скрипта")
    pl.add_argument("--questions", type=Path, required=True)
    pl.add_argument("--root", type=Path, default=Path("."))
    pl.add_argument("--truth", type=Path)
    ps = sub.add_parser("score", help="recall/precision множества адресов по записям прогона")
    ps.add_argument("--questions", type=Path, required=True)
    ps.add_argument("records", type=Path, nargs="+")
    ps.add_argument("--replay-atlas", action="store_true")
    ps.add_argument("--marker", default="atlas", help="подстрока команды Bash, которая считается вызовом atlas")
    args = ap.parse_args(argv)
    qset = json.loads(args.questions.read_text(encoding="utf-8"))
    if args.command == "lint":
        grep = git_grep_fn(args.root, qset["repo_sha"], qset.get("exclude") or [])
        truth = json.loads(args.truth.read_text(encoding="utf-8")) if args.truth else None
        problems, info = lint(qset, grep, truth)
        for row in info:
            print(f"СПРАВКА: {row}")
        for row in problems:
            print(f"ПРОБЛЕМА: {row}")
        print(f"relset lint {qset['name']}: вопросов {len(qset['questions'])}, проблем {len(problems)}")
        return 1 if problems else 0
    for path in args.records:
        record = json.loads(path.read_text(encoding="utf-8"))
        print(render(qset, path.name, score_record(qset, record, args.marker, args.replay_atlas)))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
