# ruff: noqa
"""Снимок движка записи рецепта на заданном коммите — пакет `oldrecipe` для проб «до/после» (Task 1.1i, §12.9).

Использование: python make_oldpkg.py <sha> <out_dir>
Создаёт <out_dir>/oldrecipe/ с пустым __init__.py и файлами движка из `git show <sha>:<путь>`;
дальше: sys.path.insert(0, <out_dir>); import oldrecipe.yaml_io as OLD.
"""

import subprocess  # nosec B404 — проба лида: только `git show` с аргументами-литералами
import sys
from pathlib import Path

FILES = ("yaml_io.py", "_ruamel_doc.py", "service.py", "file_lock.py", "format.py")
SRC = "multiprocess_framework/modules/recipe/"


def main(sha: str, out_dir: str) -> None:
    pkg = Path(out_dir) / "oldrecipe"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for name in FILES:
        cmd = ["git", "show", f"{sha}:{SRC}{name}"]
        data = subprocess.run(cmd, check=True, capture_output=True).stdout  # nosec B603 B607 — git из PATH, без shell
        (pkg / name).write_bytes(data)
    print(pkg)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
