"""Тесты грамматики адреса ``путь:строки`` (списки, диапазоны, колонки, Windows-пути, мусор). Ожидания — литералы."""

import json
import re
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scripts.nav_bench import score

REPO = Path(__file__).resolve().parents[3]
PILOT_A = (
    REPO / "plans/2026-11-06_atlas-passport/reports/pilot-2026-11-11/records/2026-11-11_fw2-pilot_grep-read-pilot.json"
)


def _exp(line=55, path="a.py"):
    return {"path": path, "line": line, "symbol": None}


def _match(location, line, path="a.py", prefixes=()):
    return score.location_matches(location, _exp(line, path), prefixes=prefixes)


def _question(expected, require="any"):
    return {"id": "Q1", "question": "?", "expected": expected, "require": require, "scored": True}


def _verdict(question, locations, confidence="sure"):
    answer = {"id": "Q1", "answer": "x", "locations": locations, "confidence": confidence}
    return score.score_run([question], json.dumps(answer))["per_question"][0]["verdict"]


# --- список строк: hit по любому элементу, окно ±3 ---------------------------------------------------------


def test_list_hits_by_any_item():
    assert _match("a.py:52,289-327", 55) is True  # 52 в окне 52..58
    assert _match("a.py:52,289-327", 300) is True  # диапазон 289-327 накрывает 300
    assert _match("a.py:52,289-327", 100) is False  # ни 52, ни 289-327 не близко
    assert _match("a.py:52,289-327", 49) is True  # 52 - 3 = 49: граница окна
    assert _match("a.py:52,289-327", 48) is False
    assert _match("a.py:52,289-327", 330) is True  # 327 + 3
    assert _match("a.py:52,289-327", 331) is False


def test_list_range_touching_window_edge_only():
    assert _match("a.py:1,40-52", 55) is True  # 52 касается окна 52..58
    assert _match("a.py:1,40-51", 55) is False


def test_list_with_spaces_after_commas():
    assert score.parse_claims("a.py:52, 289-327,  411-496") == [
        ("a.py", 52, 52),
        ("a.py", 289, 327),
        ("a.py", 411, 496),
    ]
    assert _match("a.py:52, 289-327", 300) is True


def test_en_dash_range():
    assert score.parse_claims("a.py:10\u201315") == [("a.py", 10, 15)]


# --- мусор и вырожденные записи: не падаем -----------------------------------------------------------------


def test_junk_in_list_keeps_valid_prefix():
    assert score.parse_claims("a.py:52,abc,10-") == [("a.py", 52, 52)]
    assert _match("a.py:52,abc,10-", 55) is True


def test_degenerate_inputs_do_not_raise():
    assert score.parse_claims("a.py:12-") == [("a.py", 12, 12)]  # обрыв диапазона: одна строка 12
    assert score.parse_claims("") == [("", None, None)]
    assert score.parse_claims("   ") == [("", None, None)]
    assert score.parse_claims("a.py:") == [("a.py:", None, None)]
    assert score.parse_claims("a.py:abc") == [("a.py:abc", None, None)]
    assert score.parse_claims("a.py:,") == [("a.py:,", None, None)]
    assert _match("a.py:12-", 12) is True
    assert _match("", 12) is False
    assert score.parse_location_range("") == ("", None, None)
    assert score.parse_location("a.py:12-") == ("a.py", 12)


def test_descending_range_is_swapped():
    assert score.parse_claims("a.py:10-5") == [("a.py", 5, 10)]
    assert _match("a.py:10-5", 12) is True  # 5..10 против окна 9..15
    assert _match("a.py:10-5", 14) is False  # окно 11..17


def test_numbers_without_path_are_not_addresses():
    assert score.parse_claims(":12") == [(":12", None, None)]
    assert score.parse_claims("52,289-327") == [("52,289-327", None, None)]
    assert _match("52,289-327", 52) is False
    assert _match(":12", 12) is False
    # цифры без пути не прилипают к соседней заявке с путём
    assert score.parse_claims("a.py:5, 7, :9") == [("a.py", 5, 5), ("a.py", 7, 7)]


def test_path_only_when_expected_has_no_line():
    entry = {"path": "a.py", "line": None, "symbol": None}
    assert score.location_matches("a.py", entry) is True
    assert score.location_matches("a.py:99", entry) is True
    assert score.location_matches("b.py:99", entry) is False


# --- колонка, Windows-пути, префиксы -----------------------------------------------------------------------


