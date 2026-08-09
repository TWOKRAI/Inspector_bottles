"""
Тесты среза графа. Работают на синтетическом мини-графе — не на реальном
`graphify-out/graph.json`, чтобы результат не зависел от даты последней сборки.

Четыре теста — регрессы на дефекты, найденные при первом прогоне инструмента:
направление стрелки, ложный ноль у `--symbol`, парсинг `git status --porcelain`
и обрезка вывода в `_git`, которая этот парсинг и ломала.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import graph_slice  # noqa: E402


FRAMEWORK = "multiprocess_framework/modules"


def node(node_id: str, label: str, path: str) -> dict:
    return {"id": node_id, "label": label, "source_file": path, "metadata": {}}


def link(source: str, target: str, relation: str, path: str = "", loc: str = "L1") -> dict:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "source_file": path,
        "source_location": loc,
    }


@pytest.fixture
def graph(tmp_path: Path) -> Path:
    """Мини-граф: alpha_module с одним классом, методом, README и двумя соседями."""
    payload = {
        "built_at_commit": "deadbeef" * 5,
        "nodes": [
            node("alpha_mgr", "AlphaManager", f"{FRAMEWORK}/alpha_module/core/mgr.py"),
            node("alpha_flush", ".flush()", f"{FRAMEWORK}/alpha_module/core/mgr.py"),
            node("alpha_readme", "Архитектура", f"{FRAMEWORK}/alpha_module/README.md"),
            node("beta_mgr", "BetaManager", f"{FRAMEWORK}/beta_module/core/beta.py"),
            node("svc_sql", "SQLManager", "Services/sql/manager.py"),
            node("beta_adr", "Решение ADR-42", f"{FRAMEWORK}/beta_module/DECISIONS.md"),
            node("stdlib_abc", "ABC", ""),
        ],
        "links": [
            # внутреннее: класс владеет методом
            link("alpha_mgr", "alpha_flush", "method", f"{FRAMEWORK}/alpha_module/core/mgr.py"),
            # входящее: сосед наследует класс модуля
            link("beta_mgr", "alpha_mgr", "inherits", f"{FRAMEWORK}/beta_module/core/beta.py"),
            link("svc_sql", "alpha_mgr", "calls", "Services/sql/manager.py"),
            # исходящее: модуль зависит от внешнего символа
            link("alpha_mgr", "stdlib_abc", "inherits", f"{FRAMEWORK}/alpha_module/core/mgr.py"),
            # документальные рёбра — по умолчанию не считаются:
            # своё (внутри модуля) и чужое (через границу, из ADR соседа)
            link("alpha_readme", "alpha_mgr", "rationale_for", f"{FRAMEWORK}/alpha_module/README.md"),
            link("beta_adr", "alpha_mgr", "rationale_for", f"{FRAMEWORK}/beta_module/DECISIONS.md"),
        ],
    }
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def run(graph: Path, *args: str, capsys) -> str:
    code = graph_slice.main([*args, "--graph", str(graph)])
    assert code == 0, f"ненулевой код возврата: {code}"
    return capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Границы
# --------------------------------------------------------------------------- #


def test_boundary_split(graph: Path, capsys):
    """Рёбра раскладываются по трём корзинам относительно границы модуля."""
    payload = json.loads(run(graph, "alpha_module", "--format", "json", capsys=capsys))
    assert payload["counts"] == {"nodes": 2, "inner": 1, "inbound": 2, "outbound": 1}
    assert payload["dependent_modules"] == {"beta_module": 1, "Services/sql": 1}


def test_docs_excluded_by_default(graph: Path, capsys):
    """
    README-узлы забивают выдачу (в error_module их 38 против 49 узлов кода),
    поэтому по умолчанию ни .md-узлов, ни рёбер `rationale_for` в срезе нет.
    С `--docs` возвращаются оба: свой README уходит во внутренние связи,
    ADR соседа — во входящие.
    """
    default = json.loads(run(graph, "alpha_module", "--format", "json", capsys=capsys))
    with_docs = json.loads(run(graph, "alpha_module", "--docs", "--format", "json", capsys=capsys))
    assert default["counts"] == {"nodes": 2, "inner": 1, "inbound": 2, "outbound": 1}
    assert with_docs["counts"] == {"nodes": 3, "inner": 2, "inbound": 3, "outbound": 1}
    assert "beta_module" in with_docs["dependent_modules"]


def test_external_symbols_grouped_apart(graph: Path, capsys):
    """Узлы без файла (ABC, Any) — не «неизвестный модуль», а отдельная группа."""
    out = run(graph, "alpha_module", capsys=capsys)
    assert "<внешние символы>" in out


# --------------------------------------------------------------------------- #
# Регрессы на найденные дефекты
# --------------------------------------------------------------------------- #


def test_arrow_follows_edge_direction(graph: Path, capsys):
    """
    Регресс: в секции «наружу» стрелка печаталась задом наперёд
    (`ABC → AlphaManager` вместо `AlphaManager → ABC`).
    """
    out = run(graph, "alpha_module", capsys=capsys)
    assert "AlphaManager → ABC" in out
    assert "ABC → AlphaManager" not in out


def test_symbol_without_inbound_warns_about_owner(graph: Path, capsys):
    """
    Регресс: у метода прямых входящих рёбер нет (граф вешает вызовы на класс),
    и голый ноль читался как «никто не зависит». Должна быть явная оговорка
    с именем владельца и числом его входящих.
    """
    out = run(graph, "alpha_module", "--symbol", ".flush()", capsys=capsys)
    assert "НЕ значит «никто не зависит»" in out
    assert "--symbol AlphaManager" in out
    assert "входящих у владельца: 2" in out


def test_porcelain_path_not_truncated(graph: Path, capsys, monkeypatch):
    """
    Регресс: путь из `git status --porcelain` резался фиксированным срезом
    и терял первый символ (`ultiprocess_framework/...`).

    Первая строка подаётся БЕЗ ведущего пробела — именно так выглядел вход в
    проде, потому что `_git` обрезал вывод целиком. Со строкой вида " M path"
    сломанный срез `line[3:]` случайно давал верный ответ, и тест был зелёным
    при возвращённом баге — это выяснилось break-injection'ом.
    """
    prefix = f"{FRAMEWORK}/alpha_module"
    changed = f"{prefix}/core/mgr.py"
    added = f"{prefix}/core/extra.py"

    def fake_git(*args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return "cafebabe" * 5
        if args[0] == "status":
            return f"M {changed}\n?? {added}"
        if args[0] == "diff":
            return ""
        return ""

    monkeypatch.setattr(graph_slice, "_git", fake_git)
    info = graph_slice.freshness("deadbeef" * 5, prefix)
    assert info["uncommitted"] == [changed, added]
    assert info["stale"] is True


def test_git_output_keeps_leading_space(monkeypatch):
    """
    Корень того же дефекта: `_git` обрезал вывод целиком и съедал ведущий
    пробел статуса. Обрезаться должны только переводы строк.
    """

    class FakeCompleted:
        returncode = 0
        stdout = " M path/to/file.py\n"

    monkeypatch.setattr(graph_slice.subprocess, "run", lambda *a, **kw: FakeCompleted())
    assert graph_slice._git("status", "--porcelain") == " M path/to/file.py"


def test_test_files_do_not_make_slice_stale(monkeypatch):
    """Тесты исключены из графа — их правка не делает срез устаревшим."""
    prefix = f"{FRAMEWORK}/alpha_module"

    def fake_git(*args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return "cafebabe" * 5
        if args[0] == "diff":
            return f"{prefix}/tests/test_alpha.py"
        if args[0] == "status":
            return ""
        return ""

    monkeypatch.setattr(graph_slice, "_git", fake_git)
    info = graph_slice.freshness("deadbeef" * 5, prefix)
    assert info["changed_since_build"] == []
    assert info["stale"] is False


# --------------------------------------------------------------------------- #
# Разрешение целей
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (f"{FRAMEWORK}/alpha_module/core/mgr.py", "alpha_module"),
        ("Services/sql/manager.py", "Services/sql"),
        ("Plugins/processing/blur.py", "Plugins/processing"),
        ("multiprocess_prototype/frontend/app.py", "multiprocess_prototype/frontend"),
        ("", "<без файла>"),
    ],
)
def test_module_of(path: str, expected: str):
    assert graph_slice.module_of(path) == expected


def test_target_accepts_path_prefix(graph: Path, capsys):
    """Целью может быть и произвольный префикс пути, не только имя модуля."""
    by_name = json.loads(run(graph, "alpha_module", "--format", "json", capsys=capsys))
    by_path = json.loads(run(graph, f"{FRAMEWORK}/alpha_module", "--format", "json", capsys=capsys))
    assert by_name["counts"] == by_path["counts"]


def test_unknown_target_exits_with_hint(graph: Path, capsys):
    """Опечатка в имени — код возврата 2 и подсказка с похожим именем."""
    assert graph_slice.main(["alpha_modul", "--graph", str(graph)]) == 2
    assert "Похожие: alpha_module" in capsys.readouterr().err
