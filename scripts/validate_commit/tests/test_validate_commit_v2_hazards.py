"""Task 2.1 (commit-mechanism) — тесты автора на опасные места самого механизма валидатора v2.

Это ДОПОЛНЕНИЕ к приёмке `test_validate_commit_v2.py` (таблица V1-V17, сторожа G1-G4), а не замена.
Приёмку писал независимый tester по критериям; здесь — то, что видно только изнутри реализации.
Что может сломаться в ЭТОМ механизме, исходя из того, как он устроен:

  H1  Порядок «пропуск → слияние». `SKIP_PREFIXES` проверяется первым, потом `MERGE_DEFAULT_RE`.
      Если вернуть `Merge ` в пропуски (или проверять слияние раньше `Revert `), то `Revert "Merge branch ..."`
      либо получит предупреждение о слиянии, либо слияние уйдёт без предупреждения. Закрепляем оба конца:
      `Revert "Merge branch 'x'"` тих, а `Merge pull request #5 from a/b` предупреждает.
  H2  Фолдинг трейлеров × сбор предупреждений. Перенесённое значение `Why:` у `merge:` не должно превращаться
      в W-MERGE-TRAILERS (абзац выпал бы из трейлеров, `Why` «исчез»). Это ровно тот дефект шаблонной копии,
      которой фолдинга не хватало: проверяем ОБЕ копии.
  H3  Корень проверки `Refs:`. Файл плана ищется от корня ТОГО worktree, где делается коммит, а не от
      главного дерева и не от каталога скрипта. План, существующий только в соседнем дереве, не считается
      (ред. 5: это W-REFS-INVALID — предупреждение, под STRICT отказ).
  H4  Обход каталогов. `Refs: plans/../README.md` по регулярке похож на путь плана, а файл существует.
      Без отдельной проверки `..` такой Refs принимался бы. Ред. 5: сегмент `.` отвергается так же
      (`plans/./queue/...` обходил исключение очереди); причина — W-REFS-INVALID, под STRICT отказ.
  H5  Несколько значений в одном `Refs:`: достаточно ОДНОГО существующего плана, плохие соседи не мешают;
      если же хорошего нет — W-REFS-INVALID называет причину по каждому (под STRICT это отказ).
  H6  Слияние на ветке с планом: `Refs` на очередь — ПРЕДУПРЕЖДЕНИЕ (ред. 5: у `merge` любая проблема Refs
      — фаза 3, не прямая ошибка; в ред. 4 тут был rc 1 — ожидание изменено намеренно), под STRICT — отказ;
      слияние без `Refs` вовсе — тоже только предупреждение (его выдаёт блок слияния, не правило 6).
  H12 Перенесённый `Refs:`: единственный годный план стоит на строке-продолжении. Это НАБЛЮДАЕМАЯ защита
      фолдинга: проверка h2 ловит лишь присутствие трейлера, потому что validate() подбирает известные
      трейлеры из любого места сообщения, а строка с отступом под TRAILER_RE не подпадает — значит, годный
      план виден только если абзац сфолжен. Без фолдинга (старая шаблонная копия) было бы W-REFS-INVALID.
      Проверяем и обычный коммит, и путь `merge:`.
  H7  Гейт тестов не должен срабатывать на слиянии: индекс слияния несёт чужие коммиты, и без исключения
      каждое слияние ветки с кодом без тестов в индексе упиралось бы в «Gated code staged without tests».
      Контроль в том же прогоне: обычный коммит с тем же индексом — отказ (гейт жив).
  H8  Границы длины первой строки: 72 — тишина, 73 — предупреждение, 100 — только первое, 101 — только
      второе; предупреждения о длине НЕ несут суффикс «error from phase 3» (отказа нет ни в каком режиме).
  H9  Scope с точкой не ослабил остальное: заглавная буква в scope по-прежнему отказ; `merge` со scope —
      отказ даже при полных трейлерах.
  H10 Refs у слияния — только при плане ветки. Реализация требовала Refs у `merge:` всегда: слияние на ветке
      без плана (`main`) с Why+Layer получало W-MERGE-TRAILERS. Закрепляем: без плана — тишина и rc 0 в
      ОБОИХ режимах; контроль в том же тесте — без Why предупреждение остаётся.
  H11 Любой текст `Merge ...` — текст git (`Merge tag`, `Merge commit`): v1 их пропускал, поэтому фаза 2
      даёт rc 0 + предупреждение; под STRICT — rc 1. Узкий regex отклонял их как «не Conventional Commits».

Метод: валидатор запускается ПОДПРОЦЕССОМ (`python <копия> -`, сообщение на stdin) в tmp-репозитории; сверяются
rc и литеральные подстроки stderr. Окружение: git без глобального конфига, `GIT_*` вычищены.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COPIES = {
    "scripts": REPO_ROOT / "scripts" / "validate_commit" / "validate_commit.py",
    "template": REPO_ROOT
    / ".claude"
    / "plugins"
    / "lang-python"
    / "templates"
    / "validate_commit"
    / "validate_commit.py",
}
TIMEOUT = 120
BRANCH = "feat/commit-mechanism"
PLAN = "plans/2026-10-03_commit-mechanism/plan.md"
OTHER_PLAN = "plans/2026-10-05_other-plan/plan.md"
LAYERS = "framework\nservices\nplugins\nprototype\ndocs\nscripts\ntests\ninfra\nmixed\n"
WHY = "Why: проверка опасных мест валидатора v2"
FULL = f"{WHY}\nLayer: docs\nRefs: {PLAN}\n"
PHASE3 = "(error from phase 3)"


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(cmd: list[str], cwd: Path, stdin_data: bytes | None = None) -> tuple[int, str]:
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        if stdin_data is not None:
            inp.write(stdin_data)
            inp.seek(0)
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=_env(),
            stdin=inp if stdin_data is not None else subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            timeout=TIMEOUT,
            check=False,
        )
        err.seek(0)
        out.seek(0)
        return proc.returncode, (out.read() + err.read()).decode("utf-8", "replace")


def _git(repo: Path, *args: str) -> None:
    rc, text = _run(["git", *args], repo)
    assert rc == 0, f"git {' '.join(args)} rc={rc}\n{text}"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _init(path: Path, branch: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", branch)
    _git(path, "config", "user.name", "Tester")
    _git(path, "config", "user.email", "tester@example.invalid")
    _git(path, "config", "core.autocrlf", "false")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def _validate(copy: str, repo: Path, message: str) -> tuple[int, str]:
    return _run([sys.executable, str(COPIES[copy]), "-"], repo, stdin_data=message.encode("utf-8"))


def _validate_both(copy: str, repo: Path, message: str, tmp_path: Path) -> tuple[int, str, int]:
    """(rc, stderr) with STRICT off, and rc with STRICT on (textual copy of the validator)."""
    strict = _strict_copy(copy, tmp_path / "strict")
    rc_off, text_off = _validate(copy, repo, message)
    rc_on, _text_on = _run([sys.executable, str(strict), "-"], repo, stdin_data=message.encode("utf-8"))
    return rc_off, text_off, rc_on


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = _init(tmp_path_factory.mktemp("hazard"), BRANCH)
    _write(root / ".claude" / "commit-layers.txt", LAYERS)
    _write(root / PLAN, f"# Plan\n\n- **Ветка:** {BRANCH}\n")
    _write(root / OTHER_PLAN, "# Plan: other\n\n- **Ветка:** feat/other-plan\n")
    _write(root / "plans" / "queue" / "2026-10-06_queued.md", "# queued\n")
    _write(root / "README.md", "# readme\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


# --------------------------------------------------------------------------- H1


@pytest.mark.parametrize("copy", list(COPIES))
def test_h1_revert_of_a_merge_stays_skipped(copy: str, repo: Path) -> None:
    rc, text = _validate(copy, repo, "Revert \"Merge branch 'x' into main\"\n")
    assert rc == 0
    assert "WARNING" not in text and "merge" not in text.lower()


@pytest.mark.parametrize("copy", list(COPIES))
def test_h1_merge_pull_request_text_warns(copy: str, repo: Path) -> None:
    rc, text = _validate(copy, repo, "Merge pull request #5 from a/b\n")
    assert rc == 0
    assert "default git merge text" in text


# --------------------------------------------------------------------------- H2


@pytest.mark.parametrize("copy", list(COPIES))
def test_h2_wrapped_why_on_a_merge_is_not_reported_missing(copy: str, repo: Path) -> None:
    message = (
        f"merge: слияние\n\nWhy: мотивация, которая случайно\nперенеслась на вторую строку\nLayer: docs\nRefs: {PLAN}\n"
    )
    rc, text = _validate(copy, repo, message)
    assert rc == 0
    assert "merge commit without" not in text, text


@pytest.mark.parametrize("copy", list(COPIES))
def test_h2_wrapped_why_on_a_plain_commit_is_not_reported_missing(copy: str, repo: Path) -> None:
    message = (
        f"feat(x): y\n\nWhy: мотивация, которая случайно\nперенеслась на вторую строку\nLayer: docs\nRefs: {PLAN}\n"
    )
    rc, text = _validate(copy, repo, message)
    assert rc == 0
    assert "Missing required trailers" not in text, text


# --------------------------------------------------------------------------- H3


@pytest.mark.parametrize("copy", list(COPIES))
def test_h3_refs_are_looked_up_in_the_worktree_of_the_commit(copy: str, tmp_path: Path) -> None:
    main = _init(tmp_path / "main", "main")
    _write(main / ".claude" / "commit-layers.txt", LAYERS)
    _write(main / "README.md", "x\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "init")
    worktree = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "feat/wt-plan", str(worktree))
    # plan A exists only in the worktree (and declares its branch); plan B only in the main tree
    _write(worktree / "plans" / "2026-10-07_wt-plan" / "plan.md", "# P\n\n- **Ветка:** feat/wt-plan\n")
    _write(main / "plans" / "2026-10-08_main-only" / "plan.md", "# M\n")

    here = f"feat(x): y\n\n{WHY}\nLayer: docs\nRefs: plans/2026-10-07_wt-plan/plan.md\n"
    elsewhere = f"feat(x): y\n\n{WHY}\nLayer: docs\nRefs: plans/2026-10-08_main-only/plan.md\n"

    rc_here, text_here = _validate(copy, worktree, here)
    rc_elsewhere, text_elsewhere, rc_elsewhere_strict = _validate_both(copy, worktree, elsewhere, tmp_path)

    assert rc_here == 0 and "Refs names no existing plan" not in text_here, text_here
    assert rc_elsewhere == 0 and rc_elsewhere_strict == 1, text_elsewhere
    assert "Refs names no existing plan" in text_elsewhere
    assert "no such file in the working tree" in text_elsewhere


# --------------------------------------------------------------------------- H4, H5


@pytest.mark.parametrize("copy", list(COPIES))
@pytest.mark.parametrize(
    "ref", ["plans/../README.md", "plans/./2026-10-05_other-plan/plan.md", "plans/./queue/2026-10-06_queued.md"]
)
def test_h4_dot_segments_in_refs_are_flagged_although_the_file_exists(
    copy: str, ref: str, repo: Path, tmp_path: Path
) -> None:
    assert (repo / ref).is_file()  # premise: the path really resolves to a file
    message = f"feat(x): y\n\n{WHY}\nLayer: docs\nRefs: {ref}\n"
    rc, text, rc_strict = _validate_both(copy, repo, message, tmp_path)
    assert rc == 0 and rc_strict == 1, text
    assert "Refs names no existing plan" in text and "segment in the path" in text


@pytest.mark.parametrize("copy", list(COPIES))
def test_h5_one_good_plan_among_bad_values_is_enough(copy: str, repo: Path) -> None:
    message = f"feat(x): y\n\n{WHY}\nLayer: docs\nRefs: plans/queue/2026-10-06_queued.md, {OTHER_PLAN}\n"
    rc, text = _validate(copy, repo, message)
    assert rc == 0, text


@pytest.mark.parametrize("copy", list(COPIES))
def test_h5_all_bad_values_are_named_in_the_warning(copy: str, repo: Path, tmp_path: Path) -> None:
    message = f"feat(x): y\n\n{WHY}\nLayer: docs\nRefs: plans/queue/2026-10-06_queued.md, plans/nonexistent.md\n"
    rc, text, rc_strict = _validate_both(copy, repo, message, tmp_path)
    assert rc == 0 and rc_strict == 1, text
    assert "Refs names no existing plan" in text and PHASE3 in text
    assert "plans/queue/ holds queued items" in text
    assert "plans/nonexistent.md: no such file" in text


# --------------------------------------------------------------------------- H6


@pytest.mark.parametrize("copy", list(COPIES))
def test_h6_merge_with_queue_refs_is_a_warning_and_under_strict_an_error(copy: str, repo: Path, tmp_path: Path) -> None:
    message = f"merge: слияние\n\n{WHY}\nLayer: docs\nRefs: plans/queue/2026-10-06_queued.md\n"
    rc, text, rc_strict = _validate_both(copy, repo, message, tmp_path)
    assert rc == 0 and rc_strict == 1, text
    assert "Refs names no existing plan" in text and "plans/queue/ holds queued items" in text


@pytest.mark.parametrize("copy", list(COPIES))
def test_h6_merge_without_refs_on_a_plan_branch_is_only_a_warning(copy: str, repo: Path) -> None:
    rc, text = _validate(copy, repo, f"merge: слияние\n\n{WHY}\nLayer: docs\n")
    assert rc == 0
    assert "merge commit without Why/Layer/Refs" in text and PHASE3 in text
    assert "Branch has a plan" not in text


# --------------------------------------------------------------------------- H7


@pytest.mark.parametrize("copy", list(COPIES))
def test_h7_tests_gate_does_not_fire_on_a_merge_but_does_on_a_plain_commit(copy: str, tmp_path: Path) -> None:
    root = _init(tmp_path / "gate", "main")
    _write(root / ".claude" / "commit-layers.txt", LAYERS)
    _write(root / "src" / "a.py", "x = 1\n")
    _git(root, "add", "-A")  # staged: gated code, no test staged
    trailers = f"{WHY}\nLayer: docs\nRefs: {PLAN}\n"

    rc_merge, text_merge = _validate(copy, root, f"merge: слияние\n\n{trailers}")
    rc_plain, text_plain = _validate(copy, root, f"feat(x): y\n\n{trailers}")

    assert rc_merge == 0, text_merge
    assert rc_plain == 1 and "Gated code staged without tests" in text_plain, text_plain


# --------------------------------------------------------------------------- H8


def _subject(length: int) -> str:
    prefix = "docs(x): "
    body = ("тест слова " * 20)[: length - len(prefix)]
    if body.endswith(" "):
        body = body[:-1] + "я"
    line = prefix + body
    assert len(line) == length
    return line


@pytest.mark.parametrize("copy", list(COPIES))
@pytest.mark.parametrize(
    ("length", "expect_72", "expect_100"),
    [(72, False, False), (73, True, False), (100, True, False), (101, False, True)],
)
def test_h8_subject_length_boundaries(copy: str, length: int, expect_72: bool, expect_100: bool, repo: Path) -> None:
    rc, text = _validate(copy, repo, f"{_subject(length)}\n\n{FULL}")
    assert rc == 0, text
    assert ("subject longer than 72" in text) is expect_72, text
    assert ("subject longer than 100" in text) is expect_100, text
    subject_lines = [line for line in text.splitlines() if "subject longer than" in line]
    assert all(PHASE3 not in line for line in subject_lines), subject_lines


# --------------------------------------------------------------------------- H9


@pytest.mark.parametrize("copy", list(COPIES))
def test_h9_scope_with_a_dot_is_accepted_and_uppercase_is_still_refused(copy: str, repo: Path) -> None:
    rc_dot, text_dot = _validate(copy, repo, f"feat(a.b,c/d): y\n\n{FULL}")
    rc_upper, _text_upper = _validate(copy, repo, f"feat(Task-5): y\n\n{FULL}")
    assert rc_dot == 0, text_dot
    assert rc_upper == 1


@pytest.mark.parametrize("copy", list(COPIES))
def test_h9_merge_with_a_scope_is_refused_even_with_full_trailers(copy: str, repo: Path) -> None:
    rc, text = _validate(copy, repo, f"merge(x): слияние\n\n{FULL}")
    assert rc == 1
    assert "takes no scope" in text


# --------------------------------------------------------------------------- H10, H11 (both modes)


def _strict_copy(copy: str, target_dir: Path) -> Path:
    text = COPIES[copy].read_bytes().decode("utf-8")
    assert text.count("STRICT = False") == 1
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "validate_commit.py"
    target.write_bytes(text.replace("STRICT = False", "STRICT = True").encode("utf-8"))
    return target


@pytest.fixture
def no_plan_repo(tmp_path: Path) -> Path:
    root = _init(tmp_path / "noplan", "main")
    _write(root / ".claude" / "commit-layers.txt", LAYERS)
    _write(root / "README.md", "x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


@pytest.mark.parametrize("copy", list(COPIES))
def test_h10_merge_without_refs_on_a_branch_without_a_plan_is_silent_in_both_modes(
    copy: str, no_plan_repo: Path, tmp_path: Path
) -> None:
    message = f"merge: feat/x в main — что вошло\n\n{WHY}\nLayer: docs\n"
    strict = _strict_copy(copy, tmp_path / "strict")

    rc_off, text_off = _validate(copy, no_plan_repo, message)
    rc_on, text_on = _run([sys.executable, str(strict), "-"], no_plan_repo, stdin_data=message.encode("utf-8"))

    assert (rc_off, rc_on) == (0, 0), f"{text_off}\n{text_on}"
    assert "WARNING" not in text_off and "merge commit without" not in text_on, f"{text_off}\n{text_on}"
    # control: the warning is still alive when Why is missing
    rc_ctl, text_ctl = _validate(copy, no_plan_repo, "merge: feat/x в main\n\nLayer: docs\n")
    assert rc_ctl == 0 and "merge commit without Why/Layer/Refs" in text_ctl


@pytest.mark.parametrize("copy", list(COPIES))
@pytest.mark.parametrize("message", ["Merge tag 'v1.0'\n", "Merge commit 'abc123'\n"])
def test_h11_any_merge_text_is_a_warning_and_under_strict_an_error(
    copy: str, message: str, no_plan_repo: Path, tmp_path: Path
) -> None:
    strict = _strict_copy(copy, tmp_path / "strict")

    rc_off, text_off = _validate(copy, no_plan_repo, message)
    rc_on, text_on = _run([sys.executable, str(strict), "-"], no_plan_repo, stdin_data=message.encode("utf-8"))

    assert rc_off == 0 and "default git merge text" in text_off and PHASE3 in text_off, text_off
    assert rc_on == 1 and "default git merge text" in text_on, text_on


# --------------------------------------------------------------------------- H12


@pytest.mark.parametrize("copy", list(COPIES))
@pytest.mark.parametrize("subject", ["feat(x): y", "merge: слияние"])
def test_h12_wrapped_refs_with_the_valid_plan_on_the_continuation_line(
    copy: str, subject: str, repo: Path, tmp_path: Path
) -> None:
    message = f"{subject}\n\n{WHY}\nLayer: docs\nRefs: plans/queue/2026-10-06_queued.md,\n  {OTHER_PLAN}\n"
    rc, text, rc_strict = _validate_both(copy, repo, message, tmp_path)
    assert (rc, rc_strict) == (0, 0), text
    assert "Refs names no existing plan" not in text and "merge commit without" not in text, text


# --------------------------------------------------------------------------- H13-H17 (ред. 6: Task, один блок)
#
# Механизм «один блок» зовёт `git interpret-trailers` подпроцессом из validate(). Опасные места:
#   H13  git не отвечает (нет бинаря, таймаут): W-TRAILERS-UNCHECKED, rc 0 в ОБОИХ режимах, и НЕ ложный
#        W-TRAILERS-SPLIT — пропуск проверки без слова был бы «ошибка проглочена».
#   H14  git отвечает отказом (rc != 0): то же самое. Пустой stdout отказа нельзя читать как «git не видит
#        ни одного трейлера» — иначе каждое сообщение получило бы ложное «трейлеры не видны».
#   H15  CRLF в самом сообщении (validate() вызван напрямую, а не через main(), который читает stdin в текстовом
#        режиме и сам сводит CRLF к LF): сообщение одним блоком не должно получить W-TRAILERS-SPLIT.
#   H16  Кириллица в значении Task: — W-TASK-FORMAT, а не исключение и не молчание; под STRICT — отказ.
#   H17  Дыра инъекции ред. 5 (I3 дала 0 красных): `merge:` + Why + Layer + `Refs: ADR-12` (не путь `plans/`)
#        на ветке с планом — предупреждение при STRICT False, отказ при STRICT True.
#
# Механизм для H13/H14: подпроцесс-обёртка. Она грузит копию валидатора по пути, ставит STRICT, подменяет
# `subprocess.run` ТОЛЬКО для вызова с `interpret-trailers` (остальной git — настоящий) и вызывает настоящий
# `main()`. Почему не поддельный `git` первым в PATH: на Windows `subprocess` по имени `git` находит лишь
# `git.exe`, шим `git.cmd` не подхватится, а собирать exe ради теста нечем. Почему не monkeypatch внутри
# pytest: нужны настоящие rc и stderr из `main()` и изоляция от процесса pytest. Контроль «без отказа» в той же
# обёртке доказывает, что виновата не она.

DRIVER = r"""
import importlib.util
import subprocess
import sys

