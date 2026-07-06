"""render_adr.py — сводка per-module DECISIONS.md (ADR) в root registry.

Парсит заголовки `## ADR-{CODE}-NNN: title` в per-module DECISIONS.md и
рендерит две таблицы в `docs/PROJECT_CONTEXT.md`:

- Между `ADR-CODES:BEGIN/END` — таблица "Коды модулей":
      | Код | Модуль | Файл решений |

- Между `ADR-INDEX:BEGIN/END` — таблица "Модульные решения":
      | Код | ADR | Title | Файл |

Глобальные ADR (cross-module) лежат в `docs/decisions/NNNN-*.md`
(единственный ADR-каталог, который деплоит skeleton).
"""

from __future__ import annotations

import re
from pathlib import Path

from collections.abc import Sequence

from .discover import ModuleEntry, discover_modules


_ADR_HEADER_RE = re.compile(
    r"^##\s+ADR-([A-Z][A-Z0-9]*)-(\d+):\s*(.+?)\s*$",
    re.MULTILINE,
)


def _parse_adrs(decisions_file: Path) -> list[tuple[str, str, str]]:
    """Возвращает список (code, number, title) из DECISIONS.md модуля.

    Сортирует по number (numeric ascending).
    """
    text = decisions_file.read_text(encoding="utf-8")
    found: list[tuple[str, str, str]] = []
    for match in _ADR_HEADER_RE.finditer(text):
        code, number, title = match.group(1), match.group(2), match.group(3)
        found.append((code, number, title))
    found.sort(key=lambda t: int(t[1]))
    return found


class RenderADR:
    """SyncModule: per-module DECISIONS.md → root ADR-CODES + ADR-INDEX tables."""

    name = "render_adr"
    description = "Сводка ADR per-module в docs/PROJECT_CONTEXT.md"

    def __init__(
        self,
        root: Path,
        target_file: Path,
        *,
        modules: Sequence[ModuleEntry] | None = None,
    ):
        """Args:
        root: корень проекта.
        target_file: путь к root registry.
        modules: опционально — заранее найденные модули (избегает повторного
            rglob). Если None — вызываем discover_modules сами.
        """
        self.root = Path(root).resolve()
        self.target_file = Path(target_file)
        self._modules = modules

    def render(self) -> dict[Path, dict[str, str]]:
        source = (
            self._modules if self._modules is not None else discover_modules(self.root)
        )
        modules = [m for m in source if m.decisions_file is not None]

        if not modules:
            empty_codes = (
                "_Не найдено ни одного DECISIONS.md. "
                "Создай `<module>/DECISIONS.md` из шаблона "
                "`.claude/plugins/core/templates/DECISIONS.template.md`._"
            )
            empty_index = "_Нет per-module ADR._"
            return {
                self.target_file: {
                    "ADR-CODES": empty_codes,
                    "ADR-INDEX": empty_index,
                }
            }

        codes_lines = [
            "| Код | Модуль | Файл решений |",
            "|-----|--------|--------------|",
        ]
        for mod in modules:
            assert mod.decisions_file is not None
            rel_path = mod.decisions_file.relative_to(self.root).as_posix()
            codes_lines.append(
                f"| **{mod.module_code}** | `{mod.name}` | [`{rel_path}`]({rel_path}) |"
            )

        index_lines = [
            "| Код | ADR | Title | Файл |",
            "|-----|-----|-------|------|",
        ]
        for mod in modules:
            assert mod.decisions_file is not None
            adrs = _parse_adrs(mod.decisions_file)
            rel_path = mod.decisions_file.relative_to(self.root).as_posix()
            for code, number, title in adrs:
                anchor = f"adr-{code.lower()}-{number}"
                index_lines.append(
                    f"| **{mod.module_code}** | `ADR-{code}-{number}` | "
                    f"{title} | [`{rel_path}#{anchor}`]({rel_path}#{anchor}) |"
                )
            if not adrs:
                index_lines.append(
                    f"| **{mod.module_code}** | _(пусто)_ | "
                    f"_создай первый `## ADR-{mod.module_code}-001: …`_ | "
                    f"[`{rel_path}`]({rel_path}) |"
                )

        return {
            self.target_file: {
                "ADR-CODES": "\n".join(codes_lines),
                "ADR-INDEX": "\n".join(index_lines),
            }
        }
