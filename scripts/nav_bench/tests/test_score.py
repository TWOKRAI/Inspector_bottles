"""Тесты разбора и оценки ответов nav_bench. Ожидаемые значения — литералы."""

import json

from scripts.nav_bench import score


def _question(qid="Q1", expected=None, scored=True):
    return {
        "id": qid,
        "question": "?",
        "expected": expected if expected is not None else [{"path": "pkg/mod.py", "line": 100, "symbol": None}],
        "scored": scored,
    }


def _text(qid, locations, confidence):
    answer = {"id": qid, "answer": "x", "locations": locations, "confidence": confidence}
    return "{}\n".format(json.dumps(answer))


def test_hit_within_three_lines_miss_at_four():
    q = [_question()]
    for line, want in [(103, 1), (97, 1), (100, 1), (104, 0), (96, 0)]:
        result = score.score_run(q, _text("Q1", [f"pkg/mod.py:{line}"], "unsure"))
        assert result["hits"] == want, f"line {line}"


def test_sure_without_match_is_false_address():
    result = score.score_run([_question()], _text("Q1", ["pkg/mod.py:200"], "sure"))
    assert result["per_question"][0]["verdict"] == "false"
    assert (result["hits"], result["false"]) == (0, 1)


def test_unsure_without_match_is_miss():
    for confidence in ("unsure", "unknown"):
        result = score.score_run([_question()], _text("Q1", ["pkg/mod.py:200"], confidence))
        assert result["per_question"][0]["verdict"] == "miss"
        assert (result["hits"], result["false"]) == (0, 0)


def test_null_line_matches_by_path():
    q = [_question(expected=[{"path": "pkg/test_x.py", "line": None, "symbol": None}])]
    assert score.score_run(q, _text("Q1", ["pkg/test_x.py:999"], "sure"))["hits"] == 1
    assert score.score_run(q, _text("Q1", ["pkg/test_x.py"], "sure"))["hits"] == 1
    assert score.score_run(q, _text("Q1", ["pkg\\test_x.py:5"], "sure"))["hits"] == 1  # обратные слэши
    other = score.score_run(q, _text("Q1", ["pkg/other.py:5"], "sure"))
    assert (other["hits"], other["false"]) == (0, 1)


def test_tolerant_parse_fenced_and_malformed():
    text = (
        "Here are my answers:\n"
        "```json\n"
        '{"id": "Q1", "answer": "abc", "locations": ["pkg/mod.py:100"], "confidence": "sure"}\n'
        "```\n"
        "prose {not json} between\n"
        '{"id": "Q2", "answer": "cut off", "locations": ["pkg/mod.py:1"\n'  # битый: обрыв
        '{"id": "Q3", "answer": "multi",\n "locations": ["pkg/mod.py:7"],\n "confidence": "unsure"}\n'
        '{"id": "Q4", "locations": "not-a-list", "confidence": "very sure"}\n'
    )
    answers = score.parse_answers(text)
    assert sorted(answers) == ["q1", "q3", "q4"]
    assert answers["q1"]["locations"] == ["pkg/mod.py:100"] and answers["q1"]["confidence"] == "sure"
    assert answers["q3"]["locations"] == ["pkg/mod.py:7"]  # многострочный объект разобран
    assert answers["q4"]["locations"] == [] and answers["q4"]["confidence"] == "unknown"
    questions = [_question(f"Q{i}") for i in (1, 2, 3, 4)]
    result = score.score_run(questions, text)
    # Q2 (битый) — нет ответа, считается unknown/miss, а не ложным адресом
    assert [row["verdict"] for row in result["per_question"]] == ["hit", "miss", "miss", "miss"]
    assert result["per_question"][1]["confidence"] == "unknown"
    assert score.parse_answers("no json here at all") == {}


def test_unscored_excluded_from_threshold_counted_in_totals():
    questions = [_question("Q1"), _question("Q2", scored=False), _question("Q3", scored=False)]
    text = (
        _text("Q1", ["pkg/mod.py:100"], "sure")
        + _text("Q2", ["pkg/mod.py:100"], "sure")  # hit на неоцениваемом
        + _text("Q3", ["pkg/mod.py:500"], "sure")  # ложный адрес на неоцениваемом
    )
    result = score.score_run(questions, text)
    assert (result["hits"], result["false"], result["scored"]) == (1, 0, 1)
    assert (result["total_hits"], result["total_false"], result["total"]) == (2, 1, 3)


def test_absolute_path_prefix_is_stripped():
    q = [_question()]
    text = _text("Q1", ["D:/repo/root/pkg/mod.py:101"], "sure")
    assert score.score_run(q, text)["hits"] == 0  # без префикса путь чужой
    assert score.score_run(q, text, prefixes=("D:\\repo\\root",))["hits"] == 1


def _hits(questions, text):
    return score.score_run(questions, text)["hits"]


