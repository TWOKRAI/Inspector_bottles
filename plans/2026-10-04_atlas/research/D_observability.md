# Группа D — планы наблюдаемости и телеметрии (15)

Дата сверки: 2026-10-04, `main` = `03952a020`. Только чтение. Числа взяты командами (`git log --grep`, `plans_progress.py --json`, `git merge-base --is-ancestor`), не из шапок.
qex не использовался (Ollama не запущена); индекс не видел ничего из этого отчёта.

## 0. Картина одним абзацем

Живых планов наблюдаемости два: **observability-closure** и **otel-export**. Оба целиком в `main`, оба без движения с 2026-10-01 (closure) и 2026-09-08 (otel, последний код-коммит) и оба стоят за Ж по решению владельца. Остальные 13 планов — закрытые или поглощённые. Из 13 на «не сделано» по счётчику `plans_progress` приходятся 6 планов (unified-routing 22/32, review-remediation 7/20, f1-hardening 0/16, stage6 11/13, observation-port 22/24, delivery-simplification 2/6). Я проверил каждую «открытую» строку по телу плана и по git: **ни одной живой невыполненной задачи в них нет, кроме трёх строк, уже принятых closure** (4.5, 4.3, 5.4). Счётчик врёт, потому что часть планов ведёт задачи заголовками `### Task X`, а не строками-чекбоксами: парсер видит «pending» там, где в теле стоит «ЗАКРЫТА 2026-08-09».

Но у закрытия есть **один реальный пробел**: ORDER.md §4.3 пишет «этап 9 roadmap → backlog.md» и «Д.1 `run_all_gates.py` → backlog», а в `plans/queue/backlog.md` этих записей **нет** (`grep -iE "fingerprint|stderr|JSON-сток|run_all_gates|проглоч"` по файлу — 0 строк). Если архивировать roadmap и dx как есть, три желанные идеи (fingerprint ошибок, fd-перехват stderr, JSON-сток) и дисциплинарные задачи Д.1–Д.4 исчезнут. Salvage — в разделе 2.

## 1. Блоки по планам

