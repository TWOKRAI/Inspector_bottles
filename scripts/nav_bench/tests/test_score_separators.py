"""Тесты границ заявки: разделители пути («;», перевод строки, «,» с пробелом), «голая» запятая, колонки."""

from scripts.nav_bench import score


def test_path_cut_by_each_separator():
    assert score.parse_claims("a.py, b.py:7") == [("b.py", 7, 7)]
    assert score.parse_claims("a.py; b.py:7") == [("b.py", 7, 7)]
    assert score.parse_claims("a.py;b.py:7") == [("b.py", 7, 7)]
    assert score.parse_claims("a.py\nb.py:7") == [("b.py", 7, 7)]
    assert score.parse_claims("a.py,\tb.py:7") == [("b.py", 7, 7)]
    assert score.parse_claims("x.py:3, a.py, b.py:7") == [("x.py", 3, 3), ("b.py", 7, 7)]
    assert score.parse_claims("x.py:3; a.py; b.py:7") == [("x.py", 3, 3), ("b.py", 7, 7)]
    assert score.parse_claims("x.py:3\na.py\nb.py:7") == [("x.py", 3, 3), ("b.py", 7, 7)]
    entry = {"path": "b.py", "line": 7}
    assert score.location_matches("a.py, b.py:7", entry) is True


def test_bare_comma_stays_in_path_documented_boundary():
    assert score.parse_claims("a.py,b.py:7") == [("a.py,b.py", 7, 7)]  # неразрешимо: путь с запятой
    assert score.location_matches("a.py,b.py:7", {"path": "b.py", "line": 7}) is False
    assert score.parse_claims("dir/a,b.py:5") == [("dir/a,b.py", 5, 5)]
    assert score.parse_claims("pkg:2/a.py:5") == [("pkg:2/a.py", 5, 5)]
    assert score.parse_claims("http://h:8080/a.py:12") == [("http://h:8080/a.py", 12, 12)]
    assert score.parse_claims("C:2024/a.py:5") == [("C:2024/a.py", 5, 5)]


def test_cut_prefix_with_digits_is_reported_as_unparsed():
    assert score.unparsed("a.py:3 x, b.py:7") == []  # «a.py:3 x» - заявка 3, остаток «x» без цифр
    assert score.unparsed("v2.py, b.py:7") == ["v2.py"]  # отрезанный путь с цифрой не теряется молча


def test_two_columns_are_allowed_third_is_leftover():
    assert score.parse_claims("a.py:12:5:7") == [("a.py", 12, 12)]
    assert score.unparsed("a.py:12:5:7") == []
    assert score.parse_claims("a.py:12:5:7:9") == [("a.py", 12, 12)]
    assert score.unparsed("a.py:12:5:7:9") == [":9"]
