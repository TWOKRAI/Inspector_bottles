"""Разбор пилота «Атлас против grep» по записям bench.py (две записи: условие grep и условие atlas).

Метрика (записана в протоколе до прогона): ДОЛЯ АДРЕСОВ — сколько из N адресов `expected` названо в ответе агента
(путь тот же, строка в окне ±3, правило `score.location_matches`), считая каждый адрес отдельно, по повторам.
Рядом: `hits` бенча (вопрос засчитан, если названы ВСЕ адреса вопроса, `require: all`), вызовы, токены, время.
Для условия atlas — диагностика «доставлено / использовано»: адрес «доставлен», если он есть в тексте вывода atlas
хотя бы одного вызова повтора (вызовы воспроизводятся по трассе без оболочки: реконструкция, не наблюдение;
вызовы с `denied`, синтаксисом оболочки или сбоем повтора — «неизвестные», см. `_atlas_texts`).
`hits` и ложные считаются заново текущим `score.score_run`, из записи не берутся.

Запуск: python analyze_pilot.py <запись_grep.json> <запись_atlas.json> [--atlas-wrapper <путь к pilot_atlas.py>]
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


# Поля вызова в записи, где мог бы лежать вывод; текущий bench.py их не пишет (только name/target/denied).
_RECORDED_TEXT_KEYS = ("output", "stdout", "result_text")
_SHELL_PUNCTUATION = set("();<>|&")


def _has_shell_syntax(command):
    """Нужна ли оболочка, чтобы выполнить команду как агент: повтор без неё был бы другим вызовом.

    Да: операторы `| > < & && ; ( )` и `2>&1`, подстановки `$..`, обратные кавычки, glob `* ? [`, `~` в начале слова,
    перевод строки, `#`-комментарий, присваивание `VAR=..` перед командой, незакрытая кавычка. Нет: слова, кавычки,
    дефисы, точки, слэши. Ошибка в сторону «да» безопасна (вызов станет «неизвестным»), в сторону «нет» — нет.
    """
    if any(char in command for char in "`$*?[\n") or re.search(r"(^|\s)#", command):
        return True
    try:
        tokens = list(shlex.shlex(command, posix=True, punctuation_chars=True))
    except ValueError:  # незакрытая кавычка: как оболочка это не разобрать
        return True
    if tokens and re.match(r"[A-Za-z_]\w*=", tokens[0]):
        return True
    return any(token.startswith("~") or (token and set(token) <= _SHELL_PUNCTUATION) for token in tokens)


def _atlas_texts(repeat):
    """(тексты, неизвестные) вывода atlas по вызовам Bash повтора; неизвестные — список (команда, причина).

    Источник текста вызова: (1) поле вывода в самой записи (`_RECORDED_TEXT_KEYS`), если есть; (2) иначе вызов
    воспроизводится через `shlex.split` БЕЗ оболочки — это реконструкция, не наблюдение: тот же вывод получится, только
    если окружение и копия репозитория те же, что у агента; (3) иначе вызов «неизвестный» и не считается ни
    доставленным, ни недоставленным. Причины неизвестности:
      - `denied` без текста в записи: в бенче это `is_error` результата, то есть отказ разрешения ИЛИ код выхода != 0
        (bench.py), а вывод бенч не хранит; частично успешный вызов (паспорта выведены, код 2) и отказ неразличимы;
      - синтаксис оболочки (`|`, `>`, `2>&1`, `&&`, `;`, `$..`): без оболочки это был бы другой вызов (`| head`
        обрезал вывод агенту, `2>/dev/null` прятал ошибки), повтор не показал бы, что он видел;
      - повтор дал код != 0 и пустой stdout, либо упал по времени.
    """
    texts, unknown = [], []
    for use in repeat["tool_uses"]:
        target = str(use.get("target") or "")
        if str(use.get("name")).casefold() != "bash" or "pilot_atlas.py" not in target:
            continue
        recorded = next((use[k] for k in _RECORDED_TEXT_KEYS if isinstance(use.get(k), str)), None)
        if recorded is not None:
            texts.append(recorded)
        elif use.get("denied"):
            unknown.append((target, "denied: отказ или код != 0, текста в записи нет"))
        elif _has_shell_syntax(target):
            unknown.append((target, "синтаксис оболочки: повтор без оболочки был бы другим вызовом"))
        else:
            argv = shlex.split(target)
            if argv[-1] == "":
                continue
            try:
                done = subprocess.run(
                    argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                unknown.append((target, f"повтор не удался: {type(exc).__name__}"))
                continue
            if done.returncode != 0 and not done.stdout.strip():
                unknown.append((target, f"повтор дал код {done.returncode} и пустой вывод"))
            else:
                texts.append(done.stdout)
    return texts, unknown


def _delivered(texts, entry):
    for text in texts:
        for path, line in bench.text_addresses(text):
            if line is not None and score.location_matches(f"{path}:{line}", entry):
                return True
    return False


def summarize(record, label, with_atlas):
    exp = _expected(record)
    unknown_atlas, unknown_reasons, stored_diff, leftovers = [], {}, [], []
    prefixes = tuple(record.get("prefixes") or ())
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
            texts, unknown = _atlas_texts(rep)
            unknown_atlas.append(len(unknown))
            for _, reason in unknown:
                unknown_reasons[reason.split(":")[0]] = unknown_reasons.get(reason.split(":")[0], 0) + 1
            for (qid, e), ok in zip(exp, got):
                d = _delivered(texts, e)
                cls[
                    ("доставлен" if d else "не доставлен")
                    + (" и назван" if d and ok else ", не назван" if d else ", назван" if ok else ", не назван")
                ] += 1
        # hits/scored/false считаются ЗАНОВО текущим score.score_run по тексту ответа, а не берутся из записи
        # (запись хранит оценку старого разбора адресов)
        fresh = score.score_run(record["questions"], rep["final_text"], prefixes)
        stored = rep["score"]
        if (fresh["hits"], fresh["false"], fresh["scored"]) != (stored["hits"], stored["false"], stored["scored"]):
            stored_diff.append(
                f"повтор {len(rows) + 1}: в записи hits {stored['hits']}, ложных {stored['false']}; "
                f"новым разбором hits {fresh['hits']}, ложных {fresh['false']}"
            )
        leftovers.append(
            [
                (row["id"], loc, score.unparsed(loc))
                for row in stored["per_question"]
                for loc in row["locations"]
                if score.unparsed(loc)
            ]
        )
        rows.append(
            dict(
                recall=sum(got),
                n=len(got),
                hits=fresh["hits"],
                scored=fresh["scored"],
                false=fresh["false"],
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
    lines += [
        "",
        "hits / ложных пересчитаны текущим `score.score_run` по тексту ответа (запись хранит оценку старого разбора "
        "адресов). Расхождения с записью: " + ("; ".join(stored_diff) if stored_diff else "нет") + ".",
    ]
    n_left = [len(items) for items in leftovers]
    lines += [
        "",
        "адресов ответа с неразобранным остатком, где есть цифры (`score.unparsed`; «не разобрал» ≠ «данных нет»), "
        "по повторам: " + ", ".join(str(n) for n in n_left) + ".",
    ]
    for i, items in enumerate(leftovers, 1):
        for qid, loc, rest in items[:3]:
            lines.append(f"  - повтор {i}, {qid}: `{loc}` -> остаток {rest}")
    if with_atlas:
        lines += [
            "",
            "доставлено / использовано (адрес × повтор; оценка ПОВТОРОМ команд без оболочки, не наблюдением): "
            + "; ".join(f"{k} {v}" for k, v in cls.items()),
        ]
        if any(unknown_atlas):
            lines += [
                "",
                "ОГОВОРКА: вызовов atlas с неизвестным выводом по повторам: "
                + ", ".join(str(n) for n in unknown_atlas)
                + " (причины: "
                + ", ".join(f"{k} {v}" for k, v in unknown_reasons.items())
                + "). Такие вызовы не учтены ни как доставленные, ни как недоставленные; «не доставлен» выше может "
                "быть занижением. Бенч помечает `denied` и отказ, и код выхода != 0 и не хранит вывод; команды с "
                "`|`, `>`, `2>&1`, `&&` без оболочки были бы другими вызовами. Повтор не заменяет наблюдение.",
            ]
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