### observability-closure  — verdict: DEFERRED-OWNER
- Goal: довести механизмы наблюдаемости до «конструкторного стандарта»: чтобы диагностика не врала, второе приложение (line-sim) не наследовало словарь инспектора, а отладчик видел потери.
- Real state: 33/46 (8 dropped/superseded/deferred не считаются выполненными: 4.1, 4.2, 4.7, 4.9, 4.10 DEFERRED; 3.4, 3.6, 3.7 SUPERSEDED). Код-коммитов с Refs: 105 (всего 229), последний код — `5a83c2323` 2026-10-01 (слияние `feat/pipeline-node-timing`, там коммиты 4.4/4.5/4.6 относятся к плану transport, не к closure). Ветка `feat/observability-closure` влита в `main` целиком. Ф0–Ф3 закрыты, из Ф4 закрыты 4.4, 4.11, 4.13.
- What changed since: посылка жива. Ф0–Ф3 принимались ревью/CTO. Ф4 переупорядочена владельцем 2026-09-07 и 2026-09-23. Все ключевые следы проверены в дереве: класса `ServiceContext` нет, `ObservabilityReadback` нет в `channel_routing_module/interfaces.py`, `optimize` в `observability_store.py` нет, `wired_at`/`observability_evicted_records` нет. То есть строки PENDING честные.
- Fit with today's priorities: решения 2, 2b, 3, 8 отложены до закрытия Ж. Ж Ф3 стартует после closure-задач по `observability_wiring.py`. ORDER.md §4 п.9 уже ставит closure «за Ж».
- Blocker / trigger: закрытие Ж (фаза с Ф2 «гейт без abort»); для Ж Ф3 — решение, кто идёт первым по `observability_wiring.py` (см. §3).
- Next concrete step (когда снимется отсрочка): Task 4.3b (счётчики форвардера, вердикт CTO 2026-09-23 `5a6454412`) — он же разблокирует otel 3.4 и касается `observability_wiring.py`. Потом 4.6 → 4.5 → 4.15 (волна 2).
- Salvage: не архивируется. В остаток входят и «чужие» задачи: переприёмка гейта Ф6 stage6 (5.4), ServiceContext (бывш. stage6 1.2 / dx А.2 / remediation C1), readback-протокол (dx В / 4.3).
- Header honesty: частично. Статус-абзац шапки датирован 2026-09-04 и говорит «Ф4 начата 2026-09-07»; раздел «Порядок выполнения» (сверено 2026-10-03) исправлен и верен. Тела Ф0–Ф4 хранят старые `[x]`/`[DONE]`; строка «Порядок выполнения» побеждает по собственному правилу. Счётчик 33/46 вводит в заблуждение: из 13 «не сделано» 5 отложены и 3 сняты, реально открытых к работе 13 (4.3, 4.3b, 4.5, 4.6, 4.8, 4.12, 4.14, 4.15, 4.16, 5.1–5.4).
- Confidence: high (код-следы проверены grep'ом, статус задач сверен с git).

### otel-export  — verdict: DEFERRED-OWNER
- Goal: отдать записи системы наружу по OTLP (Grafana/Loki, Elastic и т.д.) и тем самым получить чужой парсер как арбитра словаря полей. Снимает слово «заявлено» из отчётов.
- Real state: 13/21. Код-коммитов с Refs: 36 (всего 65), последний код — `0112fbfb4` 2026-09-08 (слияние `otel` в `main`). `feat/otel-export` и `tests/otel-t22-blind` в `main` (0 коммитов впереди). Живой worktree `.claude/worktrees/otel` (HEAD `29999d618`) грязный: 5 застейдженных файлов (память CTO, `docs/sessions/2026-09-12.md`, `logs_plane_probe/*`) — это мусор сессии, не код. Ф0–Ф2 закрыты кроме 2.5; 3.1 IN PROGRESS (фрагмент топологии `otel_export.yaml` в `main`, `94998cc6`).
- What changed since: посылка жива, но сменился порядок. Решение владельца 2026-09-23: closure 4.4 → closure 4.3b → хвост otel. 4.4 сделана (`94818d29f`), 4.3b нет. Task 3.4 BLOCKED на 4.3b (секция `forwarders` в `introspect.observability`).
- Fit with today's priorities: ORDER.md Ф7. Решение №8 «старт otel» отложено до Ж. Портфолио-сигнал, не продуктовая цель (план сам это пишет: балл вердикта двигают P-1 и P-2, не экспорт).
- Blocker / trigger: Ж закрыт + closure 4.3b в `main`. Независимые от 4.3b задачи (2.5, 3.2, 3.3) можно брать в любой момент, но владелец сказал «без запасных путей» — не делать.
- Next concrete step: когда снимется: Task 2.5 (жизненный цикл подписки при рестарте экспортёра; предусловие closure 4.4 выполнено). После 4.3b — Task 3.4, затем Ф4 (живой прогон).
- Salvage: не архивируется.
- Header honesty: да по сути (ред. 4 + пометка 2026-09-23). Но блок «Состояние closure на 2026-09-07 … Ф4–Ф5 не начаты» устарел: Ф4 начата и 4.4/4.11/4.13 закрыты. Мелочь.
- Confidence: high.

### observability-roadmap  — verdict: ARCHIVE-DONE
- Goal: управляющий план «починить наблюдаемость и положить на неё телеметрию»: этапы 0–10.
- Real state: 0/0 (задачи в таблицах, парсер не видит). Код-коммитов с Refs: 45 (всего 80), последний код — `d5ce1058e` 2026-08-12. Ветка `feat/observability-roadmap` в `main`. Этапы 0–5 закрыты (переприёмка F2 принята в раунде 3, 2026-08-12). Этап 6 → `telemetry-stage6` (влит). Этап 7 → `otel-export` (живой). Этап 8 (долги) и 10 (dx) частично поглощены closure; этап 9 нигде не исполнен.
- What changed since: роль управляющего принял сначала closure (ревью 2026-08-28 6/10 → новый план), поэтому roadmap с 2026-08-12 никто не ведёт.
- Fit with today's priorities: нет, но содержит три идеи, которые нигде больше не записаны.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: ОБЯЗАТЕЛЬНО перед архивом перенести в `backlog.md` (ORDER.md обещает это, но не сделано): 9.1 fingerprint ошибок lite («вкладка Ошибки показывает проблемы, а не ленту»; правило остановки — при нехватке lite брать sentry-sdk + GlitchTip, решение «купить»), 9.2 fd-перехват stderr нативных писателей (glog/mediapipe пишут мимо плоскости логов), 9.3 JSON-сток опциональным `register_sink_factory`. Этап 8: «~60 точек проглоченного сбоя» и «ретеншен аудита ≠ ретеншен логов» — проверить, поглощены ли closure (в `plan.md` closure слова «проглоч» нет); С-9 слепой прогон рецепта как повторяемый гейт — closure 5.1 близко, но не равно.
- Header honesty: нет. Шапка «ред. 2 (2026-08-10) — исполнение начато владельцем (этап 0)» не отражает ни закрытия этапов 0–5, ни передачи управления closure. ORDER.md §4.3 «DONE как управляющий» верно.
- Confidence: high по состоянию этапов (таблицы и ходы этапа 1–5 с хешами), medium по «60 проглоченных сбоев» (не искал по коду).

### observability-unified-routing  — verdict: ARCHIVE-DONE
- Goal: один механизм наблюдаемости для логов, ошибок, статистики и телеметрии: гейт цены, иерархия имён, пульт, документы.
- Real state: счётчик 22/32 — артефакт парсера (9 строк «unmarked»). Тело плана: Ф0–Ф8 закрыты. Проверено по таблице Ф5 в самом плане: 5.2 [x] «ЗАКРЫТА 2026-08-09 вариантом (г)», 5.4 [x] 2026-08-09, 5.5/5.6/5.7 ✅ 2026-07-30, 5.13 ✅ 2026-07-30; 2.3b закрыта Ф8.1 2026-08-06; 2.9 закрыта `7a7b4ccb`; 8.7 закрыта 2026-08-09 (95 кадров брака → 1 документ, живой прогон). 8.6 (экспорт) отложена владельцем 2026-08-06 и переехала в `otel-export`. Код-коммитов: 177 (всего 314), последний — слияние `23184cc48` 2026-08-09 (Ф0–Ф8 в `main`). Ветка влита.
- What changed since: Ф5.2 была «ждёт решения владельца а/б/в» (decisions.md №3). Тело плана говорит: закрыта вариантом (г) 2026-08-09, остаток «живой прогон». То есть решение №3 в `decisions.md` устарело: оно названо открытым, а закрыто. Это снимает одну из четырёх отложенных «наблюдательных» развилок (№3).
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: 8.6 уже живёт в otel-export. Остатка нет. Ф5.2 «живой прогон» поглощён последующими приёмками (2026-08-10 F1 7/10, 2026-08-28 полное ревью).
- Header honesty: нет, сильно. Первые строки шапки (ред. 4, 7, 9, 10) в разном порядке и говорят «открыто три ряда: Ф8, Ф5.2, Ф5.4, Ф5.1-остаток» — всё это закрыто в теле. Размер 7713 строк делает план нечитаемым.
- Confidence: high по Ф5 и Ф8 (таблица плана, коммит-слияние); medium по Ф5.2 «кроме живого прогона» (прогон не искал).

### observability-review-remediation  — verdict: ARCHIVE-DONE
- Goal: закрыть находки приёмочного ревью 2026-08-09 (6/10, 2 блокера, 16 major).
- Real state: счётчик 7/20 — артефакт (12 «unmarked»). Шапка: «ред. 9 — фаза E закрыта целиком (2026-08-10)»; фазы A–D тоже. C1 (stats-разъём плагинов) отдана владельцем в план телеметрии (решение Р-2в 2026-08-09) → stage6 → переведена в dx А.2 → closure 4.5. F1 (повторное ревью) состоялась: `docs/reviews/2026-08-10_observability-acceptance-review.md`, итог 7/10 при пороге 8+, порог не взят. Код-коммитов 17 (всего 36), последний код `2942c949c` 2026-08-10 (D4). Ветка влита в `main`.
- What changed since: порог 8+ не взят, остаток поглотил f1-hardening, затем roadmap, затем closure (его основа — полное ревью 2026-08-28).
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: C1 → closure 4.5 (уже там). Больше нет.
- Header honesty: да (шапка честнее счётчика).
- Confidence: high.

### observability-f1-hardening  — verdict: ARCHIVE-SUPERSEDED
- Goal: добить 22 находки приёмки F1 (Н-1…Н-22) до порога 8+.
- Real state: 0/16 (7 «unmarked»), статус SUPERSEDED в шапке в день создания (2026-08-10) → roadmap. 0 код-коммитов с Refs на этот план; работа шла под Refs roadmap. Ветки нет.
- What changed since: задачи перенесены в roadmap этапы 1–5, которые закрыты (трассировка Н-1…Н-22 есть в roadmap).
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: нет. Файл справочный (шаги, инъекции); roadmap на него ссылается — при архивации roadmap вместе, чтобы не сломать ссылки.
- Header honesty: да.
- Confidence: high.

### observation-port  — verdict: ARCHIVE-DONE
- Goal: порт наблюдений как четвёртый канонический слот; убрать поимённое снятие уровней и парный ключ владения, оставить один писатель чисел.
- Real state: счётчик 22/24: «0.2 pending» и «2.4 pending» неверны. 0.2 закрыта (`6e1a5bec7` 2026-08-19, Ф0 «APPROVED 9/10», merge Ф6 разблокирован), 2.4: критерий отмечен [x] с датой 2026-08-23. Ф5 «добор» закрыта 2026-08-26 (`66e7e0b3f` вердикт и матрица инъекций). Код-коммитов 52 (всего 96), последний код 2026-08-26. Ветка влита.
- What changed since: ADR-PM-038 переписал механизм владения метрик в stage6; опись удаления выполнена.
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: нет.
- Header honesty: нет. Шапка «Статус: черновик на утверждение владельцу. Код не тронут» при 52 код-коммитах и закрытых Ф0–Ф5. ORDER.md это уже отмечает значком.
- Confidence: high.

### telemetry-stage6  — verdict: ARCHIVE-DONE
- Goal: плагин отдаёт бизнес-метрику тем же жестом, что лог; доставка `kind=stats`, пределы, flight recorder.
- Real state: 11/13; «1.2 ServiceContext» переведена в `observability-dx` решением владельца 2026-08-13 (в теле плана написано «ПЕРЕВЕДЕНА»), теперь это closure 4.5. «3.5 K-8» устарела: строка 1833 плана «Блокер K-8, державший РТ-2 с 12 августа, снят измерением, а не решением»; флип РТ-2 сделан (`20327f66c` 2026-08-19, приёмка флипа). Код-коммитов 36 (всего 81), последний код 2026-08-19. Ветка в `main` (`ff0308f44`, 2026-08-19).
- What changed since: гейт Ф6 не принят (2/10 в ревью 2026-08-28), его переприёмка = closure 5.4. Механизм владения метрик переписан observation-port (в плане есть блок «ВАЖНО» об отмене пунктов Р3.5-11…15).
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: 1.2 → closure 4.5 (уже там); гейт Ф6 → closure 5.4 (уже там). Дефекты S-1…S-24 живут в `plans/queue/defects.md` (не в плане). Идеи С-4 wide event / С-5 flight recorder: flight recorder построен (`observability_flight.py`), wide event снят вердиктом CTO 2026-09-07 (closure 3.6 SUPERSEDED, «метрики объявляет потребитель»).
- Header honesty: частично. «Ред. 5 — исполнение начато» верно на 2026-08-12, но к 2026-08-19 всё закрыто; шапка этого не говорит. 2645 строк.
- Confidence: medium. Статус 3.5 выведен из строки 1833 и коммита флипа; чекбоксы 3.5 я не пересчитывал (S-3 в defects.md говорит, что они однажды врали).

### observability-dx  — verdict: ARCHIVE-SUPERSEDED
- Goal: план-спутник про форму наблюдаемости: разъём для авторов сервисов, меньше дверей конфига, readback по протоколу, карта потребления, дисциплина процесса.
- Real state: 0/0 (задачи в таблицах), 0 код-коммитов с Refs, ветки `feat/observability-dx` нет. Не начат.
- What changed since: трек А.2 = closure 4.5 (`ServiceContext`), трек В = closure 4.3 (протокол readback, `ObservabilityReadback` в `interfaces.py`). Это подтверждено и в closure `plan.md`, и в ORDER.md §4.3.
- Fit with today's priorities: нет; идеи дисциплины полезны, но не нужны сейчас.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage (в `backlog.md` их НЕТ, проверено grep'ом): Б.2 `read_env_pair` в одном месте; Б.3 П-11 одно правило приоритета env против конфига (нужен ADR); Б.4 карта дверей конфига на одной странице `CONTROL_PANEL.md`; Б.5 решение по алиасам `logger.sink.*`; Г.2 сценарная приёмка потребления (пять типовых вопросов оператора); Д.1 `scripts/run_all_gates.py` (ORDER.md обещает, что оно в backlog — не записано; один сводный вердикт вместо трёх команд; перекликается с Ж Ф2 «гейт fw-тестов без abort»); Д.2 карантин флейков маркером `quarantine(reason, until)` — сегодня в дереве `quarantine`/`run_all_gates` не найден (`git ls-files`); Д.3 post-commit-hook свежести qex (команда `/mcp-qex:install-reindex-hook` уже есть); Д.4 документы-спутники в гейте закрытия плана (пересекается с plans-progress-dashboard).
- Header honesty: да по факту «не начат»; ORDER.md тоже называет его не начатым.
- Confidence: high.

