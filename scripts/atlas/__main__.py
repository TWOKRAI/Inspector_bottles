"""CLI atlas: `build`, `check`, `card`, `pack`, `log`, `ref`, `index`, `lint-result`, `--json`
(Tasks 1.2, 1.6, 1.6b, 1.9a).

Запуск: `python -m scripts.atlas`.

Purpose: разбор argv, проводка видов card/pack/log (views.py) и ref/index (reference.py);
    корень репозитория = git toplevel (не cwd),
    база `data/atlas.sqlite` в корне.
    Коды выхода: 0 — успех, 1 — check нашёл новую blocking-находку,
    1 — `index --check`: INDEX.md отстал, 1 — `lint-result`: итог не по форме 0.7, 2 — ошибка окружения или ввода.
    `lint-result <файл>` не знает git и базу: ветка стоит до определения корня репозитория.
Public API: main.
Stability: lite
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from scripts.atlas import reference, result_form, store, views
from scripts.atlas.adapters.plans import live_plans
from scripts.atlas.build import build, to_json
from scripts.atlas.check import check, legacy_before
from scripts.atlas.tree import AtlasError, git, resolve, run_git

__all__ = ["main"]


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--main-ref", default=argparse.SUPPRESS, help="ref main-правил (по умолчанию main, иначе origin/main)"
    )
    with_ref = argparse.ArgumentParser(add_help=False)
    with_ref.add_argument("--ref", default=argparse.SUPPRESS, help="ревизия сборки (по умолчанию HEAD)")
    # SUPPRESS и никаких set_defaults: общий Action с default=None затирал бы флаг, данный до подкоманды
    top = argparse.ArgumentParser(prog="atlas", parents=[common, with_ref])
    top.add_argument("--json", action="store_true", help="напечатать реестр --ref (по умолчанию HEAD) как JSON")
    sub = top.add_subparsers(dest="command")
    sub.add_parser("build", parents=[common, with_ref], help="собрать реестр")
    sub.add_parser("check", parents=[common], help="гейт против merge-base").add_argument("--base", default=None)
    sub.add_parser("card", parents=[common, with_ref], help="карточка модуля").add_argument("module")
    pack = sub.add_parser("pack", parents=[common, with_ref], help="бриф задачи <slug>#<id>")
    pack.add_argument("task")
    pack.add_argument("--module", action="append", default=[], help="модуль задачи (повторяемый)")
    ref = sub.add_parser("ref", parents=[common, with_ref], help="справочник интерфейсов и кода модуля")
    ref.add_argument("module")
    ref.add_argument("--symbol", default=None, help="сузить вывод до одного символа")
    index = sub.add_parser("index", parents=[common, with_ref], help="индекс проекта (docs/atlas/INDEX.md)")
    index.add_argument("--write", action="store_true", help="записать docs/atlas/INDEX.md")
    index.add_argument("--check", action="store_true", help="сверить docs/atlas/INDEX.md с индексом (код 1 — отстал)")
    log = sub.add_parser("log", parents=[common], help="first-parent лог модуля по main-ref")
    log.add_argument("module")
    log.add_argument("-n", type=int, default=30)
    sub.add_parser("lint-result", help="проверить итог задачи по форме 0.7 (без git и базы)").add_argument("file")
    return top


def _default_main_ref(root: Path) -> str:
    return "main" if run_git(root, "rev-parse", "--verify", "-q", "main").returncode == 0 else "origin/main"


def _lint_result(file: str) -> int:
    """Строки `result_form.lint` и итог `lint-result: нарушений N`; нет файла или не читается -> 2."""
    try:
        text = Path(file).read_bytes().decode("utf-8-sig", "replace")  # байты как есть: CRLF разбирает парсер
    except OSError:
        print(f"lint-result: нет файла {file}", file=sys.stderr)
        return 2
    found = result_form.lint(text)
    print("\n".join([*(f"  {line}" for line in found), f"lint-result: нарушений {len(found)}"]))
    return 1 if found else 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    ref = getattr(args, "ref", None) or "HEAD"
    # верна ровно одна форма: --json без подкоманды либо подкоманда без --json; `check` не знает --ref
    both = getattr(args, "write", False) and getattr(args, "check", False)  # только у `index`
    if (
        args.json == (args.command is not None)
        or both
        or (args.command in ("check", "log", "lint-result") and hasattr(args, "ref"))
    ):
        parser.print_usage(sys.stderr)
        print(
            "atlas: нужна ровно одна форма: build, check, card, pack, log, ref, index, lint-result или --json",
            file=sys.stderr,
        )
        return 2
    if args.command == "lint-result":  # до корня репозитория: работает и вне git-репо
        return _lint_result(args.file)
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
        main_ref = getattr(args, "main_ref", None) or _default_main_ref(root)
        if args.command == "log":  # реестр не читает и не строит: соединения нет
            if args.n < 1:
                raise AtlasError("atlas: -n must be a positive integer")
            print("\n".join(views.log(root, main_ref, args.module, args.n)))
            return 0
        con = store.connect(root / "data" / "atlas.sqlite")
        try:
            if args.command == "check":
                code, lines = check(con, root, main_ref, args.base)
                print("\n".join(lines))
                return code
            if args.command in ("card", "pack"):
                lines = (
                    views.card(con, root, ref, main_ref, args.module)
                    if args.command == "card"
                    else views.pack(con, root, ref, main_ref, args.task, args.module)
                )
                print("\n".join(lines))
                return 0
            if args.command == "ref":
                print("\n".join(reference.ref(con, root, ref, main_ref, args.module, args.symbol)))
                return 0
            if args.command == "index":
                lines = reference.index(con, root, ref, main_ref)
                if args.write or args.check:
                    return reference.index_file(root, lines, args.write)
                print("\n".join(lines))
                return 0
            if args.command == "build":
                build_id = build(con, root, ref, main_ref)
                print(f"atlas build: {store.build_row(con, build_id)[0]} main_ref={main_ref} build_id={build_id}")
                return 0
            legacy = legacy_before(root, main_ref)  # только --json; build и check его не считают
            build_id = build(con, root, ref, main_ref)
            # живое значение описывает checkout: только для HEAD и только если в корне есть plans/
            is_head = resolve(root, ref) == resolve(root, "HEAD")
            live = live_plans(root) if is_head and (root / "plans").is_dir() else None
            print(to_json(con, build_id, legacy, live))
            return 0
        finally:
            con.close()
    except AtlasError as exc:
        print(exc, file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - любой сбой окружения -> 2, код 1 только у находки check
        print(f"atlas: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    try:
        # LF и UTF-8 и на Windows: без encoding вывод в канал идёт в cp1251, читатели UTF-8 получают мусор
        sys.stdout.reconfigure(newline="\n", encoding="utf-8")  # type: ignore[union-attr]
    except AttributeError:  # поток без reconfigure (подмена stdout)
        pass
    sys.exit(main())
