"""Адаптер `commits`: узлы commit, рёбра refs/implements/touches/done_by, находки DONE_* (Task 1.3b).

Purpose: коммиты сборки (first-parent, коммиты PR сверх main-ref, цели хешей DONE) и всё, что выводится из их
    текста и диффа: трейлеры Refs/Task (regex по %B), модули по путям, done_by из строк DONE планов.
Public API: CommitsAdapter.
Stability: lite
"""

from __future__ import annotations

import re
from collections import defaultdict

from scripts.atlas.adapters.modules import modules_for
from scripts.atlas.adapters.plans import adapter_version, plans_for
from scripts.atlas.modules import resolve as resolve_module
from scripts.atlas.schema import AdapterOutput, BuildContext, Edge, Finding, Node
from scripts.atlas.tree import AtlasError, git, resolve, run_git

__all__ = ["CommitsAdapter"]

_REFS = re.compile(r"^Refs:[ \t]*(\S.*?)[ \t\r]*$", re.M)
_TASK = re.compile(r"^Task:[ \t]*(\S.*?)[ \t\r]*$", re.M)
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_FAIL = "atlas: git {} failed: {}"


def _lines(root: object, *args: str) -> list[str]:
    return git(root, *args).splitlines()  # type: ignore[arg-type]


def _stdout(root: object, args: tuple[str, ...], stdin: str) -> bytes:
    proc = run_git(root, *args, input=stdin.encode("utf-8"))  # type: ignore[arg-type]
    if proc.returncode != 0:
        raise AtlasError(_FAIL.format(" ".join(args), proc.stderr.decode("utf-8", "replace").strip()))
    return proc.stdout


def _plan_slug(value: str) -> str:
    """`plans/[_archive/]<сегмент>[/…].md` -> сегмент без `.md` и без даты; иначе пустая строка."""
    if not (value.startswith("plans/") and value.endswith(".md")):
        return ""
    rest = value[len("plans/") :].removeprefix("_archive/")
    return _DATE_PREFIX.sub("", rest.split("/", 1)[0].removesuffix(".md"))


def _resolve_hashes(root: object, hashes: list[str]) -> dict[str, str]:
    """Хеш как написан -> полный SHA коммита или причина отказа (`missing`/`ambiguous`); один вызов cat-file."""
    if not hashes:
        return {}
    out = _stdout(root, ("cat-file", "--batch-check"), "".join(f"{h}^{{commit}}\n" for h in hashes))
    result: dict[str, str] = {}
    for hash_, line in zip(hashes, out.decode("utf-8", "replace").splitlines()):
        parts = line.split(" ")
        ok = len(parts) == 3 and parts[1] == "commit" and _SHA.match(parts[0]) is not None
        result[hash_] = parts[0] if ok else ("ambiguous" if parts[-1] == "ambiguous" else "missing")
    return result


def _meta(root: object, shas: list[str]) -> dict[str, tuple[int, str]]:
    """SHA -> (время %ct, полное сообщение %B) через один `git log --no-walk=unsorted --stdin`."""
    raw = _stdout(
        root, ("log", "--no-walk=unsorted", "--stdin", "--format=%H%x00%ct%x00%B%x02"), "\n".join(shas) + "\n"
    )
    meta: dict[str, tuple[int, str]] = {}
    for record in raw.decode("utf-8", "replace").split("\x02"):
        if record.strip():
            sha, ts, message = record.lstrip("\n").split("\x00", 2)
            meta[sha] = (int(ts), message)
    return meta


def _paths(root: object, shas: list[str]) -> dict[str, list[str]]:
    """SHA -> пути диффа против первого родителя (оба пути при переименовании не нужны: --no-renames)."""
    args = ("log", "--no-walk=unsorted", "--stdin", "-m", "--first-parent", "--no-renames", "--name-only", "-z")
    raw = _stdout(root, (*args, "--format=%x01%H"), "\n".join(shas) + "\n")
    paths: dict[str, list[str]] = defaultdict(list)
    current, fresh = "", False
    for token in raw.split(b"\0"):
        text = token.decode("utf-8", "replace")
        if text.startswith("\x01"):
            current, fresh = text[1:], True
        elif text:
            paths[current].append(text.lstrip("\n") if fresh else text)
            fresh = False
    return paths


