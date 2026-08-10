---
date: 2026-08-10
topic: observability-review-remediation — задача D8 закрыта (headless-презентация), раскладка `gui` пересмотрена владельцем
machine: Windows
branch: feat/observability-review-remediation
---

## Session goal

Продолжить [`plans/observability-review-remediation.md`](../../plans/observability-review-remediation.md) с фазы D. По хендоффу предыдущей сессии первой шла **D8** (Р-6=(б) уже решена владельцем): headless-стаб `gui`, дренирующий данные, — без неё D2.5 переписывает тест, а корень флейка остаётся.

## Done

**Задача D8 закрыта** (кроме одного пункта приёмки — см. «Открытые долги»). По ходу владелец **уточнил развилку Р-6**: процесс `gui` объявляется **только в рецепте**, а не в фундаменте.

**Шторм воспроизведён числами ДО правки** (стенд `webcam_sketch`, окно 30 с):

```
процессы: ProcessManager, camera_0, devices, lines, points, pult, seg   (gui НЕТ)
ProcessManager: sent_attempted +1439, sent_ok +21, errors_delivery_failed +1418  (47/с)
camera_0 / seg / points / lines: errors_delivery_failed +0
журнал: send [delivery_failed] ни один из 1 адресатов не принял: targets=['gui']
```

**Посылка плана оказалась неверной наполовину.** План утверждал «в headless `gui`-процесс существует и принимает данные, producers копят отказы». Живьём: процесса не было вовсе, а отказы копил **оркестратор**, не продюсеры — у продюсера имени `gui` нет ни очередью, ни каналом, билет уходит хабу relay'ем и засчитывается доставленным, провал случается уже на хабе.

**Собственный предохранитель был мёртв.** `backend_ctl.harness.strip_gui` («честный headless») после Ф2 стал НЕ-операцией: ни `region_pipeline`, ни `base.yaml` процесса `gui` не объявляли — вырезать было нечего. Пять его юнит-тестов на синтетических словарях оставались зелёными, докстринг фикстуры утверждал обратное.

**Новая раскладка (ADR-PMM-025):**
- рецепт объявляет `gui` в **headless-воплощении** (`frontend/headless_process.py::HeadlessGuiProcess`) — 14 рецептов + 5 легаси-топологий; у 6 бывших инлайн-объявлений заменён класс; 3 headless-пробных рецепта остались без процесса;
- `presentation.yaml` стал **патчем** (`apply_presentation_overlay`): подменяет класс, процессов не добавляет, накладывается ПОСЛЕ слияния с рецептом;
- **страж адресуемости** в `SystemBlueprint.check()`: `chain_target` в необъявленный процесс — отказ сборки с адресом (чинит КЛАСС бага, а не имя `gui`);
- harness топологию не правит; `strip_gui` удалён вместе с юнитами.

**Живая приёмка — обе половины пары.** Headless (600 с): 6/6, `errors_delivery_failed` **0** у всех восьми (было 1418/30 с), `gui.received` **+26 021** (43.4/с). С окном (60 с): 4/4, `gui.received` +2637 (44.0/с), `errors_no_route` 0.

**«Режим с презентацией не деградировал» доказан структурно, а не похожестью чисел:** сборка с презентацией **побитово идентична** состоянию до правки — `proc_dict` всех 7 процессов сверены ключ за ключом из чистого worktree на `HEAD`, **0 добавленных, 0 удалённых, 0 изменённых** после нормализации корня пути.

**Инъекции: 8 из 8 совпали с предсказанием, 11 красных, расхождений нет.**

**Полный каталог `backend_ctl/tests` — `633 passed` ТРИ прогона подряд** (9:36 / 9:03 / 8:50 — флейк-критерий выполнен). Был `1 failed / 630 passed`, и красным был ровно тест D2.5 (`test_watch_like_gui_quiet_planes_are_recipe_property_not_bug_live`): его ассерт «здоровый рецепт не пишет в ErrorManager» ломался штормом. Корень снят, тест НЕ переписывался.

