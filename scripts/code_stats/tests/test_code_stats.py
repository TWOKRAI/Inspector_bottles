"""Тесты для CLI scripts/code_stats/code_stats.py — ПО КРИТЕРИЯМ ПРИЁМКИ.

Правило проекта «три роли авторства тестов» (см. .claude/CLAUDE.md): тестер пишет
тесты по контракту (README.md + code_stats.toml + docstring модуля + `main(argv) -> int`),
НЕ читая тело функций реализации и НЕ подгоняя ожидания под неё.

Публичный контракт, зафиксированный README.md / code_stats.toml:
1. Выбор папок: позиционные аргументы | `[scan] paths` из TOML | `--root` (синоним
   одиночного пути) | пересекающиеся пути не дают двойного учёта | несуществующая
   папка -> ненулевой код возврата, сообщение в stderr, без traceback.
2. Колонки отчёта в порядке:
   group, files, dirs, lines, code, blank, comment, docstr, words, chars.
   `words` — семантика `wc -w`. `dirs` — число УНИКАЛЬНЫХ директорий с учтёнными
   файлами (в TOTAL объединяются, не суммируются по группам).
3. TOTAL считается по ВСЕМ группам даже при `--limit`; `--no-total` скрывает строку.
4. Группировка: extension | directory (с `--dir-depth`) | none.
5. Форматы table | json | csv — во всех есть `dirs` и `words`.
6. `git_tracked`: в git-репозитории считаются tracked + untracked-не-ignored;
   вне репозитория (или если git недоступен) — fallback на обход ФС + warning
   в stderr, без падения; `--no-git-tracked` считает всё, включая игнорируемое.
7. Исключения `[exclude]` (dirs / file_patterns) работают в ОБОИХ режимах обхода.

Все тесты детерминированы, работают на tmp_path со своим TOML-конфигом (кроме
одного smoke-теста на реальном корне проекта).
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.code_stats import code_stats

# Корень репозитория: tests -> code_stats -> scripts -> repo_root
REPO_ROOT = Path(__file__).parent.parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "code_stats" / "code_stats.py"

REPORT_COLUMNS = [
    "group",
    "files",
    "dirs",
    "lines",
    "code",
    "blank",
    "comment",
    "docstr",
    "words",
    "chars",
]


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def write_config(
    tmp_path: Path,
    *,
    paths: list[str] | None = None,
    recursive: bool = True,
    follow_symlinks: bool = False,
    git_tracked: bool = False,
    include: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
    file_patterns: list[str] | None = None,
    path_patterns: list[str] | None = None,
    blank_lines: bool = False,
    comments: bool = True,
    docstrings: bool = True,
    chars: bool = True,
    words: bool = True,
    encoding: str = "utf-8",
    fmt: str = "json",
    group_by: str = "extension",
    sort_by: str = "lines",
    sort_order: str = "desc",
    show_total: bool = True,
    limit: int = 0,
    dir_depth: int = 0,
    name: str = "cfg.toml",
) -> Path:
    """Пишет полный TOML-конфиг (все секции явно) и возвращает путь к файлу.

    Все секции указываются явно, чтобы не зависеть от того, что код_stats.py
    делает при отсутствующей секции (это деталь реализации, не контракт).
    """
    paths = paths if paths is not None else ["."]
    include = include if include is not None else []
    exclude_dirs = exclude_dirs if exclude_dirs is not None else []
    file_patterns = file_patterns if file_patterns is not None else []
    path_patterns = path_patterns if path_patterns is not None else []

    def _toml_list(items: list[str]) -> str:
        return "[" + ", ".join(json.dumps(i) for i in items) + "]"

    text = f"""
[scan]
paths = {_toml_list(paths)}
recursive = {str(recursive).lower()}
follow_symlinks = {str(follow_symlinks).lower()}
git_tracked = {str(git_tracked).lower()}

[formats]
include = {_toml_list(include)}