path, mode, fault, strict = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("vc_under_test", path)
mod = importlib.util.module_from_spec(spec)
sys.modules["vc_under_test"] = mod
spec.loader.exec_module(mod)
mod.STRICT = strict == "1"
real_run = subprocess.run


def fake_run(cmd, *args, **kwargs):
    if isinstance(cmd, (list, tuple)) and "interpret-trailers" in cmd:
        if fault == "missing":
            raise FileNotFoundError(2, "git not found")
        if fault == "timeout":
            raise subprocess.TimeoutExpired(cmd, 5)
        if fault == "exit":
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: boom")
    return real_run(cmd, *args, **kwargs)


subprocess.run = fake_run
if mode == "main":
    sys.exit(mod.main(["validate_commit.py", "-"]))
text = sys.stdin.buffer.read().decode("utf-8")
result = mod.validate(text)
for line in result.warnings:
    sys.stderr.write("WARNING: " + line + "\n")
for line in result.errors:
    sys.stderr.write("ERROR: " + line + "\n")
sys.exit(1 if result.errors else 0)
"""


def _driven(
    copy: str, repo: Path, tmp_path: Path, message: bytes, *, mode: str, fault: str, strict: bool
) -> tuple[int, str]:
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER, encoding="utf-8", newline="\n")
    cmd = [sys.executable, str(driver), str(COPIES[copy]), mode, fault, "1" if strict else "0"]
    return _run(cmd, repo, stdin_data=message)


ONE_BLOCK = f"feat(x): y\n\n{FULL}Co-Authored-By: Claude <noreply@anthropic.com>\n"


@pytest.mark.parametrize("copy", list(COPIES))
def test_h13_control_the_driver_without_a_fault_is_silent_on_one_block(copy: str, repo: Path, tmp_path: Path) -> None:
    rc, text = _driven(copy, repo, tmp_path, ONE_BLOCK.encode("utf-8"), mode="main", fault="none", strict=True)
    assert rc == 0, text
    assert "WARNING" not in text, text


@pytest.mark.parametrize("copy", list(COPIES))
@pytest.mark.parametrize("fault", ["missing", "timeout"])
@pytest.mark.parametrize("strict", [False, True])
def test_h13_git_unavailable_is_a_plain_warning_never_an_error_never_a_split(
    copy: str, fault: str, strict: bool, repo: Path, tmp_path: Path
) -> None:
    rc, text = _driven(copy, repo, tmp_path, ONE_BLOCK.encode("utf-8"), mode="main", fault=fault, strict=strict)
    assert rc == 0, text
    assert "cannot check trailer block" in text, text
    assert "trailers git does not see" not in text, text
    assert PHASE3 not in text, text  # a plain warning: no phase-3 suffix, not an error under STRICT


@pytest.mark.parametrize("copy", list(COPIES))
@pytest.mark.parametrize("strict", [False, True])
def test_h14_git_refusal_is_not_read_as_an_empty_trailer_block(
    copy: str, strict: bool, repo: Path, tmp_path: Path
) -> None:
    rc, text = _driven(copy, repo, tmp_path, ONE_BLOCK.encode("utf-8"), mode="main", fault="exit", strict=strict)
    assert rc == 0, text
    assert "cannot check trailer block" in text, text
    assert "trailers git does not see" not in text, text
    assert PHASE3 not in text, text


@pytest.mark.parametrize("copy", list(COPIES))
def test_h14_a_message_without_known_trailers_never_calls_git(copy: str, repo: Path, tmp_path: Path) -> None:
    # `Note:` is not a known trailer; even with git broken there must be no "cannot check" warning,
    # because the oracle is not asked at all.
    message = "feat(x): y\n\nNote: просто текст\n"
    _rc, text = _driven(copy, repo, tmp_path, message.encode("utf-8"), mode="main", fault="exit", strict=False)
    assert "cannot check trailer block" not in text, text


@pytest.mark.parametrize("copy", list(COPIES))
@pytest.mark.parametrize("strict", [False, True])
def test_h15_crlf_message_in_one_block_gets_no_split_warning(
    copy: str, strict: bool, repo: Path, tmp_path: Path
) -> None:
    crlf = ONE_BLOCK.replace("\n", "\r\n").encode("utf-8")
    rc, text = _driven(copy, repo, tmp_path, crlf, mode="raw", fault="none", strict=strict)
    assert rc == 0, text
    assert "trailers git does not see" not in text, text
    assert "cannot check trailer block" not in text, text


@pytest.mark.parametrize("copy", list(COPIES))
def test_h15_crlf_message_with_a_real_split_is_still_reported(copy: str, repo: Path, tmp_path: Path) -> None:
    # control: CRLF normalisation must not hide a genuine blank line before the last trailer
    split = f"feat(x): y\n\n{FULL}\nCo-Authored-By: Claude <noreply@anthropic.com>\n".replace("\n", "\r\n")
    rc, text = _driven(copy, repo, tmp_path, split.encode("utf-8"), mode="raw", fault="none", strict=False)
    assert rc == 0, text
    assert "trailers git does not see" in text and "Why" in text, text


@pytest.mark.parametrize("copy", list(COPIES))
def test_h16_cyrillic_task_value_is_a_format_warning_and_under_strict_an_error(
    copy: str, repo: Path, tmp_path: Path
) -> None:
    message = f"feat(x): y\n\n{FULL}Task: коммит-механизм#2.1\n"
    rc, text, rc_strict = _validate_both(copy, repo, message, tmp_path)
    assert rc == 0, text
    assert "Task is not <slug>#<id>" in text and "коммит-механизм#2.1" in text, text
    assert PHASE3 in text, text
    assert rc_strict == 1


@pytest.mark.parametrize("copy", list(COPIES))
def test_h16_control_ascii_task_value_is_silent(copy: str, repo: Path, tmp_path: Path) -> None:
    message = f"feat(x): y\n\n{FULL}Task: commit-mechanism#2.1\n"
    rc, text, rc_strict = _validate_both(copy, repo, message, tmp_path)
    assert (rc, rc_strict) == (0, 0), text
    assert "WARNING" not in text, text


@pytest.mark.parametrize("copy", list(COPIES))
def test_h17_merge_with_a_refs_that_is_not_a_plan_path_on_a_branch_with_a_plan(
    copy: str, repo: Path, tmp_path: Path
) -> None:
    message = f"merge: x\n\n{WHY}\nLayer: docs\nRefs: ADR-12\n"
    rc, text, rc_strict = _validate_both(copy, repo, message, tmp_path)
    assert rc == 0, text
    assert "WARNING" in text and PHASE3 in text, text
    assert rc_strict == 1