### telemetry-coherence-remediation  — verdict: ARCHIVE-DONE
- Goal: согласовать частотный контракт телеметрии (когда и как часто что публикуется).
- Real state: 11/12; Task 3.2 «ЧАСТИЧНО». Код-коммитов 20 (всего 45), последний код — слияние `13623920d` 2026-07-18. Ветка `feat/telemetry-coherence` в `main`. Шапка: «ЗАКРЫТ 2026-07-18, 47/60 цель достигнута».
- What changed since: хвост 3.2 шаг 3 (watcher фанит publish-секцию детям) помечен в roadmap этап 6 как «вход УСТАРЕЛ, закрыт 5.11.f (L1-конверт)»; наследник «W2: адресные per-process runtime-дельты не персистятся, respawn теряет точечную правку» принят в stage6 (задача 3.4 спеки).
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: нет (хвост W2 уже в stage6; stage6 закрыт — если W2 не закрыта там, это единственный возможный остаток; я не проверял, medium).
- Header honesty: да.
- Confidence: high по закрытию; medium по судьбе W2.

### telemetry-dashboard  — verdict: ARCHIVE-DONE
- Goal: интерактивный дашборд телеметрии на PyQtGraph.
- Real state: 6/6. Код-коммитов 6 (всего 13), последний код `becd00e76` 2026-07-17; слияние `1f5083d3`, ниты `937bc541`. Обе ветки в `main`.
- What changed since: ничего; GUI-работы отложены О-16, и этот план их не требует.
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: нет.
- Header honesty: да (шапка исправлена в сверке 2026-08-10 с «DRAFT»).
- Confidence: high.

