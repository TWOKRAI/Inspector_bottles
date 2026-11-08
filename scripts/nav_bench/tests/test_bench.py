"""Тесты CLI, запуска и статистики nav_bench. Ожидаемые значения — литералы; сессии claude — двойники."""

import functools
import io
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from scripts.nav_bench import bench, score

PKG = Path(__file__).resolve().parent.parent
K0 = PKG / "questions" / "k0.json"
ARCH = PKG / "questions" / "arch.json"
GREP_READ = PKG / "conditions" / "grep-read.json"
SOURCE_ONLY = PKG / "conditions" / "source-only.json"  # алиас прежнего имени
MAP_ONLY = PKG / "conditions" / "map-only.json"
QEX = PKG / "conditions" / "qex.json"
GRAPHIFY = PKG / "conditions" / "graphify.json"
GREP_READ_GIT = PKG / "conditions" / "grep-read+git.json"

R = "multiprocess_framework/modules/"
# Ответ агента на K0: Q1 и Q2 — оба верных адреса (require all), Q3 — «sure» мимо, остальные не отвечены.
ANSWERS = "\n".join(
    json.dumps(item)
    for item in (
        {
            "id": "Q1",
            "answer": "ABC",
            "locations": [R + "router_module/interfaces.py:22", R + "router_module/core/router_manager.py:130"],
            "confidence": "sure",
        },
        {
            "id": "Q2",
            "answer": "ABC",
            "locations": [R + "config_module/interfaces.py:20", R + "config_module/core/config.py:27"],
            "confidence": "unsure",
        },
        {"id": "Q3", "answer": "wrong", "locations": [R + "config_module/interfaces.py:60"], "confidence": "sure"},
    )
)

LAST_USAGE = {
    "input_tokens": 50,
    "cache_creation_input_tokens": 100,
    "cache_read_input_tokens": 700,
    "output_tokens": 9,
}


def _stream(
    tool_uses,
    text=ANSWERS,
    usage=None,
    turns=4,
    duration_ms=12500,
    result_text=None,
    subtype="success",
    is_error=False,
):
    """Вывод ``--output-format stream-json``: события assistant с tool_use и итоговое result."""
    events = [{"type": "system", "subtype": "init"}]
    for name, target in tool_uses:
        key = {"Read": "file_path", "Bash": "command"}.get(name, "pattern")
        block = {"type": "tool_use", "name": name, "input": {key: target}}
        events.append({"type": "assistant", "message": {"content": [block]}})
    events.append({"type": "assistant", "message": {"content": [{"type": "text", "text": text}], "usage": LAST_USAGE}})
    events.append(
        {
            "type": "result",
            "subtype": subtype,
            "is_error": is_error,
            "num_turns": turns,
            "duration_ms": duration_ms,
            "total_cost_usd": 0.05,
            "result": text if result_text is None else result_text,
            "usage": usage
            or {
                "input_tokens": 1000,
                "output_tokens": 200,
                "cache_creation_input_tokens": 300,
                "cache_read_input_tokens": 99999,
            },
        }
    )
    return "\n".join(json.dumps(e) for e in events)


class FakeRunner:
    """Двойник сессии claude: запоминает вызовы, отдаёт заранее заданный вывод."""

    def __init__(self, stdout, returncode=0, stderr=""):
        self.calls = []
        self._result = bench.SessionResult(stdout, returncode, 0.01, stderr)

    def __call__(self, cmd, prompt, cwd):
        self.calls.append((cmd, prompt, cwd))
        return self._result


def _run(tmp_path, runner, condition=GREP_READ, questions=K0, **kwargs):
    """run_bench с двойниками: копия — пустой каталог ``tmp_path/run``, git status чист, предпроверки реальные."""
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    out, err = io.StringIO(), io.StringIO()
    code, path = bench.run_bench(
        questions,
        condition,
        kwargs.pop("repeats", 2),
        kwargs.pop("root", tmp_path),
        tmp_path / "out",
        runner=runner,
        copy_fn=kwargs.pop("copy_fn", lambda qset, cond, root, err=None: run_dir),
        dirty_fn=kwargs.pop("dirty_fn", lambda root, paths: []),
        today="2026-11-06",
        out=out,
        err=err,
        **kwargs,
    )
    return code, path, out.getvalue(), err.getvalue()


def _condition_file(tmp_path, **fields):
    data = {"name": "t", "model": "haiku", "allowed_tools": ["Read"], "expected_tokens": 1000, **fields}
    path = tmp_path / "cond.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _baseline_file(tmp_path, set_name="k0", calls=40):
    path = tmp_path / "base.json"
    base = {"set": set_name, "aggregate": {"tool_calls": {"median": calls}, "final_context_tokens": {"median": 100}}}
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


def test_stats_median_bands_and_ratio_literals():
    runs = [
        {"hits": 9, "false": 0, "tool_calls": 12, "final_context_tokens": 40000, "wall_s": 10.0},
        {"hits": 8, "false": 1, "tool_calls": 30, "final_context_tokens": 60000, "wall_s": 20.0},
        {"hits": 10, "false": 0, "tool_calls": 18, "final_context_tokens": 45000, "wall_s": 40.0},
    ]
    agg = score.aggregate(runs)
    assert agg["hits"] == {"min": 8, "median": 9, "max": 10}
    assert agg["false"] == {"min": 0, "median": 0, "max": 1}
    assert agg["tool_calls"] == {"min": 12, "median": 18, "max": 30}
    assert agg["final_context_tokens"] == {"min": 40000, "median": 45000, "max": 60000}
    assert agg["wall_s"] == {"min": 10.0, "median": 20.0, "max": 40.0}
    assert score.verdict(agg)["band"] == "PASS"

    # чётное число повторов — медиана между двумя средними
    assert score.aggregate([{"hits": 8}, {"hits": 9}])["hits"]["median"] == 8.5

    slow = score.aggregate([{**r, "final_context_tokens": t} for r, t in zip(runs, (40000, 60000, 70000))])
    result = score.verdict(slow, {"tokens_median_max": 50000})  # медиана 60000 > 50000, попаданий 8 -> FIX
    assert (result["pass"], result["band"]) == (False, "FIX")
    assert [name for name, c in result["checks"].items() if c["ok"] is False] == ["tokens"]

    # три полосы по худшему повтору: >= 8 PASS, 6-7 FIX, < 6 FAIL
    for hits, band in (((9, 8, 10), "PASS"), ((9, 7, 10), "FIX"), ((9, 6, 10), "FIX"), ((9, 5, 10), "FAIL")):
        agg_h = score.aggregate([{**r, "hits": h} for r, h in zip(runs, hits)])
        assert score.verdict(agg_h)["band"] == band, hits
    weak = score.aggregate([{**r, "hits": h} for r, h in zip(runs, (9, 7, 10))])
    assert score.verdict(weak)["checks"]["hits"] == {"value": 7, "limit": 8, "ok": False}

    flaky = score.aggregate([{**r, "false": f} for r, f in zip(runs, (0, 2, 0))])  # худший повтор 2 > 1
    assert score.verdict(flaky)["checks"]["false"]["ok"] is False
    assert score.verdict(flaky)["band"] == "FIX"

    # относительные пороги к базовой записи; без базы — «не измерено», не молчаливый pass
    ratios = {"calls_ratio_max": 0.5, "tokens_ratio_max": 0.6}
    base = score.aggregate([{"tool_calls": 40, "final_context_tokens": 100000}])
    good = score.verdict(agg, ratios, baseline=base)  # 18/40 = 0.45; 45000/100000 = 0.45
    assert good["band"] == "PASS" and good["checks"]["calls_ratio"]["value"] == 0.45
    heavy = score.aggregate([{"tool_calls": 40, "final_context_tokens": 60000}])
    assert score.verdict(agg, ratios, baseline=heavy)["checks"]["tokens_ratio"]["ok"] is False  # 0.75 > 0.6
    blind = score.verdict(agg, ratios)
    assert blind["unmeasured"] == ["calls_ratio", "tokens_ratio"]


