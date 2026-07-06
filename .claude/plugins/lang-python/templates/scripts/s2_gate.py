"""s2_gate.py — deterministic contract-complete checker for the S2 pipeline stage.

Parses an ``interface.py`` (the Protocol/ABC public surface of a module) and
verifies that every public function/method declares both ``Pre:`` and ``Post:``
in its docstring. This closes the structural gap left by the advisory
``module-contract`` skill: a contract that compiles but omits its pre/postconditions.

Pre: interface_path exists and contains valid Python source
Post: exit 0 iff every public function (name not starting with ``_``) carries both
      ``Pre:`` and ``Post:`` substrings in its docstring; exit 1 otherwise, listing
      each offender on the ``Reason:`` line
Stability: lite

NOTE: This is a deterministic parser. LLM ai-judge (Task 2.0) — escalation path for
edge cases (non-ASCII docstrings, unusual ``Pre:``/``Post:`` phrasing, multi-line
contracts) that this structural parser cannot classify.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Markers a complete Design-by-Contract docstring must carry.
_PRE_MARKER = "Pre:"
_POST_MARKER = "Post:"


def _is_public(name: str) -> bool:
    """A name is public iff it does not start with an underscore."""
    return not name.startswith("_")


def _missing_markers(docstring: str | None) -> list[str]:
    """Return the contract markers absent from *docstring* (empty list = complete)."""
    text = docstring or ""
    missing: list[str] = []
    if _PRE_MARKER not in text:
        missing.append(_PRE_MARKER)
    if _POST_MARKER not in text:
        missing.append(_POST_MARKER)
    return missing


def _collect_public_functions(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    """Collect (qualified_name, node) for the public contract surface.

    Includes public top-level functions and public methods of public classes
    (Protocol/ABC). Private/dunder names (leading ``_``) are excluded — an
    ``interface.py`` exposes only its public API.
    """
    found: list[tuple[str, ast.AST]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_public(node.name):
                found.append((node.name, node))
        elif isinstance(node, ast.ClassDef) and _is_public(node.name):
            for item in node.body:
                if isinstance(
                    item, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and _is_public(item.name):
                    found.append((f"{node.name}.{item.name}", item))
    return found


def _classify(text: str) -> tuple[str, str]:
    """Classify interface source into PASS or BLOCK with a reason string.

    Returns ("PASS", "") when every public function has Pre: and Post:; otherwise
    ("BLOCK", reason). A syntax error is a BLOCK — an unparseable contract cannot
    be judged complete.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return ("BLOCK", f"interface has a syntax error: {exc.msg} (line {exc.lineno})")

    offenders: list[str] = []
    for qualname, node in _collect_public_functions(tree):
        missing = _missing_markers(ast.get_docstring(node))
        if missing:
            offenders.append(f"{qualname} (missing {', '.join(missing)})")

    if offenders:
        return (
            "BLOCK",
            "public functions without complete contract: " + "; ".join(offenders),
        )
    return ("PASS", "")


def run(interface_path: Path) -> int:
    """Parse *interface_path* and print VERDICT to stdout.

    Returns 0 (PASS — contract complete) or 1 (BLOCK — incomplete/unparseable/missing).
    """
    if not interface_path.exists():
        print(f"VERDICT: BLOCK\nReason: interface file not found: {interface_path}")
        return 1

    text = interface_path.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _classify(text)

    if verdict == "PASS":
        print("VERDICT: PASS")
        return 0

    print(f"VERDICT: BLOCK\nReason: {reason}")
    return 1


def main() -> None:
    """CLI entry point.

    Usage::

        python scripts/s2_gate.py --interface src/<pkg>/<module>/interface.py

    Exits 0 (PASS) or 1 (BLOCK).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic contract-complete checker for the S2 pipeline stage.\n"
            "Verifies every public function in interface.py declares Pre: and Post:.\n"
            "Exit 0 = PASS (contract complete); Exit 1 = BLOCK."
        )
    )
    parser.add_argument(
        "--interface",
        metavar="FILE",
        required=True,
        help="Path to interface.py (Protocol/ABC public surface) to check.",
    )
    args = parser.parse_args()

    sys.exit(run(Path(args.interface)))


if __name__ == "__main__":
    main()
