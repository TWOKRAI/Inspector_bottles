"""Тесты линтера и оценки наборов-отношений (relset). Ожидаемые значения — литералы."""

import subprocess

from scripts.nav_bench import relset


def _exp(path, line, symbol="f", tol=1):
    return {"path": path, "line": line, "symbol": symbol, "tolerance": tol, "source": "ast", "manual_check": True}


def _q(**over):
    q = {
        "id": "Q1",
        "kind": "a-callers",
        "expected_winner": "atlas",
        "winner_reason": "atlas resolves imports",
        "allowed_names": ["helper"],
        "question": "List every production call site of `helper`.",
        "expected": [_exp("pkg/a.py", 10, "helper"), _exp("pkg/b.py", 20, "helper")],
    }
    q.update(over)
    return q


def _set(*questions):
    return {"name": "t", "repo_sha": "abc", "questions": list(questions)}


def _grep_from(table):
    return lambda word, ignore_case: table.get(word, [])


# --- сопоставление -----------------------------------------------------------------------------
def test_one_address_closes_one_entry_even_if_both_in_window():
    expected = [_exp("m.py", 417), _exp("m.py", 418)]
    assert relset.score_set(expected, ["m.py:417"]) == {"tp": 1, "fp": 0, "fn": 1, "recall": 0.5, "precision": 1.0}
    assert relset.score_set(expected, ["m.py:418", "m.py:417"])["tp"] == 2


def test_matching_is_maximal_not_greedy():
    # m.py:11 подходит к обеим записям (10 и 12 при ±1), m.py:9 — только к 10: жадный порядок дал бы 1 пару
    expected = [_exp("m.py", 10), _exp("m.py", 12)]
    assert relset.score_set(expected, ["m.py:11", "m.py:9"])["tp"] == 2


def test_false_addresses_and_duplicates():
    expected = [_exp("m.py", 10)]
    row = relset.score_set(expected, ["m.py:10", "m.py:10", "tests/test_m.py:5", "m.py:40"])
    assert (row["tp"], row["fp"], row["fn"]) == (1, 2, 0)
    assert row["precision"] == 1 / 3


def test_empty_answer_has_no_precision():
    row = relset.score_set([_exp("m.py", 10)], [])
    assert row["recall"] == 0.0 and row["precision"] is None


def test_file_level_entry_matches_any_line_of_file():
    expected = [{"path": "x/y.py", "line": None, "symbol": None}]
    assert relset.score_set(expected, ["x/y.py:999"])["tp"] == 1


# --- линтер ------------------------------------------------------------------------------------
def test_good_set_has_no_problems():
    grep = _grep_from({"helper": ["pkg/a.py:10", "pkg/a.py:1", "tests/t.py:3", "docs/x.md:4", "pkg/b.py:20"]})
    problems, info = relset.lint(_set(_q()), grep)
    assert problems == []
    assert info == ["Q1: один grep — лучшее слово 'helper': recall 1.00, precision 0.40, строк 5"]


def test_trivial_question_is_flagged():
    grep = _grep_from({"helper": ["pkg/a.py:10", "pkg/b.py:20", "docs/x.md:4"]})
    problems, _ = relset.lint(_set(_q()), grep)
    assert problems == ["Q1: тривиален — `git grep -w helper` даёт recall 1.00 >= 0.8 при precision 0.67 >= 0.5"]


def test_trivial_word_is_not_hidden_by_a_higher_recall_noisy_word():
    # «helper»: 4 из 5 записей без шума (recall 0.8, precision 1.0 — тривиален);
    # «carefully» (не стоп-слово): все 5 записей + 200 лишних (recall 1.0, precision 0.02)
    expected = [_exp(f"pkg/m{i}.py", 10, "helper") for i in range(5)]
    noisy = [f"z/{i}.py:1" for i in range(200)] + [f"pkg/m{i}.py:10" for i in range(5)]
    grep = _grep_from({"helper": [f"pkg/m{i}.py:10" for i in range(4)], "carefully": noisy})
    q = _q(question="List every production call site of `helper`, carefully.", expected=expected)
    problems, _ = relset.lint(_set(q), grep)
    assert problems == ["Q1: тривиален — `git grep -w helper` даёт recall 0.80 >= 0.8 при precision 1.00 >= 0.5"]


def test_leaked_name_is_flagged_unless_allowed():
    q = _q(
        question="Which constants does `stop_budget` read? Hint: KILL_CONFIRM_S.",
        allowed_names=["stop_budget"],
        expected=[_exp("pm/stop_budget.py", 49, "KILL_CONFIRM_S")],
    )
    problems, _ = relset.lint(_set(q), _grep_from({}))
    assert problems == ["Q1: имя эталона 'KILL_CONFIRM_S' в тексте вопроса, нет в allowed_names"]