def test_real_run_refused_without_yes(tmp_path):
    runner = FakeRunner(_stream([("Read", "a.py")]))
    code, path, out, err = _run(tmp_path, runner)  # ни dry_run, ни yes
    assert code == 2 and path is None
    assert runner.calls == []
    assert "--yes" in err
    assert not (tmp_path / "out").exists()


def test_budget_and_cost_guards(tmp_path):
    runner = FakeRunner(_stream([("Read", "a.py")]))
    no_budget = _condition_file(tmp_path)  # max_budget_usd не задан
    code, path, out, err = _run(tmp_path, runner, condition=no_budget, yes=True)
    assert code == 2 and runner.calls == [] and "--no-budget" in err
    code, path, out, err = _run(tmp_path, runner, condition=no_budget, yes=True, no_budget=True)
    assert code == 0 and len(runner.calls) == 2  # явное разрешение

    zero = _condition_file(tmp_path, expected_tokens=0, max_budget_usd=1.0)
    code, _, _, err = _run(tmp_path, runner, condition=zero, yes=True)
    assert code == 2 and "expected_tokens" in err

    capped = _condition_file(tmp_path, max_budget_usd=2.5)
    _, _, out, _ = _run(tmp_path, runner, condition=capped, repeats=3, dry_run=True)
    assert "Потолок бюджета: 3 x 2.5 = 7.5 USD" in out


def test_dry_run_launches_nothing(tmp_path):
    runner = FakeRunner("must never be used")
    code, path, out, err = _run(tmp_path, runner, repeats=3, dry_run=True)
    assert code == 0 and path is None
    assert runner.calls == []
    assert not (tmp_path / "out").exists()
    assert "Оценка стоимости: 3 x 85000 = 255000 токенов" in out
    assert "Потолок бюджета: 3 x 1.0 = 3 USD" in out
    assert "[dry-run] чистая копия 1dc6c71b7 (без: scripts/nav_bench, " in out
    assert out.count("[dry-run] повтор") == 3
    assert "claude -p --output-format stream-json --verbose --model haiku" in out


def test_dry_run_through_the_cli_prints_commands_estimate_and_copy_path(capsys, tmp_path):
    code = bench.main(
        [
            "run",
            "--questions",
            str(K0),
            "--condition",
            str(GREP_READ),
            "--repeats",
            "3",
            "--dry-run",
            "--root",
            str(tmp_path),
        ]
    )
    shown = capsys.readouterr()
    assert code == 0
    assert "Оценка стоимости: 3 x 85000 = 255000" in shown.out
    assert "Потолок бюджета" in shown.out
    assert "nav_bench" in shown.out and "1dc6c71b7-" in shown.out  # путь чистой копии
    assert shown.out.count("[dry-run] повтор") == 3


def test_dirty_expected_paths_warn_loudly_but_run(tmp_path):
    runner = FakeRunner(_stream([("Read", "a.py")]))
    dirty = lambda root, paths: [" M " + R + "router_module/interfaces.py"]  # noqa: E731
    code, path, out, err = _run(tmp_path, runner, yes=True, dirty_fn=dirty)
    assert code == 0 and path is not None
    assert "ВНИМАНИЕ" in err and "router_module/interfaces.py" in err


def test_command_flags_literal():
    condition = bench.load_condition(GREP_READ)
    cmd = bench.build_command(condition)
    assert cmd[:7] == ["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", "haiku"]
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob"  # технический предел встроенных инструментов
    assert cmd[cmd.index("--allowedTools") + 1] == "Read,Grep,Glob"
    assert "Bash" in cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert "--strict-mcp-config" in cmd and "--mcp-config" not in cmd  # без MCP вовсе
    assert cmd[cmd.index("--max-budget-usd") + 1] == "1.0"
    assert "--max-turns" not in cmd  # нет в `claude --help`; max_turns проверяется после прогона

    mcp = bench.build_command(bench.load_condition(QEX), mcp_config="C:/x/qex.json", run_root="D:/copy")
    assert mcp[mcp.index("--tools") + 1] == "Read,Grep,Glob"  # mcp__ в --tools не идёт
    assert "mcp__qex__search_code" in mcp[mcp.index("--allowedTools") + 1].split(",")
    assert mcp[mcp.index("--mcp-config") + 1] == "C:/x/qex.json" and "--strict-mcp-config" in mcp
    assert 'path="D:/copy"' in mcp[mcp.index("--append-system-prompt") + 1]


def test_source_only_is_an_alias_of_grep_read():
    assert bench.load_condition(SOURCE_ONLY) == bench.load_condition(GREP_READ)


