"""
Генератор changelog из Conventional Commits.

Парсит `git log <from>..<to>` → группирует по type → рендерит markdown / plain / json.

Запуск:
    python scripts/changelog_gen/changelog_gen.py
    python scripts/changelog_gen/changelog_gen.py --from v1.0.0 --to HEAD
    python scripts/changelog_gen/changelog_gen.py --style json --no-hashes
    python scripts/changelog_gen/changelog_gen.py --release-name v1.1.0 --release-date 2026-05-24

Conventional Commits: type(scope)?!?: subject
    feat(api)!: drop /v1
    fix: avoid crash on empty input
    chore: ...

Breaking: `!` в типе ИЛИ `BREAKING CHANGE:` в теле/footer.

Exit:
    0 — успех
    2 — git недоступен / нет коммитов в диапазоне / ошибка конфига
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).with_name("changelog_gen.toml")

# type(scope)?!?: subject
_CC_HEADER = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s+(?P<subject>.+)$"
)
_BREAKING_FOOTER = re.compile(r"^BREAKING[ -]CHANGE:\s*(.+)$", re.MULTILINE)
# git log --format separator
_REC_SEP = "\x1e"
_FIELD_SEP = "\x1f"


@dataclass(frozen=True)
class Config:
    range_from: str
    range_to: str
    groups: tuple[tuple[str, tuple[str, ...]], ...]  # label → (types,)
    include_unknown: bool
    include_breaking: bool
    include_authors: bool
    include_hashes: bool
    hash_length: int
    style: str
    repo_url: str
    release_name: str
    release_date: str


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    git = raw.get("git", {})
    grp = raw.get("groups", {})
    fmt = raw.get("format", {})

    # groups: order matters
    groups: list[tuple[str, tuple[str, ...]]] = []
    for label, types in grp.items():
        if isinstance(types, list):
            groups.append((label, tuple(str(t).lower() for t in types)))

    return Config(
        range_from=str(git.get("from", "")).strip(),
        range_to=str(git.get("to", "HEAD")).strip(),
        groups=tuple(groups),
        include_unknown=bool(fmt.get("include_unknown", False)),
        include_breaking=bool(fmt.get("include_breaking", True)),
        include_authors=bool(fmt.get("include_authors", False)),
        include_hashes=bool(fmt.get("include_hashes", True)),
        hash_length=int(fmt.get("hash_length", 7)),
        style=str(fmt.get("style", "markdown")).lower(),
        repo_url=str(fmt.get("repo_url", "")).rstrip("/"),
        release_name=str(fmt.get("release_name", "Unreleased")),
        release_date=str(fmt.get("release_date", "")),
    )


@dataclass
class Commit:
    sha: str
    type: str
    scope: str
    subject: str
    breaking: bool
    breaking_msg: str
    author: str
    raw_body: str = ""
    is_conventional: bool = True


@dataclass
class Changelog:
    release_name: str
    release_date: str
    groups: dict[str, list[Commit]] = field(default_factory=dict)
    breaking: list[Commit] = field(default_factory=list)
    unknown: list[Commit] = field(default_factory=list)


def _git_log(range_spec: str, cwd: Path) -> list[str]:
    fmt = _FIELD_SEP.join(["%H", "%an", "%s", "%b"]) + _REC_SEP
    cmd = ["git", "log", "--no-merges", f"--format={fmt}"]
    if range_spec:
        cmd.append(range_spec)
    proc = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git log failed: {proc.stderr.strip()}")
    return [r for r in proc.stdout.split(_REC_SEP) if r.strip()]


def _last_tag(cwd: Path) -> str:
    proc = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def parse_commit(record: str) -> Commit | None:
    parts = record.strip().split(_FIELD_SEP)
    if len(parts) < 3:
        return None
    sha, author, subject = parts[0].strip(), parts[1].strip(), parts[2].strip()
    body = parts[3].strip() if len(parts) > 3 else ""
    m = _CC_HEADER.match(subject)
    if not m:
        return Commit(
            sha=sha,
            type="",
            scope="",
            subject=subject,
            breaking=False,
            breaking_msg="",
            author=author,
            raw_body=body,
            is_conventional=False,
        )
    ctype = m.group("type").lower()
    scope = (m.group("scope") or "").strip().lower()
    bang = bool(m.group("bang"))
    subj = m.group("subject").strip()
    breaking_msg = ""
    bm = _BREAKING_FOOTER.search(body)
    if bm:
        breaking_msg = bm.group(1).strip()
    return Commit(
        sha=sha,
        type=ctype,
        scope=scope,
        subject=subj,
        breaking=bang or bool(bm),
        breaking_msg=breaking_msg,
        author=author,
        raw_body=body,
        is_conventional=True,
    )


def group_commits(commits: list[Commit], cfg: Config) -> Changelog:
    log = Changelog(
        release_name=cfg.release_name,
        release_date=cfg.release_date or date.today().isoformat(),
    )
    for label, _ in cfg.groups:
        log.groups[label] = []
    type_to_label: dict[str, str] = {}
    for label, types in cfg.groups:
        for t in types:
            type_to_label[t] = label
    for c in commits:
        if not c.is_conventional:
            if cfg.include_unknown:
                log.unknown.append(c)
            continue
        label = type_to_label.get(c.type)
        if label is None:
            if cfg.include_unknown:
                log.unknown.append(c)
        else:
            log.groups[label].append(c)
        if c.breaking and cfg.include_breaking:
            log.breaking.append(c)
    return log


def _commit_hash_prefix(c: Commit, cfg: Config) -> str:
    if not cfg.include_hashes:
        return ""
    h = c.sha[: cfg.hash_length]
    if cfg.repo_url:
        return f"([{h}]({cfg.repo_url}/commit/{c.sha})) "
    return f"({h}) "


def _commit_line_md(c: Commit, cfg: Config) -> str:
    prefix = _commit_hash_prefix(c, cfg)
    scope = f"**{c.scope}**: " if c.scope else ""
    suffix = f" — _by_ {c.author}" if cfg.include_authors else ""
    return f"- {prefix}{scope}{c.subject}{suffix}"


def render_markdown(log: Changelog, cfg: Config) -> str:
    buf: list[str] = []
    buf.append(f"## [{log.release_name}] — {log.release_date}\n")
    for label, _ in cfg.groups:
        commits = log.groups.get(label, [])
        if not commits:
            continue
        buf.append(f"\n### {label}\n")
        for c in commits:
            buf.append(_commit_line_md(c, cfg))
    if cfg.include_breaking and log.breaking:
        buf.append("\n### ⚠ BREAKING CHANGES\n")
        for c in log.breaking:
            msg = c.breaking_msg or c.subject
            buf.append(f"- {_commit_hash_prefix(c, cfg)}{msg}")
    if cfg.include_unknown and log.unknown:
        buf.append("\n### Other\n")
        for c in log.unknown:
            buf.append(f"- {_commit_hash_prefix(c, cfg)}{c.subject}")
    buf.append("")
    return "\n".join(buf)


def render_plain(log: Changelog, cfg: Config) -> str:
    buf: list[str] = []
    buf.append(f"{log.release_name} — {log.release_date}")
    buf.append("=" * 60)
    for label, _ in cfg.groups:
        commits = log.groups.get(label, [])
        if not commits:
            continue
        buf.append(f"\n[{label}]")
        for c in commits:
            hash_part = f"{c.sha[: cfg.hash_length]} " if cfg.include_hashes else ""
            scope = f"({c.scope}) " if c.scope else ""
            buf.append(f"  {hash_part}{scope}{c.subject}")
    if cfg.include_breaking and log.breaking:
        buf.append("\n[BREAKING CHANGES]")
        for c in log.breaking:
            hash_part = f"{c.sha[: cfg.hash_length]} " if cfg.include_hashes else ""
            buf.append(f"  {hash_part}{c.breaking_msg or c.subject}")
    return "\n".join(buf) + "\n"


def render_json(log: Changelog, cfg: Config) -> str:
    def c2d(c: Commit) -> dict:
        return {
            "sha": c.sha,
            "type": c.type,
            "scope": c.scope,
            "subject": c.subject,
            "breaking": c.breaking,
            "breaking_msg": c.breaking_msg,
            "author": c.author if cfg.include_authors else "",
        }

    return json.dumps(
        {
            "release_name": log.release_name,
            "release_date": log.release_date,
            "groups": {
                label: [c2d(c) for c in log.groups.get(label, [])]
                for label, _ in cfg.groups
            },
            "breaking": [c2d(c) for c in log.breaking] if cfg.include_breaking else [],
            "unknown": [c2d(c) for c in log.unknown] if cfg.include_unknown else [],
        },
        ensure_ascii=False,
        indent=2,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="changelog_gen", description="Changelog из Conventional Commits."
    )
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--cwd", type=Path, default=Path("."), help="Корень git-репо.")
    p.add_argument(
        "--from",
        dest="range_from",
        default=None,
        help="Начало диапазона (по умолчанию: последний tag).",
    )
    p.add_argument(
        "--to",
        dest="range_to",
        default=None,
        help="Конец диапазона (по умолчанию: HEAD).",
    )
    p.add_argument("--style", choices=["markdown", "plain", "json"], default=None)
    p.add_argument("--release-name", default=None)
    p.add_argument(
        "--release-date", default=None, help="ISO date, по умолчанию сегодня."
    )
    p.add_argument("--no-hashes", action="store_true")
    p.add_argument("--no-breaking", action="store_true")
    p.add_argument("--authors", action="store_true")
    p.add_argument(
        "--include-unknown",
        action="store_true",
        help="Включать commits, не подходящие под known types.",
    )
    return p


def _force_utf8_stdout() -> None:
    """Зафиксировать UTF-8 для stdout/stderr (Windows cp1251 fix)."""
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
    if args.range_from is not None:
        overrides["range_from"] = args.range_from
    if args.range_to is not None:
        overrides["range_to"] = args.range_to
    if args.style is not None:
        overrides["style"] = args.style
    if args.release_name is not None:
        overrides["release_name"] = args.release_name
    if args.release_date is not None:
        overrides["release_date"] = args.release_date
    if args.no_hashes:
        overrides["include_hashes"] = False
    if args.no_breaking:
        overrides["include_breaking"] = False
    if args.authors:
        overrides["include_authors"] = True
    if args.include_unknown:
        overrides["include_unknown"] = True
    if overrides:
        cfg = Config(**{**cfg.__dict__, **overrides})

    cwd = args.cwd.resolve()
    if not (cwd / ".git").exists():
        print(f"error: не git-репозиторий: {cwd}", file=sys.stderr)
        return 2

    range_from = cfg.range_from or _last_tag(cwd)
    range_spec = ""
    if range_from:
        range_spec = f"{range_from}..{cfg.range_to}"
    elif cfg.range_to and cfg.range_to != "HEAD":
        range_spec = cfg.range_to

    try:
        records = _git_log(range_spec, cwd)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    commits: list[Commit] = []
    for rec in records:
        c = parse_commit(rec)
        if c is not None:
            commits.append(c)

    log = group_commits(commits, cfg)

    if cfg.style == "json":
        sys.stdout.write(render_json(log, cfg))
    elif cfg.style == "plain":
        sys.stdout.write(render_plain(log, cfg))
    else:
        sys.stdout.write(render_markdown(log, cfg))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
