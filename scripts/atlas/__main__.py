"""CLI atlas: `build`, `check`, `card`, `pack`, `log`, `ref`, `index`, `lint-result`, `lint-brief`, `brief`, `metrics`,
`--json` (Tasks 1.2, 1.6, 1.6b, 1.9a, 1.9b, 1.9c, 1.9f, 4.2a).

Запуск: `python -m scripts.atlas`.

Purpose: разбор argv, проводка видов card/pack/log (views.py) и ref/index (reference.py);
    корень репозитория = git toplevel (не cwd),
    база `data/atlas.sqlite` в корне.
    Коды выхода: 0 — успех, 1 — check нашёл новую blocking-находку,
    1 — `index --check`: INDEX.md отстал, 1 — `lint-result`: итог не по форме 0.7, 1 — `brief --check`: блок FACTS
    отстал от своего маркера, 2 — ошибка окружения или ввода (у `brief` и `--write` вместе с `--check`, нет файла
    или маркеров, метка FACTS без маркеров, нет DESIGN, задача или символ не найдены), 1 — `lint-brief`: в брифе есть
    ошибка (предупреждения кода не меняют), 2 — `lint-brief`: нет файла, имя не по форме, файл вне репозитория.
    `metrics`: 0 — все ячейки посчитаны, 1 — есть `?` (нарушение формы отчёта или хеш DONE вне репозитория), 2 — нет
    плана или задачи, неверный spec, usage; читает рабочее дерево, реестр не строит.
    `lint-result <файл>` не знает git и базу: ветка стоит до определения корня репозитория.
    `ref <id>... --format passport|json` (Task 4.2a): паспорт символа (`passport.py`); без `--format` ровно один id и
    прежний вывод. Код 2 по вводу: без `--format` больше одного id, `--symbol` с `--format`, `--budget`/`--all`/
    `--full` без `--format`, `--format` не `passport`/`json`, `--all` не из списка; код 2 и у ошибочного id
    (`not found`, `ambiguous`) — остальные паспорта печатаются. `--root <путь>` — корень берётся от этого пути, не от
    cwd; `--exclude <путь>` (повторяемый) — префиксы, которые паспорт не читает.
Public API: main.
Stability: lite
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

if not __package__:  # запуск путём `python <repo>/scripts/atlas`: кодовый корень в sys.path (DESIGN 7), не --root
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.atlas import brief, lint_brief, metrics, passport, reference, result_form, store, views  # noqa: E402
from scripts.atlas.adapters.plans import live_plans  # noqa: E402
from scripts.atlas.build import build, to_json  # noqa: E402
from scripts.atlas.check import check, legacy_before  # noqa: E402
from scripts.atlas.tree import AtlasError, git, resolve, run_git  # noqa: E402

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
    ref = sub.add_parser(
        "ref", parents=[common, with_ref], help="справочник интерфейсов и кода модуля, паспорт символа"
    )
    ref.add_argument("module", nargs="+", metavar="id", help="модуль (или id символа с --format); id идут до опций")
    ref.add_argument("--symbol", default=None, help="сузить вывод до одного символа")
    ref.add_argument("--format", default=None, help="паспорт символа: passport (текст) или json; id можно несколько")
    ref.add_argument("--budget", type=int, default=None, help="строк на паспорт (по умолчанию 40); нужен --format")
    ref.add_argument(
        "--all", action="append", default=[], help="не резать раздел паспорта (повторяемый); нужен --format"
    )
    ref.add_argument("--full", action="store_true", help="паспорт без среза; нужен --format")
    ref.add_argument("--root", default=None, help="корень репозитория берётся от этого пути (по умолчанию cwd)")
    ref.add_argument("--exclude", action="append", default=[], help="префикс пути, который паспорт не читает")
    index = sub.add_parser("index", parents=[common, with_ref], help="индекс проекта (docs/atlas/INDEX.md)")
    index.add_argument("--write", action="store_true", help="записать docs/atlas/INDEX.md")
    index.add_argument("--check", action="store_true", help="сверить docs/atlas/INDEX.md с индексом (код 1 — отстал)")
    log = sub.add_parser("log", parents=[common], help="first-parent лог модуля по main-ref")
    log.add_argument("module")
    log.add_argument("-n", type=int, default=30)
    blk = sub.add_parser("brief", parents=[common, with_ref], help="блок FACTS брифа задачи <slug>#<id>")
    blk.add_argument("task")
    blk.add_argument("--module", action="append", default=[], help="модуль задачи (повторяемый)")
    blk.add_argument("--symbol", default=None, help="объект задачи (по умолчанию из текста задачи)")
    blk.add_argument("--write", action="store_true", help="записать блок в tasks/<id>.md плана")
    blk.add_argument("--check", action="store_true", help="сверить рабочее дерево с маркером (код 1 — отстал)")
    sub.add_parser("lint-result", help="проверить итог задачи по форме 0.7 (без git и базы)").add_argument("file")
    lb = sub.add_parser("lint-brief", help="проверить бриф tasks/<id>[.<роль>].md (форма, повтор команд, REDS)")
    lb.add_argument("file")
    lb.add_argument("--no-replay", action="store_true", help="не запускать команды строк факта и сбор тестов")
    lb.add_argument("--no-fresh", action="store_true", help="не сверять FACTS со свежестью маркера")
    mt = sub.add_parser("metrics", help="таблица M1-M4 по брифам плана: <spec>... [--base <spec>]...")
    mt.add_argument("specs", nargs="*", help="<slug> (все задачи плана) или <slug>#<id>")
    mt.add_argument("--base", action="append", default=[], help="колонка-основа для сравнения (повторяемый)")
    return top


def _default_main_ref(root: Path) -> str:
    return "main" if run_git(root, "rev-parse", "--verify", "-q", "main").returncode == 0 else "origin/main"


_FORMATS = ("passport", "json")


def _ref_usage_error(args: argparse.Namespace) -> str | None:
    """Текст ошибки ввода подкоманды `ref` (код 2) или None; тексты постоянные, значения флагов в них не входят."""
    if args.format is None:
        if len(args.module) > 1:
            return "atlas ref: без --format нужен ровно один id"
        if args.budget is not None or args.all or args.full:
            return "atlas ref: --budget, --all и --full требуют --format"
        return None
    if args.format not in _FORMATS:
        return "atlas ref: --format принимает passport или json"
    if args.symbol is not None:
        return "atlas ref: --symbol несовместим с --format"
    if any(name not in passport.SHOW_ALL_SECTIONS for name in args.all):
        return "atlas ref: --all принимает used_by, call_sites, subclasses, structural, tests"
    return None


def _ref_passport(root: Path, ref: str, args: argparse.Namespace) -> int:
    """`ref <id>... --format`: паспорта в порядке id; ошибочный id -> строка в stderr и код 2, остальные печатаются."""
    records = passport.passports_for(root, ref, list(args.module), exclude=tuple(args.exclude))
    failed = False
    for number, record in enumerate(records, 1):
        if "error" in record:
            failed = True
            print(f"atlas ref: id {number}: {record['error']}", file=sys.stderr)
    if args.format == "json":
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 2 if failed else 0
    budget = 40 if args.budget is None else args.budget
    blocks = []
    for record in records:
        if "error" in record:
            blocks.append("\n".join([f"== {record['id']} ==", record["error"], *record.get("candidates", [])]))
        else:
            blocks.append(passport.render_text(record, budget=budget, show_all=frozenset(args.all), full=args.full))
    print("\n\n".join(blocks))
    return 2 if failed else 0


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
    both = getattr(args, "write", False) and getattr(args, "check", False)  # только у `index` и `brief`
    if (
        args.json == (args.command is not None)
        or both
        or (args.command in ("check", "log", "lint-result", "lint-brief", "metrics") and hasattr(args, "ref"))
    ):
        parser.print_usage(sys.stderr)
        print(
            "atlas: нужна ровно одна форма: build, check, card, pack, log, ref, index, lint-result, lint-brief, "
            "brief, metrics или --json",
            file=sys.stderr,
        )
        return 2
    if args.command == "metrics" and not (args.specs or args.base):
        parser.print_usage(sys.stderr)
        print("atlas metrics: нужен хотя бы один <spec> или --base <spec>", file=sys.stderr)
        return 2
    if args.command == "lint-result":  # до корня репозитория: работает и вне git-репо
        return _lint_result(args.file)
    if args.command == "ref" and (usage_error := _ref_usage_error(args)) is not None:  # до git: ввод не зависит от репо
        parser.print_usage(sys.stderr)
        print(usage_error, file=sys.stderr)
        return 2
    try:
        start = Path(args.root) if args.command == "ref" and args.root is not None else Path.cwd()
        root = Path(git(start, "rev-parse", "--show-toplevel"))
        main_ref = getattr(args, "main_ref", None) or _default_main_ref(root)
        if args.command == "lint-brief":  # реестр не читает и не строит: соединения нет
            code, lines = lint_brief.run(root, args.file, replay=not args.no_replay, fresh=not args.no_fresh)
            print("\n".join(lines))
            return code
        if args.command == "metrics":  # реестр не читает и не строит: соединения нет
            code, lines = metrics.run(root, args.specs, args.base)
            print("\n".join(lines))
            return code
        if args.command == "log":  # реестр не читает и не строит: соединения нет
            if args.n < 1:
                raise AtlasError("atlas: -n must be a positive integer")
            print("\n".join(views.log(root, main_ref, args.module, args.n)))
            return 0
        if args.command == "brief" and args.check:  # без сборки и SQLite
            code, lines = brief.check(root, brief.task_file(root, args.task))
            print("\n".join(lines))
            return code
        if args.command == "ref" and args.format is not None:  # паспорт читает ревизию, соединения нет
            return _ref_passport(root, ref, args)
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
                print("\n".join(reference.ref(con, root, ref, main_ref, args.module[0], args.symbol)))
                return 0
            if args.command == "brief":
                path = brief.task_file(root, args.task) if args.write else None  # плохой путь — до сборки
                block = brief.brief(con, root, ref, main_ref, args.task, args.module, args.symbol, "main_ref" in args)
                print(brief.write(root, path, block) if path else "\n".join(block))
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