def test_fake_session_end_to_end_writes_counts(tmp_path):
    uses = [
        ("Read", "multiprocess_framework/x.py"),
        ("Grep", "IRouterManager"),
        ("Read", "multiprocess_framework/y.py"),
    ]
    runner = FakeRunner(_stream(uses))
    code, path, out, err = _run(tmp_path, runner, repeats=2, yes=True)
    assert code == 0
    assert path == tmp_path / "out" / "2026-11-06_k0_grep-read.json"
    assert len(runner.calls) == 2
    assert "Q1: What kind of type is `IRouterManager`" in runner.calls[0][1]  # промпт содержит вопросы
    assert runner.calls[0][2] == tmp_path / "run"  # сессия идёт в чистой копии, не в репозитории

    record = json.loads(path.read_text(encoding="utf-8"))
    first = record["repeats"][0]
    assert (first["tool_calls"], first["turns"], first["wall_s"]) == (3, 4, 12.5)
    assert first["final_context_tokens"] == 850  # 50 + 100 + 700 последнего assistant-события, без output
    assert first["cumulative_tokens"] == 1500  # 1000 + 200 + 300, чтение кэша не входит
    assert first["cache_read_tokens"] == 99999
    assert first["subtype"] == "success"
    assert first["cost_usd"] == 0.05
    assert (first["score"]["hits"], first["score"]["false"], first["score"]["scored"]) == (2, 1, 8)
    assert [r["verdict"] for r in first["score"]["per_question"]][:4] == ["hit", "hit", "false", "miss"]
    assert record["aggregate"]["hits"] == {"min": 2, "median": 2, "max": 2}
    assert record["aggregate"]["tool_calls"]["median"] == 3
    assert record["verdict"]["pass"] is False and record["verdict"]["band"] == "FAIL"  # 2 попадания < 6
    assert record["root"] == str((tmp_path / "run").resolve())

    table = path.with_suffix(".md").read_text(encoding="utf-8")
    assert "| 1 | 2/8 | 1 | 0/0 | 2/10 | 3 | 850 | 1500 | 99999 | 12.5 | 4 | success |" in table
    assert "**Вердикт: FAIL**" in table

    # повторный запуск в тот же день не затирает прошлую запись
    _, second, _, _ = _run(tmp_path, runner, yes=True)
    assert second.name == "2026-11-06_k0_grep-read_2.json"

    # пересчёт по сохранённому тексту даёт ту же таблицу строк повторов
    shown = io.StringIO()
    assert bench.score_command(path, None, out=shown) == 0
    assert "| 1 | 2/8 | 1 | 0/0 | 2/10 | 3 | 850 | 1500 | 99999 | 12.5 | 4 | success |" in shown.getvalue()

    # compare сводит две записи рядом
    side = io.StringIO()
    assert bench.compare_command(path, second, out=side) == 0
    assert "| hits median | 2 | 2 |" in side.getvalue()
    assert "| Q1 | 2/2 | 2/2 |" in side.getvalue()


def test_single_json_output_has_no_tool_call_count():
    parsed = bench.parse_session_output(
        json.dumps(
            {"type": "result", "is_error": False, "num_turns": 7, "result": ANSWERS, "usage": {"input_tokens": 5}}
        )
    )
    assert parsed["tool_calls"] is None  # формат json вызовов не перечисляет
    assert (parsed["turns"], parsed["cumulative_tokens"], parsed["final_context_tokens"]) == (7, 5, None)
    assert parsed["final_text"] == ANSWERS


def test_failed_session_is_recorded_not_raised(tmp_path):
    runner = FakeRunner("", returncode=1, stderr="auth required")
    code, path, out, err = _run(tmp_path, runner, repeats=1, yes=True)
    assert code == 0
    rep = json.loads(path.read_text(encoding="utf-8"))["repeats"][0]
    assert rep["error"] == "auth required" and rep["returncode"] == 1
    assert (rep["score"]["hits"], rep["tool_calls"], rep["final_context_tokens"]) == (0, None, None)
    assert "auth required" in err  # ошибка видна, не проглочена


def test_map_only_audit_flags_reads_outside_context(tmp_path):
    uses = [
        ("Read", "docs/arch-map/units.md"),
        ("Read", "multiprocess_framework/modules/x.py"),
        ("Grep", "IRouterManager"),
    ]
    runner = FakeRunner(_stream(uses))
    _, path, _, _ = _run(
        tmp_path, runner, condition=MAP_ONLY, repeats=1, yes=True, baseline_path=_baseline_file(tmp_path)
    )
    rep = json.loads(path.read_text(encoding="utf-8"))["repeats"][0]
    assert rep["violations"] == ["Read:multiprocess_framework/modules/x.py", "Grep:IRouterManager"]


def test_audit_is_allowlist_and_casefold():
    allowed = ["Read", "Grep", "mcp__qex__search_code"]
    context = ["docs/arch-map/units.md"]
    uses = [
        {"name": "read", "target": "x.py"},  # имя без учёта регистра
        {"name": "mcp__qex__search_code", "target": None},
        {"name": "Bash", "target": "ls"},  # вне списка
        {"name": "mcp__graphify__query_graph", "target": None},  # MCP вне списка
    ]
    assert bench.audit_violations(uses, allowed, context, ()) == ["Bash:ls", "mcp__graphify__query_graph:"]
    reads = [{"name": "Read", "target": "D:\\Run\\Docs\\Arch-Map\\units.md"}, {"name": "Read", "target": "a.py"}]
    assert bench.audit_violations(reads, allowed, context, ("D:/run",), audit_reads=True) == ["Read:a.py"]
    assert bench.audit_violations(reads, [], context, ()) == []  # пустой allowed_tools — без ограничений


def test_over_max_turns_is_flagged(tmp_path):
    runner = FakeRunner(_stream([("Read", "a.py")], turns=61))  # max_turns в grep-read = 60
    _, path, _, _ = _run(tmp_path, runner, repeats=1, yes=True)
    assert json.loads(path.read_text(encoding="utf-8"))["repeats"][0]["over_max_turns"] is True


def test_subprocess_runner_passes_prompt_on_stdin(tmp_path):
    """Боевой двойник: настоящий subprocess_runner, вместо claude — интерпретатор, печатающий свой stdin."""
    # байтами UTF-8: локаль Windows (cp1251) у дочернего процесса не влияет на результат
    cmd = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().decode('utf-8').upper().encode('utf-8'))",
    ]
    result = bench.subprocess_runner(cmd, "вопрос Q1", tmp_path)
    assert (result.returncode, result.stdout) == (0, "ВОПРОС Q1")
    missing = bench.subprocess_runner(["no-such-binary-nav-bench", "-p"], "x", tmp_path)
    assert missing.returncode == -1 and "no-such-binary-nav-bench" in missing.stderr


def test_sets_load_and_expectations_are_well_formed():
    qset = bench.load_questions(K0)
    assert (qset["name"], qset["repo_sha"], len(qset["questions"])) == ("k0", "1dc6c71b7", 10)
    assert [q["id"] for q in qset["questions"] if not q["scored"]] == ["Q8", "Q9"]
    by_id = {q["id"]: q for q in qset["questions"]}
    assert [q.get("require") for q in (by_id["Q1"], by_id["Q2"], by_id["Q4"])] == ["all", "all", "all"]
    assert [e["tolerance"] for q in (by_id["Q2"], by_id["Q3"]) for e in q["expected"]] == [0, 0, 0]
    assert "scripts/nav_bench" in qset["exclude"] and "docs/reviews" in qset["exclude"]
    assert any(
        e["path"].endswith("config_module/tools/__init__.py") and e["line"] == 17 for e in by_id["Q7"]["expected"]
    )
    assert len(by_id["Q6"]["expected"]) == 3

    arch = bench.load_questions(ARCH)
    assert (arch["name"], arch["repo_sha"], len(arch["questions"])) == ("arch", "1dc6c71b7", 10)
    assert arch["thresholds"]["facts_hit_min"] == 8 and arch["exclude"] == qset["exclude"]
    assert all(q["scored"] and q["expected_facts"] and "expected" not in q for q in arch["questions"])


