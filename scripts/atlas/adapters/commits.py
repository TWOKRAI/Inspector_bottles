"""Адаптер `commits`: узлы commit, рёбра refs/implements/touches/done_by, находки DONE_* и REF_* (Tasks 1.3b, 1.3c).

Purpose: узлы commit — коммиты сборки (first-parent, коммиты PR сверх main-ref, цели хешей DONE) и коммиты
    без слияний с трейлером Refs/Task (любое значение). Рёбра
    refs/implements и находки REF_* берутся из трейлеров Refs/Task (regex по %B; токен `plans/…` начинается
    в начале значения или после пробела , ; ( ) всех предков сборки без слияний (`rev-list --no-merges`),
    в том числе коммитов без узла; коммиты-слияния трейлеров не дают. Служебные имена plans/ (константа
    _SERVICE_NAMES, зеркало plans_progress.is_service_name) не считаются планами в дереве коммита.
    Модули по путям (touches) и done_by из строк DONE планов — только для узлов сборки (не для добавленных трейлерных).
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
_TOKEN = re.compile(r"(?:^|(?<=[\s,;(]))plans/[^\s,;)]+")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SERVICE_NAMES = frozenset({"queue", "_archive", "QUEUE.md", "README.md"})
_RESULT = re.compile(r"\.result-.+\.md$")
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
    lines = _batch_check(root, [x for h in hashes for x in (h, f"{h}^{{commit}}")])
    result: dict[str, str] = {}
    for hash_, bare, full in zip(hashes, lines[0::2], lines[1::2]):
        parts = full.split(" ")
        ok = len(parts) == 3 and parts[1] == "commit" and _SHA.match(parts[0]) is not None
        result[hash_] = parts[0] if ok else ("ambiguous" if bare.endswith(" ambiguous") else "missing")
    return result


def _batch_check(root: object, queries: list[str]) -> list[str]:
    """Ответы одного `cat-file --batch-check` по одному на строку запроса (по позиции)."""
    out = _stdout(root, ("cat-file", "--batch-check"), "".join(f"{q}\n" for q in queries))
    return out.decode("utf-8", "replace").splitlines()


def _is_service_name(name: str) -> bool:
    """Служебное имя в `plans/` (не план). Дубль правила plans_progress.is_service_name: plans_progress для атласа —
    источник данных через --json, а не донор кода; синхронность с ним проверяет тест."""
    return name.startswith(".") or name in _SERVICE_NAMES or bool(_RESULT.search(name))


def _plans_in_tree(root: object, sha: str) -> set[str]:
    """slug планов в `plans/` и `plans/_archive/` дерева коммита (имя без каталога, `.md` и даты)."""
    raw = _stdout(root, ("ls-tree", "-z", "--name-only", sha, "plans/", "plans/_archive/"), "")
    names = (n.decode("utf-8", "replace").rsplit("/", 1)[-1] for n in raw.split(b"\0") if n)
    return {_DATE_PREFIX.sub("", n.removesuffix(".md")) for n in names if not _is_service_name(n)}


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


_PLACE = {
    ("Refs", "missing"): "Refs: путь {x} не найден ни в дереве сборки, ни в дереве коммита",
    ("Refs", "moved"): "Refs: путь {x} есть в дереве коммита, но не в дереве сборки (перенос или архив)",
    ("Task", "missing"): "Task: план {x} не найден ни в дереве сборки, ни в дереве коммита",
    ("Task", "moved"): "Task: план {x} есть в дереве коммита, но не в дереве сборки (перенос или архив)",
}


def _ref_findings(
    root: object,
    build: str,
    shas: list[str],
    tokens: dict[str, list[str]],
    values: dict[str, list[str]],
    slugs: set[str],
    tasks: set[str],
) -> list[Finding]:
    """REF_TO_MISSING (blocking) / REF_MOVED (info) по путям Refs и значениям Task; один вызов cat-file."""
    distinct = sorted({t for ts in tokens.values() for t in ts})
    pairs = [(s, t) for s in shas for t in tokens[s]]
    answers = _batch_check(root, [f"{build}:{t}" for t in distinct] + [f"{s}:{t}" for s, t in pairs])
    in_build = {t: not a.endswith(" missing") for t, a in zip(distinct, answers)}
    in_commit = {pair: not a.endswith(" missing") for pair, a in zip(pairs, answers[len(distinct) :])}

    def make(sha: str, kind: str, state: str, detail: str, subject: str) -> Finding:
        code, level = ("REF_MOVED", "info") if state == "moved" else ("REF_TO_MISSING", "blocking")
        return Finding(code, level, f"commit:{sha}", detail, _PLACE[(kind, state)].format(x=subject), sha)

    found: list[Finding] = []
    for s in shas:
        for t in tokens[s]:
            if not in_build[t]:
                found.append(make(s, "Refs", "moved" if in_commit[(s, t)] else "missing", t, t))
        local: set[str] | None = None
        for value in values[s]:
            slug, _, _ = value.partition("#")
            if slug in slugs:
                if value not in tasks:
                    msg = f"Task: в плане {slug} нет задачи {value.partition('#')[2]}"
                    found.append(Finding("REF_TO_MISSING", "blocking", f"commit:{s}", value, msg, s))
                continue
            local = _plans_in_tree(root, s) if local is None else local
            found.append(make(s, "Task", "moved" if slug in local else "missing", value, slug))
    return found


class CommitsAdapter:
    name = "commits"
    _BASE = 3

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
        authors = _lines(root, "rev-list", "--no-merges", sha)  # трейлеры: все предки без слияний
        meta = _meta(root, list(dict.fromkeys([*shas, *authors])))
        trailered = [s for s in authors if s not in order and (_REFS.search(meta[s][1]) or _TASK.search(meta[s][1]))]
        out.nodes = [Node("commit", s, None, None, meta[s][0]) for s in [*shas, *trailered]]

        implements: dict[str, list[str]] = defaultdict(list)  # task id -> SHA коммитов, как есть в сообщениях
        tokens: dict[str, list[str]] = {}  # SHA -> токены `plans/…` из Refs, без повторов
        values: dict[str, list[str]] = {}  # SHA -> значения Task с `#` и непустыми частями, без повторов
        for s in authors:
            message = meta[s][1]
            found = (t.rstrip(".") for v in _REFS.findall(message) for t in _TOKEN.findall(v))
            tokens[s] = list(dict.fromkeys(found))
            for slug in filter(None, dict.fromkeys(_plan_slug(t) for t in tokens[s])):
                out.edges.append(Edge("refs", f"commit:{s}", f"plan:{slug}", "trailer:Refs"))
            values[s] = []
            for value in dict.fromkeys(_TASK.findall(message)):
                slug_part, sep, id_part = value.partition("#")
                if sep and slug_part and id_part:
                    out.edges.append(Edge("implements", f"commit:{s}", f"task:{value}", "trailer:Task"))
                    implements[value].append(s)
                    values[s].append(value)
        out.findings.extend(_ref_findings(root, sha, authors, tokens, values, {slug for slug, _ in plans}, set(tasks)))

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