class CommitsAdapter:
    name = "commits"
    _BASE = 1

    @property
    def version(self) -> int:
        return adapter_version(self._BASE)

    def collect(self, ctx: BuildContext) -> AdapterOutput:
        root, sha = ctx.tree.root, ctx.tree.ref
        try:
            tip = resolve(root, ctx.main_ref)
        except AtlasError:
            raise AtlasError("atlas: main ref not found") from None
        if git(root, "rev-parse", "--is-shallow-repository") == "true":
            raise AtlasError("atlas: shallow clone — commits need full history; run: git fetch --unshallow")

        order = dict.fromkeys(_lines(root, "rev-list", "--first-parent", sha))
        order.update(dict.fromkeys(_lines(root, "rev-list", sha, "--not", tip)))
        out = AdapterOutput()

        plans, _ = plans_for(ctx.tree)
        tasks = {f"{slug}#{t['id']}": (plan["path"], t) for slug, plan in plans for t in plan["tasks"]}
        done = {tid: (path, (t.get("ref") or "").strip()) for tid, (path, t) in tasks.items() if t["status"] == "done"}
        resolved = _resolve_hashes(root, sorted({ref for _, ref in done.values() if ref}))
        order.update(dict.fromkeys(s for s in resolved.values() if _SHA.match(s)))
        ancestors = set(_lines(root, "rev-list", sha)) if any(_SHA.match(s) for s in resolved.values()) else set()

        shas = list(order)
        meta = _meta(root, shas)
        out.nodes = [Node("commit", s, None, None, meta[s][0]) for s in shas]

        implements: dict[str, list[str]] = defaultdict(list)  # task id -> SHA коммитов, как есть в сообщениях
        for s in shas:
            message = meta[s][1]
            plan_ids = dict.fromkeys(_plan_slug(v) for v in _REFS.findall(message))
            for slug in filter(None, plan_ids):
                out.edges.append(Edge("refs", f"commit:{s}", f"plan:{slug}", "trailer:Refs"))
            for value in dict.fromkeys(_TASK.findall(message)):
                slug_part, sep, id_part = value.partition("#")
                if sep and slug_part and id_part:
                    out.edges.append(Edge("implements", f"commit:{s}", f"task:{value}", "trailer:Task"))
                    implements[value].append(s)

        modules = modules_for(ctx.tree)
        paths = _paths(root, shas)
        module_of: dict[str, str] = {}
        for s in shas:
            for p in paths.get(s, []):
                module_of.setdefault(p, resolve_module(p, modules))
            for module in sorted({module_of[p] for p in paths.get(s, [])}):
                out.edges.append(Edge("touches", f"commit:{s}", f"module:{module}", "path"))

        for tid, (path, ref) in done.items():
            if not ref:
                if tid not in implements:
                    out.findings.append(
                        Finding(
                            "DONE_WITHOUT_COMMIT", "info", f"task:{tid}", "", f"Задача {tid} done без коммита", path
                        )
                    )
                continue
            found = resolved[ref]
            target = found if _SHA.match(found) else None
            if target is not None:
                out.edges.append(Edge("done_by", f"task:{tid}", f"commit:{target}", "plan-line"))
            if target is None or target not in ancestors:
                reasons = {"missing": "не найден", "ambiguous": "неоднозначен"}
                reason = reasons.get(found, "не предок ревизии сборки")
                msg = f"Хеш в строке DONE задачи {tid}: коммит {reason}"
                out.findings.append(Finding("DONE_HASH_NOT_IN_MAIN", "blocking", f"task:{tid}", ref, msg, path))

        for tid, commits in implements.items():
            if tid in tasks and tid not in done:
                msg = f"Коммит назван в Task: для задачи {tid}, но она не в статусе done"
                out.findings.append(Finding("COMMIT_WITHOUT_DONE", "info", f"task:{tid}", "", msg, min(commits)))
        return out