def test_verify_set_flags_missing_file_and_symbol_outside_window():
    qset = {
        "name": "t",
        "repo_sha": "abc",
        "questions": [
            {
                "id": "Q1",
                "expected": [
                    {"path": "a.py", "line": 3, "symbol": "Foo"},
                    {"path": "a.py", "line": 9, "symbol": "Foo", "tolerance": 0},
                    {"path": "gone.py", "line": 1, "symbol": "X"},
                    {"path": "a.py", "line": None, "symbol": None},
                    {"path": "a.py", "line": 3, "symbol": "Mod.Foo"},
                ],
            },
            {"id": "A1", "expected_facts": [], "evidence": [{"path": "a.py", "contains": "nothing here"}]},
        ],
    }
    text = "\n".join(["x", "y", "class Foo:", "z", "z", "z", "z", "z", "z", "z", "z"])
    shown = lambda root, sha, path: text if path == "a.py" else None  # noqa: E731
    problems, checked = bench.verify_set(qset, Path("."), shown)
    assert checked == 6
    assert problems == [
        "Q1: символ 'Foo' не найден в a.py:9 ±0",
        "Q1: файла gone.py нет на abc",
        "A1: evidence: в a.py нет строки 'nothing here'",
    ]


def test_floor_run_sends_trivial_prompt_and_records_overhead(tmp_path):
    runner = FakeRunner(_stream([], text='{"id": "F0", "answer": "ready", "locations": [], "confidence": "unknown"}'))
    code, path, out, err = _run(tmp_path, runner, repeats=1, yes=True, floor=True)
    assert code == 0
    assert runner.calls[0][1] == bench.FLOOR_PROMPT
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["set"] == "floor-k0" and path.name == "2026-11-06_floor-k0_grep-read.json"
    assert record["repeats"][0]["final_context_tokens"] == 850
    assert record["verdict"]["band"] == "PASS"


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True
    )


def test_clean_copy_excludes_answer_paths(tmp_path):
    repo = tmp_path / "repo"
    files = {
        "src/code.py": "code",
        "scripts/nav_bench/key.json": "answers",
        "docs/reports/answers.md": "answers",
        "docs/keep.md": "keep",
    }
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    (repo / "notes").mkdir()
    (repo / "notes" / "ctx.md").write_text("context", encoding="utf-8")  # не закоммичен: докладывается из дерева

    qset = {"repo_sha": sha, "exclude": ["scripts/nav_bench", "docs/reports"]}
    condition = {**bench.CONDITION_DEFAULTS, "name": "c", "model": "haiku", "context_files": ["notes/ctx.md"]}
    temp = tmp_path / "tmp"
    copy = bench.prepare_clean_copy(qset, condition, repo, temp_base=temp, err=io.StringIO())

    assert copy.parent == temp / "nav_bench" and copy.name.startswith(sha + "-")
    assert (copy / "src" / "code.py").read_text(encoding="utf-8") == "code"
    assert (copy / "docs" / "keep.md").exists()
    assert not (copy / "scripts" / "nav_bench").exists()  # ключ ответов вырезан
    assert not (copy / "docs" / "reports").exists()
    assert (copy / "notes" / "ctx.md").read_text(encoding="utf-8") == "context"  # контекст условия докладан
    assert not (copy / ".git").exists()

    (copy / "marker").write_text("kept", encoding="utf-8")  # повторный вызов берёт готовую копию
    assert bench.prepare_clean_copy(qset, condition, repo, temp_base=temp) == copy
    assert (copy / "marker").exists()
    # другое условие (другие context_files) — другая копия: карта прошлого условия не просочится
    other = {**condition, "context_files": []}
    assert bench.clean_copy_path(qset, other, temp) != copy


def test_violation_makes_verdict_tainted(tmp_path):
    # пороги выполнены, но был нарушающий доступ — вердикт TAINTED, а не PASS
    agg = score.aggregate([{"hits": 9, "false": 0}, {"hits": 9, "false": 0}])
    assert score.verdict(agg, tainted=False)["band"] == "PASS"
    tainted = score.verdict(agg, tainted=True)
    assert (tainted["band"], tainted["pass"]) == ("TAINTED", False)

    uses = [("Read", "docs/arch-map/units.md"), ("Grep", "IRouterManager")]  # Grep вне allowed_tools map-only
    runner = FakeRunner(_stream(uses))
    _, path, _, _ = _run(
        tmp_path, runner, condition=MAP_ONLY, repeats=2, yes=True, baseline_path=_baseline_file(tmp_path)
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["verdict"]["band"] == "TAINTED" and record["verdict"]["pass"] is False
    assert "**Вердикт: TAINTED**" in path.with_suffix(".md").read_text(encoding="utf-8")


def test_final_text_fallback_and_budget_subtype_visible(tmp_path):
    # result короткий («Готово»), ответы — в текстовых блоках assistant; Q3 в result исправлен: result побеждает
    fixed_q3 = json.dumps(
        {"id": "Q3", "answer": "Protocol", "locations": [R + "config_module/interfaces.py:17"], "confidence": "sure"}
    )
    stdout = _stream([("Read", "a.py")], result_text=fixed_q3, subtype="error_max_budget_usd", is_error=True)
    runner = FakeRunner(stdout)
    code, path, out, err = _run(tmp_path, runner, repeats=1, yes=True)
    assert code == 0
    rep = json.loads(path.read_text(encoding="utf-8"))["repeats"][0]
    assert [r["verdict"] for r in rep["score"]["per_question"]][:3] == ["hit", "hit", "hit"]  # Q1, Q2 — из assistant
    assert (rep["score"]["hits"], rep["score"]["false"]) == (3, 0)
    assert rep["subtype"] == "error_max_budget_usd" and rep["error"] == "error_max_budget_usd"
    assert "error_max_budget_usd" in err  # обрыв по бюджету виден сразу
    assert "| error_max_budget_usd |" in path.with_suffix(".md").read_text(encoding="utf-8")

    # полный result (ответов не меньше, чем вопросов) assistant-текстом не разбавляется
    parsed = bench.parse_session_output(_stream([], text="intro"))
    assert bench._answer_text({**parsed, "final_text": ANSWERS}, 3) == ANSWERS


def test_mcp_condition_refuses_without_index(tmp_path):
    qex_home = tmp_path / "qexhome"
    qex_home.mkdir()
    preflight = functools.partial(bench.check_requires, qex_home=qex_home)
    runner = FakeRunner(_stream([("Read", "a.py")]))
    run_dir = tmp_path / "run"
    base = _baseline_file(tmp_path)  # у qex относительные пороги: без базы отказ случился бы раньше индекса

    code, path, out, err = _run(tmp_path, runner, condition=QEX, yes=True, preflight_fn=preflight, baseline_path=base)
    assert code == 2 and path is None and runner.calls == []
    assert f'mcp__qex__index_codebase(path="{run_dir}", force=true)' in err  # точная команда сборки

    code, _, _, err = _run(tmp_path, runner, condition=GRAPHIFY, yes=True, preflight_fn=preflight, baseline_path=base)
    assert code == 2 and runner.calls == []
    assert "/graphify . --update" in err and "graphify-out" in err

    # индекс есть -> запуск идёт, MCP-конфиг записан рядом с копией и подставлен в команду
    info = qex_home / "p_1" / "project_info.json"
    info.parent.mkdir()
    info.write_text(
        json.dumps({"project_name": "run", "project_path": "\\\\?\\" + str(run_dir.resolve())}), encoding="utf-8"
    )
    code, path, _, err = _run(
        tmp_path, runner, condition=QEX, yes=True, preflight_fn=preflight, repeats=1, baseline_path=base
    )
    assert code == 0 and len(runner.calls) == 1
    cmd = runner.calls[0][0]
    config_path = Path(cmd[cmd.index("--mcp-config") + 1])
    assert config_path == tmp_path / "run.mcp-qex.json" and "--strict-mcp-config" in cmd
    servers = json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]
    assert list(servers) == ["qex"] and servers["qex"]["command"] == sys.executable


