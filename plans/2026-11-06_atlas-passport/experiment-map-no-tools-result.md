# Опыт «карта без инструментов» — результат (2026-11-11)

Протокол: `plans/2026-11-06_atlas-passport/experiment-map-no-tools.md`, коммит `33cad132b` (порог ≥ 14 из 19 записан до прогона). Вход: `docs/atlas/INDEX.md` на `42d9805d9` (blob `b174a0d5…`, sha256 `e394d97c…` — совпали). Модель: `claude-haiku-4-5-20251001`. Способ вызова: `claude -p --model haiku --tools "" --setting-sources "" --strict-mcp-config --disable-slash-commands`, пустой каталог, подписка (ключ API не использовался). 19 независимых вызовов, повторов и сбоев нет.

## Итог: 8 верных из 19 = 42,1 % -> «Провал» по таблице протокола (≤ 9)

По протоколу: гипотеза «карта как файл без инструментов» не подтвердилась; заморозка паспорта по плану Fable; 4.7a/4.7b, rel1, Kill-2 остаются замороженными; дерево файлов (T4–T7) не строится по правилу стопа поправки 26. Порог и вопросы не менялись. Перезапуск на новом наборе (правило для 10–13) не применяется: исход ниже 10.

## Таблица

| N | Вид | Слой | S | Эталон | Ответ Haiku | Верно |
|---|---|---|---|---|---|---|
| 1 | C | framework | H | `frontend_module` | `worker_module` | нет |
| 2 | A | services | E | `services/ml_train` | `services/ml_train` | да |
| 3 | B | framework | M | `state_store_module` | `router_module` | нет |
| 4 | A | services | E | `services/auth` | `services/auth` | да |
| 5 | C | plugins | H | `plugins/sources` | `services/hikvision_camera` | нет |
| 6 | A | plugins | H | `plugins/sim` | `plugins/sinks` | нет |
| 7 | B | framework | M | `shared_resources_module` | `shared_resources_module` | да |
| 8 | A | framework | M | `statistics_module` | `telemetry_readmodel_module` | нет |
| 9 | C | framework | H | `chain_module` | `worker_module` | нет |
| 10 | A | framework | E | `logger_module` | `logger_module` | да |
| 11 | B | services | E | `services/robot_comm` | `services/robot_comm` | да |
| 12 | C | services | H | `services/device_hub` | `services/vfd_comm` | нет |
| 13 | B | plugins | M | `plugins/filter` | `plugins/filter` | да |
| 14 | C | services | M | `services/otel_export` | `services/otel_export` | да |
| 15 | B | tools | M | `tools/utils` | `tools/utils` | да |
| 16 | A | services | M | `services/line_sim` | `services/robot_comm` | нет |
| 17 | B | framework | H | `channel_routing_module` | `shared_resources_module` | нет |
| 18 | C | plugins | M | `plugins/io` | `data_schema_module` | нет |
| 19 | B | prototype | M | `prototype/frontend/widgets/tabs/services` | `prototype/frontend/widgets` | нет |

## Разбор (для понимания, не меняет вердикта)

- По виду: A (по назначению) 3 из 6; B (имя класса) 4 из 7; C («двойник») 1 из 6.
- По априорной сложности: E 4 из 4; M 4 из 9; H 0 из 6.
- Все 11 ошибок — выбор соседнего юнита по правдоподобию (`worker_module` вместо `chain_module`, `shared_resources_module` вместо `channel_routing_module`, родитель вместо самого узкого юнита в Q19); выдуманных id нет (все 10 ошибочных id есть в карте, проверено поиском по `INDEX.md`). В карте нет имён классов `ThreadManager`, `TopologyGateMiddleware`, `HikvisionBackend`, `WorkerPoolDispatcher`, `ObservabilityStore` (проверено `grep`): Q1, Q3, Q5, Q9, Q17 про них — все пять неверны. Карта называет публичные классы выборочно («… ещё N»), вывод юнита по имени класса, которого в ней нет, модель делает по догадке.
- Карта-индекс отвечает на лёгкие и часть средних вопросов; на «двойников» и менее известные юниты — нет.
- Расход: input 171 + cache_creation 107 161 + output 86 529 токенов; выход большой, потому что Haiku рассуждал до ответа (в протоколе не оговорено). Общий расход ≈ 194k — внутри диапазона 100–320k.

## Что опыт проверяет и что нет

Проверен только вход «INDEX.md целиком в промпте, без инструментов, без поиска» на вопросах «в каком юните». НЕ проверены: файл по пути из CLAUDE.md с последующим Read/Glob, уровни 2–3 (MODULE.md, файл на класс), `map`, реальные задачи агента, подача карты вместе с поиском (F2 протокола). Шум: при n = 19 и истинной доле 70 % результат ≤ 8 бывает с вероятностью ≈ 1,1 % (биномиальный расчёт: сумма P(k) для k = 0…8, n = 19, p = 0,7 -> 0,0105) — провал не объясняется выборкой.

## Что осталось открытым / ненадёжным

- Эталоны выводил один автор, перепроверки нет; Q12, Q14 неоднозначны для человека.
- Haiku 4.5 с рассуждением; другая модель (Sonnet) или режим могут дать иное — не проверялось.
- Решение, что делать дальше (заморозка паспорта целиком / проверка уровней 2–3 отдельным опытом / иной вход), принадлежит владельцу и Fable; этот файл его не принимает.