[exclude]
dirs = {_toml_list(exclude_dirs)}
file_patterns = {_toml_list(file_patterns)}
path_patterns = {_toml_list(path_patterns)}

[count]
blank_lines = {str(blank_lines).lower()}
comments = {str(comments).lower()}
docstrings = {str(docstrings).lower()}
chars = {str(chars).lower()}
words = {str(words).lower()}
encoding = {json.dumps(encoding)}

[output]
format = {json.dumps(fmt)}
group_by = {json.dumps(group_by)}
sort_by = {json.dumps(sort_by)}
sort_order = {json.dumps(sort_order)}
show_total = {str(show_total).lower()}
limit = {limit}
dir_depth = {dir_depth}
"""
    # Конфиг кладём В СОСЕДНЮЮ папку, а не внутрь сканируемой: иначе он сам
    # попадает в счёт (include = [] означает «все файлы») и каждое ожидание
    # «здесь 2 файла» тихо превращается в 3. Артефакт окружения теста, а не
    # поведение утилиты.
    cfg_dir = tmp_path.parent / f"{tmp_path.name}__cfg"
    cfg_dir.mkdir(exist_ok=True)
    cfg_path = cfg_dir / name
    cfg_path.write_text(text, encoding="utf-8")
    return cfg_path


def run_main(argv: list[str]) -> int:
    """Вызывает main() напрямую (in-process) — быстрый путь для большинства тестов."""
    return code_stats.main(argv)


def run_json(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    """Запускает main() и парсит stdout как JSON."""
    rc, data, _ = run_json_err(argv, capsys)
    return rc, data


def run_json_err(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict, str]:
    """
    То же, плюс stderr.

    Отдельный helper нужен потому, что `capsys.readouterr()` ОПУСТОШАЕТ буфер:
    повторный вызов в теле теста вернёт пустую строку и проверка предупреждения
    пройдёт вхолостую независимо от того, было оно или нет.
    """
    rc = run_main(argv)
    captured = capsys.readouterr()
    return rc, json.loads(captured.out), captured.err


# ---------------------------------------------------------------------------
# 1. Выбор папок
# ---------------------------------------------------------------------------


def test_positional_paths_count_both_dirs(tmp_path: Path, capsys):
    """Позиционные аргументы main(["dirA", "dirB"]) считают файлы из ОБЕИХ папок."""
    (tmp_path / "dirA").mkdir()
    (tmp_path / "dirA" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "dirB").mkdir()
    (tmp_path / "dirB" / "b.py").write_text("y = 2\n", encoding="utf-8")

    cfg = write_config(tmp_path, group_by="none")
    rc, data = run_json(["--config", str(cfg), str(tmp_path / "dirA"), str(tmp_path / "dirB")], capsys)

    assert rc == 0
    assert data["total"]["files"] == 2


def test_no_positional_args_uses_toml_scan_paths(tmp_path: Path, capsys, monkeypatch):
    """Без позиционных аргументов main([]) берёт `[scan] paths` из TOML."""
    target = tmp_path / "from_toml"
    target.mkdir()
    (target / "only.py").write_text("z = 3\n", encoding="utf-8")
    # посторонняя папка, которую НЕ должно быть в paths конфига
    other = tmp_path / "not_scanned"
    other.mkdir()
    (other / "ignore_me.py").write_text("w = 4\n" * 5, encoding="utf-8")

    cfg = write_config(tmp_path, paths=["from_toml"], group_by="none")
    monkeypatch.chdir(tmp_path)

    rc, data = run_json(["--config", str(cfg)], capsys)

    assert rc == 0
    assert data["total"]["files"] == 1
    assert data["rows"][0]["group"] == "only.py"


def test_root_flag_is_alias_for_single_path(tmp_path: Path, capsys):
    """`--root X` — синоним одиночного пути (обратная совместимость с позиционным)."""
    (tmp_path / "solo").mkdir()
    (tmp_path / "solo" / "f.py").write_text("a = 1\n", encoding="utf-8")

    cfg = write_config(tmp_path, group_by="none")
    rc, data = run_json(["--config", str(cfg), "--root", str(tmp_path / "solo")], capsys)

    assert rc == 0
    assert data["total"]["files"] == 1
    assert data["rows"][0]["group"] == "f.py"


def test_overlapping_paths_do_not_double_count(tmp_path: Path, capsys):
    """Пересекающиеся пути (`.` и `./sub`) не дают двойного учёта общего файла."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "top.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "sub" / "s.py").write_text("b = 2\n", encoding="utf-8")

    cfg = write_config(tmp_path, group_by="none")
    rc, data = run_json(["--config", str(cfg), str(tmp_path), str(tmp_path / "sub")], capsys)

    assert rc == 0
    # Без объединения было бы 2 (top+sub) + 2 (top+sub из sub) - 1 = 3 файла корректно,
    # но s.py учтён бы дважды если пути не пересекаются -> проверяем итог напрямую.
    assert data["total"]["files"] == 2
    groups = sorted(row["group"].replace("\\", "/") for row in data["rows"])
    assert groups == ["sub/s.py", "top.py"]


