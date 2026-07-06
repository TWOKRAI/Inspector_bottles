"""
Meta-аудит инфраструктуры .claude/: frontmatter агентов и команд, SKILL.md,
ссылки в MEMORY.md, скрипты под slash-командами, хуки в settings.json.

Запуск:
    python scripts/claude_md_audit/claude_md_audit.py
    python scripts/claude_md_audit/claude_md_audit.py --format json
    python scripts/claude_md_audit/claude_md_audit.py --claude-dir .claude --no-strict

Exit:
    0 — нет находок
    1 — есть находки (под strict=true)
    2 — ошибка (нет .claude/, плохой конфиг)
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import fnmatch
import io
import json
import re
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).with_name("claude_md_audit.toml")

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# `python scripts/<name>/<name>.py` или `bash scripts/<file>.sh`
_SCRIPT_REF = re.compile(
    r"(?:python|bash|sh|uv\s+run|uvx)\s+(scripts/[^\s`'\"]+\.(?:py|sh))",
    re.IGNORECASE,
)
_MEM_LINK = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<href>[^)#]+\.md)(?:#[^)]*)?\)")

# Code-fence (```...```), inline-code (`...`) и frontmatter (--- ... ---).
# Содержимое не должно парситься как ссылки/пути.
_FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_LEADING_FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)


def _strip_code_and_frontmatter(text: str) -> str:
    """Убрать содержимое markdown-блоков, которое не должно парситься как prose.

    Удаляет: leading frontmatter (--- ... ---), fenced code blocks (```...```),
    inline code (`...`). Возвращает текст-prose, по которому безопасно искать
    реальные ссылки на скрипты.
    """
    out = _LEADING_FRONTMATTER.sub("", text, count=1)
    out = _FENCED_BLOCK.sub("", out)
    out = _INLINE_CODE.sub("", out)
    return out


@dataclass(frozen=True)
class Config:
    claude_dir: Path
    project_root: Path
    required_agent_fields: tuple[str, ...]
    required_command_fields: tuple[str, ...]
    ignore_patterns: tuple[str, ...]
    check_agents: bool
    check_commands: bool
    check_skills: bool
    check_slash_scripts: bool
    check_memory_links: bool
    check_hooks_settings: bool
    output_format: str
    group_by: str
    sort_by: str
    limit: int
    strict: bool


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    scan = raw.get("scan", {})
    req = raw.get("required_fields", {})
    chk = raw.get("checks", {})
    out = raw.get("output", {})
    return Config(
        claude_dir=Path(scan.get("claude_dir", ".claude")).expanduser(),
        project_root=Path(scan.get("project_root", ".")).expanduser(),
        required_agent_fields=tuple(req.get("agents", ["description"])),
        required_command_fields=tuple(req.get("commands", ["description"])),
        ignore_patterns=tuple(scan.get("ignore_patterns", ["_*"])),
        check_agents=bool(chk.get("agents", True)),
        check_commands=bool(chk.get("commands", True)),
        check_skills=bool(chk.get("skills", True)),
        check_slash_scripts=bool(chk.get("slash_scripts", True)),
        check_memory_links=bool(chk.get("memory_links", True)),
        check_hooks_settings=bool(chk.get("hooks_settings", True)),
        output_format=str(out.get("format", "table")).lower(),
        group_by=str(out.get("group_by", "kind")).lower(),
        sort_by=str(out.get("sort_by", "file")).lower(),
        limit=int(out.get("limit", 0)),
        strict=bool(out.get("strict", True)),
    )


def _is_ignored_name(name: str, patterns: tuple[str, ...]) -> bool:
    """Имя файла соответствует одному из glob-паттернов игнора."""
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def _infra_dirs(claude_dir: Path, segment: str) -> list[Path]:
    """Все каталоги с инфра-сегментом (agents/commands/skills/...).

    Plugin-раскладка держит контент каждого плагина под
    ``.claude/plugins/<id>/<segment>/`` (без flat-агрегации); legacy-flat
    ``.claude/<segment>/`` принимается как fallback / со-источник.
    """
    dirs: list[Path] = []
    flat = claude_dir / segment
    if flat.is_dir():
        dirs.append(flat)
    plugins = claude_dir / "plugins"
    if plugins.is_dir():
        for plugin in sorted(plugins.iterdir()):
            seg = plugin / segment
            if seg.is_dir():
                dirs.append(seg)
    return dirs


def _seed_script_exists(cfg: Config, name: str) -> bool:
    """True, если seed-скрипт *name* живёт внутри ``.claude/``.

    Plugin-раскладка: ``.claude/plugins/<id>/scripts/<name>`` или
    ``.claude/plugins/<id>/templates/scripts/<tool>/<name>``; плюс legacy-flat.
    """
    if (cfg.claude_dir / "scripts" / name).is_file():
        return True
    plugins = cfg.claude_dir / "plugins"
    if plugins.is_dir():
        for pattern in (f"*/scripts/{name}", f"*/templates/scripts/*/{name}"):
            for hit in plugins.glob(pattern):
                if hit.is_file():
                    return True
    return False


@dataclass
class Issue:
    file: str
    kind: str
    detail: str


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    m = _FRONTMATTER.match(text)
    if not m:
        return None
    fm: dict[str, str] = {}
    cur_key = ""
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0] not in " \t" and ":" in raw:
            key, _, val = raw.partition(":")
            cur_key = key.strip()
            fm[cur_key] = val.strip()
        elif cur_key:
            # многострочное значение — игнорируем содержимое, но фиксируем что ключ непустой
            fm[cur_key] = fm.get(cur_key) or "<multiline>"
    return fm


def _rel(p: Path, base: Path) -> str:
    try:
        return p.relative_to(base).as_posix()
    except ValueError:
        return p.as_posix()


def _audit_frontmatter(
    files: list[Path],
    required: tuple[str, ...],
    kind_prefix: str,
    base: Path,
) -> list[Issue]:
    out: list[Issue] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        rel = _rel(f, base)
        if fm is None:
            out.append(
                Issue(
                    rel, f"{kind_prefix}_missing_frontmatter", "нет блока --- ... ---"
                )
            )
            continue
        for field in required:
            if not fm.get(field):
                out.append(
                    Issue(rel, f"{kind_prefix}_missing_field", f"нет поля {field!r}")
                )
    return out


def audit_agents(cfg: Config) -> list[Issue]:
    if not cfg.check_agents:
        return []
    dirs = _infra_dirs(cfg.claude_dir, "agents")
    if not dirs:
        return []
    files = [
        p
        for d in dirs
        for p in d.rglob("*.md")
        if p.is_file()
        and p.name != "README.md"
        and not _is_ignored_name(p.name, cfg.ignore_patterns)
    ]
    return _audit_frontmatter(
        files, cfg.required_agent_fields, "agent", cfg.project_root
    )


def audit_commands(cfg: Config) -> list[Issue]:
    if not cfg.check_commands:
        return []
    dirs = _infra_dirs(cfg.claude_dir, "commands")
    if not dirs:
        return []
    files = [
        p
        for d in dirs
        for p in d.rglob("*.md")
        if p.is_file()
        and p.name != "README.md"
        and not _is_ignored_name(p.name, cfg.ignore_patterns)
    ]
    return _audit_frontmatter(
        files, cfg.required_command_fields, "command", cfg.project_root
    )


def audit_skills(cfg: Config) -> list[Issue]:
    if not cfg.check_skills:
        return []
    out: list[Issue] = []
    for skills_dir in _infra_dirs(cfg.claude_dir, "skills"):
        for sub in skills_dir.iterdir():
            if not sub.is_dir():
                continue
            if (sub / "SKILL.md").is_file():
                continue
            out.append(
                Issue(
                    _rel(sub, cfg.project_root),
                    "skill_missing_skill_md",
                    f"в {sub.name}/ нет SKILL.md",
                )
            )
    return out


def audit_slash_scripts(cfg: Config) -> list[Issue]:
    """Slash-команда ссылается на `python scripts/<x>` — проверить, что файл есть.

    Игнорирует ссылки внутри code-fence / inline-code (`<example>` блоки в
    docs самого claude-md-audit.md). Принимает fallback на seed-скрипты,
    живущие под `.claude/plugins/<id>/scripts/` (и legacy-раскладку), для
    скриптов вроде `lint_agents.py`, которые живут в seed, а не в проекте.
    """
    if not cfg.check_slash_scripts:
        return []
    cmd_dirs = _infra_dirs(cfg.claude_dir, "commands")
    if not cmd_dirs:
        return []
    out: list[Issue] = []
    for cmd_dir in cmd_dirs:
        for f in cmd_dir.rglob("*.md"):
            if f.name == "README.md":
                continue
            if _is_ignored_name(f.name, cfg.ignore_patterns):
                continue
            try:
                raw_text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            text = _strip_code_and_frontmatter(raw_text)
            rel_cmd = _rel(f, cfg.project_root)
            seen: set[str] = set()
            for m in _SCRIPT_REF.finditer(text):
                script_path = m.group(1)
                if script_path in seen:
                    continue
                seen.add(script_path)
                primary = cfg.project_root / script_path
                if primary.is_file():
                    continue
                # Fallback: seed-скрипты под .claude/plugins/<id>/scripts/
                # (напр. `lint_agents.py`), плюс legacy-раскладка.
                if _seed_script_exists(cfg, Path(script_path).name):
                    continue
                out.append(
                    Issue(
                        rel_cmd,
                        "command_orphan_script",
                        f"ссылается на отсутствующий {script_path}",
                    )
                )
    return out


def audit_memory_links(cfg: Config) -> list[Issue]:
    if not cfg.check_memory_links:
        return []
    mem_dir = cfg.claude_dir / "memory"
    index = mem_dir / "MEMORY.md"
    if not index.is_file():
        return []
    try:
        text = index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[Issue] = []
    seen: set[str] = set()
    for m in _MEM_LINK.finditer(text):
        href = m.group("href")
        if href in seen or href.startswith(("http://", "https://")):
            continue
        seen.add(href)
        target = (index.parent / href).resolve()
        if not target.exists():
            out.append(
                Issue(
                    _rel(index, cfg.project_root),
                    "memory_broken_link",
                    f"в MEMORY.md ссылка на отсутствующий {href}",
                )
            )
    return out


def audit_hooks_settings(cfg: Config) -> list[Issue]:
    """settings.json hooks → каждый command-путь должен существовать."""
    if not cfg.check_hooks_settings:
        return []
    settings = cfg.claude_dir / "settings.json"
    if not settings.is_file():
        return []
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [
            Issue(_rel(settings, cfg.project_root), "settings_invalid_json", str(e))
        ]

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return []
    out: list[Issue] = []
    rel_settings = _rel(settings, cfg.project_root)
    for event, configs in hooks.items():
        if not isinstance(configs, list):
            continue
        for entry in configs:
            for h in (entry.get("hooks") if isinstance(entry, dict) else None) or []:
                cmd = h.get("command") if isinstance(h, dict) else None
                if not cmd or not isinstance(cmd, str):
                    continue
                # Поиск пути в команде: токен, похожий на относительный путь хука
                # под .claude/plugins/<id>/hooks/ (и legacy-раскладку).
                for token in re.split(r"[\s|;&<>]+", cmd):
                    if not token:
                        continue
                    candidate = token.strip("\"'")
                    if candidate.startswith(".claude/") and (
                        candidate.endswith(".sh") or candidate.endswith(".py")
                    ):
                        target = cfg.project_root / candidate
                        if not target.is_file():
                            out.append(
                                Issue(
                                    rel_settings,
                                    "hook_missing_script",
                                    f"event={event!r} ссылается на {candidate}",
                                )
                            )
    return out


def _sort_issues(issues: list[Issue], cfg: Config) -> list[Issue]:
    key = {
        "file": lambda i: (i.file, i.kind),
        "kind": lambda i: (i.kind, i.file),
    }.get(cfg.sort_by, lambda i: (i.file, i.kind))
    out = sorted(issues, key=key)
    return out[: cfg.limit] if cfg.limit > 0 else out


def render_table(issues: list[Issue]) -> str:
    if not issues:
        return "OK: проблем в .claude/ не найдено.\n"
    headers = ["kind", "file", "detail"]
    data = [[i.kind, i.file, i.detail] for i in issues]
    widths = [len(h) for h in headers]
    for row in data:
        for j, c in enumerate(row):
            widths[j] = max(widths[j], len(str(c)))
    buf = io.StringIO()
    sep = "  "
    buf.write(sep.join(h.ljust(widths[j]) for j, h in enumerate(headers)) + "\n")
    buf.write(sep.join("-" * w for w in widths) + "\n")
    for row in data:
        buf.write(sep.join(str(c).ljust(widths[j]) for j, c in enumerate(row)) + "\n")
    return buf.getvalue()


def render_summary(issues: list[Issue], cfg: Config) -> str:
    if not issues or cfg.group_by == "none":
        return ""
    counts: dict[str, int] = defaultdict(int)
    key_fn = (lambda i: i.kind) if cfg.group_by == "kind" else (lambda i: i.file)
    for i in issues:
        counts[key_fn(i)] += 1
    title = "Kind" if cfg.group_by == "kind" else "File"
    rows = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    width = max((len(k) for k, _ in rows), default=len(title))
    buf = io.StringIO()
    buf.write(f"{title.ljust(width)}  count\n")
    buf.write("-" * width + "  -----\n")
    for k, v in rows:
        buf.write(f"{k.ljust(width)}  {v}\n")
    buf.write("\n")
    return buf.getvalue()


def render_json(issues: list[Issue]) -> str:
    return json.dumps(
        {"summary": {"total": len(issues)}, "issues": [i.__dict__ for i in issues]},
        ensure_ascii=False,
        indent=2,
    )


def render_csv(issues: list[Issue]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["kind", "file", "detail"])
    for i in issues:
        w.writerow([i.kind, i.file, i.detail])
    return buf.getvalue()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude_md_audit", description="Meta-аудит .claude/."
    )
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--claude-dir", type=Path, default=None)
    p.add_argument("--project-root", type=Path, default=None)
    p.add_argument("--format", choices=["table", "json", "csv"], default=None)
    p.add_argument("--group-by", choices=["kind", "file", "none"], default=None)
    p.add_argument("--sort-by", choices=["file", "kind"], default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-strict", action="store_true")
    return p


def _force_utf8_stdout() -> None:
    """Зафиксировать UTF-8 для stdout/stderr.

    На Windows-консоли (cp1251 codepage) русские строки в выводе превращаются
    в '?????'. Python 3.11+ умеет переключить io-streams в UTF-8 на лету.
    Safe для не-TTY и redirected потоков (no-op если reconfigure недоступен).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    overrides: dict = {}
    if args.claude_dir is not None:
        overrides["claude_dir"] = args.claude_dir
    if args.project_root is not None:
        overrides["project_root"] = args.project_root
    if args.format is not None:
        overrides["output_format"] = args.format
    if args.group_by is not None:
        overrides["group_by"] = args.group_by
    if args.sort_by is not None:
        overrides["sort_by"] = args.sort_by
    if args.limit is not None:
        overrides["limit"] = args.limit
    if args.no_strict:
        overrides["strict"] = False
    if overrides:
        cfg = Config(**{**cfg.__dict__, **overrides})

    if not cfg.claude_dir.is_dir():
        print(f"error: claude_dir не существует: {cfg.claude_dir}", file=sys.stderr)
        return 2

    issues: list[Issue] = []
    issues.extend(audit_agents(cfg))
    issues.extend(audit_commands(cfg))
    issues.extend(audit_skills(cfg))
    issues.extend(audit_slash_scripts(cfg))
    issues.extend(audit_memory_links(cfg))
    issues.extend(audit_hooks_settings(cfg))

    issues = _sort_issues(issues, cfg)

    if cfg.output_format == "json":
        sys.stdout.write(render_json(issues))
    elif cfg.output_format == "csv":
        sys.stdout.write(render_csv(issues))
    else:
        sys.stdout.write(render_summary(issues, cfg))
        sys.stdout.write(render_table(issues))

    if issues and cfg.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
