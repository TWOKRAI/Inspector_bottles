# ruff: noqa: E501  -- литералы-фикстуры в одну строку
"""Task 2.5 «доверие к цифрам и защита сида» — красные тесты автора (пункты 1-6 решения лида 2026-10-03).

1. команды ship/plan-status: вызовы plans_progress.py только если скрипт существует;
2. ORDER_BLOCK_STALE / ORDER_BLOCK_MISSING — информационные;
3. шапка плана (header_status), чипы закрытых планов и HEADER_STATUS_CONFLICT;
4. «без статуса K» / «без отметки K» в блоке и сводке CLI;
5. хвостовое правило заголовков (разделитель, регистр, PARTIAL, знак ✅);
6. нумерованный `1. Task 1.1:` вне эталона -> TASK_ID_UNPARSED.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRESS = Path(__file__).resolve().parents[1] / "plans_progress.py"
BEGIN = "<!-- progress:begin -->"
END = "<!-- progress:end -->"
SECTION = "## Порядок выполнения\n\n"
TIMEOUT = 60


def _out(cp) -> str:
    return f"{cp.stdout}\n{cp.stderr}"


def _lines(out: str, code: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith(code + " ")]


# =========================================================================== 1. сид: команды


COMMAND_FILES = [
    ".claude/plugins/dev/commands/ship.md",
    ".claude/commands/dev/ship.md",
    ".claude/plugins/dev/commands/plan-status.md",
    ".claude/commands/dev/plan-status.md",
]
EXISTS_PHRASE = "if `scripts/plans_progress/plans_progress.py` exists and `plans/queue/progress-baseline.txt` exists"


@pytest.mark.parametrize("rel", COMMAND_FILES)
def test_every_plans_progress_block_is_conditional_on_the_script_existing(rel):
    text = (REPO_ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")
    blocks = [b for b in re.findall(r"```bash\n(.*?)```", text, re.S) if "plans_progress.py" in b]
    assert blocks, f"{rel}: нет блока с plans_progress.py"
    assert text.lower().count(EXISTS_PHRASE) >= len(blocks), f"{rel}: условие 'exists' есть не у каждого блока"
    assert "otherwise skip" in text.lower()
    assert "plans_progress.py --check" in text
    assert "(always" not in text.lower(), f"{rel}: осталось безусловное 'always'"


# =========================================================================== 2. блок не блокирует


def _git(cwd: Path, *args: str) -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, timeout=TIMEOUT, env=env)


def _main_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "tester")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "snap")


def _order_files(order_text: str) -> dict[str, str]:
    return {
        "plans/2026-10-02_x.md": "# X\n\n" + SECTION + "- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n",
        "plans/queue/ORDER.md": order_text,
        "plans/queue/progress-baseline.txt": "",
    }


def _check_main(root: Path):
    base = root / "plans" / "queue" / "progress-baseline.txt"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(PROGRESS), "--root", str(root), "--check", "--baseline", str(base)],
        capture_output=True,
        timeout=TIMEOUT,
        env=env,
        encoding="utf-8",
        errors="replace",
    )


@pytest.mark.parametrize(
    ("order_text", "code"),
    [
        (f"# О\n\n{BEGIN}\n- старое — 9 из 9 · 100%\nв архиве: 7\n{END}\n", "ORDER_BLOCK_STALE"),
        ("# О\n\nбез маркеров\n", "ORDER_BLOCK_MISSING"),
    ],
    ids=["stale", "missing"],
)
def test_order_block_findings_on_main_are_info_and_do_not_fail(make_root, order_text, code):
    root = make_root(_order_files(order_text))
    _main_repo(root)
    cp = _check_main(root)
    assert cp.returncode == 0, _out(cp)[-500:]
    lines = _lines(_out(cp), code)
    assert lines and all(" info " in ln and " blocking " not in ln for ln in lines), _out(cp)[-500:]


def test_stale_finding_text_keeps_the_sync_command(make_root):
    root = make_root(_order_files(f"# О\n\n{BEGIN}\nстарое\n{END}\n"))
    _main_repo(root)
    assert "--sync-order" in "\n".join(_lines(_out(_check_main(root)), "ORDER_BLOCK_STALE"))


# =========================================================================== 3. шапка плана


def _plan_file(header: str, items: str = "- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n") -> str:
    return f"# План\n\n{header}\n\n" + SECTION + items


HEADER_CASES = [
    # observability-review-remediation: слово не в начале значения ("ред. 9 — ФАЗА E ЗАКРЫТА …") — по правилу ревью не статус
    ("> Статус: **ред. 9 — ФАЗА E ЗАКРЫТА ЦЕЛИКОМ (2026-08-10).**", None),
    ("> Статус: **ЗАКРЫТА ЦЕЛИКОМ (2026-08-10).**", "done"),
    (
        "> Статус: **SUPERSEDED (2026-08-10, в день создания) → [`observability-roadmap.md`](observability-roadmap.md).**",
        "superseded",
    ),  # observability-f1-hardening
    ("- **Статус:** DONE 2026-09-24 — Task 1.1 и Task 1.2 приняты", "done"),
    ("**Статус:** DEFERRED — после 4.1", "deferred"),
    ("Status: DONE", "done"),
    ("- **Статус:** DRAFT", None),  # sql-insert-many-atomic: слова набора нет
]


@pytest.mark.parametrize(("header", "expected"), HEADER_CASES)
def test_header_status_in_json(make_root, one_plan, header, expected):
    root = make_root({"plans/2026-10-02_h.md": _plan_file(header)})
    assert one_plan(root, "2026-10-02_h")["header_status"] == expected


def test_header_status_is_null_without_a_status_line_and_ignores_lines_past_30(make_root, one_plan):
    far = "# План\n\n" + "проза\n" * 40 + "**Статус:** DONE\n\n" + SECTION + "- Task 1.1: a [PENDING]\n"
    root = make_root(
        {"plans/2026-10-02_none.md": "# П\n\n" + SECTION + "- Task 1.1: a [PENDING]\n", "plans/2026-10-02_far.md": far}
    )
    assert one_plan(root, "2026-10-02_none")["header_status"] is None
    assert one_plan(root, "2026-10-02_far")["header_status"] is None


def test_header_conflict_is_info_only_when_tasks_are_not_all_done(make_root, progress):
    root = make_root(
        {
            "plans/2026-10-02_bad.md": _plan_file("- **Статус:** DONE"),
            "plans/2026-10-02_fine.md": _plan_file("- **Статус:** DONE", "- Task 1.1: a [DONE]\n"),
        }
    )
    cp = progress(root, "--check")
    lines = _lines(_out(cp), "HEADER_STATUS_CONFLICT")
    assert cp.returncode == 0
    assert len(lines) == 1 and "2026-10-02_bad" in lines[0] and " info " in lines[0], lines
    assert "1 из 2" in lines[0]


def _summary(raw: str, name: str) -> str:
    after = raw.split(f'data-plan="{name}"', 1)[1]
    return after.split("</summary>", 1)[0]


def _page(make_root, progress, tmp_path, files):
    root = make_root(files)
    out = tmp_path / "p.html"
    assert progress(root, "--html", str(out)).returncode == 0
    return out.read_text(encoding="utf-8")


def test_closed_tier_43_plan_shows_chip_instead_of_progress_but_keeps_the_numbers(
    make_root, progress, tmp_path, order_md
):
    # 2026-06-05_sql-insert-many-atomic: §4.3, шапка DRAFT, 0 из 5
    items = "".join(f"- Task 1.{i}: a [PENDING]\n" for i in range(1, 6))
    raw = _page(
        make_root,
        progress,
        tmp_path,
        {
            "plans/p-sql.md": _plan_file("- **Статус:** DRAFT", items),
            "plans/queue/ORDER.md": order_md(tier43=["p-sql"]),
        },
    )
    summ = _summary(raw, "p-sql")
    assert "<progress" not in summ
    assert re.search(r'data-chip="closed"[^>]*>закрыт · задачи 0 из 5<', summ), summ


def test_superseded_header_gives_the_word_snyat(make_root, progress, tmp_path, order_md):
    raw = _page(
        make_root,
        progress,
        tmp_path,
        {
            "plans/p-f1.md": _plan_file("> Статус: **SUPERSEDED (2026-08-10)**", "- Task 1.1: a [PENDING]\n"),
            "plans/queue/ORDER.md": order_md(tier43=["p-f1"]),
        },
    )
    assert re.search(r'data-chip="closed"[^>]*>снят · задачи 0 из 1<', _summary(raw, "p-f1"))


def test_fully_done_closed_plan_gets_plain_chip(make_root, progress, tmp_path, order_md):
    raw = _page(
        make_root,
        progress,
        tmp_path,
        {
            "plans/p-ok.md": _plan_file("**Статус:** DONE", "- Task 1.1: a [DONE]\n"),
            "plans/queue/ORDER.md": order_md(tier43=["p-ok"]),
        },
    )
    summ = _summary(raw, "p-ok")
    assert re.search(r'data-chip="closed"[^>]*>закрыт<', summ) and "<progress" not in summ


def test_active_queue_plan_with_done_header_and_open_tasks_gets_warning_and_keeps_progress(
    make_root, progress, tmp_path, order_md
):
    # observability-review-remediation: шапка DONE, задачи 1 из 2 (на живом дереве 7 из 20)
    raw = _page(
        make_root,
        progress,
        tmp_path,
        {
            "plans/p-rr.md": _plan_file("> Статус: **ЗАКРЫТА ЦЕЛИКОМ**"),
            "plans/queue/ORDER.md": order_md(tier41=["p-rr"]),
        },
    )
    summ = _summary(raw, "p-rr")
    assert re.search(r'data-chip="header-conflict"[^>]*>⚠ шапка: DONE, задачи 1 из 2<', summ), summ
    assert "<progress" in summ and 'data-chip="closed"' not in summ


# =========================================================================== 4. «без статуса» / «без отметки»


def _block_root(make_root):
    return make_root(
        {
            "plans/2026-10-02_u.md": "# U\n\n" + SECTION + "- Task 1.1: a [DONE]\n- Task 1.2: b [DONE-ish]\n",
            "plans/2026-10-02_h.md": "# H\n\n### Task 1.1 — a [DONE]\n\n### Task 1.2 — b\nтекст без признаков статуса\n",
            "plans/2026-10-02_ok.md": "# O\n\n" + SECTION + "- Task 1.1: a [DONE]\n",
            "plans/queue/ORDER.md": f"# О\n\n{BEGIN}\n{END}\n",
        }
    )


def test_block_lines_carry_unknown_and_unmarked_tails_only_when_nonzero(make_root, progress):
    root = _block_root(make_root)
    assert progress(root, "--sync-order").returncode == 0
    text = (root / "plans" / "queue" / "ORDER.md").read_text(encoding="utf-8")
    body = text.split(BEGIN + "\n", 1)[1].split(END, 1)[0].splitlines()
    assert body == [
        "- 2026-10-02_h — 1 из 2 · 50% · без отметки 1",
        "- 2026-10-02_ok — 1 из 1 · 100%",
        "- 2026-10-02_u — 1 из 1 · 100% · без статуса 1",
        "в архиве: 0",
    ]


def test_cli_summary_line_carries_the_same_tails(make_root, progress):
    out = progress(_block_root(make_root)).stdout.splitlines()
    by_name = {ln.split()[0]: ln for ln in out}
    assert by_name["2026-10-02_h"].endswith("1 из 2 · 50% · без отметки 1")
    assert by_name["2026-10-02_u"].endswith("1 из 1 · 100% · без статуса 1")
    assert by_name["2026-10-02_ok"].endswith("1 из 1 · 100%")


# =========================================================================== 5. хвостовое правило


NOT_STATUS = [
    "### Task 7.1 — перевести план в DONE",
    "### Task 7.1 — не DONE (откатили)",
    "### Task 7.1 — статус pending (не done)",
    "### Task 7.1 — имя — done",
    "### Task 7.1 — кнопка ✅ в тулбаре",
    "### Task 7.1 — ⚠️ PARTIAL (шаг 3 отложен)",
    "### Task 7.1 — доделать (DONE-детектор)",
]


@pytest.mark.parametrize("heading", NOT_STATUS)
def test_tail_rule_rejects_words_without_separator_lowercase_latin_and_partial(make_root, one_plan, statuses, heading):
    root = make_root({"plans/2026-10-02_t.md": "# П\n\n" + heading + "\nтекст\n"})
    assert statuses(one_plan(root, "2026-10-02_t")) == {"7.1": "pending"}


POSITIVE = [
    ("### Task 7.1 — имя (ЗАКРЫТА 2026-08-09, ADR-PM-028)", "done"),  # observability-unified-routing 8.5
    ("### Task 7.1 — имя ✅ DONE", "done"),
    ("### Task 7.1 — имя — ✅ 2026-09-29 (`53d17d9d`)", "done"),
    ("### Task 7.1 ✅ — имя", "done"),
    ("### Task 7.1 — имя  ✅ (9be0b852)", "done"),
    ("### Task 7.1 — имя — DEFERRED", "deferred"),
    ("### Task 7.1 — имя **SUPERSEDED**", "superseded"),
]


@pytest.mark.parametrize(("heading", "expected"), POSITIVE)
def test_tail_rule_still_accepts_real_markers(make_root, one_plan, statuses, heading, expected):
    root = make_root({"plans/2026-10-02_t.md": "# П\n\n" + heading + "\nтекст\n"})
    assert statuses(one_plan(root, "2026-10-02_t")) == {"7.1": expected}


# =========================================================================== 6. нумерованный список


def test_numbered_task_lines_are_reported_not_silently_dropped(make_root, progress, plans_json):
    items = "1. Task 1.1: a [DONE]\n2) Task 1.2: b [DONE]\n- Task 1.3: c [DONE]\n"
    root = make_root({"plans/2026-10-02_n.md": "# П\n\n" + SECTION + items})
    assert [t["id"] for t in plans_json(root)["2026-10-02_n"]["tasks"]] == ["1.3"]
    lines = _lines(_out(progress(root, "--check")), "TASK_ID_UNPARSED")
    assert len(lines) == 1 and "нумерованный пункт вне эталона" in lines[0], lines
    assert "- Task" in lines[0] and "неразобранным id" not in lines[0], lines


# =========================================================================== раунд ревью 2.4+2.5

FALSE_DONE_HEADERS = [
    "**Статус:** P1 (Python протокол) + P2 (Lua укладка) DONE — 116 тестов robot_comm/driver зелёные",  # robot-place-pose
    "**Статус:** Phase 1-2 DONE (ядро + плагин, 49 тестов зелёных, ruff чист). Phase 3 ЧАСТИЧНО:",  # word-layout
    "**Статус:** В работе. Тракт распознавания DONE. Цикл укладки→возврата — в процессе.",  # letter-robot-cycle
    "**Статус:** **БЛОК А ЗАКРЫТ (2026-07-19), Блок В ждёт codemod.**",  # frontend-constructor
    "**Статус:** Phase 1-3 DONE + qt-mcp smoke verified; остался Phase 4 (память).",  # pult-control-panel
    "- **Статус:** DRAFT — после DONE первой фазы",
]


@pytest.mark.parametrize("header", FALSE_DONE_HEADERS)
def test_header_word_must_start_the_status_value(make_root, one_plan, header):
    root = make_root({"plans/2026-10-02_h.md": _plan_file(header)})
    assert one_plan(root, "2026-10-02_h")["header_status"] is None


START_HEADERS = [
    ("**Статус:** DONE", "done"),
    ("> Статус: **SUPERSEDED (2026-08-10)**", "superseded"),
    ("> Статус: **ЗАКРЫТА ЦЕЛИКОМ**", "done"),
    ("- **Статус:** **ЗАКРЫТ** — merge `1f6bbd40` (ADR-PM-018)", "done"),  # telemetry-publish-control
    ("- **Статус:** DONE (2026-07-16). Фазы 0-3 закрыты", "done"),  # gui-telemetry-read-model
    ("> **Статус: SUPERSEDED → [`telemetry-stage6.md`](telemetry-stage6.md) (Ф3)** — 2026-08-12", "superseded"),
    ("**Статус:** ✅ DONE", "done"),
]


@pytest.mark.parametrize(("header", "expected"), START_HEADERS)
def test_header_word_at_the_start_is_still_read(make_root, one_plan, header, expected):
    root = make_root({"plans/2026-10-02_h.md": _plan_file(header)})
    assert one_plan(root, "2026-10-02_h")["header_status"] == expected


PAREN_NOT_STATUS = [
    "### Task 7.1 — экспорт (DONE позже, после 3.1)",
    "### Task 7.1 — режим (закрыт канал записи)",
    "### Task 7.1 — выгрузка (сделано наполовину)",
    "### Task 7.1 — кэш (отложено решение о TTL до замера)",
    "### Task 7.1 — (снята блокировка записи) новый API",
]


@pytest.mark.parametrize("heading", PAREN_NOT_STATUS)
def test_word_after_open_paren_needs_date_hash_comma_or_close_paren(make_root, one_plan, statuses, heading):
    root = make_root({"plans/2026-10-02_t.md": "# П\n\n" + heading + "\nтекст\n"})
    assert statuses(one_plan(root, "2026-10-02_t")) == {"7.1": "pending"}


@pytest.mark.parametrize(
    "heading",
    [
        "### Task 7.1 — имя (ЗАКРЫТА 2026-08-09, ADR-PM-028)",
        "### Task 7.1 — имя (DONE)",
        "### Task 7.1 — имя (DONE `abc1234`)",
        "### Task 7.1 — имя (закрыта, ADR-1)",
    ],
)
def test_word_after_open_paren_with_date_hash_comma_or_close_paren_is_done(make_root, one_plan, statuses, heading):
    root = make_root({"plans/2026-10-02_t.md": "# П\n\n" + heading + "\nтекст\n"})
    assert statuses(one_plan(root, "2026-10-02_t")) == {"7.1": "done"}


def test_header_conflict_is_not_reported_for_superseded_plans(make_root, progress):
    root = make_root({"plans/2026-10-02_sup.md": _plan_file("- **Статус:** SUPERSEDED (2026-08-10)")})
    cp = progress(root, "--check")
    assert not _lines(_out(cp), "HEADER_STATUS_CONFLICT"), _out(cp)[-400:]
    assert cp.returncode == 0


def test_numbered_item_with_a_bad_id_keeps_the_unparsed_wording(make_root, progress):
    root = make_root(
        {"plans/2026-10-02_n.md": "# П\n\n" + SECTION + "- Task 1.1: a [DONE]\n1. Task \u0422.1: б [DONE]\n"}
    )
    lines = _lines(_out(progress(root, "--check")), "TASK_ID_UNPARSED")
    assert len(lines) == 1 and "неразобранным id" in lines[0] and "нумерованный" not in lines[0], lines