### telemetry-publish-control  — verdict: ARCHIVE-DONE
- Goal: управляемая публикация телеметрии: частота и вкл/выкл (publisher-gate, центральный троттл, ADR-PM-018).
- Real state: 10/10. Код-коммитов 8 (всего 14), последний код `b8ee3353e` 2026-07-17; слияние `1f6bbd40a`. Ветка в `main`.
- What changed since: «каскад двух плоскостей» закрыт в unified-routing Ф8.2 (2026-08-07).
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: нет.
- Header honesty: да.
- Confidence: high.

### gui-telemetry-read-model  — verdict: ARCHIVE-DONE
- Goal: GUI читает телеметрию из локальной read-model, а не блокирующими подписками (ADR-136); убрать шторм при открытии вкладки.
- Real state: 11/11. Код-коммитов 8 (всего 11), последний код `4d33e21d6` 2026-07-16 (CI-инвариант «открытие вкладки без блокирующего IPC»). Ветка в `main`. Документ-коммит 2026-08-14 «долг K-5 — необъяснённая задержка доставки stats».
- What changed since: заменил `telemetry-delivery-simplification`. Долг K-5 (задержка `kind=stats` до GUI 5.6–13.4 с, стенд 2026-08-14) живёт в `plans/queue/defects.md` строка K-5.
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: K-5 уже в defects.md. Остатка нет.
- Header honesty: да.
- Confidence: high.

