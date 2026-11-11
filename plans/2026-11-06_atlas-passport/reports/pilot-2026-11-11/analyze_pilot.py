"""Разбор пилота «Атлас против grep» по записям bench.py (две записи: условие grep и условие atlas).

Метрика (записана в протоколе до прогона): ДОЛЯ АДРЕСОВ — сколько из N адресов `expected` названо в ответе агента
(путь тот же, строка в окне ±3, правило `score.location_matches`), считая каждый адрес отдельно, по повторам.
Рядом: `hits` бенча (вопрос засчитан, если названы ВСЕ адреса вопроса, `require: all`), вызовы, токены, время.
Для условия atlas — диагностика «доставлено / использовано»: адрес «доставлен», если он есть в тексте вывода atlas
хотя бы одного вызова повтора (вызовы воспроизводятся по трассе повторно — warm-кэш, платных вызовов нет).

Запуск: python analyze_pilot.py <запись_grep.json> <запись_atlas.json> [--atlas-wrapper <путь к pilot_atlas.py>]
"""

from __future__ import annotations

import argparse
import json
import shlex
import statistics
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from scripts.nav_bench import bench, score  # noqa: E402


def _expected(record):
    """[(qid, entry)] — каждый адрес отдельной строкой."""
    return [(str(q["id"]), e) for q in record["questions"] for e in q["expected"]]


def _answer_locations(repeat, qid):
    for row in repeat["score"]["per_question"]:
        if str(row["id"]) == qid:
            return row["locations"]
    return []


def _found(record, repeat, qid, entry):
    prefixes = tuple(record.get("prefixes") or ())
    return any(score.location_matches(loc, entry, prefixes=prefixes) for loc in _answer_locations(repeat, qid))


def _atlas_texts(repeat):
    """Тексты вывода atlas по вызовам Bash повтора (воспроизведение команд трассы)."""
    texts = []
    for use in repeat["tool_uses"]:
        if str(use.get("name")).casefold() != "bash" or use.get("denied") or not use.get("target"):
            continue
        argv = shlex.split(use["target"])
        if "pilot_atlas.py" not in " ".join(argv) or argv[-1] == "":
            continue
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        texts.append(done.stdout)
    return texts


def _delivered(texts, entry):
    for text in texts:
        for path, line in bench.text_addresses(text):
            if line is not None and score.location_matches(f"{path}:{line}", entry):
                return True
    return False


def summarize(record, label, with_atlas):
    exp = _expected(record)
    rows, per_q, cls = (
        [],
        {},
        {"доставлен и назван": 0, "доставлен, не назван": 0, "не доставлен, назван": 0, "не доставлен, не назван": 0},
    )
    for rep in record["repeats"]:
        got = [_found(record, rep, qid, e) for qid, e in exp]
        for (qid, _), ok in zip(exp, got):
            per_q.setdefault(qid, [0, 0])
            per_q[qid][0] += ok
            per_q[qid][1] += 1
        atlas_calls = sum(
            1
            for u in rep["tool_uses"]
            if str(u.get("name")).casefold() == "bash" and "pilot_atlas" in str(u.get("target"))
        )
        outside = sum(
            1
            for u in rep["tool_uses"]
            if u.get("name") in ("Read", "Grep", "Glob")
            and str(u.get("target") or "").startswith("/")
            and not any(str(u["target"]).startswith(p) for p in (record.get("prefixes") or []))
        )
        if with_atlas:
            texts = _atlas_texts(rep)
            for (qid, e), ok in zip(exp, got):
                d = _delivered(texts, e)
                cls[
                    ("доставлен" if d else "не доставлен")
                    + (" и назван" if d and ok else ", не назван" if d else ", назван" if ok else ", не назван")
                ] += 1
        rows.append(
            dict(
                recall=sum(got),
                n=len(got),
                hits=rep["score"]["hits"],
                scored=rep["score"]["scored"],
                false=rep["score"]["false"],
                calls=rep["tool_calls"],
                ctx=rep["final_context_tokens"],
                cum=rep["cumulative_tokens"],
                wall=rep["wall_s"],
                cost=rep["cost_usd"],
                atlas=atlas_calls,
                outside=outside,
                viol=len(rep["violations"]),
                err=rep["error"] or "",
            )
        )
    lines = [
        f"### {label}",
        "",
        "| повтор | адресов | hits (из 6) | ложных | вызовов | atlas | ctx токенов | cum токенов "
        "| сек | вне копии | нарушений | ошибка |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['recall']}/{r['n']} | {r['hits']} | {r['false']} | {r['calls']} | {r['atlas']} "
            f"| {r['ctx']} | {r['cum']} | {r['wall']} | {r['outside']} | {r['viol']} | {r['err'][:40]} |"
        )
    med = lambda k: statistics.median([r[k] for r in rows if r[k] is not None] or [0])  # noqa: E731
    lines += [
        "",
        f"медиана: адресов {med('recall')}/{rows[0]['n']}, hits {med('hits')}, вызовов {med('calls')}, "
        f"ctx {med('ctx')}, cum {med('cum')}",
        "",
        "по вопросам (найдено адресов из возможных по всем повторам): "
        + ", ".join(f"{q} {a}/{b}" for q, (a, b) in per_q.items()),
    ]
    if with_atlas:
        lines += ["", "доставлено / использовано (адрес × повтор): " + "; ".join(f"{k} {v}" for k, v in cls.items())]
    return "\n".join(lines), rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("grep_record", type=Path)
    parser.add_argument("atlas_record", type=Path)
    args = parser.parse_args()
    out = []
    for path, label, with_atlas in (
        (args.grep_record, "grep-read (Read, Grep, Glob)", False),
        (args.atlas_record, "atlas-pilot (+ atlas ref/map)", True),
    ):
        text, _ = summarize(json.loads(path.read_text(encoding="utf-8")), label, with_atlas)
        out.append(text)
    print("\n\n".join(out))


if __name__ == "__main__":
    main()