def test_clean_copy_path_differs_per_condition():
    # граф graphify строится внутри копии: grep-read и qex не должны делить с ним каталог
    qset = bench.load_questions(K0)
    paths = {
        name: bench.clean_copy_path(qset, bench.load_condition(PKG / "conditions" / f"{name}.json"), Path("T"))
        for name in ("grep-read", "qex", "graphify", "all")
    }
    assert len(set(paths.values())) == 4, paths
    assert paths["grep-read"] == bench.clean_copy_path(qset, bench.load_condition(SOURCE_ONLY), Path("T"))  # алиас


def test_baseline_chain_ratio_fix_and_refusal_without_base(tmp_path):
    ratio = _condition_file(
        tmp_path,
        max_budget_usd=1.0,
        thresholds={"hits_min": 2, "false_max": 1, "calls_ratio_max": 0.5},
    )
    runner = FakeRunner(_stream([("Read", "a.py")] * 31))  # K0: Q1, Q2 попали, Q3 ложный адрес -> 2 / 1

    # с базой в 40 вызовов: 31 / 40 = 0.775 > 0.5, попаданий достаточно -> FIX
    code, path, _, _ = _run(
        tmp_path, runner, condition=ratio, repeats=1, yes=True, baseline_path=_baseline_file(tmp_path)
    )
    assert code == 0 and len(runner.calls) == 1
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["verdict"]["checks"]["calls_ratio"] == {"value": 0.775, "limit": 0.5, "ok": False}
    assert (record["verdict"]["band"], record["verdict"]["pass"]) == ("FIX", False)
    assert record["baseline"]["set"] == "k0"

    # без базы относительный порог не проверить: отказ до запуска сессий
    code, path, _, err = _run(tmp_path, runner, condition=ratio, repeats=1, yes=True)
    assert (code, path) == (2, None) and len(runner.calls) == 1 and "calls_ratio_max" in err

    # база чужого набора: отказ
    other = _baseline_file(tmp_path, set_name="arch")
    code, _, _, err = _run(tmp_path, runner, condition=ratio, repeats=1, yes=True, baseline_path=other)
    assert code == 2 and len(runner.calls) == 1 and "arch" in err

    # floor: относительные пороги теряют смысл — база не нужна, отказа нет
    code, _, _, _ = _run(tmp_path, runner, condition=ratio, repeats=1, yes=True, floor=True)
    assert code == 0 and len(runner.calls) == 2


def test_unmeasured_metric_is_not_a_pass():
    agg = score.aggregate([{"hits": 9, "false": 0}, {"hits": 9, "false": 0}])  # вызовов и токенов нет
    ratios = {"calls_ratio_max": 0.5}
    result = score.verdict(agg, ratios)  # и базы нет
    assert result["unmeasured"] == ["calls_ratio"]
    assert (result["pass"], result["band"]) == (False, "UNMEASURED")
    metric_none = score.verdict(agg, {"calls_median_max": 20})  # имя поля в живом выводе не совпало
    assert (metric_none["pass"], metric_none["band"]) == (False, "UNMEASURED")
    assert score.verdict(agg, ratios, tainted=True)["band"] == "TAINTED"  # TAINTED первее
    assert score.verdict(agg)["band"] == "PASS"  # порогов на метрики нет — нечего не измерять
    # провал на измеренном не прячется за UNMEASURED: UNMEASURED ставится только там, где иначе был бы PASS
    weak = score.aggregate([{"hits": 7, "false": 0}, {"hits": 7, "false": 0}])
    assert score.verdict(weak, ratios)["band"] == "FIX"
    bad = score.aggregate([{"hits": 2, "false": 0}, {"hits": 2, "false": 0}])
    assert score.verdict(bad, ratios)["band"] == "FAIL"
    assert score.verdict(weak, ratios, tainted=True)["band"] == "TAINTED"


def test_audit_prefixes_cover_resolved_and_raw_run_root(tmp_path):
    # %TEMP% бывает в короткой форме (C:\\Users\\TWOKRA~1\\...): resolve() её раскрывает, cwd сессии — нет.
    # Здесь тот же разрыв делает симлинк: сырой путь копии != resolve().
    real = tmp_path / "real" / "run"
    real.mkdir(parents=True)
    try:
        (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"ОС не даёт создать симлинк ({type(exc).__name__}: {exc}) — проверка не выполнена")
    raw = tmp_path / "link" / "run"
    assert str(raw) != str(raw.resolve())

    uses = [
        ("Read", f"{raw}/docs/arch-map/units.md"),  # путь, как его видит cwd сессии
        ("Read", f"{raw.resolve()}/docs/arch-map/findings.md"),  # раскрытый путь
        ("Read", f"{raw}/multiprocess_framework/x.py"),  # настоящее нарушение остаётся нарушением
    ]
    runner = FakeRunner(_stream(uses))
    code, path, _, _ = _run(
        tmp_path,
        runner,
        condition=MAP_ONLY,
        repeats=1,
        yes=True,
        copy_fn=lambda qset, cond, root, err=None: raw,
        baseline_path=_baseline_file(tmp_path),
    )
    assert code == 0
    rep = json.loads(path.read_text(encoding="utf-8"))["repeats"][0]
    assert rep["violations"] == [f"Read:{raw}/multiprocess_framework/x.py"]