### telemetry-delivery-simplification  — verdict: ARCHIVE-SUPERSEDED
- Goal: упростить путь доставки live-телеметрии (целевая архитектура D, snapshot-канал).
- Real state: 2/6. Код-коммитов 3 (всего 7), последний код `7f81383ad` 2026-06-04. Ветка `feat/comm-system-target-architecture` (родитель в `_archive/`). Шапка SUPERSEDED 2026-07-16.
- What changed since: gate из плана сработал 2026-07-16; вместо отдельного snapshot-канала построена read-model поверх уже живого потока дельт (`gui-telemetry-read-model`, ADR-136). Строки 3.1 и 3.2 (издатели FPS/latency и `system.health`) выполнены коммитом `7f81383ad`, хотя помечены pending; 1.2 и 2.1 (multi-subscriber bridge, fail-loud на доставке IO→Qt) относятся к снятой архитектуре.
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: 2.1 «fail-loud в доставке IO→Qt и десериализации дельт» — сам принцип жив (правило «ошибки не глотать»), но задачи привязаны к снятому коду; отдельно не переносить.
- Header honesty: да (SUPERSEDED).
- Confidence: high по замене; medium по 1.2/2.1 (сверял только заголовки).

### telemetry-pull-on-demand  — verdict: ARCHIVE-SUPERSEDED
- Goal: телеметрия по опросу (уровни) и push для фронтов — направление владельца.
- Real state: 0/0, 0 коммитов с Refs, DRAFT с 2026-07-22; ветки не было.
- What changed since: SUPERSEDED 2026-08-12 → `telemetry-stage6` (Ф3, задача 3.2). Модель «уровни по опросу, фронты push'ем» реализована в stage6 (heartbeat-опрос уровней, `current_levels_snapshot`).
- Fit with today's priorities: нет.
- Blocker / trigger: нет.
- Next concrete step: нет.
- Salvage: нет.
- Header honesty: да.
- Confidence: high.

