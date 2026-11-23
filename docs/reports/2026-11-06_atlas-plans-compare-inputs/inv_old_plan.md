# Инвентарь старого плана атласа (plans/2026-10-04_atlas/plan.md, amendments.md)

Снимок: main @c07fb7cb7 (2026-11-06). Дерево plans/2026-10-04_atlas совпадает с main (git diff main -- plans/2026-10-04_atlas пуст).
Qex не использовался. Поиск: git grep, git log, git ls-tree.
«коммитов atlas#id» = число коммитов в `git log main` с трейлером `Task: atlas#<id>` (проверено и regex с экранированной точкой, и grep -F).
0 трейлеров НЕ значит «не влито»: см. колонку «в main (по subject/хешу)».

| id | суть | статус (как в плане) | result.md | в main | ссылка |
|---|---|---|---|---|---|
| 0.1 | трейлеры коммитов (предусловие) | DONE 2026-10-05 | да | трейлер 1; хеш 06a70f7e6 | plan.md:140 |
| 0.2 | валидатор коммитов в CI | DONE 2026-10-05 | да | трейлер 7; хеш 1663d06fd | plan.md:141 |
| 0.3 | modules.yaml v0 | DONE | да | трейлер 10; хеш a4ef89961 | plan.md:142 |
| 0.4 | сведение трёх копий памяти | DONE | да | трейлер 20; хеш ed6e289ad | plan.md:143 |
| 0.5 | отсечка legacy, ADR-ATL-002 | DONE 2026-10-06 | нет | трейлер 0; в main через b9c6d77eb / merge 04cc44659 (subject «0.5, 0.7, 1.1»); ADR-ATL-002 в DECISIONS.md:172 | plan.md:144; amendments.md:7-14 |
| 0.6 | базовые метрики | DONE | да | трейлер 1; хеш 986448682 | plan.md:145 |
| 0.7 | формат result.md, шаблон | DONE 2026-10-06 | нет | трейлер 0; в main через b9c6d77eb / 04cc44659; шаблон .claude/plugins/dev/templates/task-result.md есть | plan.md:146; amendments.md:17-22 |
| 0.8 | CI на main зелёный Linux | DONE 2026-10-05 | да | трейлер 27 | plan.md:147 |
| P1.1 | пилот облачной сессии | DONE 2026-10-06 | да | трейлер 6 | plan.md:153 |
| 1.1 | ADR и схема реестра | DONE 2026-10-06 | нет | трейлер 2 (04cc44659, b9c6d77eb) | plan.md:161 |
| 1.2 | ядро scripts/atlas build/check | DONE 2026-10-06 | да | трейлер 10 | plan.md:162 |
| 1.3a | адаптеры plans, modules | DONE 2026-10-06 | да | трейлер 13; хеш 4aee917c6 | plan.md:163 |
| 1.3b | адаптер commits | DONE 2026-10-06 | да | трейлер 12; хеш 364ae736f | plan.md:164 |
| 1.3c | находки REF_TO_MISSING, REF_MOVED | DONE 2026-10-07 | да | трейлер 27; хеш 2b5964886 | plan.md:165 |
| 1.4 | адаптер docs | DEFERRED — FREEZE по K0b 2026-10-12, без даты | нет | трейлер 0 | plan.md:166; amendments.md:37-39 |
| 1.5a | слой качества по коду | DONE 2026-10-07 | да | трейлер 14; хеш bf6a6d1c7 | plan.md:167 |
| 1.5b | инъекции и mutation | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:168; amendments.md:37-38 |
| 1.6 | виды card, pack, log | DONE 2026-10-07 | да | трейлер 15; хеш 31907b566 | plan.md:169 |
| 1.6b | справочник atlas index, ref | DONE 2026-10-07 | да | трейлер 22; хеш 5f781c3a8 | plan.md:173 |
| 1.6c | ref/card на griffe, grimp | DONE 2026-10-08 | да | трейлер 23; хеш bb296e3a9 | plan.md:174 |
| 1.6d | каналы роутера в card | DEFERRED до 2026-11-10 | нет | трейлер 0 | plan.md:203 |
| 1.6e | кэш ref/card, LF в CLI | DONE 2026-10-08 | да | трейлер 10 | plan.md:175 |
| 1.6f | карта покрытия из прогона | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:207 |
| 1.6g | скорость card/ref | DONE | да | трейлер 26; хеш 93960e630 | plan.md:185 |
| 1.7 | гейты CI (исходная) | SUPERSEDED (на 1.7a/1.7b/1.7c) | нет | трейлер 0 | plan.md:170; amendments.md:79 |
| 1.7a | job atlas в CI | DONE | да | трейлер 9 | plan.md:183 |
| 1.7b | гейт-храповик | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:202 |
| 1.7c | остальные гейты | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:206 |
| 1.8 | мутационный балл, job mutation | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:172; amendments.md:37-38 |
| 1.9a | хвосты без потерь, lint-result | DONE | да | трейлер 8 | plan.md:184 |
| 1.9b | atlas brief | DONE | да | трейлер 17; хеш d6257c8d5 | plan.md:187 |
| 1.9c | atlas lint-brief | DONE 2026-10-11 | да | трейлер 18; хеш 9820f075b | plan.md:188 |
| 1.9d | ADR-ATL-004, форматы | DONE | да | трейлер 13; хеш 42e8c4556 | plan.md:186 |
| 1.9e | atlas inject | DEFERRED до 2026-11-10 | нет | трейлер 0 | plan.md:189 |
| 1.9f | atlas metrics | DONE 2026-10-12 | да | трейлер 13; хеш 1f78f3aad | plan.md:193 |
| 1.9g | допуск в metrics | PENDING (разрешено владельцем по K0b) | нет | трейлер 0 | plan.md:198 |
| 1.10a | библиотека scripts/atlas | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:190 |
| 1.10b | журнал доступа ролей (урезанно) | PENDING (урезанно по K0b) | нет | трейлер 0 | plan.md:191 |
| 1.10c | документы в карточке | DEFERRED до 2026-11-10 | нет | трейлер 0 | plan.md:204 |
| 1.10d | охват modules.yaml | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:205 |
| 1.10e | сервер Атласа (MCP) | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:192; amendments.md:101 |
| 2.1 | один дом ADR, удалить docs/decisions | PENDING (разрешено по K0b) | нет | трейлер 0 | plan.md:213 |
| 2.2 | генерируемые блоки, sync --write | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:214 |
| 2.3 | result.md обязателен | SUPERSEDED (на 1.9a) | нет | трейлер 0 | plan.md:215 |
| 2.4 | контекст агентов по ролям | IN PROGRESS (сверить 2.4h/2.4i) | нет | трейлер 7 | plan.md:216 |
| 2.4g | подзадача 2.4 | нет отдельной строки в plan.md | да (2.4g.result.md) | трейлер 14 | tasks/2.4g.md; tasks/2.4g.result.md |
| 2.4j | индекс по модулям | нет строки в plan.md (есть в amendments.md:110, plan.md:246); коммит bd7c99347 пишет DONE | нет (2.4j.md есть) | трейлер 0 | amendments.md:110; plan.md:246 |
| 2.4h, 2.4i | перевод на английский | открыто владельцем (CTO предлагает FREEZE) | нет | трейлер 0 | amendments.md:101-102; plan.md:216 |
| 2.5 | удаление мёртвого и дублей | PENDING (разрешено по K0b) | нет | трейлер 0 | plan.md:217 |
| K0 | ранняя проверка pack | SUPERSEDED (на K0b) | нет | трейлер 2 | plan.md:221; amendments.md:73-77 |
| K0b | честный повтор замера | DONE 2026-10-12, FREEZE на достигнутом | да | трейлер 3 | plan.md:194; plan.md:200; tasks/K0b.result.md:6 |
| K0c | замер цены | DONE 2026-10-12 | да | трейлер 0 (grep -F 'atlas#K0c' = 0); subject «merge: atlas K0c» 5916f184f | plan.md:195-197; tasks/K0c.result.md:91 |
| K1.1 | kill-проверка | PENDING, не раньше 2026-11-10 | нет | трейлер 0 | plan.md:222 |
| 3.1 | одно окно владельца, atlas html | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:226 |
| 4.1 | горячие устаревшие модули | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:230 |
| 5.1 | пороги MUTATION_BELOW и долг | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:234 |
| 5.2 | seed-пакет claude_seed | DEFERRED — FREEZE по K0b, без даты | нет | трейлер 0 | plan.md:235 |

