# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку
"""Тесты автора на внутренние опасности резолвера «worktree -> план» и `--who` (Task 5.2).

Приёмку по критериям пишет независимый тестер (test_acceptance_active.py). Здесь — места, видимые только по
устройству механизма: порядок шагов и то, какой из них вообще вызывается; git, чьи вызовы падают или висят;
журнал со строками, на которых наивный разбор спотыкается (U+2028 внутри строки JSON, BOM, глубокая вложенность,
не-UTF-8 байты); формы путей Windows; число вызовов git (корень без свежей строки git не трогает).

Почти все тесты импортируют модуль напрямую и подменяют `pp._git` / `subprocess.run`: подмена показывает, КАКИЕ
вызовы сделаны, чего через CLI не видно. Два теста идут через настоящий git и CLI: проводка целиком.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_active_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_active_under_test"] = pp
_spec.loader.exec_module(pp)

NOW = datetime(2026, 10, 3, 12, 0, 0)
HOUR6 = timedelta(hours=6)


# =========================================================================== хелперы


def rec(ts: str, session: str = "s1", agent: str = "a1", event: str = "Start", **extra) -> dict:
    return {"ts": ts, "event": event, "session_id": session, "agent_id": agent, **extra}


def write_journal(wt: Path, *lines: dict | str | bytes) -> None:
    path = wt / "data" / "agent-journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = []
    for ln in lines:
        raw = (
            ln
            if isinstance(ln, bytes)
            else (ln if isinstance(ln, str) else json.dumps(ln, ensure_ascii=False)).encode("utf-8")
        )
        chunks.append(raw + b"\n")
    path.write_bytes(b"".join(chunks))


def mem_plan(name: str, branch: str = "", archived: bool = False) -> pp.Plan:
    p = pp.Plan(name=name, rel=name, archived=archived)
    p.header_branch = branch
    return p


class FakeGit:
    """Подмена `pp._git`: таблица (префикс аргументов -> ответ), журнал вызовов."""

    def __init__(self, *table: tuple[tuple[str, ...], str | None]) -> None:
        self.table = list(table)
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def __call__(self, args: list[str], cwd) -> str | None:
        self.calls.append((tuple(args), str(cwd)))
        for prefix, result in self.table:
            if tuple(args[: len(prefix)]) == prefix:
                return result
        return None

    def verbs(self) -> list[str]:
        return [c[0][0] for c in self.calls]


# =========================================================================== флаги: разбор значений


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30m", timedelta(minutes=30)),
        ("6h", HOUR6),
        ("1d", timedelta(days=1)),
        ("0m", timedelta(0)),
        ("007h", timedelta(hours=7)),
    ],
)
def test_parse_window_accepts_number_and_one_unit(text, expected):
    assert pp.parse_window(text) == expected


@pytest.mark.parametrize(
    "text", ["", "6", "h", "6x", "6hh", "1w", " 6h", "6h ", "-6h", "6.5h", "٣h", "6H", "99999999999999999d"]
)
def test_parse_window_rejects_everything_else_without_raising(text):
    # «٣h» — арабская цифра: int() её съест, а `[0-9]` не должен; огромное число — OverflowError в timedelta
    assert pp.parse_window(text) is None


@pytest.mark.parametrize("text", ["2026-10-03T12:00:00", "2026-10-03T12:00", "2026-10-03"])
def test_parse_now_accepts_local_iso(text):
    assert isinstance(pp.parse_now(text), datetime)


@pytest.mark.parametrize("text", ["", "x", "2026-10-03T12:00:00Z", "2026-10-03T12:00:00+03:00", "2026-13-45T00:00:00"])
def test_parse_now_rejects_zoned_and_garbage(text):
    assert pp.parse_now(text) is None


# =========================================================================== журнал


def test_journal_line_with_raw_u2028_inside_a_string_is_one_record(tmp_path):
    # splitlines() режет по U+2028 и рвёт запись пополам: обе половины битый JSON, сигнал потерян
    write_journal(tmp_path, rec("2026-10-03T11:00:00", tail="до\u2028после"))
    assert pp.read_signal(tmp_path, NOW, HOUR6) == {"sessions": 1, "agents": 1, "last_signal": "2026-10-03T11:00:00"}


def test_journal_with_bom_and_crlf_is_read(tmp_path):
    path = tmp_path / "data" / "agent-journal.jsonl"
    path.parent.mkdir(parents=True)
    body = (
        json.dumps(rec("2026-10-03T11:00:00", "s1")) + "\r\n" + json.dumps(rec("2026-10-03T11:10:00", "s2")) + "\r\n"
    ).encode("utf-8")
    path.write_bytes(b"\xef\xbb\xbf" + body)
    sig = pp.read_signal(tmp_path, NOW, HOUR6)
    assert sig == {"sessions": 2, "agents": 1, "last_signal": "2026-10-03T11:10:00"}


def test_journal_bad_utf8_bytes_ruin_only_their_own_line(tmp_path):
    write_journal(
        tmp_path,
        b'{"ts": "2026-10-03T11:00:00", "event": "E", "session_id": "\xff\xfe"}',
        rec("2026-10-03T11:20:00", "s2"),
    )
    sig = pp.read_signal(tmp_path, NOW, HOUR6)
    assert sig is not None and sig["last_signal"] == "2026-10-03T11:20:00"


def test_journal_deeply_nested_json_is_skipped_not_a_crash(tmp_path):
    write_journal(tmp_path, "[" * 200000, rec("2026-10-03T11:00:00"))
    assert pp.read_signal(tmp_path, NOW, HOUR6)["sessions"] == 1


def test_journal_missing_or_unreadable_gives_no_signal(tmp_path):
    assert pp.read_signal(tmp_path, NOW, HOUR6) is None  # файла нет
    (tmp_path / "data" / "agent-journal.jsonl").mkdir(parents=True)  # вместо файла — каталог
    assert pp.read_signal(tmp_path, NOW, HOUR6) is None


def test_journal_record_without_event_or_with_non_string_event_is_not_counted(tmp_path):
    write_journal(
        tmp_path,
        {"ts": "2026-10-03T11:00:00", "session_id": "sMissing", "agent_id": "aMissing"},
        {"ts": "2026-10-03T11:01:00", "event": None, "session_id": "sNone"},
        {"ts": "2026-10-03T11:02:00", "event": 7, "session_id": "sInt"},
    )
    assert pp.read_signal(tmp_path, NOW, HOUR6) is None


def test_journal_non_string_ids_are_not_counted_as_sessions(tmp_path):
    write_journal(
        tmp_path, rec("2026-10-03T11:00:00", session=5, agent=["a"]), rec("2026-10-03T11:01:00", "real", "real")
    )
    assert pp.read_signal(tmp_path, NOW, HOUR6) == {"sessions": 1, "agents": 1, "last_signal": "2026-10-03T11:01:00"}


def test_journal_last_signal_keeps_the_original_string_and_first_of_equal_ts(tmp_path):
    write_journal(tmp_path, rec("2026-10-03T11:00:00.000", "a"), rec("2026-10-03T11:00:00", "b"))
    # ts равны как время; в ответе — строка первой из равных, а не пересобранная из datetime
    assert pp.read_signal(tmp_path, NOW, HOUR6)["last_signal"] == "2026-10-03T11:00:00.000"


def test_journal_window_edge_is_inclusive_and_future_is_fresh(tmp_path):
    edge = (NOW - HOUR6).isoformat()
    write_journal(tmp_path, rec(edge))
    assert pp.read_signal(tmp_path, NOW, HOUR6) is not None
    write_journal(tmp_path, rec((NOW - HOUR6 - timedelta(seconds=1)).isoformat()))
    assert pp.read_signal(tmp_path, NOW, HOUR6) is None
    write_journal(tmp_path, rec("2099-01-01T00:00:00"))
    assert pp.read_signal(tmp_path, NOW, HOUR6)["last_signal"] == "2099-01-01T00:00:00"


def test_journal_path_given_as_windows_forward_slash_string(tmp_path):
    # porcelain на Windows даёт `C:/…`: в read_signal путь приходит строкой, не Path
    write_journal(tmp_path, rec("2026-10-03T11:00:00"))
    assert pp.read_signal(str(tmp_path).replace("\\", "/"), NOW, HOUR6)["sessions"] == 1


# =========================================================================== git: список worktree


def _root_fake(tmp_path: Path, listing: str | None, top: str | None = None) -> FakeGit:
    return FakeGit(
        (("rev-parse", "--show-toplevel"), (str(tmp_path) if top is None else top) + "\n"),
        (("worktree", "list", "--porcelain"), listing),
    )


def test_worktrees_parse_porcelain_branch_detached_bare_and_path_forms(tmp_path, monkeypatch):
    listing = (
        "worktree C:/Users/Иван Петров/repo\nHEAD aaa\nbranch refs/heads/main\n\n"
        "worktree C:/Users/Иван Петров/wt a\nHEAD bbb\nbranch refs/heads/feat/a/deep\n\n"
        "worktree D:/detached\nHEAD ccc\ndetached\n\n"
        "worktree D:/bare.git\nbare\n\n"
        "worktree D:/odd\nHEAD ddd\nbranch refs/remotes/o/x\nlocked reason\n"
    )
    monkeypatch.setattr(pp, "_git", _root_fake(tmp_path, listing))
    assert pp.git_worktrees(tmp_path) == [
        ("C:/Users/Иван Петров/repo", "main"),
        ("C:/Users/Иван Петров/wt a", "feat/a/deep"),
        ("D:/detached", ""),
        ("D:/odd", "refs/remotes/o/x"),
    ]


def test_worktrees_parse_porcelain_with_crlf(tmp_path, monkeypatch):
    listing = (
        "worktree C:/r\r\nHEAD a\r\nbranch refs/heads/main\r\n\r\nworktree C:/w\r\nHEAD b\r\nbranch refs/heads/x\r\n"
    )
    monkeypatch.setattr(pp, "_git", _root_fake(tmp_path, listing))
    assert pp.git_worktrees(tmp_path) == [("C:/r", "main"), ("C:/w", "x")]


def test_worktrees_empty_when_git_has_no_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "_git", FakeGit())  # на всё None: нет git, не репозиторий, таймаут
    assert pp.git_worktrees(tmp_path) == []


def test_worktrees_empty_when_toplevel_is_another_directory(tmp_path, monkeypatch):
    root = tmp_path / "sub"
    root.mkdir()
    fake = _root_fake(tmp_path, "worktree C:/r\nbranch refs/heads/main\n", top=str(tmp_path))
    monkeypatch.setattr(pp, "_git", fake)
    assert pp.git_worktrees(root) == []
    assert ("worktree", "list", "--porcelain") not in [c[0] for c in fake.calls], (
        "список worktree чужого репозитория не запрашивается"
    )


def test_worktrees_empty_when_toplevel_path_does_not_exist_or_is_blank(tmp_path, monkeypatch):
    for top in (str(tmp_path / "no_such_dir"), ""):
        monkeypatch.setattr(pp, "_git", _root_fake(tmp_path, "worktree C:/r\nbranch refs/heads/main\n", top=top))
        assert pp.git_worktrees(tmp_path) == [], top


def test_worktrees_toplevel_in_git_slash_form_matches_root(tmp_path, monkeypatch):
    # git печатает toplevel с `/`, а --root приходит как Path с `\` (Windows): samefile, не сравнение строк
    monkeypatch.setattr(
        pp,
        "_git",
        _root_fake(tmp_path, "worktree C:/r\nbranch refs/heads/main\n", top=str(tmp_path).replace("\\", "/")),
    )
    assert pp.git_worktrees(tmp_path) == [("C:/r", "main")]


# =========================================================================== git: вызов


def test_git_helper_failure_modes_all_return_none(monkeypatch):
    for exc in (
        subprocess.TimeoutExpired(["git"], 10),
        FileNotFoundError("git"),
        PermissionError("x"),
        ValueError("embedded null byte"),
    ):

        def boom(*a, _exc=exc, **k):
            raise _exc

        monkeypatch.setattr(pp.subprocess, "run", boom)
        assert pp._git(["status"], ".") is None, exc


def test_git_helper_nonzero_exit_is_none_even_with_stdout(monkeypatch):
    monkeypatch.setattr(
        pp.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 128, stdout="partial\n", stderr="fatal")
    )
    assert pp._git(["x"], ".") is None


def test_git_helper_passes_timeout_utf8_and_strips_inherited_git_env(monkeypatch):
    seen = {}

    def spy(args, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.setenv(var, "C:/elsewhere")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "keep")
    monkeypatch.setattr(pp.subprocess, "run", spy)
    assert pp._git(["x"], ".") == "ok"
    assert seen["timeout"] == pp.GIT_TIMEOUT
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
    assert not {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"} & set(seen["env"])
    assert seen["env"]["GIT_AUTHOR_NAME"] == "keep"


# =========================================================================== имена планов


@pytest.mark.parametrize(
    ("value", "name"),
    [
        ("A", "A"),
        ("plans/A", "A"),
        ("plans/A/", "A"),
        ("./plans/A/plan.md", "A"),
        ("plans/A/tasks/1.1.md", "A"),
        ("plans\\A\\tasks\\1.1.md", "A"),
        ("plans/F.md", "F"),
        ("plans/_archive/OLD/plan.md", "OLD"),
        ("plans/_archive/2026-Q3/OLD.md", "OLD"),
        ("plans/_archive/2026-Q3/OLD/tasks/2.1.md", "OLD"),
        ("  plans/A \n", "A"),
        ("", None),
        ("plans/", None),
        ("plans/.md", None),
        ("plans/_archive/", None),
        ("plans/_archive/2026-Q3", None),
    ],
)
def test_plan_name_from_ref(value, name):
    assert pp.plan_name_from_ref(value) == name


def test_find_plan_prefers_live_over_archived_and_ignores_empty_name():
    live, old = mem_plan("X"), mem_plan("X", archived=True)
    assert pp.find_plan([old, live], "X") is live
    assert pp.find_plan([old], "X") is old
    assert pp.find_plan([live], None) is None and pp.find_plan([live], "") is None and pp.find_plan([live], "Y") is None


# =========================================================================== шаг refs: токен


@pytest.mark.parametrize(
    ("message", "token"),
    [
        ("feat: x\n\nWhy: w\nRefs: plans/Y/tasks/1.1.md", "plans/Y/tasks/1.1.md"),
        ("Refs: plans/Y/plan.md, plans/Z/plan.md; ADR-1", "plans/Y/plan.md"),
        ("Refs: (plans/Y)", "plans/Y"),
        ("Refs: plans/Y.", "plans/Y"),
        ("Refs: ADR-120\n  plans/Q/plan.md", "plans/Q/plan.md"),  # перенос трейлера с отступом
        ("Refs: ADR-120\nplans/Q/plan.md", None),  # строка без отступа — уже не Refs
        ("Refs: ADR-120\nWhy: see plans/Q", None),
        ("see plans/Q in the body", None),  # токен вне строки Refs
        ("Refs: ADR-120", None),
        ("", None),
    ],
)
def test_newest_refs_token(message, token):
    assert pp._newest_refs_token(message) == token


def test_refs_step_skips_commits_without_a_token_and_stops_at_first_token_even_if_unknown(monkeypatch):
    plans = [mem_plan("Y")]
    log = "\0".join(["chore: nothing", "docs\n\nRefs: ADR-1", "feat: n\n\nRefs: plans/N", "feat: y\n\nRefs: plans/Y"])
    monkeypatch.setattr(pp, "_git", FakeGit((("log",), log)))
    assert pp._step_refs("feat/y", Path("."), plans) is None  # новейший токен назвал N: к Y не идём
    log2 = "\0".join(["chore: nothing", "docs\n\nRefs: ADR-1", "feat: y\n\nRefs: plans/Y"])
    monkeypatch.setattr(pp, "_git", FakeGit((("log",), log2)))
    assert pp._step_refs("feat/y", Path("."), plans) is plans[0]


def test_refs_step_log_range_is_main_to_the_branch_ref(monkeypatch):
    fake = FakeGit((("log",), ""))
    monkeypatch.setattr(pp, "_git", fake)
    pp._step_refs("feat/y", Path("R"), [])
    args, cwd = fake.calls[0]
    assert "main..refs/heads/feat/y" in args and args[-1] == "--" and cwd == "R"


# =========================================================================== шаг header: разбор шапки и выбор


def test_find_header_branch_first_label_line_decides_even_without_a_token():
    assert pp.find_header_branch("- **Ветка:** позже\n- **Ветка:** feat/later") == ""
    assert pp.find_header_branch("# T\n- **Branch:** `feat/a/b` — трек\n") == "feat/a/b"
    assert pp.find_header_branch("Ветка: feat/x.") == "feat/x"


@pytest.mark.parametrize(
    ("line", "branch"),
    [
        ("- **Ветка:** feat/x+y", "feat/x+y"),
        ("- **Ветка:** `feat/a@b#1`", "feat/a@b#1"),
        ("- **Ветка:** feat/x+y (от main)", "feat/x+y"),
        ("- **Ветка:** `feat/x+y` — трек", "feat/x+y"),
        ("- **Ветка:** feat/x+y, затем fix/z", "feat/x+y"),
        ("- **Ветка:** feat/x+y; поправить", "feat/x+y"),
    ],
)
def test_find_header_branch_keeps_git_legal_characters_and_cuts_the_tail(line, branch):
    assert pp.find_header_branch(line) == branch


def test_real_git_branch_with_plus_at_and_hash_resolves_via_header(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    (repo / "plans").mkdir(parents=True)
    body = "\n## Порядок выполнения\n\n- Task 1.1: x [PENDING]\n"
    (repo / "plans" / "P.md").write_text("# P\n\n- **Ветка:** feat/x+y\n" + body, encoding="utf-8")
    (repo / "plans" / "Q.md").write_text("# Q\n\n- **Ветка:** `feat/a@b#1` — трек\n" + body, encoding="utf-8")
    _git_ok(repo, "init", "-q", "-b", "main")
    for k, v in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
        _git_ok(repo, "config", k, v)
    _git_ok(repo, "add", "-A")
    _git_ok(repo, "commit", "-q", "-m", "init")
    wts = {}
    for name, branch in (("p", "feat/x+y"), ("q", "feat/a@b#1")):
        wts[name] = tmp_path / f"wt_{name}"
        _git_ok(repo, "worktree", "add", "-q", "-b", branch, str(wts[name]), "main")
        write_journal(wts[name], rec("2026-10-03T11:30:00"))
    code, out, _ = _run_main(["--root", str(repo), "--who", "--now", "2026-10-03T12:00:00"], capsys)
    who = json.loads(out)
    assert code == 0 and who["orphans"] == []
    assert sorted((e["plan"], e["branch"], e["via"]) for e in who["active"]) == [
        ("P", "feat/x+y", "header"),
        ("Q", "feat/a@b#1", "header"),
    ]


def test_find_header_branch_ignores_fenced_lines_and_lines_past_30():
    assert pp.find_header_branch("```\nВетка: feat/in-fence\n```\nВетка: feat/after") == "feat/after"
    assert pp.find_header_branch("\n" * 30 + "Ветка: feat/x") == ""
    assert pp.find_header_branch("\n" * 29 + "Ветка: feat/x") == "feat/x"


def test_header_step_live_duplicate_does_not_fall_through_to_archive():
    a, b, old = mem_plan("P", "feat/d"), mem_plan("Q", "feat/d"), mem_plan("OLD", "feat/d", archived=True)
    assert pp._step_header("feat/d", [a, b, old]) is None
    assert pp._step_header("feat/d", [a, old]) is a
    assert pp._step_header("feat/d", [old]) is old
    assert pp._step_header("feat/d", [old, mem_plan("OLD2", "feat/d", archived=True)]) is None


def test_header_step_needs_whole_branch_and_nonempty_branch():
    assert pp._step_header("feat/x", [mem_plan("P", "feat/xy")]) is None
    assert pp._step_header("", [mem_plan("P", "")]) is None  # detached HEAD не равен плану без ветки в шапке


# =========================================================================== порядок шагов и вызовы


def test_resolver_plan_ref_wins_and_later_steps_are_not_even_run(monkeypatch):
    plans = [mem_plan("A"), mem_plan("Y"), mem_plan("H", "feat/a")]
    fake = FakeGit((("config",), "plans/A\n"), (("log",), "feat\n\nRefs: plans/Y"))
    monkeypatch.setattr(pp, "_git", fake)
    found = pp.resolve_plan("feat/a", Path("W"), Path("R"), plans)
    assert found == (plans[0], "plan_ref")
    assert fake.verbs() == ["config"]
    assert fake.calls[0][0] == ("config", "--worktree", "--get", "plan.ref") and fake.calls[0][1] == "W"


def test_resolver_unknown_plan_ref_blank_ref_and_git_failure_fall_through(monkeypatch):
    plans = [mem_plan("Y"), mem_plan("H", "feat/a")]
    for config in ("plans/Nope\n", "\n", "   \n", None):
        fake = FakeGit((("config",), config), (("log",), "feat\n\nRefs: plans/Y"))
        monkeypatch.setattr(pp, "_git", fake)
        assert pp.resolve_plan("feat/a", Path("W"), Path("R"), plans) == (plans[0], "refs"), config


def test_resolver_unknown_refs_name_does_not_block_header_step(monkeypatch):
    plans = [mem_plan("H", "feat/a")]
    monkeypatch.setattr(pp, "_git", FakeGit((("log",), "feat\n\nRefs: plans/Nope")))
    assert pp.resolve_plan("feat/a", Path("W"), Path("R"), plans) == (plans[0], "header")


def test_resolver_without_worktree_skips_only_plan_ref(monkeypatch):
    # путь Task 5.5: ветка без каталога. config не вызывается ни разу; refs и header работают
    plans = [mem_plan("Y"), mem_plan("H", "feat/h")]
    fake = FakeGit((("log",), "feat\n\nRefs: plans/Y"))
    monkeypatch.setattr(pp, "_git", fake)
    assert pp.resolve_plan("feat/y", None, Path("R"), plans) == (plans[0], "refs")
    assert "config" not in fake.verbs()


def test_resolver_without_worktree_header_step_when_log_has_no_trace(monkeypatch):
    plans = [mem_plan("H", "feat/h")]
    fake = FakeGit()  # git молчит на всё
    monkeypatch.setattr(pp, "_git", fake)
    assert pp.resolve_plan("feat/h", None, Path("R"), plans) == (plans[0], "header")
    assert "config" not in fake.verbs()


def test_resolver_detached_head_runs_only_plan_ref(monkeypatch):
    plans = [mem_plan("H", "")]
    fake = FakeGit((("config",), None))
    monkeypatch.setattr(pp, "_git", fake)
    assert pp.resolve_plan("", Path("W"), Path("R"), plans) is None
    assert fake.verbs() == ["config"], "пустая ветка: ни `log main..`, ни шапка"
    fake2 = FakeGit((("config",), "plans/H\n"))
    monkeypatch.setattr(pp, "_git", fake2)
    assert pp.resolve_plan("", Path("W"), Path("R"), plans) == (plans[0], "plan_ref")


def test_resolver_returns_none_and_never_raises_when_every_git_call_fails(monkeypatch):
    monkeypatch.setattr(pp, "_git", FakeGit())
    assert pp.resolve_plan("feat/x", Path("W"), Path("R"), [mem_plan("P", "feat/other")]) is None
    assert pp.resolve_plan("feat/x", None, Path("R"), []) is None


# =========================================================================== сбор: число вызовов git и сортировка


def test_git_runs_per_root_only_for_roots_with_a_fresh_journal_line(tmp_path, monkeypatch):
    names = [f"w{i:02d}" for i in range(40)]
    dirs = {n: tmp_path / n for n in names}
    listing = "".join(f"worktree {dirs[n]}\nHEAD a\nbranch refs/heads/feat/{n}\n\n" for n in names)
    write_journal(dirs["w07"], rec("2026-10-03T11:00:00"))  # свежая
    write_journal(dirs["w08"], rec("2026-10-02T01:00:00"))  # старая
    write_journal(dirs["w09"], "{broken")  # битая
    fake = FakeGit((("rev-parse",), str(tmp_path) + "\n"), (("worktree",), listing))
    monkeypatch.setattr(pp, "_git", fake)
    active, orphans = pp.collect_active(tmp_path, [], NOW, HOUR6)
    assert active == [] and [o["branch"] for o in orphans] == ["feat/w07"]
    assert fake.verbs().count("config") == 1 and fake.verbs().count("log") == 1, fake.verbs()
    assert len(fake.calls) == 2 + 2, "rev-parse + worktree list + config + log для одного свежего корня"


def test_collect_active_entry_key_order_and_orphan_keys(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    write_journal(a, rec("2026-10-03T11:00:00"))
    write_journal(b, rec("2026-10-03T11:00:00"))
    listing = f"worktree {a}\nbranch refs/heads/feat/a\n\nworktree {b}\nbranch refs/heads/feat/b\n"
    monkeypatch.setattr(pp, "_git", FakeGit((("rev-parse",), str(tmp_path) + "\n"), (("worktree",), listing)))
    plans = [mem_plan("A", "feat/a")]
    active, orphans = pp.collect_active(tmp_path, plans, NOW, HOUR6)
    assert [(p.name, list(e)) for p, e in active] == [
        ("A", ["branch", "worktree", "via", "sessions", "agents", "last_signal"])
    ]
    assert list(orphans[0]) == ["branch", "worktree", "sessions", "agents", "last_signal"]


def test_attach_active_sorts_by_worktree_string_as_porcelain_wrote_it():
    p = mem_plan("X")
    pp.attach_active([p], [(p, {"worktree": "C:/b"}), (p, {"worktree": "C:/a/zz"}), (p, {"worktree": "C:/a"})])
    assert [e["worktree"] for e in p.active] == ["C:/a", "C:/a/zz", "C:/b"]


def test_to_json_active_is_a_fresh_list_per_plan_and_last_key():
    p, q = mem_plan("P"), mem_plan("Q")
    p.active.append({"worktree": "x"})
    data = json.loads(pp.to_json([p, q]))
    assert data[0]["active"] == [{"worktree": "x"}] and data[1]["active"] == []
    assert list(data[0])[-1] == "active" and list(data[1])[-1] == "active"


# =========================================================================== CLI: проводка


def _run_main(argv, capsys) -> tuple[int, str, str]:
    code = pp.main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def _plain_root(tmp_path: Path) -> Path:
    root = tmp_path / "plain"
    (root / "plans").mkdir(parents=True)
    (root / "plans" / "X.md").write_text("# X\n\n## Порядок выполнения\n\n- Task 1.1: x [PENDING]\n", encoding="utf-8")
    return root


def test_main_who_survives_git_timeouts_everywhere(tmp_path, monkeypatch, capsys):
    root = _plain_root(tmp_path)

    def hang(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 10)

    monkeypatch.setattr(pp.subprocess, "run", hang)
    code, out, _ = _run_main(["--root", str(root), "--who", "--now", "2026-10-03T12:00:00"], capsys)
    assert code == 0 and json.loads(out) == {"active": [], "orphans": []}
    code, out, _ = _run_main(["--root", str(root), "--json", "--now", "2026-10-03T12:00:00"], capsys)
    assert code == 0 and json.loads(out)[0]["active"] == []


def test_main_flag_errors_exit_2_before_any_work_and_before_any_write(tmp_path, capsys):
    root = _plain_root(tmp_path)
    page = tmp_path / "page.html"
    for argv in (
        ["--who", "--html", str(page)],
        ["--who", "--sync-order"],
        ["--now", "oops", "--check"],  # флаг, который режиму не нужен, всё равно проверяется
        ["--active-window", "6x", "--html", str(page)],
    ):
        code, out, err = _run_main(["--root", str(root), *argv], capsys)
        assert code == 2 and out == "" and err.strip(), argv
    assert not page.exists() and not (root / "data").exists()


def test_main_window_with_more_digits_than_int_allows_exits_2_without_echo(tmp_path, capsys):
    value = "9" * 4301 + "h"  # int() на 4301 цифре — ValueError «Exceeds the limit»: был exit 1 вместо 2
    code, out, err = _run_main(["--root", str(_plain_root(tmp_path)), "--who", "--active-window", value], capsys)
    assert code == 2 and out == "" and err.strip()
    assert "9999" not in err


def test_main_html_and_check_do_not_touch_git_for_the_active_resolver(tmp_path, monkeypatch, capsys):
    root = _plain_root(tmp_path)
    monkeypatch.setattr(pp, "collect_active", lambda *a, **k: pytest.fail("резолвер вызван вне --json/--who"))
    assert _run_main(["--root", str(root), "--html", str(tmp_path / "p.html")], capsys)[0] == 0
    assert _run_main(["--root", str(root), "--check"], capsys)[0] in (0, 1)
    assert _run_main(["--root", str(root)], capsys)[0] == 0


def _git_ok(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, timeout=60)


def test_real_git_only_the_log_step_hangs_and_the_root_becomes_an_orphan(tmp_path, monkeypatch, capsys):
    """Настоящий репозиторий и worktree; таймаут только у `git log`: шаг refs молчит, шапки нет -> сирота, exit 0."""
    repo = tmp_path / "repo"
    (repo / "plans").mkdir(parents=True)
    (repo / "plans" / "Y.md").write_text("# Y\n\n## Порядок выполнения\n\n- Task 1.1: x [PENDING]\n", encoding="utf-8")
    _git_ok(repo, "init", "-q", "-b", "main")
    for k, v in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
        _git_ok(repo, "config", k, v)
    _git_ok(repo, "add", "-A")
    _git_ok(repo, "commit", "-q", "-m", "init")
    wt = tmp_path / "wt"
    _git_ok(repo, "worktree", "add", "-q", "-b", "feat/y", str(wt), "main")
    _git_ok(wt, "commit", "-q", "--allow-empty", "-m", "feat: y\n\nWhy: w\nLayer: tests\nRefs: plans/Y")
    write_journal(wt, rec("2026-10-03T11:30:00"))

    real_run = subprocess.run

    def run_hanging_log(args, **kw):
        if args[:2] == ["git", "log"]:
            raise subprocess.TimeoutExpired(args, kw.get("timeout", 0))
        return real_run(args, **kw)

    argv = ["--root", str(repo), "--who", "--now", "2026-10-03T12:00:00"]
    code, out, _ = _run_main(argv, capsys)
    assert code == 0 and [(e["plan"], e["via"]) for e in json.loads(out)["active"]] == [("Y", "refs")], (
        "контроль: без зависания план найден"
    )
    monkeypatch.setattr(pp.subprocess, "run", run_hanging_log)
    code, out, _ = _run_main(argv, capsys)
    who = json.loads(out)
    assert code == 0 and who["active"] == []
    assert [Path(e["worktree"]) for e in who["orphans"]] == [wt.resolve()] and who["orphans"][0]["branch"] == "feat/y"
