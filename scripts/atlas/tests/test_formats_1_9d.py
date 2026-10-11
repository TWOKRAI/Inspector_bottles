"""Тест-контракт форматов ADR-ATL-004: «пример шаблона -> читатель -> те же поля» (Task 1.9d, RED до шаблонов).

Purpose: слепые тесты по REDS «Tester» брифа plans/2026-10-04_atlas/tasks/1.9d.tester.md. Пример берётся из шаблона
    (`.claude/plugins/dev/templates/`: task-brief.md, injections.md, review-report.md), проходит через читателя
    (`plans_ledger.build_brief`, `views._lead_parts`, хук `lint-brief.sh`) или сверяется с литералами ADR-ATL-004.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Источник истины — раздел `## ADR-ATL-004` файла `scripts/atlas/DECISIONS.md`: регулярки, наборы ключей и слова ниже —
литералы оттуда, из шаблонов под проверкой они не читаются. Блоки берутся по §1 ADR (1-й/2-й блок в четырёх обратных
кавычках с меткой `markdown`; 1-й блок в трёх с меткой `json`), строки режутся `splitlines()` (Windows — CRLF).
Второго парсера меток нет: блоки и позиции меток — через `plans_ledger`. Хук запускается, не импортируется.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATES = _ROOT / ".claude" / "plugins" / "dev" / "templates"
_DECISIONS = _ROOT / "scripts" / "atlas" / "DECISIONS.md"
_HOOK = _ROOT / ".claude" / "plugins" / "dev" / "hooks" / "lint-brief.sh"

# --- литералы ADR-ATL-004 ----------------------------------------------------------------------------------------

# §2.1: роли файла роли
_ROLES = ("tester", "developer", "teamlead", "junior", "debugger")
# §2.3: регулярка метки (байт в байт _BRIEF_LABEL_RE и LABEL_RE хука)
_LABEL_RE = re.compile(r"^[ \t]*([A-Z][A-Z \-/]{2,})(?:[ \t]*\(.*)?:")
# §2.5: маркеры FACTS и строка FACTS/ACCEPTANCE (тире U+2014, стрелка U+2192)
_FACTS_OPEN_RE = re.compile(r"^<!-- atlas:facts (?P<sha>[0-9a-f]{7}) -->$")
_FACTS_CLOSE = "<!-- /atlas:facts -->"
_FACT_LINE_RE = re.compile(r"^[ \t]*- (?P<what>.+?) — `(?P<cmd>[^`]+)` → (?:`(?P<lit>[^`]+)`|exit (?P<code>\d+))$")
# §3: восемь ключей и nodeid
_INJ_KEYS = {"id", "prop", "file", "old", "new", "forecast", "observed", "test"}
_NODEID_RE = re.compile(r"^[^\s:]+\.py::\S+$")
# §5: три строки шапки и пункт замечания
_VERDICT_RE = re.compile(r"^Вердикт: (APPROVED|CHANGES REQUESTED)$")
_TOTAL_RE = re.compile(r"^Итог: blocker (\d+), major (\d+), minor (\d+), nit (\d+)$")
_CLASSES_RE = re.compile(
    r"^Классы: fact (\d+), dryrun (\d+), form (\d+), context (\d+), design (\d+), scope (\d+), process (\d+)$"
)
_BULLET_RE = re.compile(r"^- \[(blocker|major|minor|nit)/(fact|dryrun|form|context|design|scope|process)\] \S")
_SEVERITIES = ("blocker", "major", "minor", "nit")
_CLASSES = ("fact", "dryrun", "form", "context", "design", "scope", "process")

# --- извлечение примеров из шаблонов -----------------------------------------------------------------------------


def _fence_blocks(path: Path, ticks: int, lang: str) -> list[list[str]]:
    """Блоки `<ticks>×"`" + lang` ... `<ticks>×"`"` файла: строки между ограждениями, в порядке файла."""
    assert path.is_file(), f"шаблон отсутствует: {path}"
    fence = "`" * ticks
    open_re = re.compile(rf"^{fence}{lang}\s*$")
    close_re = re.compile(rf"^{fence}\s*$")
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if current is None:
            if open_re.match(line):
                current = []
        elif close_re.match(line):
            blocks.append(current)
            current = None
        else:
            current.append(line)
    return blocks


def _example(path: Path, ticks: int, lang: str, nth: int) -> list[str]:
    blocks = _fence_blocks(path, ticks, lang)
    assert len(blocks) > nth, f"{path.name}: нет блока №{nth + 1} ({'`' * ticks}{lang}), найдено {len(blocks)}"
    return blocks[nth]


def _main_brief() -> list[str]:
    return _example(_TEMPLATES / "task-brief.md", 4, "markdown", 0)


def _role_brief() -> list[str]:
    return _example(_TEMPLATES / "task-brief.md", 4, "markdown", 1)


def _write_brief(tmp_path: Path, name: str, lines: list[str]) -> Path:
    """Кладёт пример в `<tmp>/plans/2099-01-01_probe/tasks/<name>.md`; возвращает каталог плана."""
    plan_dir = tmp_path / "plans" / "2099-01-01_probe"
    tasks = plan_dir / "tasks"
    tasks.mkdir(parents=True)
    (tasks / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return plan_dir


def _build(tmp_path: Path, name: str, lines: list[str]) -> str:
    from scripts.plans_ledger import build_brief

    plan_dir = _write_brief(tmp_path, name, lines)
    return build_brief(root=_ROOT, plan_path=plan_dir, task_id=name)


def _main_id(lines: list[str]) -> str:
    """id из главного H1 `# Task <id> — …` (§2.1)."""
    for line in lines:
        m = re.match(r"^# Task (\S+) — ", line)
        if m:
            return m.group(1)
    pytest.fail("в главном примере нет H1 `# Task <id> — <суть>`")


def _role_id_and_role(lines: list[str]) -> tuple[str, str]:
    """id и роль из H1 файла роли `# <id> — бриф <role>` (§2.1)."""
    for line in lines:
        m = re.match(r"^# (\S+) — бриф (\S+)$", line)
        if m:
            return m.group(1), m.group(2)
    pytest.fail("в примере роли нет H1 `# <id> — бриф <role>`")


# --- РЕДЫ ---------------------------------------------------------------------------------------------------------


def test_task_brief_example_builds(tmp_path: Path) -> None:
    from scripts.plans_ledger import _brief_label_positions

    lines = _main_brief()
    task_id = _main_id(lines)
    out_lines = _build(tmp_path, task_id, lines).splitlines()

    assert out_lines[0].startswith("TASK:"), out_lines[0]
    first_label = _brief_label_positions("\n".join(lines))[0][0]
    leaked = [ln for ln in lines[:first_label] if ln.strip() and ln in out_lines]
    assert leaked == [], f"шапка лида ушла в спавн: {leaked}"
    opens = [ln for ln in out_lines if _FACTS_OPEN_RE.match(ln)]
    assert opens, "в собранном брифе нет строки `<!-- atlas:facts <sha7> -->`"
    assert _FACTS_CLOSE in out_lines, "в собранном брифе нет строки `<!-- /atlas:facts -->`"


def test_role_file_example_builds(tmp_path: Path) -> None:
    from scripts.plans_ledger import extract_task_ids

    lines = _role_brief()
    task_id, role = _role_id_and_role(lines)
    assert role in _ROLES, role
    out_lines = _build(tmp_path, f"{task_id}.{role}", lines).splitlines()

    assert any(re.match(rf"^ROLE: {role}(?:\s|$)", ln) for ln in out_lines), f"нет строки `ROLE: {role}`"
    assert extract_task_ids("\n".join(lines), in_task_file=True) == []


def test_facts_and_acceptance_lines_follow_grammar() -> None:
    from scripts.plans_ledger import _label_blocks

    lines = _main_brief()
    starts = [i for i, ln in enumerate(lines) if _FACTS_OPEN_RE.match(ln)]
    assert starts, "в главном примере нет открывающего маркера FACTS"
    ends = [i for i, ln in enumerate(lines) if ln == _FACTS_CLOSE and i > starts[0]]
    assert ends, "в главном примере нет закрывающего маркера FACTS после открывающего"
    sha = _FACTS_OPEN_RE.match(lines[starts[0]]).group("sha")  # type: ignore[union-attr]
    assert re.fullmatch(r"[0-9a-f]{7}", sha), sha

    facts = lines[starts[0] + 1 : ends[0]]
    assert len(facts) >= 1, "между маркерами FACTS нет строк"
    bad_facts = [ln for ln in facts if not _FACT_LINE_RE.match(ln)]
    assert bad_facts == [], f"строки FACTS вне грамматики §2.5: {bad_facts}"

    blocks = _label_blocks(lines)
    assert "ACCEPTANCE" in blocks, "в главном примере нет метки ACCEPTANCE"
    items = [ln for ln in blocks["ACCEPTANCE"][1:] if ln.lstrip().startswith("- ")]
    assert len(items) >= 1, "в блоке ACCEPTANCE нет пунктов `- `"
    bad_items = [ln for ln in items if not _FACT_LINE_RE.match(ln)]
    assert bad_items == [], f"пункты ACCEPTANCE вне грамматики §2.5: {bad_items}"


def test_lead_parts_reads_open_questions() -> None:
    from scripts.atlas.views import _lead_parts

    parts = _lead_parts("\n".join(_main_brief()))
    assert parts, "`_lead_parts` не нашёл строк `О<n>` под `## Открыто для лида`"
    assert parts[0].startswith("    Открыто для лида ("), parts[0]


def test_spawn_hook_allows_built_brief(tmp_path: Path) -> None:
    from scripts.plans_ledger import _label_blocks

    git = shutil.which("git")
    bash = None
    for parent in Path(git).resolve().parents if git else []:
        if (parent / "bin" / "bash.exe").is_file():
            bash = str(parent / "bin" / "bash.exe")
            break
    if bash is None:
        bash = shutil.which("bash") if sys.platform != "win32" else None
    if bash is None:
        pytest.skip("нет Git Bash: хук lint-brief.sh не запустить")

    lines = _role_brief()
    task_id, role = _role_id_and_role(lines)
    built = _build(tmp_path, f"{task_id}.{role}", lines)

    env = dict(os.environ)
    env["CLAUDE_PYTHON_BIN"] = sys.executable
    env["CLAUDE_PROJECT_DIR"] = str(_ROOT)

    def run_hook(prompt: str) -> subprocess.CompletedProcess[str]:
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "tester", "prompt": prompt}}
        return subprocess.run(
            [bash, _HOOK.as_posix()],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(_ROOT),
            timeout=60,
        )

    allowed = run_hook(built)
    assert allowed.returncode == 0, allowed.stderr
    assert "deny" not in allowed.stdout, allowed.stdout

    # парный контроль: тот же текст без блока DESIGN — хук обязан отказать (доказывает, что он отработал)
    built_lines = built.splitlines()
    block = _label_blocks(built_lines)["DESIGN"]
    start = next(i for i, ln in enumerate(built_lines) if (m := _LABEL_RE.match(ln)) and m.group(1).strip() == "DESIGN")
    control_lines = built_lines[:start] + built_lines[start + len(block) :]
    assert "DESIGN" not in _label_blocks(control_lines)
    denied = run_hook("\n".join(control_lines))
    assert denied.returncode == 0, denied.stderr
    assert '"permissionDecision": "deny"' in denied.stdout, denied.stdout


def test_injections_example_schema() -> None:
    raw = "\n".join(_example(_TEMPLATES / "injections.md", 3, "json", 0))
    data = json.loads(raw)

    assert isinstance(data, list)
    assert len(data) >= 2, f"в примере {len(data)} объект(ов), нужно >= 2"
    assert all(isinstance(o, dict) for o in data)
    for obj in data:
        assert set(obj) == _INJ_KEYS, sorted(set(obj) ^ _INJ_KEYS)
    assert [o["id"] for o in data] == [f"inj-{n}" for n in range(1, len(data) + 1)]
    for obj in data:
        for key in ("old", "file", "prop", "test"):
            assert isinstance(obj[key], str) and obj[key], f"{obj['id']}.{key}: нужна непустая строка"
        assert isinstance(obj["new"], str), f"{obj['id']}.new: нужна строка (может быть пустой)"
        assert isinstance(obj["forecast"], list), f"{obj['id']}.forecast: нужен список"
        bad = [n for n in obj["forecast"] if not (isinstance(n, str) and _NODEID_RE.match(n))]
        assert bad == [], f"{obj['id']}.forecast: не nodeid: {bad}"
        if obj["observed"] is not None:
            assert isinstance(obj["observed"], list), f"{obj['id']}.observed: null или список"
            bad = [n for n in obj["observed"] if not (isinstance(n, str) and _NODEID_RE.match(n))]
            assert bad == [], f"{obj['id']}.observed: не nodeid: {bad}"
    assert any(o["observed"] is None for o in data), "нет объекта с observed: null"
    assert any(isinstance(o["observed"], list) for o in data), "нет объекта с observed: список"


def test_review_example_counts_match_header() -> None:
    lines = _example(_TEMPLATES / "review-report.md", 4, "markdown", 0)
    assert len(lines) >= 4, f"в примере {len(lines)} строк(и), нужно >= 4"

    verdict = _VERDICT_RE.fullmatch(lines[1])
    total = _TOTAL_RE.fullmatch(lines[2])
    classes = _CLASSES_RE.fullmatch(lines[3])
    assert verdict, f"строка 2 вне грамматики §5: {lines[1]!r}"
    assert total, f"строка 3 вне грамматики §5: {lines[2]!r}"
    assert classes, f"строка 4 вне грамматики §5: {lines[3]!r}"

    bullets = [m for ln in lines if (m := _BULLET_RE.match(ln))]
    assert len(bullets) >= 1, "в примере нет ни одного замечания `- [степень/класс] …`"
    stray = [ln for ln in lines if ln.lstrip().startswith("- [") and not _BULLET_RE.match(ln)]
    assert stray == [], f"строки с `- [` вне грамматики: {stray}"

    by_sev = [sum(1 for m in bullets if m.group(1) == s) for s in _SEVERITIES]
    by_cls = [sum(1 for m in bullets if m.group(2) == c) for c in _CLASSES]
    assert by_sev == [int(g) for g in total.groups()], f"степени: пункты {by_sev} против Итог {total.groups()}"
    assert by_cls == [int(g) for g in classes.groups()], f"классы: пункты {by_cls} против Классы {classes.groups()}"


# --- ГАРД ---------------------------------------------------------------------------------------------------------


def test_adr_table_names_reader_and_contract() -> None:
    lines = _DECISIONS.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## ADR-ATL-004"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = lines[start:end]

    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header = next(cells(ln) for ln in section if ln.startswith("| формат |"))
    readers_at = header.index("читатели")
    contract_at = header.index("тест-контракт")
    rows = {cells(ln)[0]: cells(ln) for ln in section if ln.startswith("| ") and len(cells(ln)) == len(header)}

    for name in ("бриф", "инъекции", "итог", "отчёт ревью"):
        assert name in rows, f"в таблице §1 нет строки {name!r}"
        for at, title in ((readers_at, "читатели"), (contract_at, "тест-контракт")):
            cell = rows[name][at]
            assert cell and cell != "—", f"строка {name!r}: ячейка {title!r} пуста или «—»"