## Цитаты (файл:строка)

- Решение K0b (FREEZE): plan.md:194 «[DONE 2026-10-12 — FREEZE на достигнутом ...]»; plan.md:200 «ревизия владельца 2026-10-12 по K0b — FREEZE на достигнутом ...»; tasks/K0b.result.md:6 «Вердикт по букве строгого критерия: FREEZE на достигнутом.»; tasks/K0b.result.md:110 «Решение владельца 2026-10-12 (после итога): ... после K0c — 1.9e (4), 1.6d (3), 1.10c (2)».
- DEFERRED с датой 2026-11-10: plan.md:189 (1.9e), plan.md:203 (1.6d), plan.md:204 (1.10c). Источник: tasks/K0c.result.md:91 «1.9e, 1.6d, 1.10c — DEFERRED до 2026-11-10»; merge 5916f184f.
- Фраза про удалила/добавила: plan.md:56 «5. Фаза принята, если удалила больше, чем добавила.» (повтор: research/CTO_VERDICT.md:70).
- Kill-критерии: plan.md:120 «**Kill (Task K1.1)** — останавливаемся на минимуме при любом из шести:», пункты plan.md:121-126; plan.md:128 «Минимум = два гейта CI + гейты связности + генерируемые блоки; карточка, HTML и сид снимаются.»
- Порог/условие K0 (SUPERSEDED): plan.md:221 «размораживать 1.4, 1.5b, 1.8 и строку доказанности, только если лучше базы ≥ 2 из Q1–Q3, иначе Атлас остаётся на минимуме».
- Прочие упоминания kill: plan.md:64, plan.md:96-97; amendments.md:68 «экзамен не сдан — K0 закрывается отказом от расширения»; amendments.md:104 «ответ на kill №6».
- Критерий K0c (принят 2026-10-12): plan.md:196-197 (Б6: 1.9e открыть при медиане доли инъекций ≥ 15 %, иначе DEFERRED до 2026-11-10).
- Слова «стоп» и «умереть» в plan.md и amendments.md не найдены (git grep -i -E 'kill|умер|стоп|порог|останавлив').

## Числа (main)

- scripts/atlas: 63 файла (git ls-tree -r --name-only main -- scripts/atlas | wc -l). .py всего 60; не-тестовых 23; тестовых 37 (35 test_*.py + __init__ + conftest).
- Строк .py: не-тестовые 4623; scripts/atlas/tests 13680; всего 18303 (git grep -I -h '' main -- 'scripts/atlas/*.py' | wc -l; сходится с суммой).
- Файлов в scripts/atlas/tests: 39 (включая данные briefs_1_9c/*.md). def test_: 332 (git grep -h -E '^def test_' main -- 'scripts/atlas/tests/*.py' | wc -l).
- scripts/atlas/DECISIONS.md: 502 строки, 83378 байт; ADR-ATL-001..004 (DECISIONS.md:13, 172, 291, 326).
- docs/atlas/INDEX.md: 134 строки, 20019 байт (git grep -c '' main -- docs/atlas/INDEX.md; git ls-tree -l main -- docs/atlas/).