def test_require_all_needs_every_expected():
    expected = [{"path": "a.py", "line": 10, "symbol": None}, {"path": "b.py", "line": 20, "symbol": None}]
    need_all = [{**_question(expected=expected), "require": "all"}]
    need_any = [_question(expected=expected)]
    one = _text("Q1", ["a.py:10"], "unsure")
    both = _text("Q1", ["a.py:10", "b.py:21"], "unsure")
    assert (_hits(need_all, one), _hits(need_all, both)) == (0, 1)
    assert (_hits(need_any, one), _hits(need_any, both)) == (1, 1)
    # неполное совпадение при sure без постороннего адреса — miss, не ложный адрес
    partial = score.score_run(need_all, _text("Q1", ["a.py:10"], "sure"))
    assert partial["per_question"][0]["verdict"] == "miss" and partial["false"] == 0


def test_tolerance_zero_separates_adjacent_symbols():
    strict = [_question(expected=[{"path": "i.py", "line": 17, "symbol": None, "tolerance": 0}])]
    assert [_hits(strict, _text("Q1", [f"i.py:{n}"], "unsure")) for n in (17, 18, 20, 16)] == [1, 0, 0, 0]
    loose = [_question(expected=[{"path": "i.py", "line": 17, "symbol": None}])]  # по умолчанию ±3
    assert [_hits(loose, _text("Q1", [f"i.py:{n}"], "unsure")) for n in (20, 21)] == [1, 0]


def test_extra_locations_over_cap_are_false():
    q = [_question()]  # один эталон -> учитываются первые 2 адреса
    shotgun = ["x.py:1", "x.py:2", "pkg/mod.py:100"]  # верный — третий, за потолком
    sure = score.score_run(q, _text("Q1", shotgun, "sure"))
    assert sure["per_question"][0]["verdict"] == "false" and sure["false"] == 1
    assert score.score_run(q, _text("Q1", shotgun, "unsure"))["per_question"][0]["verdict"] == "miss"
    within = score.score_run(q, _text("Q1", ["x.py:1", "pkg/mod.py:100"], "sure"))  # второй — в пределах потолка
    assert within["per_question"][0]["verdict"] == "hit"


def test_range_intersecting_window_is_hit():
    q = [_question()]  # окно 97..103
    cases = {"90-97": 1, "103-120": 1, "50-200": 1, "98-99": 1, "90-96": 0, "104-120": 0}
    for rng, want in cases.items():
        assert _hits(q, _text("Q1", [f"pkg/mod.py:{rng}"], "unsure")) == want, rng
    assert score.parse_location_range("a/b.py:12-20") == ("a/b.py", 12, 20)
    assert score.parse_location_range("a/b.py:12") == ("a/b.py", 12, 12)


def _answer(qid, text, confidence="unsure"):
    return json.dumps({"id": qid, "answer": text, "locations": [], "confidence": confidence}) + "\n"


def test_facts_any_of_casefold_and_require_all():
    facts = [{"any_of": ["Router Manager", "routermanager"]}, {"any_of": ["queue"]}]
    q_all = [{"id": "Q1", "question": "?", "expected_facts": facts, "scored": True}]
    q_any = [{**q_all[0], "facts_require": "any"}]
    both = _answer("Q1", "The ROUTERMANAGER writes into a Queue")
    only_queue = _answer("Q1", "just a queue")
    result = score.score_run(q_all, both)
    assert result["per_question"][0]["facts"] == "hit" and (result["facts_hit"], result["facts_scored"]) == (1, 1)
    assert result["per_question"][0]["verdict"] == "n/a" and (result["hits"], result["scored"]) == (0, 0)
    assert score.score_run(q_all, only_queue)["facts_hit"] == 0  # require all: не хватает первого факта
    assert score.score_run(q_any, only_queue)["facts_hit"] == 1  # require any: хватает второго
    assert score.score_run(q_all, "")["per_question"][0]["facts"] == "miss"


def test_last_answer_id_wins():
    q = [_question()]
    wrong_then_right = _text("Q1", ["pkg/mod.py:1"], "sure") + _text("Q1", ["pkg/mod.py:100"], "sure")
    right_then_wrong = _text("Q1", ["pkg/mod.py:100"], "sure") + _text("Q1", ["pkg/mod.py:1"], "sure")
    assert (_hits(q, wrong_then_right), score.score_run(q, wrong_then_right)["false"]) == (1, 0)
    assert (_hits(q, right_then_wrong), score.score_run(q, right_then_wrong)["false"]) == (0, 1)


def test_confidence_casefold_unknown_values_and_sure_without_locations():
    q = [_question()]
    assert score.score_run(q, _text("Q1", ["pkg/mod.py:200"], " SURE "))["false"] == 1  # регистр и пробелы
    high = score.score_run(q, _text("Q1", ["pkg/mod.py:200"], "high"))  # синонимов нет: high = unknown
    assert (high["false"], high["per_question"][0]["confidence"]) == (0, "unknown")
    empty = score.score_run(q, _text("Q1", [], "sure"))  # sure без адресов — miss
    assert (empty["per_question"][0]["verdict"], empty["false"]) == ("miss", 0)
