---
name: feedback_sentrux_html_href_is_an_import_edge
description: "sentrux считает href/src в HTML импортом: две страницы docs со ссылками друг на друга = цикл, acyclicity падает; исключить файлы на уровне репо нельзя; ленивый абсолютный импорт sentrux считает, относительный нет (sentrux html href import edge, cycle in docs, no repo-level exclusion)"
mechanism: [dev-tooling, guards]
metadata:
  node_type: memory
  type: feedback
  modified: 2026-11-12
---

Плагин `~/.sentrux/plugins/html/queries/tags.scm` берёт любой атрибут `href`/`src` как импорт. Две отслеживаемые страницы со ссылками друг на друга дают `Found 1 circular dependencies` (micro-репо, 2026-11-12). На main это был один из двух циклов: `docs/diagrams/foundation-audit` ↔ `system-map`; второй — настоящий код `adapters/recipe_canonical` ↔ `stores/recipe_store`.

Исключить файлы на уровне репо нельзя: у CLI есть только `[PATH]`, сканируется `git ls-files`, `.gitignore` и `.ignore` на отслеживаемые файлы не влияют, `.sentrux/plugins/` в репо игнорируется. `sentrux plugin remove html` действует только на машине — гейт начнёт зависеть от машины.

Ленивый (в теле функции) АБСОЛЮТНЫЙ импорт sentrux считает. ОТНОСИТЕЛЬНЫЙ — нет, даже на верхнем уровне (0 рёбер); форма `from pkg import module` тоже мимо. Разрешается около 40 % импортов. Во framework почти все импорты относительные.

**Why:** арх-ревью 2026-11-12 искало причину красного acyclicity в ленивых импортах framework (F1), а настоящие циклы были другие: один в коде прототипа, один в HTML. Выводы «F1 закроет метрику» опровергнуты экспериментом (бисекция по каталогам в отдельном worktree).

**How to apply:** красный acyclicity — сначала узнать, какие файлы в цикле: убирать каталоги в worktree и смотреть `Quality`, включая `docs/*.html`. Зелёный sentrux не доказывает, что framework ацикличен: нужен AST-граф (`scripts/arch_graph/ast_graph.py`). Ссылки между страницами docs — только в одну сторону. Связь [[feedback_pytest_import_order_hides_a_cycle]]: цикл проверять и в чистом `python -I` с модулем первым.