## What did NOT work

**Первая редакция GUI-пробы краснела законно, но не на том.** Она требовала `errors_delivery_failed == 0` и получила `lines` 22, `points` 22, `seg` 21 за 60 с. Разбор: живой GUI отстаёт от трёх продюсеров, его data-очередь переполняется. Роутер считает ОДНИМ ключом «приёмника нет» и «приёмник не успевает». Проверка переписана на пару «`errors_no_route` = 0 + `received` растёт»; число переполнений печатается фактом. Долг заведён — `plans/QUEUE.md`, L-3.

**Дефект нашёлся в моём собственном дубле.** `_Router.receive` отвечал мгновенно, тогда как настоящий блокирует до таймаута. Под инъекцией «цикл не слышит `stop_event`» это дало не красный тест, а **разгон по памяти** (список вызовов рос безостановочно) — прогон пришлось снимать вручную, и одна инъекция осталась применённой в дереве. Дубль исправлен на блокирующий; урок: дубль, ведущий себя не как оригинал, превращает инъекцию в негодную.

**Первая редакция пробы шторма читала не тот ключ ответа** (`router` вместо `router_stats`) и получала нули на процессе, чей журнал в тот же момент писал `errors_delivery_failed=1354`. Неверный ключ читается как «отказов нет» — теперь проба явно отказывает, если секции нет.

**Мелочи, стоившие времени:**
- `git worktree add` в скретчпад-каталог падает на Windows («Filename too long») — короткий путь (`/d/wt_d8_before`) решает;
- фоновая команда с пайпом (`| tail`) теряет вывод целиком — писать в файл и читать оттуда; Python при редиректе буферизует, нужен `-u`;
- вывод в консоль Windows — cp866, русский текст в отчётах скриптов читается мохнатым; числа при этом верны.

## Key decisions made

- **Р-6 уточнена владельцем: `gui` объявляется ТОЛЬКО в рецепте.** Замерено до выбора: `gui` адресуют 14 рецептов из 17, объявляли 6. Альтернатива «объявить в фундаменте рядом с `devices`» отвергнута: рецепт остался бы неполным (адресует то, чего не объявлял), а класс бага чинился бы только для имени `gui`.
- **Overlay — патч, а не слагаемое, и НЕ добавляет процессов.** Рецепт без узла презентации окна не получает и с overlay'ем; таких три (`dualcam_synth`, `dualcam_webcam`, `g1_perf_probe`), и все три — заведомо headless-пробные, дисплеев не объявляют.
- **Страж живёт в `check()`, а НЕ в `check_structure()`.** Последний судит рецепт БЕЗ фундамента (gate записи), и там адрес в always-on процесс был бы отвергнут законным сохранением.
- **Golden-снапшоты сборки правились точечно** (по одному ключу `proc_dicts.gui.class`), чтобы не проглотить предсуществующий красный по секции `observability.documents`.
- **Кадры из SHM headless-воплощение не читает намеренно** — цена без потребителя. Следствие названо: при `FW_SHM_LOAN_PROTOCOL` (дефолт выключен) нужен release-путь.

## Состояние прогонов

| Прогон | Результат |
|---|---|
| fw-suite (`scripts/run_framework_tests.py`) | **7252 passed, 6 skipped** (было 7243) |
| корневой pytest | **2936 passed, 5 skipped**, 2 прежних красных |
| `backend_ctl/tests` (полный каталог) | **633 passed ×3 подряд** — 9:36 / 9:03 / 8:50 (был 1 failed / 630) |
| live headless D8 (600 с) | **6/6**, `logs_live/2026-08-10_D8_gui-headless/probe.log` |
| live с презентацией (60 с) | **4/4**, `logs_live/2026-08-10_D8_gui-headless/presentation_probe.log` |
| инъекции | **8/8 совпали**, 11 красных |
| `scripts/validate.py` | зелёный |

