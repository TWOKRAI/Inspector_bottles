# Prior art для «Атласа», 2026-11-06

STATUS: DONE_WITH_CONCERNS

[поиск] = факт только из выдачи поиска, страница не открыта: не проверено.

| Технология | Что даёт (лицензия) | Ложится на принципы? | Взять | URL |
|---|---|---|---|---|
| Aider repo map | tree-sitter теги, граф файлов, ранжирование, бюджет `--map-tokens` (1k). Замеров экономии нет. | Частично: локально да; ранжирование не доказано | идея | aider.chat/2023/10/22/repomap.html |
| tree-sitter tags.scm | Захваты `@definition.*`, `@reference.*`, CLI `tree-sitter tags` | Да: один движок, декларативно | зависимость + идея | tree-sitter.github.io/tree-sitter/4-code-navigation.html |
| SCIP (Sourcegraph) | Protobuf-индекс, строковые ID символов; компактнее LSIF; инкрементальность не реализована (пост 2022) | Частично: тяжело для паспорта | идея (ID) | sourcegraph.com/blog/announcing-scip |
| Glean (Meta) | Факты-предикаты, инкрементальный индекс, Angle; Python есть; лицензия не указана | Частично: рассчитан на миллионы строк | идея | engineering.fb.com/2024/12/19/developer-tools/glean-open-source-code-indexing/ |
| griffe | Статический разбор и динамический; docstrings; `griffe dump` в JSON; ISC | Да: уже используем | зависимость (есть) | mkdocstrings.github.io/griffe/ |
| grimp | Граф импортов: `build_graph`, `find_upstream_modules`; BSD-2 | Да: статический граф | зависимость | github.com/seddonym/grimp |
| import-linter | Контракты импортов; BSD-2 | Частично: дублирует sentrux | не брать | github.com/seddonym/import-linter |
| Tach (Rust) | Границы, публичный интерфейс, циклы; MIT; `tach.toml` | Частично: правила в конфиге = рукопись | идея | github.com/gauge-sh/tach |
| pytest-archon | Запреты импортов как pytest-тесты; Apache-2.0 | Да: тесты, без облака | идея | github.com/jwbargsten/pytest-archon |
| MCP tools/list | `inputSchema`, `outputSchema` (сервер MUST соответствовать), `annotations` (клиент MUST считать недоверенными). Поля `access`/owner в спеке нет | Да: образец каталога команд | идея (формат) | modelcontextprotocol.io/specification/2025-06-18/server/tools |
| Backstage catalog-info | Component: `spec.type`, `lifecycle`, `owner` обязательны | Нет: заполняется руками | идея (поля) | backstage.io/docs/features/software-catalog/descriptor-format/ |
| Structurizr DSL / C4 | Уровни person/system/container/component; code-to-model только Java | Частично: уровни да, DSL рукопись | идея (уровни) | docs.structurizr.com/dsl/language |
| RepoGraph | Граф строк кода, действие агента `search_repo`; Apache-2.0; замеры только в обзорах [поиск] | Частично: цель SWE-bench | идея | github.com/ozyyshr/RepoGraph |
| code-graph-rag | tree-sitter в SQLite/Memgraph; MIT; `cgr trace` добавляет реальные вызовы из тестов; Python 3.12+ | Частично: тяжело, трасса полезна | идея (трасса) | github.com/vitali87/code-graph-rag |
| git co-change | Temporal coupling из `git log`; hotspot = частота × сложность [поиск] | Да: только git | идея | [поиск] codescene.com (Tornhill) |
| AGENTS.md / llms.txt | Файлы инструкций и входа для агента; эффект llms.txt не измерен | Частично: ручные файлы | идея | agents.md ; llmstxt.org |

Замеры токенов: agentmap заявляет ~98% меньше контекста, Atlarix получил +54% контекста с картой ([поиск], self-reported). Независимого замера «карта против grep» не нашёл.

## ТОП-5, что украсть
1. Ранжирование и бюджет токенов (Aider): паспорт режется по важности, а не по длине.
2. Один tree-sitter сканер с захватами definition/reference: одна схема для языков.
3. Каталог команд в формате MCP (inputSchema/outputSchema/annotations) с полями access и owner: один источник для паспорта и рантайма.
4. Трасса тестов как источник реальных рёбер (code-graph-rag): добирает то, что статика пропускает.
5. Co-change из git log: связность без импортов, дешево и локально.

## Что не нашёл / ненадёжно
- Не открыто: Kythe (лицензия, Python-индексер), Pyright `--outputjson` (текст страницы не получен), CodeQL CLI и Joern (лицензии; CodeQL CLI по памяти с ограничениями ToU, not verified), Semgrep: правила под Semgrep Rules License [поиск].
- Agentless и SWE-agent ACI: цифры из вторичных сайтов расходятся; не открыто.
- Не искал: jedi, pdoc, mkdocstrings, Sphinx autodoc, ctags, D2, Mermaid, Doxygen, CodeCompass, приёмы Cursor и Claude Code.
- graphify: официальная страница не дала лицензии и механики; данные расходятся [поиск].
- Не подтверждено: динамические импорты у Tach; `model_json_schema` в FastStream; даты релизов.
- Независимых замеров экономии токенов не нашёл. Соответствие нашему коду не проверялось (проект не читан).

## Sources (открыты через WebFetch)
- aider.chat/2023/10/22/repomap.html
- tree-sitter.github.io/tree-sitter/4-code-navigation.html
- sourcegraph.com/blog/announcing-scip
- engineering.fb.com/2024/12/19/developer-tools/glean-open-source-code-indexing/
- mkdocstrings.github.io/griffe/ и github.com/mkdocstrings/griffe
- github.com/seddonym/grimp
- github.com/seddonym/import-linter
- github.com/gauge-sh/tach
- github.com/jwbargsten/pytest-archon
- modelcontextprotocol.io/specification/2025-06-18/server/tools
- backstage.io/docs/features/software-catalog/descriptor-format/
- docs.structurizr.com/dsl/language
- github.com/ozyyshr/RepoGraph
- github.com/vitali87/code-graph-rag
- graphify.com/what-is-graphify (открыт, полезных данных не дал)
- microsoft.github.io/pyright/ (открыт, текст про outputjson не дал)
- llmstxt.org
- agents.md