---

## 2. Итог

### 2.1 Сводная таблица

| slug | verdict | одна строка |
|---|---|---|
| observability-closure | DEFERRED-OWNER | живой; 33/46, 13 реально открытых; за Ж; первая по сроку 4.3b |
| otel-export | DEFERRED-OWNER | живой; 13/21; 3.4 BLOCKED на closure 4.3b; старт otel — решение №8 за Ж |
| observability-roadmap | ARCHIVE-DONE | этапы 0–5 закрыты; ПЕРЕД архивом внести этап 9 и часть этапа 8 в backlog |
| observability-unified-routing | ARCHIVE-DONE | Ф0–Ф8 в `main` (`23184cc48`); счёт 22/32 — артефакт парсера; шапка врёт |
| observability-review-remediation | ARCHIVE-DONE | A–E закрыты; F1 дала 7/10; C1 → closure 4.5 |
| observability-f1-hardening | ARCHIVE-SUPERSEDED | в день создания ушёл в roadmap; 0 код-коммитов |
| observation-port | ARCHIVE-DONE | Ф0–Ф5 в `main`; «0.2» и «2.4 pending» — ложные; шапка «черновик» врёт |
| telemetry-stage6 | ARCHIVE-DONE | в `main` (`ff0308f44`); 1.2 → closure 4.5, гейт Ф6 → closure 5.4 |
| observability-dx | ARCHIVE-SUPERSEDED | не начат; А.2 = 4.5, В = 4.3; Б.2–Б.5, Г.2, Д.1–Д.4 внести в backlog |
| telemetry-coherence-remediation | ARCHIVE-DONE | слит 2026-07-18 |
| telemetry-dashboard | ARCHIVE-DONE | слит 2026-07-17 |
| telemetry-publish-control | ARCHIVE-DONE | слит 2026-07-17 |
| gui-telemetry-read-model | ARCHIVE-DONE | ADR-136, слит 2026-07-16; долг K-5 в defects.md |
| telemetry-delivery-simplification | ARCHIVE-SUPERSEDED | заменён gui-telemetry-read-model |
| telemetry-pull-on-demand | ARCHIVE-SUPERSEDED | заменён telemetry-stage6 Ф3 |

Итог после аудита: живых планов наблюдаемости **два** — `observability-closure` и `otel-export`. «Что ещё» из вопроса координатора: третьего живого плана нет. Но у наблюдаемости есть три дома кроме планов, и их нужно держать живыми: `plans/queue/defects.md` (K-5, S-1…S-24 — дефекты stage6/closure, на них ссылаются тесты), `plans/queue/backlog.md` (сейчас в нём нет ничего про наблюдаемость — исправить, см. salvage), и `docs/claude/OPEN_QUESTIONS.md`. Все 13 остальных можно архивировать одним коммитом по О-8 после того, как salvage записан.

### 2.2 Задачи closure Ф4, которые трогают `observability_wiring.py` (Ж Ф3 ждёт их)

Источник: поля **Files:** в `plans/observability-closure/phase-4-scale-and-form.md`; список совпадает со строкой в `lifecycle-owner-scope/plan.md:21` (там названы 4.1, 4.3, 4.3b, 4.14). Последняя правка самого файла `observability_wiring.py` — `acfbfe524` 2026-09-07 (closure 3.8), с тех пор не менялся.

| Задача | Статус | Что делает с `observability_wiring.py` |
|---|---|---|
| 4.3b | PENDING | реестр форвардеров `process_module._observability_forwarders`; канал создаётся в замыкании `:279-283`, результат `push_batch` выбрасывается; секция `forwarders` в readback |
| 4.3 | PENDING | `_sink_readback` (`:380-420`); AST-страж «`getattr` по менеджерам = 0» по `observability_reload.py` и `observability_wiring.py` (на 60c1fe6c таких было 19); распил `builtin_commands.py:1576-2300` |
| 4.14 | PENDING | такт свипа ретенции (`purge`, `optimize`) |
| 4.1 | DEFERRED (до профиля, показавшего нагрузку) | `:120-130` — канал уровней как карта последних значений, ёмкость из политики |

Не трогают файл: 4.5, 4.6, 4.12 (`telemetry.py`, `process_manager_process.py:3151`), 4.15 (`frame_trace.py`, `observability_reload.py`), 4.16 (`logger_core.py`, `observable_mixin.py`), 4.8/5.x (стенд, документы).
Ж Ф3 переписывает пары `wire_/unwire_` в этом файле (`DESIGN.md:236`). Значит реальных «ждёт» три задачи: 4.3b, 4.3, 4.14. Задача 4.3b одновременно блокирует otel 3.4, поэтому она первая по пользе.