Два красных корневого прогона — `test_build_characterization[phone_sketch]` и `[hikvision_letter_robot]`. **Остаются красными по ПРЕЖНЕЙ, не нашей причине**: структурная дельта показывает расхождения только по секции `observability.documents` (45 и 60 ключей), которой нет в golden; после точечной правки снапшотов `changed=0`.

## Открытые долги

- **Переписать тест D2.5** — его посылка («тишина ui/errors — свойство рецепта») опровергнута корнем Б-1; это задача D2.5, не D8. D8 снял только корень флейка.
- **L-3 в `plans/QUEUE.md`** — `errors_delivery_failed` не различает «приёмника нет» и «приёмник не успевает».
- **Независимый `tester` не звался** — субагенты в этой сессии не использовались (ограничение харнесса). Роль независимого автора тестов от acceptance не выполнена; объявляю вслух, как требует правило.
- Радиус Б-2 на живом hikvision по-прежнему не проверен — до первого железного прогона.

## Next step

Остаток фазы D по плану: **D2** (тестовая сетка; включая переписывание D2.5), **D1** (реентерабельность tap/sink), **D3** (стор: `auto_vacuum` + честность `dropped`), **D5** (слепые зоны ретеншена), **D4** (радиус «inspector», развилка Р-4 — подтверждение владельца перед стартом), **D6** (удалить мёртвое; `KIND_STATS` не трогать), **D7** (обходы единственного писателя). Затем фаза **E** (четыре справочника) и **F1** — повторное ревью, исполнитель внешний к автору фаз.

## Files changed

Не закоммичено на момент записи (рабочее дерево грязное, 45 позиций).

```
 backend_ctl/harness.py                                    (strip_gui удалён)
 backend_ctl/tests/conftest.py                             (ложный докстринг снят)
 backend_ctl/tests/test_harness.py                         (контракт переписан)
 backend_ctl/tests/test_routing_epoch_live.py              (докстринг)
 backend_ctl/probes/probe_d8_gui_storm_live.py             (новый)
 backend_ctl/probes/probe_d8_gui_presentation_live.py      (новый)
 docs/contracts/CAPABILITIES.{yaml,md}                     (перегенерированы, только добавления)
 multiprocess_framework/DECISIONS.md                       (scripts.sync)
 multiprocess_framework/modules/process_manager_module/DECISIONS.md          (ADR-PMM-025)
 multiprocess_framework/modules/process_manager_module/topology/blueprint.py (страж)
 multiprocess_framework/modules/process_manager_module/tests/test_chain_target_addressability.py (новый)
 multiprocess_prototype/STATUS.md                          (раскладка Ф2 обновлена)
 multiprocess_prototype/backend/config/manifest.py         (докстринг)
 multiprocess_prototype/backend/launch.py                  (apply_presentation_overlay)
 multiprocess_prototype/backend/topology/base.yaml         (комментарии)
 multiprocess_prototype/backend/topology/{hello_world,inspection_basic,inspection_full,multi_camera,TEMPLATE}.yaml (gui объявлен)
 multiprocess_prototype/backend/topology/pilot_widgets.yaml (класс → headless)
 multiprocess_prototype/backend/topology/tests/test_base_merge.py (контракты переписаны)
 multiprocess_prototype/backend/tests/snapshots/*.build.json (точечно: класс gui)
 multiprocess_prototype/frontend/headless_process.py       (новый)
 multiprocess_prototype/frontend/presentation.yaml         (overlay = патч)
 multiprocess_prototype/frontend/run.py                    (докстринг)
 multiprocess_prototype/frontend/tests/test_headless_process.py (новый)
 multiprocess_prototype/recipes/*.yaml                     (14 рецептов: gui объявлен)
 plans/QUEUE.md                                            (L-3)
 plans/observability-review-remediation.md                 (Ход D8)
 pyproject.toml                                            (testpaths: hazard-тесты дренажа)
```
