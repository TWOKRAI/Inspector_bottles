# ruff: noqa: E501  -- литералы-фикстуры планов и ожидания в одну строку
"""Тесты автора Task 3.4 plans_progress: опасности механизмов `BRANCH_MISSING` и `tier`-слов.

Приёмку по критериям пишет независимый тестер (test_acceptance_status_tier.py). Здесь — что ломается
в ЭТОМ устройстве, каким оно построено:

* git зовётся лишний раз. Находка нужна только плану с названной веткой; без неё `--check` на корне без
  ORDER.md не обязан запускать git вообще. Счёт — на границе ОС (`GIT_TRACE` пишет сам git), а не шпионом
  по имени `_git`: переименование помощника не должно обнулять защиту.
* git зовётся на каждый план. Список веток читается ОДНИМ `for-each-ref`, сколько бы планов ни назвало ветку.
* `lstrip("refs/heads/")` режет набор символов, а не префикс: `feat/x` превращается в `t/x`, и существующая
  ветка «пропадает». Ветка `heads/foo` (имя начинается с `heads/`) ловит и вариант `%(refname:short)`.
* Фильтр «живой» расходится с `plan_closed`: закрыт может быть план не только в архиве или в §4.3, но и по
  шапке `superseded` или по задачам (все закрыты) — находка для такого плана шум.
* Обратная таблица яруса уходит от прямой: слово без адреса роняет бейдж страницы (`KeyError`).
* Нет git / `--root` внутри чужого репозитория: находок нет и падения нет.
* Длинное имя ветки: текст находки обрезается `clean_md(…, 80)`, а сравнение идёт по полному имени.

Часть тестов импортирует модуль напрямую (внутренние функции), часть ходит через CLI в subprocess.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_status_tier_author", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_status_tier_author"] = pp
_spec.loader.exec_module(pp)

CALL_TIMEOUT = 60


# --------------------------------------------------------------------------- хелперы


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=env or _env(),
        encoding="utf-8",
        errors="replace",
    )


def _git_ok(cwd: Path, *args: str) -> None:
    cp = _run(["git", *args], cwd)
    assert cp.returncode == 0, cp.stderr


def _plan_text(branch_line: str, task: str = "- Task 1.1: делаем [PENDING]", header: tuple[str, ...] = ()) -> str:
    return "\n".join(["# План", "", *header, branch_line, "", "## Порядок выполнения", task, ""])


def _write_plans(root: Path, plans: dict[str, str]) -> None:
    for name, text in plans.items():
        f = root / "plans" / name / "plan.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")


def _init_repo(root: Path, *branches: str) -> None:
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _git_ok(root, "init", "-q")
    _git_ok(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git_ok(root, "config", "user.email", "t@example.invalid")
    _git_ok(root, "config", "user.name", "author")
    _git_ok(root, "config", "core.autocrlf", "false")
    _git_ok(root, "add", "README.md")
    _git_ok(root, "commit", "-q", "-m", "init")
    for b in branches:
        _git_ok(root, "branch", b)


def _check(root: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return _run([sys.executable, str(_MOD_PATH), "--root", str(root), "--check"], root, env)


def _missing(stdout: str) -> list[str]:
    return [ln.split()[1] for ln in stdout.splitlines() if ln.startswith("BRANCH_MISSING ")]


def _trace_calls(trace: Path) -> list[str]:
    """Строки `trace: built-in: git <команда>` — по одной на каждый запуск git, видимый из ОС."""
    if not trace.is_file():
        return []
    return [ln for ln in trace.read_text(encoding="utf-8", errors="replace").splitlines() if "built-in: git" in ln]


# --------------------------------------------------------------------------- git: сколько и когда


def test_git_not_called_when_no_live_plan_names_a_branch(tmp_path):
    """Планы: без поля, с шаблоном, с прозой `main — …`, закрытый по шапке — git не вызывается ни разу."""
    root = tmp_path / "r"
    root.mkdir()
    _write_plans(
        root,
        {
            "2026-10-01_nofield": _plan_text("Описание."),
            "2026-10-01_tpl": _plan_text("- **Ветка:** `feat/x-<фаза>`"),
            "2026-10-01_prose": _plan_text("- **Ветка:** `main` — короткие ветки (`docs/…`)"),
            "2026-10-01_doneheader": _plan_text("- **Ветка:** `feat/nope`", header=("- **Статус:** DONE",)),
        },
    )
    _init_repo(root)
    trace = tmp_path / "trace.txt"
    cp = _check(root, _env(GIT_TRACE=str(trace)))
    assert cp.returncode == 0, cp.stderr
    assert "BRANCH_MISSING" not in cp.stdout
    assert _trace_calls(trace) == []


def test_git_called_exactly_once_for_branch_list_with_many_plans(tmp_path):
    """Контроль достижимости: ветка названа — git виден в трассе; три плана — один for-each-ref."""
    root = tmp_path / "r"
    root.mkdir()
    _write_plans(
        root,
        {f"2026-10-0{i}_p{i}": _plan_text(f"- **Ветка:** `feat/nope{i}`") for i in (1, 2, 3)},
    )
    _init_repo(root)
    trace = tmp_path / "trace.txt"
    cp = _check(root, _env(GIT_TRACE=str(trace)))
    assert cp.returncode == 0, cp.stderr
    assert sorted(_missing(cp.stdout)) == ["2026-10-01_p1", "2026-10-02_p2", "2026-10-03_p3"]
    calls = _trace_calls(trace)
    assert len([c for c in calls if "for-each-ref" in c]) == 1, calls


# --------------------------------------------------------------------------- имя ветки и сравнение


def test_prefix_strip_is_a_prefix_not_a_char_set(tmp_path):
    """`feat/shared` существует: `lstrip("refs/heads/")` дал бы `t/shared` и ложную находку."""
    root = tmp_path / "r"
    root.mkdir()
    _write_plans(root, {"2026-10-01_shared": _plan_text("- **Ветка:** `feat/shared`")})
    _init_repo(root, "feat/shared")
    cp = _check(root)
    assert cp.returncode == 0, cp.stderr
    assert _missing(cp.stdout) == []


def test_branch_whose_name_starts_with_heads_is_found(tmp_path):
    """Имя `heads/foo` целиком: `%(refname:short)` и `[len("refs/"):]` оба дали бы чужое имя."""
    root = tmp_path / "r"
    root.mkdir()
    _write_plans(
        root,
        {
            "2026-10-01_heads-yes": _plan_text("- **Ветка:** `heads/foo`"),
            "2026-10-01_heads-no": _plan_text("- **Ветка:** `heads/bar`"),
        },
    )
    _init_repo(root, "heads/foo")
    cp = _check(root)
    assert cp.returncode == 0, cp.stderr
    assert _missing(cp.stdout) == ["2026-10-01_heads-no"]


def test_long_branch_name_is_cut_in_text_but_compared_whole(tmp_path):
    long_name = "feat/" + "x" * 120
    root = tmp_path / "r"
    root.mkdir()
    _write_plans(
        root,
        {
            "2026-10-01_long-yes": _plan_text(f"- **Ветка:** `{long_name}`"),
            "2026-10-01_long-no": _plan_text(f"- **Ветка:** `{long_name}y`"),
        },
    )
    _init_repo(root, long_name)
    cp = _check(root)
    assert cp.returncode == 0, cp.stderr
    assert _missing(cp.stdout) == ["2026-10-01_long-no"]
    line = next(ln for ln in cp.stdout.splitlines() if ln.startswith("BRANCH_MISSING "))
    assert "x" * 120 not in line and "…" in line


# --------------------------------------------------------------------------- «живой» = not plan_closed


def test_closed_plans_never_get_branch_missing(tmp_path):
    """Закрыт по шапке superseded и закрыт по задачам (все DONE) — находки нет; контроль: живой рядом есть."""
    root = tmp_path / "r"
    root.mkdir()
    _write_plans(
        root,
        {
            "2026-10-01_live": _plan_text("- **Ветка:** `feat/nope`"),
            "2026-10-01_superseded": _plan_text("- **Ветка:** `feat/nope`", header=("- **Статус:** SUPERSEDED",)),
            "2026-10-01_alldone": _plan_text("- **Ветка:** `feat/nope`", task="- Task 1.1: делаем [DONE]"),
        },
    )
    _init_repo(root)
    cp = _check(root)
    assert cp.returncode == 0, cp.stderr
    assert _missing(cp.stdout) == ["2026-10-01_live"]


def test_branch_findings_skips_tier_closed_and_archived_in_memory(tmp_path):
    """Фильтр на уровне функции: tier `closed` и archived отсеиваются тем же `plan_closed`."""
    _init_repo(tmp_path)

    def mem(name: str, **kw) -> pp.Plan:
        p = pp.Plan(name=name, rel=name, archived=kw.get("archived", False))
        p.tier = kw.get("tier")
        p.branch_claim = "feat/nope"
        return p

    plans = [mem("live"), mem("closed-tier", tier="closed"), mem("arch", archived=True), mem("waiting", tier="waiting")]
    got = pp.branch_findings(plans, tmp_path)
    assert [f.plan for f in got] == ["live", "waiting"]
    assert all(f.code == "BRANCH_MISSING" and not f.blocking for f in got)


# --------------------------------------------------------------------------- нет git / чужой репозиторий


def test_no_git_binary_gives_no_findings_and_no_crash(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _write_plans(root, {"2026-10-01_nope": _plan_text("- **Ветка:** `feat/nope`")})
    _init_repo(root)
    cp = _check(root, _env(PATH=""))
    assert cp.returncode == 0, cp.stderr
    assert "BRANCH_MISSING" not in cp.stdout


def test_root_that_is_a_subdirectory_of_a_repo_gives_no_findings(tmp_path):
    """Корень внутри репозитория не его верхний каталог: ветки того репозитория — не данные этого `--root`."""
    outer = tmp_path / "outer"
    outer.mkdir()
    _init_repo(outer)
    inner = outer / "sub"
    inner.mkdir()
    _write_plans(inner, {"2026-10-01_nope": _plan_text("- **Ветка:** `feat/nope`")})
    cp = _check(inner)
    assert cp.returncode == 0, cp.stderr
    assert "BRANCH_MISSING" not in cp.stdout


def test_is_repo_top_helper_and_worktrees_share_one_definition(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    _init_repo(outer)
    inner = outer / "sub"
    inner.mkdir()
    assert pp._is_repo_top(outer) is True
    assert pp._is_repo_top(inner) is False
    assert pp.git_worktrees(inner) == []
    assert [b for _path, b in pp.git_worktrees(outer)] == ["main"]


# --------------------------------------------------------------------------- tier: слова и адреса


def test_tier_tables_are_inverse_and_complete():
    assert pp.TIER_BY_SECTION == {"4.1": "queue", "4.2": "waiting", "4.3": "closed"}
    assert pp.SECTION_BY_TIER == {"queue": "4.1", "waiting": "4.2", "closed": "4.3"}
    assert len(set(pp.TIER_BY_SECTION.values())) == len(pp.TIER_BY_SECTION)


def test_every_parsed_order_row_tier_has_a_section_address(tmp_path):
    order = tmp_path / "ORDER.md"
    order.write_text(
        "# Порядок\n\n### 4.1 Очередь\n\n| План | Полоса | Статус | Шаг |\n|---|---|---|---|\n| [a](a/plan.md) | С | x | y |\n\n"
        "### 4.2 Ждут\n\n| План | Остаток | Триггер |\n|---|---|---|\n| [b](b/plan.md) | x | y |\n\n"
        "### 4.3 Закрыто\n\n| План | Факт |\n|---|---|\n| [c](c/plan.md) | x |\n",
        encoding="utf-8",
    )
    rows = pp.parse_order(order)
    assert [(r.name, r.tier) for r in rows] == [("a", "queue"), ("b", "waiting"), ("c", "closed")]
    assert all(r.tier in pp.SECTION_BY_TIER for r in rows)


def test_page_badge_survives_a_tier_word_without_an_address():
    """Слово яруса вне таблицы (дрейф) не роняет страницу: бейдж показывает слово как есть."""
    p = pp.Plan(name="x", rel="x", archived=False)
    p.tier = "bogus"
    html = pp._plan_html(p, False)
    assert "§bogus" in html


# --------------------------------------------------------------------------- шаблон и значение поля


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- **Ветка:** `feat/yes`", "feat/yes"),
        ("- **Ветка:** **feat/bold**", "feat/bold"),
        ("- Branch: `feat/en` — трек", "feat/en"),
        ("- **Ветка:** `main` — короткие ветки (`docs/…`)", ""),
        ("- **Ветка:** `feat/x-<фаза>`", ""),
        ("- **Ветка:** `feat/*`", ""),
        ("- **Ветка:** (от main) `feat/late`", ""),
        ("- **Ветка:** `feat/dot.`", "feat/dot"),
        ("- **Ветка:** —", ""),
        ("Описание без поля.", ""),
    ],
)
def test_find_branch_claim_value_rules(line, expected):
    assert pp.find_branch_claim("# План\n\n" + line + "\n") == expected


def test_find_branch_claim_ignores_field_inside_code_fence():
    text = "# План\n\n```\n- **Ветка:** `feat/in-fence`\n```\n\nТекст.\n"
    assert pp.find_branch_claim(text) == ""
