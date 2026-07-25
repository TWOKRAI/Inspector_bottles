---
name: project_graphify_mcp_setup
description: graphify-MCP настройка — mcp вшивать через `uv tool install --with mcp`, единый граф по 5 каталогам, рантайм --with даёт таймаут коннекта
metadata:
  type: project
---

graphify (PyPI `graphifyy`, канонический репо `Graphify-Labs/graphify`; `safishamsi/graphify` — старый личный, тот же пакет) отдаёт граф проекта через MCP (`graphify-mcp` = `python -m graphify.serve`, transport stdio). В `.mcp.json` сервер стартует так: `uv tool run --from graphifyy graphify-mcp graphify-out/graph.json` — БЕЗ рантайм-флага `--with mcp`.

Граф пересобран 2026-07-25 (graphifyy 0.9.26) как ЕДИНЫЙ AST-граф по 5 каталогам: multiprocess_framework + multiprocess_prototype + backend_ctl + Plugins + Services (29950 узлов / 48686 рёбер / 1354 сообщества, 97% EXTRACTED). Скоуп задан в `.graphifyignore` (ведущий `/` якорит исключение прочих top-level каталогов, вложенные config/ внутри framework/prototype не страдают). MCP-инструменты: query_graph, get_node, get_neighbors, get_community, god_nodes, graph_stats, shortest_path — прописаны в промптах investigator/tech-writer/developer, имена сверены с реальными.

**Why:** `mcp` НЕ в dependencies graphifyy (баг upstream). Рантайм-`--with mcp` собирал overlay-окружение и пере-резолвил его на КАЖДОМ старте сервера → коннект MCP не укладывался в таймаут, сервер молча не поднимался (в сессии не было `mcp__graphify__*`). Апгрейд graphifyy — pre-1.0, между минорами возможны breaking changes; версию фиксировать.

**How to apply:** один раз выполнить `uv tool install graphifyy --with mcp --force` (install-команды — за пользователем) → `mcp` вшит в tool-env, `--with mcp` в .mcp.json не нужен. Пересборка графа: `graphify update . --force` (AST, без LLM, токены=0) → перезапуск Claude Code, чтобы MCP перечитал graph.json (запущенный сервер держит старый в памяти). Проверка после рестарта: `mcp__graphify__graph_stats`. Связано: [[feedback_always_project_venv]], [[feedback_package_install_by_user]], [[project_prototype_carveout]].