def test_column_is_not_a_line():
    assert score.parse_claims("a.py:12:34") == [("a.py", 12, 12)]
    assert _match("a.py:12:34", 34) is False  # 34 - колонка: ложного попадания нет
    assert _match("a.py:12:34", 12) is True
    assert score.parse_claims("a.py:12:5, b.py:20-25") == [("a.py", 12, 12), ("b.py", 20, 25)]
    assert score.parse_claims("a.py:12:5,20-25") == [("a.py", 12, 12)]  # список после колонки - не грамматика, мусор


def test_windows_drive_path_with_colon():
    assert score.parse_claims("C:\\repo\\pkg\\a.py:12") == [("C:/repo/pkg/a.py", 12, 12)]
    assert score.parse_claims("C:\\repo\\a.py:12-14,40:3") == [("C:/repo/a.py", 12, 14), ("C:/repo/a.py", 40, 40)]
    assert _match("C:\\repo\\pkg\\a.py:12", 12, path="pkg/a.py", prefixes=("C:\\repo",)) is True
    assert _match("C:\\repo\\pkg\\a.py:12", 12, path="pkg/a.py") is False  # без префикса путь другой


def test_quotes_and_backticks_stripped():
    assert score.parse_claims("`a.py:12`") == [("a.py", 12, 12)]
    assert score.parse_claims('"a.py":12') == [("a.py", 12, 12)]


# --- несколько адресов в одной строке; повторы -------------------------------------------------------------


def test_several_addresses_in_one_string():
    assert score.parse_claims("a.py:5,6; b.py:10-12") == [("a.py", 5, 5), ("a.py", 6, 6), ("b.py", 10, 12)]
    assert score.parse_claims("a.py:5, b.py:7") == [("a.py", 5, 5), ("b.py", 7, 7)]
    assert score.parse_claims("a.py:5 b.py:7") == [("a.py", 5, 5), ("b.py", 7, 7)]
    assert score.parse_claims("a.py:5\nb.py:7") == [("a.py", 5, 5), ("b.py", 7, 7)]
    assert _match("a.py:5; b.py:70", 70, path="b.py") is True
    assert _match("a.py:5; b.py:70", 70, path="a.py") is False  # строка 70 принадлежит b.py, не a.py


def test_repeated_claim_in_one_string_collapses():
    assert score.parse_claims("a.py:5,5,5-5") == [("a.py", 5, 5)]
    assert score.parse_claims("a.py:5,6,5") == [("a.py", 5, 5), ("a.py", 6, 6)]


# --- прежнее поведение одиночных адресов -------------------------------------------------------------------


def test_single_address_unchanged():
    assert score.parse_claims("a.py:52") == [("a.py", 52, 52)]
    assert score.parse_claims("a.py:50-60") == [("a.py", 50, 60)]
    assert score.parse_location_range("a/b.py:12-20") == ("a/b.py", 12, 20)
    assert score.parse_location_range("a/b.py:12") == ("a/b.py", 12, 12)
    assert score.parse_location_range("a/b.py") == ("a/b.py", None, None)
    assert score.parse_location_range("./a/b.py:7") == ("a/b.py", 7, 7)
    assert _match("a.py:52", 55) is True
    assert _match("a.py:52", 56) is False
    assert _match("a.py:50-60", 55) is True
    assert _match("a.py:50-60", 64) is False
    assert _match("a.py:50-60", 63) is True


# --- classify: заявка = адрес (потолок, ложные) ------------------------------------------------------------


def test_list_equals_separate_strings():
    q = _question([_exp(52), _exp(300)], require="all")
    together = _verdict(q, ["a.py:52,289-327"])
    apart = _verdict(q, ["a.py:52", "a.py:289-327"])
    assert (together, apart) == ("hit", "hit")


def test_stray_claim_inside_list_counts_like_separate_address():
    q = _question([_exp(52), _exp(300)], require="all")  # потолок 3 заявки
    assert _verdict(q, ["a.py:52,900"], "sure") == "false"  # 300 не закрыт, 900 - лишняя заявка
    assert _verdict(q, ["a.py:52", "a.py:900"], "sure") == "false"  # ровно то же отдельными строками
    assert _verdict(q, ["a.py:52,900"], "unsure") == "miss"
    assert _verdict(q, ["a.py:52,300,900"], "sure") == "hit"  # одна лишняя заявка в пределах потолка hit не лишает


def test_list_does_not_bypass_ceiling():
    q = _question([_exp(55)])  # потолок: 2 заявки
    assert _verdict(q, ["a.py:55,900"], "unsure") == "hit"  # в пределах потолка
    assert _verdict(q, ["a.py:54,55,56"], "sure") == "false"  # три заявки > потолка, хотя строка одна
    assert _verdict(q, ["a.py:54,55,56"], "unsure") == "miss"
    assert _verdict(q, ["a.py:54", "a.py:55", "a.py:56"], "sure") == "false"  # эквивалентно отдельным строкам