def test_nonexistent_dir_returns_nonzero_without_traceback(tmp_path: Path, capsys):
    """Несуществующая папка -> ненулевой код возврата, сообщение в stderr, без traceback."""
    missing = tmp_path / "does_not_exist_xyz"
    cfg = write_config(tmp_path)

    rc = run_main(["--config", str(cfg), str(missing)])
    captured = capsys.readouterr()

    assert rc != 0
    assert captured.err.strip() != ""
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


# ---------------------------------------------------------------------------
# 2. Колонки отчёта
# ---------------------------------------------------------------------------


def test_json_columns_in_expected_order(tmp_path: Path, capsys):
    """JSON: каждая строка содержит колонки в порядке group,files,dirs,lines,code,blank,comment,docstr,words,chars."""
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    cfg = write_config(tmp_path, group_by="extension", fmt="json")

    rc, data = run_json(["--config", str(cfg), str(tmp_path)], capsys)

    assert rc == 0
    assert list(data["rows"][0].keys()) == REPORT_COLUMNS
    assert list(data["total"].keys()) == REPORT_COLUMNS


def test_csv_columns_in_expected_order(tmp_path: Path, capsys):
    """CSV: заголовок содержит колонки в порядке group,files,dirs,lines,code,blank,comment,docstr,words,chars."""
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    cfg = write_config(tmp_path, group_by="extension", fmt="csv")

    rc = run_main(["--config", str(cfg), str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    reader = csv.reader(io.StringIO(out))
    header = next(reader)
    assert header == REPORT_COLUMNS


def test_table_header_contains_expected_columns(tmp_path: Path, capsys):
    """Table: строка заголовка содержит все колонки контракта в правильном порядке."""
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    cfg = write_config(tmp_path, group_by="extension", fmt="table")

    rc = run_main(["--config", str(cfg), str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    header_line = out.splitlines()[0]
    tokens = header_line.split()
    assert tokens == REPORT_COLUMNS


def test_words_counts_like_wc_w_with_cyrillic_and_extra_whitespace(tmp_path: Path, capsys):
    """`words` — семантика wc -w (последовательности непробельных символов), включая кириллицу."""
    content = "Привет   мир\nfoo\tbar  \n\nbaz\n"
    expected_words = len(content.split())  # эталон "как wc -w"
    (tmp_path / "words.py").write_text(content, encoding="utf-8")

    cfg = write_config(tmp_path, group_by="none")
    rc, data = run_json(["--config", str(cfg), str(tmp_path)], capsys)

    assert rc == 0
    row = next(r for r in data["rows"] if r["group"] == "words.py")
    assert row["words"] == expected_words


def test_dirs_counts_unique_directories_not_summed_across_groups(tmp_path: Path, capsys):
    """TOTAL.dirs — число УНИКАЛЬНЫХ директорий, а не сумма dirs по группам.

    Один и тот же каталог содержит .py и .md — при group_by=extension получится
    две группы (каждая с dirs=1), но TOTAL.dirs должен остаться 1, а не стать 2.
    """
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# hi\n", encoding="utf-8")

    cfg = write_config(tmp_path, group_by="extension")
    rc, data = run_json(["--config", str(cfg), str(tmp_path)], capsys)

    assert rc == 0
    assert len(data["rows"]) == 2
    assert all(r["dirs"] == 1 for r in data["rows"])
    assert data["total"]["dirs"] == 1


def test_files_column_counts_number_of_files(tmp_path: Path, capsys):
    """`files` — количество учтённых файлов в группе / TOTAL."""
    for i in range(3):
        (tmp_path / f"f{i}.py").write_text("x = 1\n", encoding="utf-8")

    cfg = write_config(tmp_path, group_by="extension")
    rc, data = run_json(["--config", str(cfg), str(tmp_path)], capsys)

    assert rc == 0
    assert data["rows"][0]["files"] == 3
    assert data["total"]["files"] == 3


# ---------------------------------------------------------------------------
# 3. TOTAL
# ---------------------------------------------------------------------------


def test_total_sums_all_groups_even_when_limited(tmp_path: Path, capsys):
    """TOTAL считается по ВСЕМ группам, даже когда вывод обрезан --limit."""
    extensions = {
        "a.py": "x = 1\n",
        "b.md": "# md\n",
        "c.toml": "k = 1\n",
        "d.yaml": "k: 1\n",
        "e.sh": "echo hi\n",
    }
    for name, content in extensions.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    cfg_full = write_config(tmp_path, group_by="extension", limit=0)
    rc_full, data_full = run_json(["--config", str(cfg_full), str(tmp_path)], capsys)
    assert rc_full == 0
    assert len(data_full["rows"]) == 5

    cfg_limited = write_config(tmp_path, group_by="extension", limit=2, name="cfg_limited.toml")
    rc_limited, data_limited = run_json(["--config", str(cfg_limited), str(tmp_path)], capsys)
    assert rc_limited == 0
    assert len(data_limited["rows"]) == 2

    # TOTAL не должен усечься вместе со списком видимых строк.
    assert data_limited["total"]["files"] == data_full["total"]["files"] == 5
    assert data_limited["total"]["lines"] == data_full["total"]["lines"]


def test_no_total_hides_total_row_json(tmp_path: Path, capsys):
    """--no-total скрывает итоговую строку (JSON: ключ "total" отсутствует)."""
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    cfg = write_config(tmp_path, group_by="extension", show_total=True)

    rc, data = run_json(["--config", str(cfg), str(tmp_path), "--no-total"], capsys)

    assert rc == 0
    assert "total" not in data or data.get("total") is None


def test_no_total_hides_total_row_table(tmp_path: Path, capsys):
    """--no-total скрывает итоговую строку (table: строки "TOTAL" нет в выводе)."""
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    cfg = write_config(tmp_path, group_by="extension", fmt="table", show_total=True)

    rc = run_main(["--config", str(cfg), str(tmp_path), "--no-total"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "TOTAL" not in out


# ---------------------------------------------------------------------------
# 4. Группировка
# ---------------------------------------------------------------------------


def test_group_by_extension(tmp_path: Path, capsys):
    """--group-by extension группирует строки отчёта по расширению файла."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("# hi\n", encoding="utf-8")

    cfg = write_config(tmp_path, group_by="extension")
    rc, data = run_json(["--config", str(cfg), str(tmp_path)], capsys)

    assert rc == 0
    groups = {r["group"]: r["files"] for r in data["rows"]}
    assert groups[".py"] == 2
    assert groups[".md"] == 1


def test_group_by_directory_dir_depth_1_collapses_to_top_segment(tmp_path: Path, capsys):
    """--group-by directory --dir-depth 1 схлопывает путь до верхнего сегмента (a/b/c -> a)."""
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    (nested / "deep.py").write_text("x = 1\n", encoding="utf-8")

    cfg = write_config(tmp_path, group_by="directory", dir_depth=1)
    rc, data = run_json(["--config", str(cfg), str(tmp_path)], capsys)

    assert rc == 0
    groups = [r["group"].replace("\\", "/") for r in data["rows"]]
    assert "a" in groups
    assert "a/b/c" not in groups


def test_group_by_directory_dir_depth_0_keeps_full_path(tmp_path: Path, capsys):
    """--group-by directory --dir-depth 0 группирует по полному относительному пути директории."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "deep.py").write_text("x = 1\n", encoding="utf-8")

    cfg = write_config(tmp_path, group_by="directory", dir_depth=0)
    rc, data = run_json(["--config", str(cfg), str(tmp_path)], capsys)

    assert rc == 0
    groups = [r["group"].replace("\\", "/") for r in data["rows"]]
    assert "a/b" in groups


def test_group_by_none_gives_one_row_per_file(tmp_path: Path, capsys):
    """--group-by none выдаёт одну строку отчёта на файл."""
    for i in range(3):
        (tmp_path / f"f{i}.py").write_text("x = 1\n", encoding="utf-8")

    cfg = write_config(tmp_path, group_by="none")
    rc, data = run_json(["--config", str(cfg), str(tmp_path)], capsys)

    assert rc == 0
    assert len(data["rows"]) == 3
    assert all(r["files"] == 1 for r in data["rows"])


# ---------------------------------------------------------------------------
# 5. Форматы вывода
# ---------------------------------------------------------------------------


def test_json_output_is_valid_and_has_new_columns(tmp_path: Path, capsys):
    """--format json парсится json.loads и содержит колонки dirs и words."""
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    cfg = write_config(tmp_path, fmt="json")

    rc, data = run_json(["--config", str(cfg), str(tmp_path)], capsys)

    assert rc == 0
    assert "dirs" in data["rows"][0]
    assert "words" in data["rows"][0]


def test_csv_output_is_valid_and_has_new_columns(tmp_path: Path, capsys):
    """--format csv парсится csv.reader и содержит колонки dirs и words."""
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    cfg = write_config(tmp_path, fmt="csv")

    rc = run_main(["--config", str(cfg), str(tmp_path)])
    out = capsys.readouterr().out

    reader = csv.reader(io.StringIO(out))
    header = next(reader)

    assert rc == 0
    assert "dirs" in header
    assert "words" in header


def test_table_output_has_new_columns(tmp_path: Path, capsys):
    """--format table содержит колонки dirs и words в заголовке."""
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    cfg = write_config(tmp_path, fmt="table")

    rc = run_main(["--config", str(cfg), str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    header_line = out.splitlines()[0]
    assert "dirs" in header_line.split()
    assert "words" in header_line.split()


# ---------------------------------------------------------------------------
# 6. Режим git (git_tracked)
# ---------------------------------------------------------------------------


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=repo, check=True)


def test_git_tracked_excludes_gitignored_file(tmp_path: Path, capsys):
    """В git-репозитории с git_tracked=true файл под .gitignore НЕ попадает в счёт."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    (repo / "tracked.py").write_text("a = 1\n", encoding="utf-8")
    (repo / "ignored.py").write_text("b = 2\n", encoding="utf-8")
    (repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    cfg = write_config(repo, git_tracked=True, exclude_dirs=[".git"], group_by="none", name="cfg.toml")
    rc, data = run_json(["--config", str(cfg), str(repo)], capsys)

    assert rc == 0
    groups = {r["group"] for r in data["rows"]}
    assert "ignored.py" not in groups
    assert "tracked.py" in groups


def test_git_tracked_includes_tracked_and_untracked_nonignored(tmp_path: Path, capsys):
    """git_tracked=true считает tracked-файлы И untracked-не-ignored-файлы."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    (repo / "tracked.py").write_text("a = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    (repo / "untracked_not_ignored.py").write_text("b = 2\n", encoding="utf-8")

    cfg = write_config(repo, git_tracked=True, exclude_dirs=[".git"], group_by="none")
    rc, data = run_json(["--config", str(cfg), str(repo)], capsys)

    assert rc == 0
    groups = {r["group"] for r in data["rows"]}
    assert "tracked.py" in groups
    assert "untracked_not_ignored.py" in groups


def test_no_git_tracked_flag_counts_ignored_files_too(tmp_path: Path, capsys):
    """--no-git-tracked считает всё, включая файлы, попавшие под .gitignore."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    (repo / "tracked.py").write_text("a = 1\n", encoding="utf-8")
    (repo / "ignored.py").write_text("b = 2\n", encoding="utf-8")
    (repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    cfg = write_config(repo, git_tracked=True, exclude_dirs=[".git"], group_by="none")
    rc, data = run_json(["--config", str(cfg), str(repo), "--no-git-tracked"], capsys)

    assert rc == 0
    groups = {r["group"] for r in data["rows"]}
    assert "ignored.py" in groups
    assert "tracked.py" in groups


def test_outside_git_repo_falls_back_to_fs_walk_with_warning(tmp_path: Path, capsys, monkeypatch):
    """Вне git-репозитория git_tracked=true не падает: fallback на обход ФС + warning в stderr.

    GIT_CEILING_DIRECTORIES обязателен: без него git может найти произвольный
    объемлющий репозиторий выше по дереву (например, домашний каталог пользователя)
    и тест перестанет проверять сценарий "вне репозитория".
    """
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "f.py").write_text("a = 1\n", encoding="utf-8")

    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))

    cfg = write_config(plain, git_tracked=True, exclude_dirs=[".git"], group_by="none")
    rc, data, stderr = run_json_err(["--config", str(cfg), str(plain)], capsys)

    assert rc == 0
    assert data["total"]["files"] == 1  # f.py, посчитан обходом ФС
    assert stderr.strip() != ""
    assert "Traceback" not in stderr


def test_exclude_dirs_applied_in_fs_walk_mode(tmp_path: Path, capsys):
    """[exclude] dirs работает при обходе ФС (git_tracked=false): __pycache__ не попадает в счёт."""
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "real.py").write_text("y = 2\n", encoding="utf-8")

    cfg = write_config(tmp_path, git_tracked=False, exclude_dirs=["__pycache__"], group_by="none")
    rc, data = run_json(["--config", str(cfg), str(tmp_path)], capsys)

    assert rc == 0
    groups = {r["group"] for r in data["rows"]}
    assert "real.py" in groups
    assert not any("__pycache__" in g for g in groups)


def test_exclude_dirs_applied_in_git_tracked_mode(tmp_path: Path, capsys):
    """[exclude] dirs работает и при git_tracked=true, даже если git знает про файл."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "cached.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "real.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    cfg = write_config(repo, git_tracked=True, exclude_dirs=["__pycache__", ".git"], group_by="none")
    rc, data = run_json(["--config", str(cfg), str(repo)], capsys)

    assert rc == 0
    groups = {r["group"] for r in data["rows"]}
    assert "real.py" in groups
    assert not any("__pycache__" in g for g in groups)


# ---------------------------------------------------------------------------
# Smoke: реальный корень проекта
# ---------------------------------------------------------------------------


def test_smoke_run_on_project_root_returns_zero():
    """Запуск на корне проекта с дефолтным конфигом возвращает код 0 (без падения)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )

    assert result.returncode == 0, f"Ожидался exit code 0, получен {result.returncode}\nstderr: {result.stderr}"