def test_file_stem_counts_as_leak():
    q = _q(
        question="Who imports not_inspected_marker?",
        allowed_names=[],
        expected=[_exp("r/not_inspected_marker.py", 3, "x")],
    )
    problems, _ = relset.lint(_set(q), _grep_from({}))
    assert problems == ["Q1: имя эталона 'not_inspected_marker' в тексте вопроса, нет в allowed_names"]


def test_missing_kind_winner_reason_source_and_check():
    bad_entry = {"path": "pkg/a.py", "line": 10, "symbol": "helper"}
    q = _q(kind="x", expected_winner="maybe", winner_reason=" ", expected=[bad_entry])
    del q["allowed_names"]
    problems, _ = relset.lint(_set(q), _grep_from({}))
    assert problems == [
        "Q1: kind 'x' не из ('a-callers', 'b-implementations', 'c-importers', 'd-paraphrase', 'e-known-gap')",
        "Q1: expected_winner 'maybe' не из ('grep', 'atlas', 'tie')",
        "Q1: нет winner_reason (почему ожидаем этого победителя — до замера)",
        "Q1: нет списка allowed_names (пустой список — тоже явное решение)",
        "Q1: expected[0] без source из ('ast', 'manual')",
        "Q1: expected[0] не сверен чтением (manual_check != true)",
        "Q1: имя эталона 'helper' в тексте вопроса, нет в allowed_names",
    ]


def test_no_grep_is_a_problem():
    problems, _ = relset.lint(_set(_q()), None)
    assert problems == ["проверка «один grep» не выполнена (нет git)"]


def test_truth_mismatch_is_flagged():
    truth = {"questions": {"Q1": {"entries": [{"path": "pkg/a.py", "line": 10}]}}}
    problems, _ = relset.lint(_set(_q()), _grep_from({}), truth)
    assert problems == ["Q1: expected не равен эталону скрипта: +[('pkg/b.py', 20)] -[]"]


# --- живой git: настоящий git_grep_fn на временном репозитории ---------------------------------------
def test_real_git_grep_flags_trivial_and_passes_noisy(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("def helper():\n    pass\n\n\nhelper()\n", encoding="utf-8")
    (tmp_path / "skip").mkdir()
    (tmp_path / "skip" / "s.py").write_text("helper()\nhelper()\nhelper()\n", encoding="utf-8")
    git("add", "pkg/a.py", "skip/s.py")
    git("commit", "-q", "-m", "x")
    sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    q = _q(expected=[_exp("pkg/a.py", 5, "helper")], allowed_names=["helper"])
    trivial, _ = relset.lint(_set(q), relset.git_grep_fn(tmp_path, sha, ["skip"]))
    assert trivial == ["Q1: тривиален — `git grep -w helper` даёт recall 1.00 >= 0.8 при precision 0.50 >= 0.5"]
    noisy, info = relset.lint(_set(q), relset.git_grep_fn(tmp_path, sha, []))
    assert noisy == []
    assert info == ["Q1: один grep — лучшее слово 'helper': recall 1.00, precision 0.20, строк 5"]


# --- оценка записи ------------------------------------------------------------------------------------
def test_score_record_rows_and_atlas_counts():
    qset = _set(_q())
    record = {
        "prefixes": ["/tmp/copy"],
        "repeats": [
            {
                "index": 1,
                "tool_calls": 7,
                "final_context_tokens": 1000,
                "cumulative_tokens": 1500,
                "violations": [],
                "subtype": "success",
                "tool_uses": [
                    {"name": "Bash", "target": "python pilot_atlas.py ref helper", "denied": True},
                    {"name": "Bash", "target": "python pilot_atlas.py ref pkg/a.py::helper", "denied": False},
                    {"name": "Read", "target": "pkg/a.py"},
                ],
                "final_text": '{"id": "Q1", "answer": "x", "locations": ["/tmp/copy/pkg/a.py:10", "pkg/c.py:1"],'
                ' "confidence": "sure"}',
            }
        ],
    }
    result = relset.score_record(qset, record)
    assert relset.macro(result["rows"], 1) == (0.5, 0.5)
    assert result["rows"] == [{"id": "Q1", "repeat": 1, "tp": 1, "fp": 1, "fn": 1, "recall": 0.5, "precision": 0.5}]
    assert result["repeats"][0]["atlas_calls"] == 2 and result["repeats"][0]["atlas_errors"] == 1