def test_require_all_with_lists():
    q = _question([_exp(52), _exp(300)], require="all")
    assert _verdict(q, ["a.py:52,289-327"]) == "hit"
    assert _verdict(q, ["a.py:52,100"], "sure") == "false"  # 300 не закрыт, 100 лишний
    assert _verdict(q, ["a.py:52"], "unsure") == "miss"


# --- запись пилота: A r1 (grep-read), списки строк ---------------------------------------------------------


@pytest.mark.skipif(not PILOT_A.exists(), reason="запись пилота не в этой копии репозитория")
def test_pilot_a_repeat1_lists_are_recognized():
    record = json.loads(PILOT_A.read_text(encoding="utf-8"))
    repeat = record["repeats"][0]
    prefixes = tuple(record["prefixes"])
    result = score.score_run(record["questions"], repeat["final_text"], prefixes)
    verdicts = {row["id"]: row["verdict"] for row in result["per_question"]}
    # до правки: G9 miss (blueprint.py:54-71,342-352 считался путём), G11 false (layout_controller.py:52,289-327,...)
    assert verdicts == {"G1": "miss", "G3": "hit", "G5": "false", "G7": "false", "G9": "hit", "G11": "hit"}
    assert (result["hits"], result["false"]) == (3, 2)
    # адресов эталона найдено (каждая запись отдельно): было 11 из 22
    found = sum(
        any(score.location_matches(loc, entry, prefixes=prefixes) for loc in _locations(repeat, question["id"]))
        for question in record["questions"]
        for entry in question["expected"]
    )
    assert found == 19


def _locations(repeat, qid):
    return next(row["locations"] for row in repeat["score"]["per_question"] if row["id"] == qid)


# --- свойства (Hypothesis) ---------------------------------------------------------------------------------

_SEGMENT = st.text(alphabet="abcdxyz_", min_size=1, max_size=6)
_PATHS = st.builds(
    lambda drive, parts, ext: drive + "/".join(parts) + ext,
    st.sampled_from(["", "./", "C:\\"]),
    st.lists(_SEGMENT, min_size=1, max_size=3),
    st.sampled_from([".py", ".md", ""]),
)
_LINE = st.integers(min_value=0, max_value=100_000)
_ITEMS = st.lists(
    st.one_of(
        _LINE.map(lambda n: (n, n, str(n))), st.tuples(_LINE, _LINE).map(lambda t: (min(t), max(t), f"{t[0]}-{t[1]}"))
    ),
    min_size=1,
    max_size=8,
)


@settings(max_examples=300, deadline=None)
@given(path=_PATHS, items=_ITEMS, space=st.sampled_from(["", " "]), dash=st.sampled_from(["-", "\u2013"]))
def test_property_list_round_trip(path, items, space, dash):
    """Форматирование списка ``путь:N,M-K,…`` и разбор дают то же множество строк (порядок и повторы схлопнуты)."""
    text = path + ":" + ("," + space).join(spec.replace("-", dash) for _, _, spec in items)
    expected = list(dict.fromkeys((score.normalize_path(path), lo, hi) for lo, hi, _ in items))
    assert score.parse_claims(text) == expected


def _old_parse_location_range(text):
    """Копия разбора до правки (эталон поведения для строк без списков), прежние регэкспы - литералом."""
    raw = text.strip().strip("`'\"")
    found = re.match(r"^(?P<path>.+?):(?P<start>\d+)(?:[-–](?P<end>\d+))?(?:[:,]\d+)*(?:[-–]\d+)?$", raw)
    if found is None:
        return score.normalize_path(raw), None, None
    start = int(found.group("start"))
    end = int(found.group("end")) if found.group("end") else start
    return score.normalize_path(found.group("path")), min(start, end), max(start, end)


@settings(max_examples=300, deadline=None)
@given(
    path=_PATHS,
    lines=st.one_of(st.none(), st.tuples(_LINE, st.one_of(st.none(), _LINE), st.one_of(st.none(), _LINE))),
    expected_line=_LINE,
)
def test_property_no_list_parsing_equals_old(path, lines, expected_line):
    """Строки без списков (``путь``, ``путь:N``, ``путь:N-M``, ``путь:N:колонка``) разбираются как до правки."""
    text = path
    if lines is not None:
        first, last, column = lines
        text += f":{first}" + (f"-{last}" if last is not None else "") + (f":{column}" if column is not None else "")
    assert score.parse_location_range(text) == _old_parse_location_range(text)
    old_start, old_end = _old_parse_location_range(text)[1:]
    old_hit = old_start is not None and old_start <= expected_line + 3 and old_end >= expected_line - 3
    assert score.location_matches(text, {"path": path, "line": expected_line}) is old_hit
