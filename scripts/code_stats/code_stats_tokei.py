"""
Обёртка над tokei с тем же TOML-конфигом, что у code_stats.py.

Зачем: точный подсчёт LOC через настоящие токенайзеры (без regex-эвристики
для docstring/комментариев). Фильтры (расширения, исключения, формат вывода)
берутся из code_stats.toml — конфиг общий.

Зависимости: бинарь `tokei` (brew install tokei / cargo install tokei).
Если не установлен — exit 3 с подсказкой.

Запуск:
    python scripts/code_stats/code_stats_tokei.py
    python scripts/code_stats/code_stats_tokei.py --root multiprocess_framework --format json
    python scripts/code_stats/code_stats_tokei.py --config scripts/code_stats/code_stats.toml
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Переиспользуем парсер конфига и форматтеры из соседнего модуля.
sys.path.insert(0, str(Path(__file__).parent))
from code_stats import (  # type: ignore[import-not-found]
    Config,
    GroupRow,
    DEFAULT_CONFIG_PATH,
    apply_overrides,
    build_parser as build_base_parser,
    load_config,
    render,
)


# Расширение → имя языка в tokei (полный список: `tokei --languages`).
# Не претендует на полноту — расширяй по мере необходимости.
EXT_TO_LANG: dict[str, str] = {
    ".py": "Python",
    ".md": "Markdown",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".sh": "Shell",
    ".bash": "BASH",
    ".zsh": "Zsh",
    ".rs": "Rust",
    ".go": "Go",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TSX",
    ".jsx": "JSX",
    ".c": "C",
    ".h": "C Header",
    ".cpp": "C++",
    ".hpp": "C++ Header",
    ".java": "Java",
    ".rb": "Ruby",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "Sass",
    ".xml": "XML",
}


def ensure_tokei() -> str:
    path = shutil.which("tokei")
    if path:
        return path
    print(
        "error: tokei not found in PATH.\n"
        "  macOS:  brew install tokei\n"
        "  Linux:  cargo install tokei  (или пакетный менеджер дистрибутива)\n"
        "  Windows: scoop install tokei\n"
        "Альтернатива без установки: python scripts/code_stats/code_stats.py",
        file=sys.stderr,
    )
    raise SystemExit(3)


def build_tokei_argv(tokei: str, cfg: Config) -> list[str]:
    argv = [tokei, "--output", "json", str(cfg.scan.root.resolve())]

    # --types фильтр (tokei v12+ принимает --types, v11 — --type).
    # Используем длинную форму --types, она поддержана начиная с v12.
    types: list[str] = []
    for ext in sorted(cfg.formats.include):
        lang = EXT_TO_LANG.get(ext.lower())
        if lang and lang not in types:
            types.append(lang)
    if types:
        argv += ["--types", ",".join(types)]

    # Исключения: dirs + file_patterns + path_patterns — все идут через --exclude.
    excludes: list[str] = []
    excludes.extend(cfg.exclude.dirs)
    excludes.extend(cfg.exclude.file_patterns)
    excludes.extend(cfg.exclude.path_patterns)
    for pat in excludes:
        argv += ["--exclude", pat]

    if not cfg.scan.follow_symlinks:
        # tokei по умолчанию symlinks не следует — флага не нужен.
        pass

    return argv


def run_tokei(tokei: str, cfg: Config) -> dict:
    argv = build_tokei_argv(tokei, cfg)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"error: tokei exited {e.returncode}\nstderr:\n{e.stderr}", file=sys.stderr)
        raise SystemExit(e.returncode)
    return json.loads(proc.stdout)


def tokei_to_rows(payload: dict, cfg: Config) -> list[GroupRow]:
    """Конвертирует JSON tokei в GroupRow-ы, совместимые с render() из code_stats."""
    rows: list[GroupRow] = []
    # tokei v12+ кладёт языки на верхний уровень, ключ "Total" — сумма (её игнорим — мы строим свою).
    for lang, data in payload.items():
        if lang == "Total" or not isinstance(data, dict):
            continue
        code = int(data.get("code", 0))
        comments = int(data.get("comments", 0))
        blanks = int(data.get("blanks", 0))
        reports = data.get("reports") or []
        files = len(reports) if reports else int(data.get("inaccurate", 0)) and 0
        if not files:
            # fallback: посчитать reports или взять nFiles если он есть
            files = len(reports)
        # chars tokei не выдаёт — оставляем 0; колонка будет нулевой в этом режиме.
        rows.append(
            GroupRow(
                key=lang,
                files=files,
                lines_total=code + comments + blanks,
                lines_code=code,
                lines_blank=blanks,
                lines_comment=comments,
                lines_docstring=0,  # tokei относит docstring к comments
                chars=0,
            )
        )

    sort_key = {
        "lines": lambda r: r.lines_code,
        "chars": lambda r: r.chars,
        "files": lambda r: r.files,
        "name": lambda r: r.key,
    }.get(cfg.output.sort_by, lambda r: r.lines_code)
    rows.sort(key=sort_key, reverse=(cfg.output.sort_order != "asc"))

    if cfg.output.limit > 0:
        rows = rows[: cfg.output.limit]
    return rows


def main(argv: list[str] | None = None) -> int:
    # Используем тот же парсер, что у code_stats — но --group-by directory здесь
    # неприменим: tokei группирует по языкам, без файлового детализатора.
    parser = build_base_parser()
    parser.prog = "code_stats_tokei"
    parser.description = (
        "Подсчёт LOC через tokei (точные токенайзеры). "
        "Общий TOML с code_stats; --group-by игнорируется (всегда language)."
    )
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config or DEFAULT_CONFIG_PATH)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    cfg = apply_overrides(cfg, args)

    tokei = ensure_tokei()
    payload = run_tokei(tokei, cfg)
    rows = tokei_to_rows(payload, cfg)
    sys.stdout.write(render(rows, cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