## 3. Пересечения и противоречия между планами

1. **Счётчик `plans_progress` врёт по 6 планам группы.** unified-routing (22/32, 9 unmarked), review-remediation (7/20, 12 unmarked), f1-hardening (0/16), observation-port (22/24), stage6 (11/13), delivery-simplification (2/6). Причина: задачи записаны заголовками `### Task X` без статус-маркера в формате парсера, либо статус стоит в теле. Все эти планы стоят в `plans_progress` на tier 4.3 (архив): дашборд не ошибается в решении «закрыт», но врёт в «done/total». Для plans-progress-dashboard: отдельный вход «шапка DONE, счёт < 100 %».
2. **ORDER.md §4.3 обещает salvage, которого нет.** Фраза «этап 9 → backlog.md», «Д.1 → backlog» не выполнена: `backlog.md` (51 строка) про наблюдаемость молчит.
3. **ORDER.md противоречит closure по порядку 4.5.** ORDER Ф2: «4.5 `ServiceContext`; миграция robot_comm/vfd_comm/modbus» (польза для Р). ORDER Ф6: «4.3b → 4.6 → 4.15 → 4.14». closure `plan.md`: «4.5 (после 4.6)», 4.6 «после 4.3b». То есть 4.5 в ORDER стоит раньше, чем разрешает closure. Если владелец захочет 4.5 раньше (польза Р: 0 записей ошибок на 2336 строк журнала `robot_comm`), надо сначала сделать 4.3b и 4.6, иначе нарушается зависимость плана.
4. **decisions.md: №2 и №3 устарели.** №3 (Ф5.2 а/б/в) закрыт вариантом (г) 2026-08-09, тело unified-routing это подтверждает. №2 «Р-1…Р-7 roadmap»: Р-7 помечена `[x]` в roadmap 2026-08-11; этапы 1–5 (где живут Р-1…Р-6) закрыты — решения применены. Реально открытые наблюдательные решения: №2b (Р-2…Р-8 closure) и №8 (старт otel и его Р-6; Р-6 в roadmap уже закрыта вариантом б, значит №8 сводится к «стартовать ли»). Это сокращает «отложенные до Ж» с четырёх до двух.
5. **Устаревшие шапки.** closure (статус 2026-09-04), otel-export (блок «Ф4–Ф5 не начаты»), unified-routing (открыты Ф5.2/Ф5.4), observation-port («код не тронут»), roadmap («исполнение начато владельцем (этап 0)»), stage6 («исполнение начато»). Исправлять шапки в закрываемых планах не нужно (их архивируют); исправить closure и otel-export.
6. **Ветки и worktree (О-15).** В `main` влито 15 веток группы: `feat/observability-closure`, `feat/otel-export`, `feat/observation-port`, `feat/observability-unified-routing`, `feat/observability-review-remediation`, `feat/observability-roadmap`, `feat/observability-control-plane`, `feat/telemetry-stage6`, `feat/telemetry-coherence`, `feat/telemetry-dashboard`, `feat/telemetry-dashboard-followups`, `feat/telemetry-publish-control`, `feat/gui-telemetry-read-model`, `feat/pipeline-telemetry-and-demo`, `tests/otel-t22-blind`; четыре из них есть и на `origin`. Не влита одна: `draft/observability-2.3b` (1 коммит `8990b3f6c` 2026-08-03 «Ф2.3b черновик»; задача 2.3b закрыта позже Ф8.1 через `root_level_rule`) — кандидат на удаление. Worktree `.claude/worktrees/otel` (ветка влита) и `otel-t22`: в `otel` застейджены 5 файлов (память CTO `project_otlp_http_timeout_is_not_a_call_ceiling.md`, `docs/sessions/2026-09-12.md`, `logs_plane_probe/observability.db` и др.) — перед удалением открыть: журнал сессии 09-12 и заметка CTO могут быть единственным следом, `logs_plane_probe/*` — мусор. Worktree `otel` держит ветку `feat/otel-export`: удалять только вместе с решением №8, иначе агент otel потеряет рабочее дерево (стейджинг не потеряется, коммит — нет).
7. **Дубли в содержании.** `observability-f1-hardening` (спека 214 строк) целиком повторяется в roadmap этапах 1–5; `telemetry-pull-on-demand` повторяется в stage6 Ф3; `observability-dx` — частично в closure 4.3/4.5. Ничего не противоречит, но для читателя лишний шум.
8. **Ссылки.** Closure и otel-export ссылаются на roadmap, dx, stage6, observation-port (`plan.md` closure, строки 4–8; otel-export строки 3–7). При архивации в `plans/_archive/` эти ссылки сломаются, нужен проход `link_check` (closure 5.2 как раз вводит его в гейт). Архивировать вместе с обновлением ссылок или оставить заглушки.

