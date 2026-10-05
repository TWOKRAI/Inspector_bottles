# -*- coding: utf-8 -*-
"""Task 2.3: hazard-тесты автора — риски ИМЕННО этого механизма (разбор shell-текста и JSONL-потока).

Что может сломаться в классификаторе, учитывая, как он устроен:
  * кавычка через несколько строк с `\\"` внутри — построчный разбор теряет попытку или видит чужой `git commit`;
  * heredoc внутри `$(...)` внутри `"..."` — тело (с апострофами и «git commit») не должно ни ломать кавычки, ни
    давать лишнюю попытку;
  * `tool_result.content` — список блоков, а не строка;
  * битая строка JSONL — пропустить, посчитать, сказать в stderr, не падать;
  * транскрипт в несколько МБ — разбор линейный (враждебный ввод: миллионы точек/пустых строк/`;`);
  * пути Windows с `\\` в `cd` и в `cwd`;
  * порядок писателей: побеждает ПОСЛЕДНИЙ (Bash после Edit и Edit после Bash дают разные метки).
Ожидаемые значения — литералы. Корни собираются во временном каталоге под именем проекта.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "classify.py"
PROJECT_DIR = "d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles"
REPO = "D:\\PROJECT_INNOTECH\\Inspector_vision\\Inspector_bottles"
RUFF_FORMAT_FAILED = "ruff format" + "." * 50 + "Failed\n- hook id: ruff-format\n- files were modified by this hook\n"
B1_TEXT = (
    "ERROR: Commit message is invalid:\n"
    "  - Branch has a plan (plans/x.md) but commit is missing matching `Refs:` trailer.\n"
)
OK_COMMIT = "[feat/x 1a2b3c4] test: something\n 1 file changed, 2 insertions(+)\n"


# ----------------------------------------------------------------------------------------------
# сборка транскрипта и запуск CLI (с дедлайном: тест, который может зависнуть, не должен вешать набор)
# ----------------------------------------------------------------------------------------------
def use(tid: str, command: str, ts: str = "2026-09-10T12:00:00.000Z", cwd: str = REPO) -> str:
    block = {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": command}}
    return json.dumps({"type": "assistant", "timestamp": ts, "cwd": cwd, "message": {"content": [block]}})


def edit(tid: str, path: str, name: str = "Edit", ts: str = "2026-09-10T11:00:00.000Z") -> str:
    block = {"type": "tool_use", "id": tid, "name": name, "input": {"file_path": path}}
    return json.dumps({"type": "assistant", "timestamp": ts, "cwd": REPO, "message": {"content": [block]}})


def res(tid: str, content, ts: str = "2026-09-10T12:00:05.000Z") -> str:
    block = {"type": "tool_result", "tool_use_id": tid, "content": content}
    return json.dumps({"type": "user", "timestamp": ts, "cwd": REPO, "message": {"content": [block]}})


def make_root(tmp_path: Path, lines: list[str]) -> Path:
    folder = tmp_path / "root" / PROJECT_DIR
    folder.mkdir(parents=True)
    (folder / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path / "root"


def run(root: Path, deadline: float = 60.0) -> tuple[dict, str, float]:
    """Запустить CLI в потоке с дедлайном; вернуть (JSON-отчёт, stderr, секунды)."""
    cmd = [sys.executable, str(SCRIPT), "--root", str(root), "--since", "2026-09-01", "--until", "2026-10-05", "--json"]
    box: dict = {}

    def work() -> None:
        box["proc"] = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"}
        )

    started = time.perf_counter()
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(deadline)
    elapsed = time.perf_counter() - started
    assert not thread.is_alive(), f"classify.py не уложился в {deadline} с (квадратичный разбор?)"
    proc = box["proc"]
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr: {proc.stderr[:400]}"
    return json.loads(proc.stdout), proc.stderr, elapsed


def one(tmp_path: Path, command: str, result: str = B1_TEXT, cwd: str = REPO) -> dict:
    return run(make_root(tmp_path, [use("t1", command, cwd=cwd), res("t1", result)]))[0]


# ----------------------------------------------------------------------------------------------
# кавычка через несколько строк
# ----------------------------------------------------------------------------------------------
def test_multiline_python_c_with_escaped_quotes_hides_the_commit_text_but_not_the_real_one(tmp_path):
    # внутри строки — `git merge` (другой вид попытки): закройся кавычка на `\"`, merge стал бы виден
    command = 'python -c "\nprint(\\"x\\")\ngit merge inside_the_string\n" && git commit -q -m real'
    out = one(tmp_path, command)
    assert (out["commit_calls"], out["merge_calls"]) == (1, 0)
    assert out["table"]["B1"]["commit"] == 1


def test_commit_text_only_inside_a_multiline_quote_is_not_an_attempt(tmp_path):
    command = 'python -c "\nprint(\\"ok\\")\ngit commit -m inside_the_string\n"'
    out = one(tmp_path, command)
    assert out["commit_calls"] == 0 and out["attempts"] == {}


def test_attempt_after_a_multiline_quote_with_an_unbalanced_apostrophe_inside_double_quotes(tmp_path):
    command = 'echo "line one\nit\'s not a quote start\nline three"\ngit commit -q -m x'
    out = one(tmp_path, command)
    assert out["commit_calls"] == 1


# ----------------------------------------------------------------------------------------------
# heredoc внутри $(...)
# ----------------------------------------------------------------------------------------------
def test_nested_heredoc_inside_command_substitution_neither_breaks_quotes_nor_adds_attempts(tmp_path):
    command = (
        "git add a.py && git commit -m \"$(cat <<'EOF'\n"
        'fix: it\'s "quoted" and mentions\ngit merge feat/other\ngit commit -m fake\nEOF\n)" && git status'
    )
    out = one(tmp_path, command)
    assert out["commit_calls"] == 1
    assert out["merge_calls"] == 0
    assert out["attempts"]["t1"]["kinds"] == ["commit"]


def test_two_heredocs_in_one_command_both_bodies_are_dropped(tmp_path):
    command = (
        "cat > a.txt <<'A'\ngit commit -m body_a\nA\ncat > b.txt <<'B'\ngit merge body_b\nB\ngit commit -q -m real"
    )
    out = one(tmp_path, command)
    assert (out["commit_calls"], out["merge_calls"]) == (1, 0)


def test_unterminated_heredoc_swallows_the_rest_like_bash_and_keeps_the_header_command(tmp_path):
    command = "git commit -q -F - <<'EOF'\nmessage without a closing delimiter\ngit merge feat/x"
    out = one(tmp_path, command)
    assert (out["commit_calls"], out["merge_calls"]) == (1, 0)


# ----------------------------------------------------------------------------------------------
# tool_result.content — список блоков
# ----------------------------------------------------------------------------------------------
def test_tool_result_content_as_a_list_of_text_blocks_is_classified_like_a_string(tmp_path):
    blocks = [{"type": "text", "text": "warning: crlf\n"}, {"type": "text", "text": RUFF_FORMAT_FAILED}]
    out = one(tmp_path, "git commit -q -m x", result=blocks)
    assert "A1" in out["attempts"]["t1"]["classes"]
    assert out["attempts"]["t1"]["outcome"] == "failure"


def test_tool_result_with_null_or_empty_content_is_an_attempt_with_unknown_outcome(tmp_path):
    for content in (None, [], ""):
        out = one(tmp_path / str(type(content).__name__), "git commit -q -m x", result=content)
        assert out["attempts"]["t1"] == {"kinds": ["commit"], "classes": [], "hidden": False, "outcome": "unknown"}


def test_crlf_in_the_tool_result_does_not_break_the_status_line_anchor(tmp_path):
    out = one(tmp_path, "git commit -q -m x", result=RUFF_FORMAT_FAILED.replace("\n", "\r\n"))
    assert "A1" in out["attempts"]["t1"]["classes"]


# ----------------------------------------------------------------------------------------------
# битый JSONL
# ----------------------------------------------------------------------------------------------
def test_malformed_jsonl_lines_are_skipped_counted_and_reported_on_stderr(tmp_path):
    lines = [
        "{this is not json",
        use("t1", "git commit -q -m x"),
        '{"truncated": "line',
        "[1, 2, 3]",
        res("t1", B1_TEXT),
    ]
    out, err, _ = run(make_root(tmp_path, lines))
    assert out["table"]["B1"]["commit"] == 1
    assert "3 malformed JSONL line" in err


def test_a_clean_transcript_prints_only_the_files_summary_on_stderr(tmp_path):
    _, err, _ = run(make_root(tmp_path, [use("t1", "git commit -q -m x"), res("t1", B1_TEXT)]))
    assert err == "classify: 1 file(s) read, 0 skipped (mtime before --since)\n"


# ----------------------------------------------------------------------------------------------
# большой транскрипт: разбор линейный
# ----------------------------------------------------------------------------------------------
def test_a_multi_megabyte_transcript_is_scanned_in_linear_time(tmp_path):
    filler = [use(f"f{i}", f"ls -la dir_{i} && echo {'x' * 200}") for i in range(8000)]  # ~2.3 МБ командами
    noisy = "echo 'a'; " * 120_000 + "git commit -q -m x"  # ~1.2 МБ одной командой: много `;` и кавычек
    lines = [*filler, use("big", noisy), res("big", B1_TEXT)]
    out, _, elapsed = run(make_root(tmp_path, lines), deadline=60.0)
    assert out["table"]["B1"]["commit"] == 1
    assert elapsed < 40.0, f"{elapsed:.1f} с на ~3.5 МБ: разбор не линейный"


@pytest.mark.parametrize(
    "result",
    [
        pytest.param("x" + "." * 1_500_000, id="one-line-of-1.5M-dots"),
        pytest.param("\n" * 1_500_000 + "error: a.py: patch does not apply", id="1.5M-blank-lines-then-A3"),
        pytest.param("ruff" + "." * 60 + "Failed\n" + "E501 Line too long\n" * 50_000, id="50k-lines-in-one-block"),
    ],
)
def test_hostile_tool_result_does_not_make_the_signatures_quadratic(tmp_path, result):
    out, _, elapsed = run(make_root(tmp_path, [use("t1", "git commit -q -m x"), res("t1", result)]), deadline=60.0)
    assert out["commit_calls"] == 1
    assert elapsed < 30.0, f"{elapsed:.1f} с на враждебном tool_result"


def test_one_huge_quote_spanning_megabytes_is_masked_in_linear_time(tmp_path):
    command = 'python -c "' + ('print(\\"x\\")\n' * 150_000) + '" && git commit -q -m x'
    out, _, elapsed = run(make_root(tmp_path, [use("t1", command), res("t1", B1_TEXT)]))
    assert out["table"]["B1"]["commit"] == 1
    assert elapsed < 30.0


# ----------------------------------------------------------------------------------------------
# пути Windows
# ----------------------------------------------------------------------------------------------
def test_cd_with_backslashes_into_the_repo_from_a_scratch_cwd_counts(tmp_path):
    scratch = "C:\\Users\\x\\AppData\\Local\\Temp\\claude\\sess\\scratchpad"
    command = f"cd {REPO}\\.claude\\worktrees\\wt && git commit -q -m x"
    assert one(tmp_path, command, cwd=scratch)["commit_calls"] == 1


def test_cd_with_backslashes_out_of_the_repo_does_not_count(tmp_path):
    command = "cd C:\\Users\\x\\AppData\\Local\\Temp\\lab && git commit -q -m x"
    assert one(tmp_path, command)["commit_calls"] == 0


def test_cd_to_a_relative_backslash_path_resolves_against_the_record_cwd(tmp_path):
    assert one(tmp_path, "cd .claude\\worktrees\\wt && git commit -q -m x")["commit_calls"] == 1


def test_cd_dotdot_out_of_the_repo_uses_the_normalised_path(tmp_path):
    cwd = REPO + "\\.claude\\worktrees\\wt"
    assert one(tmp_path / "up", "cd ..\\..\\.. && git commit -q -m x", cwd=cwd)["commit_calls"] == 1
    assert one(tmp_path / "out", "cd ..\\..\\..\\.. && git commit -q -m x", cwd=cwd)["commit_calls"] == 0


def test_windows_cwd_with_a_lowercase_drive_and_forward_slashes_counts(tmp_path):
    out = one(tmp_path, "git commit -q -m x", cwd="d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles")
    assert out["commit_calls"] == 1


# ----------------------------------------------------------------------------------------------
# порядок писателей A1: побеждает последний
# ----------------------------------------------------------------------------------------------
PY = REPO + "\\mod\\a.py"


def _a1_split(tmp_path: Path, writers: list[str]) -> list[str]:
    lines = [*writers, use("c1", "git add mod/a.py && git commit -q -m x"), res("c1", RUFF_FORMAT_FAILED)]
    out = run(make_root(tmp_path, lines))[0]
    return [c for c in out["attempts"]["c1"]["classes"] if c.startswith("A1-")]


def test_a1_split_edit_then_bash_write_is_bash(tmp_path):
    writers = [edit("e1", PY), use("b1", "sed -i 's/a/b/' mod/a.py", ts="2026-09-10T11:30:00.000Z")]
    assert _a1_split(tmp_path, writers) == ["A1-Bash"]


def test_a1_split_bash_write_then_edit_is_edit_write(tmp_path):
    writers = [use("b1", "sed -i 's/a/b/' mod/a.py", ts="2026-09-10T10:30:00.000Z"), edit("e1", PY, name="MultiEdit")]
    assert _a1_split(tmp_path, writers) == ["A1-Edit/Write"]


def test_a1_split_without_any_writer_in_the_transcript_is_undecided(tmp_path):
    assert _a1_split(tmp_path, []) == ["A1-undecided"]


def test_a1_split_bash_command_that_only_reads_the_file_is_not_a_writer(tmp_path):
    writers = [edit("e1", PY), use("b1", "pytest mod/a.py -q > out.txt", ts="2026-09-10T11:30:00.000Z")]
    assert _a1_split(tmp_path, writers) == ["A1-Edit/Write"]


def test_a1_split_does_not_run_for_a_failure_without_a1(tmp_path):
    lines = [edit("e1", PY), use("c1", "git add mod/a.py && git commit -q -m x"), res("c1", B1_TEXT)]
    out = run(make_root(tmp_path, lines))[0]
    assert out["attempts"]["c1"]["classes"] == ["B1"]


def test_a1_staged_via_a_previous_git_add_call_after_the_last_attempt(tmp_path):
    lines = [
        edit("e1", PY),
        use("a1", "git add mod/a.py", ts="2026-09-10T11:20:00.000Z"),
        res("a1", ""),
        use("c1", "git commit -q -m x"),
        res("c1", RUFF_FORMAT_FAILED),
    ]
    out = run(make_root(tmp_path, lines))[0]
    assert "A1-Edit/Write" in out["attempts"]["c1"]["classes"]


def test_dash_a_commit_takes_the_py_written_after_the_previous_attempt(tmp_path):
    lines = [edit("e1", PY), use("c1", "git commit -q -a -m x"), res("c1", RUFF_FORMAT_FAILED)]
    out = run(make_root(tmp_path, lines))[0]
    assert "A1-Edit/Write" in out["attempts"]["c1"]["classes"]


# ----------------------------------------------------------------------------------------------
# якорь ^ у сигнатур: цитата посреди строки (вывод cat документа, лог в тексте) — не класс
# (инъекция лида L10: снятый якорь у A3 не краснил ни один тест)
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "quoted",
    [
        "> error: docs/sessions/x.md: patch does not apply",
        "see:   - Branch has a plan (plans/x.md) but commit is missing matching `Refs:` trailer.",
        "note:   - Unknown type 'merge'.",
        "quote: bash: line 3: unexpected EOF while looking for matching `''",
        "> error: could not read file '-'",
    ],
    ids=["A3", "B1", "B2", "C2", "C4"],
)
def test_a_signature_quoted_mid_line_is_not_a_class(tmp_path, quoted):
    out = one(tmp_path, "git commit -q -m x", result=f"doc line\n{quoted}\n{OK_COMMIT}")
    assert out["attempts"]["t1"]["classes"] == [], out["attempts"]["t1"]


# ----------------------------------------------------------------------------------------------
# Ред. 4: писатель — по ЦЕЛЯМ записи (ревью r1)
# ----------------------------------------------------------------------------------------------
def _split_with(tmp_path: Path, before: list[str], commit_cmd: str) -> list[str]:
    """Метки разбивки A1 для коммит-вызова `commit_cmd` после событий `before` (Edit/Write — id e*, Bash — b*)."""
    lines = [*before, use("c1", commit_cmd), res("c1", RUFF_FORMAT_FAILED)]
    out = run(make_root(tmp_path, lines))[0]
    return [c for c in out["attempts"]["c1"]["classes"] if c.startswith("A1-") and c != "A1-F401"]


def _bash(tid: str, command: str, minute: int = 30) -> str:
    return use(tid, command, ts=f"2026-09-10T11:{minute:02d}:00.000Z")


def test_python_open_w_inside_a_heredoc_is_a_bash_write_of_the_py_it_names(tmp_path):
    """Реальный случай toolu_01Fu9ZJy…: Write .py, затем `python - <<'EOF'` с open(p,'w').write(...), затем A1."""
    body = 'python - <<\'EOF\'\np = "mod/a.py"\nopen(p, "w").write("x = 1\n")\nEOF'
    got = _split_with(tmp_path, [edit("e1", PY), _bash("b1", body)], "git add mod/a.py && git commit -q -m x")
    assert got == ["A1-Bash"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "python -c \"from pathlib import Path; Path('mod/a.py').write_text('x')\"", id="write_text-in-quotes"
        ),
        pytest.param("python - <<'EOF'\nf = open('mod/a.py', 'a')\nf.write('y')\nEOF", id="open-a-then-dot-write"),
    ],
)
def test_python_write_forms_in_raw_text_are_bash_writes(tmp_path, body):
    got = _split_with(tmp_path, [edit("e1", PY), _bash("b1", body)], "git add mod/a.py && git commit -q -m x")
    assert got == ["A1-Bash"]


def test_python_that_only_reads_the_py_is_not_a_writer(tmp_path):
    body = "python - <<'EOF'\ntext = open('mod/a.py').read()\nprint(len(text))\nEOF"
    got = _split_with(tmp_path, [edit("e1", PY), _bash("b1", body)], "git add mod/a.py && git commit -q -m x")
    assert got == ["A1-Edit/Write"]


def test_sed_i_on_another_file_in_the_commit_call_does_not_make_the_staged_py_a_bash_write(tmp_path):
    cmd = "sed -i 's/x/y/' notes.md; git add mod/a.py && git commit -q -m x"
    assert _split_with(tmp_path, [edit("e1", PY)], cmd) == ["A1-Edit/Write"]


def test_tee_of_a_log_after_pytest_naming_the_py_is_not_a_write_of_that_py(tmp_path):
    before = [edit("e1", PY), _bash("b1", "pytest mod/a.py -q | tee /tmp/log.txt")]
    assert _split_with(tmp_path, before, "git add mod/a.py && git commit -q -m x") == ["A1-Edit/Write"]


def test_heredoc_to_a_tmp_py_writes_only_that_file_not_the_py_that_is_read_afterwards(tmp_path):
    body = "cat > /tmp/tag.py <<'EOF'\nprint(1)\nEOF\npython /tmp/tag.py; sed -n 1,5p mod/a.py"
    assert _split_with(tmp_path, [edit("e1", PY), _bash("b1", body)], "git add mod/a.py && git commit -q -m x") == [
        "A1-Edit/Write"
    ]
    # а сама цель записи — писатель Bash
    tag = "git add /tmp/tag.py && git commit -q -m x"
    assert _split_with(tmp_path / "t", [_bash("b1", body)], tag) == ["A1-Bash"]


def test_redirect_target_py_is_a_bash_write(tmp_path):
    before = [edit("e1", PY), _bash("b1", "python gen.py > mod/a.py")]
    assert _split_with(tmp_path, before, "git add mod/a.py && git commit -q -m x") == ["A1-Bash"]


def test_cp_writes_its_last_argument_not_the_source(tmp_path):
    src = REPO + "\\mod\\src.py"
    before = [edit("e1", src), _bash("b1", "cp mod/src.py mod/dst.py")]
    assert _split_with(tmp_path / "s", before, "git add mod/src.py && git commit -q -m x") == ["A1-Edit/Write"]
    assert _split_with(tmp_path / "d", before, "git add mod/dst.py && git commit -q -m x") == ["A1-Bash"]


def test_cp_into_a_directory_writes_the_py_sources(tmp_path):
    before = [edit("e1", PY), _bash("b1", "cp mod/a.py /tmp/backup_dir/")]
    assert _split_with(tmp_path, before, "git add mod/a.py && git commit -q -m x") == ["A1-Bash"]


def test_mv_install_rsync_write_their_last_argument(tmp_path):
    for i, verb in enumerate(
        ("mv mod/old.py mod/a.py", "install -m 644 mod/old.py mod/a.py", "rsync -a mod/old.py mod/a.py")
    ):
        before = [edit("e1", PY), _bash("b1", verb)]
        assert _split_with(tmp_path / str(i), before, "git add mod/a.py && git commit -q -m x") == ["A1-Bash"]


def test_tee_argument_py_is_a_bash_write(tmp_path):
    before = [edit("e1", PY), _bash("b1", "echo x | tee mod/a.py")]
    assert _split_with(tmp_path, before, "git add mod/a.py && git commit -q -m x") == ["A1-Bash"]


def test_git_checkout_and_restore_of_the_py_are_bash_writes(tmp_path):
    for i, verb in enumerate(("git checkout abc123 -- mod/a.py", "git restore mod/a.py")):
        before = [edit("e1", PY), _bash("b1", verb)]
        assert _split_with(tmp_path / str(i), before, "git add mod/a.py && git commit -q -m x") == ["A1-Bash"]


def test_for_loop_list_elements_are_write_targets_when_the_body_copies_the_loop_variable(tmp_path):
    loop = 'for f in mod/a.py mod/b.py; do cp "/tmp/w/$f" "$f"; done'
    got = _split_with(tmp_path / "cp", [edit("e1", PY), _bash("b1", loop)], "git add mod/a.py && git commit -q -m x")
    assert got == ["A1-Bash"]
    reader = 'for f in mod/a.py mod/b.py; do cat "$f"; done'
    got = _split_with(tmp_path / "cat", [edit("e1", PY), _bash("b1", reader)], "git add mod/a.py && git commit -q -m x")
    assert got == ["A1-Edit/Write"]


def test_git_add_variable_with_several_words_is_split_into_paths(tmp_path):
    before = [edit("e1", PY), _bash("b1", "cat > mod/b.py <<'EOF'\nx = 1\nEOF")]
    cmd = 'F="mod/b.py mod/a.py"; git add $F && git commit -q -m x'
    assert _split_with(tmp_path, before, cmd) == ["A1-Bash"]  # b.py — писал Bash; без разбиения оба пути не находятся


def test_stderr_summary_lists_the_skipped_things_and_is_never_empty(tmp_path):
    lines = [
        use("o1", "cd C:\\Users\\x\\AppData\\Local\\Temp\\lab && git commit -q -m x"),
        res("o1", B1_TEXT),
        use("d1", "git commit --dry-run -m x"),
        res("d1", ""),
        use("d2", "git merge --abort"),
        res("d2", ""),
        use("n1", "git commit -q -m x"),  # без tool_result
    ]
    _, err, _ = run(make_root(tmp_path, lines))
    assert "1 attempt(s) outside the repo" in err
    assert "2 git commit/merge invocation(s) skipped" in err
    assert "1 attempt(s) without tool_result" in err
    assert "file(s) read" in err