def _written_record(tmp_path):
    runner = FakeRunner(_stream([("Read", "a.py")]))
    _, path, _, _ = _run(tmp_path, runner, repeats=1, yes=True)
    return path


def test_score_command_reports_foreign_baseline_set_without_traceback(tmp_path, capsys):
    path = _written_record(tmp_path)
    foreign = _baseline_file(tmp_path, set_name="arch")
    out = io.StringIO()
    assert bench.score_command(path, None, out=out, baseline_path=foreign) == 2
    assert out.getvalue() == "" and "ОШИБКА" in capsys.readouterr().err
    record = json.loads(path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="arch"):
        bench.rescore_record(record, record["questions"], foreign)
    same = _baseline_file(tmp_path, set_name="k0")
    assert bench.score_command(path, None, out=out, baseline_path=same) == 0 and "Вердикт" in out.getvalue()


def test_rescore_old_record_without_prefixes_uses_root(tmp_path):
    path = _written_record(tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["prefixes"][0] == record["root"]
    band = record["verdict"]["band"]
    del record["prefixes"]  # запись, снятая до появления поля
    rescored = bench.rescore_record(record, record["questions"])
    assert rescored["repeats"][0]["score"]["hits"] == 2 and rescored["verdict"]["band"] == band == "FAIL"


def test_floor_ignores_baseline_of_another_set(tmp_path):
    runner = FakeRunner(_stream([("Read", "a.py")]))
    foreign = _baseline_file(tmp_path, set_name="arch")
    code, _, _, _ = _run(tmp_path, runner, repeats=1, yes=True, floor=True, baseline_path=foreign)
    assert code == 0 and len(runner.calls) == 1


# --- Task 7.2: копия с историей git и Bash по шаблонам --------------------------------------------
GIT_PATTERNS = ["git log", "git log *", "git show *", "git blame *", "git grep *"]
SET_EXCLUDE = ["scripts/nav_bench", "docs/reports"]
TOOLS = ["Read", "Grep", "Glob"]


def _audit_bash(commands, patterns=GIT_PATTERNS, exclude=SET_EXCLUDE, prefixes=()):
    uses = [{"name": "Bash", "target": command} for command in commands]
    return bench.audit_violations(uses, TOOLS, [], prefixes, bash_allow=patterns, exclude=exclude)


def _within(seconds, func, *args, **kwargs):
    """Вызов в демон-потоке с дедлайном: зависший git не вешает прогон тестов."""
    box = {}

    def target():
        try:
            box["value"] = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается в поток теста
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"{getattr(func, '__name__', func)} не вернулся за {seconds} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _out(repo, *args, check=True):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if check:
        assert done.returncode == 0, done.stderr
    return done


def _history_repo(tmp_path):
    """Одноразовый репозиторий: first -> second (= repo_sha); ветка side и тег; main ушла дальше (third)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")

    def commit(files, message):
        for rel, text in files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text, encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", message)
        return _out(repo, "rev-parse", "HEAD").stdout.strip()

    first = commit(
        {
            "src/code.py": "v1",
            "docs/keep.md": "keep",
            "scripts/nav_bench/key.json": "answers",
            "docs/reports/deep/answer.md": "answers",
        },
        "first",
    )
    second = commit({"src/code.py": "v2"}, "second")
    _git(repo, "checkout", "-q", "-b", "side")
    side = commit({"side.txt": "side"}, "side-only")
    _git(repo, "tag", "v-side")
    _git(repo, "checkout", "-q", "main")
    third = commit({"src/code.py": "v3"}, "third")
    return {"repo": repo, "first": first, "sha": second, "side": side, "third": third}


def _clone_set(info, **fields):
    return {"repo_sha": info["sha"], "exclude": list(SET_EXCLUDE), "copy": "clone", **fields}


def _clone_condition(**fields):
    return {**bench.CONDITION_DEFAULTS, "name": "c", "model": "haiku", **fields}


def _make_clone(tmp_path, info, **set_fields):
    return _within(
        120,
        bench.prepare_clean_copy,
        _clone_set(info, **set_fields),
        _clone_condition(),
        info["repo"],
        temp_base=tmp_path / "tmp",
        err=io.StringIO(),
    )


def _questions_file(tmp_path, repo_sha, **fields):
    data = {
        "name": "mini",
        "repo_sha": repo_sha,
        "questions": [{"id": "Q1", "question": "where?", "expected": [{"path": "src/code.py", "line": 1}]}],
        **fields,
    }
    path = tmp_path / "mini.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# RED 1
def test_bash_outside_pattern_is_violation():
    assert _audit_bash(["ls"]) == ["bash-pattern:ls"]
    assert _audit_bash(["git logx"]) == ["bash-pattern:git logx"]  # `git log` без `*` — только точная команда
    assert _audit_bash(["Git log -1"]) == ["bash-pattern:Git log -1"]  # регистр значим
    assert _audit_bash(["git status"]) == ["bash-pattern:git status"]
    assert _audit_bash([""]) == ["bash-pattern:"]

    for sep in (";", "&&", "||", "|", "&", ">", "<", "`"):
        command = f"git log -1 {sep} x"
        assert _audit_bash([command]) == [f"bash-chain:{command}"], sep
    assert _audit_bash(["git log $(id)"]) == ["bash-chain:git log $(id)"]

    for command in (
        "git log --output=x",
        "git show -O orderfile HEAD",
        "git log --git-dir=/x",
        "git grep --work-tree d x",
    ):
        assert _audit_bash([command]) == [f"bash-flag:{command}"], command
    assert _audit_bash(["git log --out=x"]) == ["bash-flag:git log --out=x"]  # сокращение длинного флага git

    # F1: git grep --open-files-in-pager=<cmd> исполняет команду; git принимает и сокращение --open
    for command in ("git grep --open-files-in-pager=sh x", "git grep --open=cat x", "git grep --open-f=sh x"):
        assert _audit_bash([command]) == [f"bash-flag:{command}"], command
    # F2: настоящий -O (отдельно, в связке, с приклеенным значением) остаётся грязным
    for command in ("git grep -O sh x", "git grep -nOsh x", "git grep -Osh x"):
        assert _audit_bash([command]) == [f"bash-flag:{command}"], command
    # F1': у git grep -G и -L — флаги без значения: `-GOsh` это -G и -O, пейджер запускается (git 2.51.2)
    for command in ("git grep -GOsh x", "git grep -LOsh x", "git grep -nGOsh x", "git grep -lLOsh x"):
        assert _audit_bash([command]) == [f"bash-flag:{command}"], command
    # bash-chain не учитывает кавычки (fail-closed): `|` в кавычках — ложный TAINTED, он виден в записи
    assert _audit_bash(["git grep -E 'a|b'"]) == ["bash-chain:git grep -E 'a|b'"]

    assert _audit_bash(["git grep -C 3 x"]) == []  # `-C` — не из списка запретных
    assert _audit_bash(["git grep -o x"]) == []  # `-o` в нижнем регистре — не `-O`

    newline = _audit_bash(["git log -1\nls"])
    assert len(newline) == 1 and newline[0].startswith("bash-chain:")

    long_command = "ls " + "x" * 200
    (text,) = _audit_bash([long_command])
    rule, shown = text.split(":", 1)
    assert rule == "bash-pattern" and shown == long_command[:80]


# RED 2
def test_bash_with_excluded_path_is_tainted(tmp_path):
    key = "scripts/nav_bench/key.json"
    assert _audit_bash([f"git show HEAD:{key}"]) == [f"bash-exclude:git show HEAD:{key}"]  # <rev>:<путь>
    assert _audit_bash(["git show HEAD:docs/reports/a.md"]) == ["bash-exclude:git show HEAD:docs/reports/a.md"]
    assert _audit_bash(["git blame -- ./Scripts/NAV_bench/key.json"]) == [
        "bash-exclude:git blame -- ./Scripts/NAV_bench/key.json"
    ]  # без регистра, без ./
    assert _audit_bash(["git log -- scripts\\nav_bench\\x"]) == ["bash-exclude:git log -- scripts\\nav_bench\\x"]
    assert _audit_bash(["git grep x -- 'scripts/nav_bench'"]) == ["bash-exclude:git grep x -- 'scripts/nav_bench'"]
    assert _audit_bash(["git log -- /c/copy/docs/reports/a.md"], prefixes=("/c/copy",)) == [
        "bash-exclude:git log -- /c/copy/docs/reports/a.md"
    ]  # путь с префиксом копии
    # F4: лишние `/` вокруг префикса копии не прячут путь
    for command in (
        "git log -- /c/copy//docs/reports/x.md",
        "git log -- //c/copy/docs/reports/x.md",
        "git show HEAD:/c/copy//docs/reports/x.md",
    ):
        assert _audit_bash([command], prefixes=("/c/copy",)) == [f"bash-exclude:{command}"], command
    assert _audit_bash(["git log -- docs/reports-other/x"]) == []  # соседний каталог — не внутри exclude
    assert _audit_bash(["git log -- docs/keep.md"]) == []

    # сквозной прогон: git log -1 чист, git show HEAD:<exclude> — одно нарушение
    uses = [("Bash", "git log -1")]
    runner = FakeRunner(_stream(uses))
    ok = lambda condition, run_root, repo_sha: []  # noqa: E731 — копия-пустышка, история не проверяется
    _, path, _, _ = _run(tmp_path, runner, condition=GREP_READ_GIT, repeats=1, yes=True, history_fn=ok)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["repeats"][0]["violations"] == []
    assert record["verdict"]["band"] != "TAINTED"

    runner = FakeRunner(_stream(uses + [("Bash", f"git show HEAD:{key}")]))
    _, path, _, _ = _run(tmp_path, runner, condition=GREP_READ_GIT, repeats=1, yes=True, history_fn=ok)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["repeats"][0]["violations"] == [f"bash-exclude:git show HEAD:{key}"]
    assert record["verdict"]["band"] == "TAINTED"


# RED 3
def test_build_command_passes_bash_patterns():
    condition = bench.load_condition(GREP_READ_GIT)
    cmd = bench.build_command(condition)
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob,Bash"
    assert cmd[cmd.index("--allowedTools") + 1] == (
        "Read,Grep,Glob,Bash(git log),Bash(git log *),Bash(git show *),Bash(git blame *),Bash(git grep *)"
    )
    assert "Bash" not in cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert cmd[cmd.index("--setting-sources") + 1] == "user"  # settings*.json копии не вливаются в разрешения

    plain = bench.build_command(bench.load_condition(GREP_READ))
    assert "--setting-sources" not in plain  # условие без Bash — команда прежняя

    templated = {
        **condition,
        "bash_allow": ["git show {repo_sha}:*", "git grep * {run_root}/src"],
        "prompt_prefix": "root {run_root} sha {repo_sha} repo {repo_root}",
    }
    cmd = bench.build_command(templated, run_root="C:\\tmp\\copy", repo_root="D:\\repo", repo_sha="abc123")
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert allowed[3:] == ["Bash(git show abc123:*)", "Bash(git grep * C:/tmp/copy/src)"]
    assert cmd[cmd.index("--append-system-prompt") + 1] == "root C:/tmp/copy sha abc123 repo D:/repo"


# RED 4
def test_clone_copy_has_history_at_repo_sha(tmp_path):
    info = _history_repo(tmp_path)
    copy = _make_clone(tmp_path, info)
    assert (copy / ".git").exists()
    assert _out(copy, "rev-parse", "HEAD").stdout.strip() == info["sha"]
    assert _out(copy, "log", "--format=%s").stdout.split() == ["second", "first"]  # история до repo_sha, не дальше
    assert (copy / "src" / "code.py").read_text(encoding="utf-8") == "v2"  # дерево на repo_sha, не на HEAD источника
    assert _out(copy, "symbolic-ref", "-q", "HEAD", check=False).returncode != 0  # HEAD отсоединён
    assert (copy / "docs" / "keep.md").read_text(encoding="utf-8") == "keep"
    # копия-клон лежит в своём каталоге: хеш с полем copy не совпадает с хешем archive
    plain = {"repo_sha": info["sha"], "exclude": list(SET_EXCLUDE)}
    assert bench.clean_copy_path(plain, _clone_condition(), tmp_path) != copy
    assert copy == bench.clean_copy_path(_clone_set(info), _clone_condition(), tmp_path / "tmp")


# RED 5
def test_clone_copy_removes_set_exclude_and_status_is_clean(tmp_path):
    info = _history_repo(tmp_path)
    copy = _make_clone(tmp_path, info)
    assert not (copy / "scripts" / "nav_bench" / "key.json").exists()  # файл
    assert not (copy / "scripts" / "nav_bench").exists()
    assert not (copy / "docs" / "reports").exists()  # каталог с вложенным файлом
    assert (copy / "docs" / "keep.md").exists()
    assert _out(copy, "status", "--porcelain").stdout == ""  # «gitStatus» не назовёт удалённое


# RED 6
def test_clone_copy_hides_other_refs(tmp_path):
    info = _history_repo(tmp_path)
    copy = _make_clone(tmp_path, info)
    assert _out(copy, "for-each-ref").stdout == ""  # ни веток, ни тегов, ни origin/*
    assert _out(copy, "remote").stdout == ""
    assert _out(copy, "log", "--all", "--format=%H").stdout.split() == [info["sha"], info["first"]]
    assert _out(copy, "reflog", "show", "HEAD").stdout == ""  # «checkout: moving from ...» не остаётся


# RED 7
def test_clone_copy_has_no_alternates_or_foreign_objects(tmp_path):
    info = _history_repo(tmp_path)
    copy = _make_clone(tmp_path, info)
    assert not (copy / ".git" / "objects" / "info" / "alternates").exists()
    for foreign in (info["third"], info["side"]):
        assert _out(copy, "cat-file", "-e", foreign, check=False).returncode != 0, foreign
    assert _out(copy, "fsck", "--no-dangling", check=False).returncode == 0  # без alternates объекты свои, целые


# RED 8
def test_unknown_copy_value_is_refused(tmp_path):
    bad_copy = _questions_file(tmp_path, "abc", copy="clon")
    runner = FakeRunner(_stream([("Read", "a.py")]))
    code, path, _, err = _run(tmp_path, runner, questions=bad_copy, yes=True)
    assert (code, path) == (2, None) and runner.calls == []
    assert "ОТКАЗ: copy набора должен быть archive или clone" in err

    for field, value in (("bash_allow", ["git log {bogus}"]), ("prompt_prefix", "go {nope}")):
        condition = _condition_file(tmp_path, **{"bash_allow": ["git log *"], field: value})
        code, path, _, err = _run(tmp_path, runner, condition=condition, yes=True)
        name = "bogus" if field == "bash_allow" else "nope"
        assert (code, path) == (2, None) and runner.calls == [], field
        assert f"ОТКАЗ: неизвестный плейсхолдер {{{name}}}" in err

    known = _condition_file(
        tmp_path,
        max_budget_usd=1.0,
        bash_allow=["git show {repo_sha}:*"],
        prompt_prefix="{repo_root} {repo_sha} {run_root}",
    )
    ok = lambda condition, run_root, repo_sha: []  # noqa: E731
    code, _, _, _ = _run(tmp_path, runner, condition=known, repeats=1, yes=True, history_fn=ok)
    assert code == 0 and len(runner.calls) == 1  # свои три подстановки — не отказ


# RED 9
def test_bash_condition_requires_history_in_copy(tmp_path):
    info = _history_repo(tmp_path)
    questions = _questions_file(tmp_path, info["sha"], exclude=list(SET_EXCLUDE), copy="clone")
    base = {"root": info["repo"], "questions": questions, "condition": GREP_READ_GIT, "repeats": 1, "yes": True}
    dirty_free = lambda root, paths: []  # noqa: E731

    # копия без .git (пустой каталог тестового копировщика) — отказ до сессии
    runner = FakeRunner(_stream([("Bash", "git log -1")]))
    code, path, _, err = _run(tmp_path, runner, **base)
    assert (code, path) == (2, None) and runner.calls == []
    assert "ОТКАЗ" in err and "нет истории git" in err

    # клон другого коммита — тоже отказ
    other_copy = _make_clone(tmp_path, {**info, "sha": info["first"]})
    code, path, _, err = _run(tmp_path, runner, copy_fn=lambda q, c, r, err=None: other_copy, **base)
    assert (code, path) == (2, None) and runner.calls == [] and "нет истории git" in err

    # настоящий клон на repo_sha — запуск идёт
    real = functools.partial(bench.prepare_clean_copy, temp_base=tmp_path / "real")
    code, path, _, err = _within(120, _run, tmp_path, runner, copy_fn=real, dirty_fn=dirty_free, **base)
    assert code == 0 and len(runner.calls) == 1, err


# RED 10
def test_parse_session_output_marks_denied_bash():
    def use(uid, name, **args):
        return {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": uid, "name": name, "input": args}]},
        }

    def result(uid, is_error, text):
        block = {"type": "tool_result", "tool_use_id": uid, "content": text, "is_error": is_error}
        return {"type": "user", "message": {"content": [block]}}

    events = [
        use("t1", "Bash", command="ls"),
        result("t1", True, "Permission to use Bash with command ls has been denied."),
        use("t2", "Bash", command="git log -1"),
        result("t2", False, "abc commit"),
        use("t3", "Read", file_path="a.py"),
        result("t3", True, "no such file"),
        result("t9", True, "result of an unknown call"),
        {"type": "result", "subtype": "success", "is_error": False, "result": "x", "num_turns": 1},
    ]
    parsed = bench.parse_session_output("\n".join(json.dumps(e) for e in events))
    assert parsed["tool_uses"] == [
        {"name": "Bash", "target": "ls", "denied": True},
        {"name": "Bash", "target": "git log -1", "denied": False},
        {"name": "Read", "target": "a.py"},  # tool_result читается только у Bash
    ]
    assert parsed["tool_calls"] == 3


# G1
def test_bash_matching_pattern_is_clean():
    commands = [
        "git log",
        "git log -1",
        "git log --oneline -n 5 -- src/code.py",
        "git show HEAD~1:src/code.py",
        "git blame -L 1,5 -- src/code.py",
        "git grep -n Router -- '*.py'",
        "git grep -C 3 x",
        # F2: заглавная O внутри значения флага (-S -G -L -e ...) — не флаг -O
        "git log -S'Order'",
        'git log -G"OpenCV"',
        "git grep -eObject -- src",
        "git log -L:OnClick:src/gui.py",
        "git log -SOrder --oneline",
        "git grep -neObject src",
        "git grep -e Object",
        # F1': у log/show/blame -G и -L берут значение, поэтому O после них — часть значения
        "git log -GOsh x",
        "git blame -LOsh x",
    ]
    assert _audit_bash(commands) == []
    assert _audit_bash(["  git log -1  "]) == []  # пробелы по краям команды не важны


# G2
def test_bash_template_literal_with_exclude_is_clean():
    patterns = ["git show *:scripts/nav_bench/key.json"]  # `exclude` — в литерале шаблона, не в группе `*`
    assert _audit_bash(["git show HEAD:scripts/nav_bench/key.json"], patterns=patterns) == []
    assert _audit_bash(["git show HEAD~2:scripts/nav_bench/key.json"], patterns=patterns) == []


# G3
def test_archive_copy_and_cache_key_unchanged(tmp_path):
    qset = bench.load_questions(K0)
    condition = bench.load_condition(GREP_READ)
    expected = Path("T/nav_bench/1dc6c71b7-cd10f5dfa7")  # хеш прежней формулы: exclude + имя + context_files
    assert bench.clean_copy_path(qset, condition, Path("T")) == expected
    assert bench.clean_copy_path({**qset, "copy": "archive"}, condition, Path("T")) == expected

    info = _history_repo(tmp_path)
    copy = bench.prepare_clean_copy(
        {"repo_sha": info["sha"], "exclude": list(SET_EXCLUDE)},  # поля copy нет — archive
        _clone_condition(),
        info["repo"],
        temp_base=tmp_path / "tmp",
        err=io.StringIO(),
    )
    assert not (copy / ".git").exists()
    assert (copy / "src" / "code.py").read_text(encoding="utf-8") == "v2"
    assert not (copy / "docs" / "reports").exists()