## 4. Вопросы владельцу (максимум 5)

1. **Архивировать 13 планов группы одним коммитом по О-8?** Рекомендация: да, но только после того, как в `backlog.md` внесены 9.1 fingerprint ошибок, 9.2 fd-перехват stderr, 9.3 JSON-сток, Д.1 `run_all_gates.py`, Д.2 карантин флейков, Б.3 правило приоритета env/конфиг. Без этого три идеи владельца (стратегическое ревью 2026-08-10) исчезнут.
2. **Закрыть в `decisions.md` №2 и №3 как устаревшие?** Рекомендация: да. №3 закрыт вариантом (г) 2026-08-09; №2 исполнен этапами 1–5 roadmap. Остаётся ждать Ж только №2b и №8.
3. **Кто идёт первым по `observability_wiring.py`: closure или Ж Ф3?** Рекомендация: closure делает только 4.3b (≈3 файла, он же разблокирует otel 3.4) до Ж Ф3; 4.3 (распил, AST-страж getattr) и 4.14 (ретенция по байтам) ждут Ж Ф3 и переписываются поверх новых `wire_/unwire_`. Иначе Ж Ф3 и 4.3 правят одни и те же строки дважды.
4. **Снять из closure пять отложенных задач (4.1, 4.2, 4.7, 4.9, 4.10) и три снятые (3.4, 3.6, 3.7) в `backlog.md` с их условиями?** Рекомендация: да. Тогда счётчик closure станет честным (33 из 38, а не 33 из 46), а в плане останется то, что реально ждёт владельца: 13 задач.
5. **Оставлять ли otel-export отдельным планом после Ж?** Рекомендация: да, но ставить его после closure 4.3b и только по слову владельца (портфолио-сигнал, не продуктовая цель по собственной «честной оценке» плана: балл вердикта двигают P-1 и P-2). Если владельцу нужен «OTel виден снаружи» к конкретной демонстрации — назвать дату, иначе остаётся DEFERRED.

## 5. Что я оставил открытым и что в моей работе ненадёжно

- Я **не открывал код** задач в 7713-строчном unified-routing и 2645-строчном stage6 целиком. Статус Ф5 и Ф8 взят из таблиц самого плана и слияния `23184cc48`; для stage6 3.5 (K-8) — из строки 1833 плана и коммита флипа `20327f66c`. Чекбоксы 3.5 не пересчитывал, хотя defects.md S-3 фиксирует, что они однажды врали.
- Не проверял, закрыл ли кто-нибудь этап 8 roadmap («~60 точек проглоченного сбоя», «ретеншен аудита ≠ ретеншен логов»). В closure `plan.md` слова «проглоч» нет, в `backlog.md` тоже. Возможно, остаток живой. Рекомендация: отдельный grep по `except Exception: pass` с адресом перед архивом.
- Судьба хвоста «W2» (персист адресных runtime-дельт, respawn теряет точечную правку) из coherence-remediation → stage6 3.4 не проверена; возможно, не закрыта.
- Не сверял кодом «ложный счёт» observation-port 0.2: опирался на коммит `6e1a5bec7` и «APPROVED 9/10» из `f8ef3a28d`.
- Не смотрел содержимое грязного worktree `otel` (только `git status --short`, 5 строк). Что в застейдженных файлах, не знаю.
- qex недоступен, граф graphify не использовался; все выводы по связям (Files у задач Ф4) — из текста плана, а не из актуального дерева. Файл `observability_wiring.py` не читал, только историю и grep по плану. Если задача 4.3 уже частично реализована, моя строка в 2.2 устарела.
- Даты последнего код-коммита для closure (`5a83c2323`, 2026-10-01) — это слияние ветки другого плана с задачами, названными «4.4/4.5/4.6» ради transport; по closure реальный последний код — 4.4 (`94818d29f`, 2026-09-23). Эту разницу я не разгребал глубже.
- Подсчёт «13 реально открытых» в closure: задачи 4.3, 4.3b, 4.5, 4.6, 4.8, 4.12, 4.14, 4.15, 4.16, 5.1, 5.2, 5.3, 5.4 — взято из `plans_progress --json`, он верен только настолько, насколько верны отметки в строке «Порядок выполнения».
