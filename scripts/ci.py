"""
CI-standalone проверка качества проекта.

Запускает все quality gates без LLM (Claude Code не нужен).
Для использования в GitHub Actions, GitLab CI, pre-push hooks.

Проверки:
1. Структурная валидация (validate.py)
2. Тесты фреймворка (run_framework_tests.py)
3. ADR sync дрифт (scripts/sync --check)
4. Архитектурные границы (sentrux check, если установлен)
5. Ruff lint (если установлен)

Запуск: python scripts/ci.py
Опции:
  --fast      Пропустить тесты (только структура + lint)
  --no-sentrux  Пропустить sentrux check
  --verbose   Подробный вывод

Exit codes: 0 = всё ок, 1 = есть ошибки, 2 = ошибка конфигурации
"""

import subprocess
import sys
import shutil
from pathlib import Path

BASE = Path(__file__).parent.parent


class CIRunner:
    """Запуск CI-проверок с аккумуляцией результатов."""

    def __init__(self, fast: bool = False, no_sentrux: bool = False, verbose: bool = False):
        self.fast = fast
        self.no_sentrux = no_sentrux
        self.verbose = verbose
        self.results: list[tuple[str, bool, str]] = []  # (название, passed, детали)

    def run_step(self, name: str, cmd: list[str], *, optional: bool = False) -> bool:
        """Запускает шаг и сохраняет результат."""
        print(f"\n{'─' * 60}")
        print(f"  {name}")
        print(f"{'─' * 60}")

        # Проверка наличия бинаря
        if not shutil.which(cmd[0]) and cmd[0] != sys.executable:
            if optional:
                detail = f"пропущен ({cmd[0]} не найден)"
                print(f"  [SKIP] {detail}")
                self.results.append((name, True, detail))
                return True
            else:
                detail = f"{cmd[0]} не найден"
                print(f"  [FAIL] {detail}")
                self.results.append((name, False, detail))
                return False

        try:
            result = subprocess.run(
                cmd,
                capture_output=not self.verbose,
                text=True,
                cwd=str(BASE),
                timeout=300,  # 5 мин макс на шаг
            )
        except subprocess.TimeoutExpired:
            detail = "timeout (300s)"
            print(f"  [FAIL] {detail}")
            self.results.append((name, False, detail))
            return False

        passed = result.returncode == 0

        if passed:
            print("  [OK]")
        else:
            print(f"  [FAIL] exit code {result.returncode}")
            if not self.verbose and result.stdout:
                # Показать последние 20 строк вывода
                lines = result.stdout.strip().splitlines()
                for line in lines[-20:]:
                    print(f"    {line}")
            if not self.verbose and result.stderr:
                for line in result.stderr.strip().splitlines()[-10:]:
                    print(f"    {line}")

        self.results.append((name, passed, "" if passed else f"exit {result.returncode}"))
        return passed

    def run_all(self) -> int:
        """Запускает все проверки и возвращает exit code."""
        print(f"\n{'=' * 60}")
        print("  CI QUALITY GATE — Inspector_bottles")
        print(f"{'=' * 60}")

        # 1. Структурная валидация
        self.run_step(
            "Структурная валидация",
            [sys.executable, "scripts/validate.py"],
        )

        # 2. Тесты фреймворка
        if not self.fast:
            self.run_step(
                "Тесты фреймворка",
                [sys.executable, "scripts/run_framework_tests.py"],
            )
        else:
            self.results.append(("Тесты фреймворка", True, "пропущен (--fast)"))

        # 3. ADR sync
        self.run_step(
            "ADR sync дрифт",
            [sys.executable, "-m", "scripts.sync", "--check"],
        )

        # 4. Sentrux check (архитектурные границы)
        if not self.no_sentrux:
            self.run_step(
                "Архитектурные границы (sentrux)",
                ["sentrux", "check", str(BASE)],
                optional=True,
            )
        else:
            self.results.append(("Архитектурные границы", True, "пропущен (--no-sentrux)"))

        # 5. Ruff lint
        self.run_step(
            "Ruff lint",
            [sys.executable, "-m", "ruff", "check", "multiprocess_framework/", "Services/"],
            optional=True,
        )

        # Итог
        print(f"\n{'=' * 60}")
        print("  ИТОГ")
        print(f"{'=' * 60}")

        failed = []
        for name, passed, detail in self.results:
            status = "OK" if passed else "FAIL"
            suffix = f" — {detail}" if detail else ""
            print(f"  [{status}] {name}{suffix}")
            if not passed:
                failed.append(name)

        total = len(self.results)
        passed_count = sum(1 for _, p, _ in self.results if p)

        print(f"\n  {passed_count}/{total} passed")

        if failed:
            print(f"  FAILED: {', '.join(failed)}")
            return 1
        else:
            print("  All checks passed!")
            return 0


def main() -> int:
    args = set(sys.argv[1:])

    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    runner = CIRunner(
        fast="--fast" in args,
        no_sentrux="--no-sentrux" in args,
        verbose="--verbose" in args or "-v" in args,
    )
    return runner.run_all()


if __name__ == "__main__":
    sys.exit(main())
