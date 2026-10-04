# CRAFT.split.md — как разрезать CRAFT.md по триггеру

Источник: `merged/CRAFT.md` (40 233 Б, 164 строки, 173 ссылки, все ведут на feedback_*). Это указатель без собственных уроков. Сегодня агент читает его целиком (12.5 КБ раздела «Канон» перед каждым тестом). Цель: читать 7–10 КБ по триггеру.

## 1. Предложение: четыре файла

R3 предлагал три. Три дают файл 14 КБ (тесты + вакуумные ассерты). Четыре дают 7.5–9.9 КБ. Если лид хочет три — слить `CRAFT-config-qt` в `CRAFT-verdict` (15.5 КБ), остальное не трогать.

| Файл | Триггер (одна строка в шапке файла и в MEMORY.md) | Строки исходного CRAFT.md | Ссылок | Байт после чистки |
|---|---|---|---|---|
| `CRAFT-injection.md` | планируешь инъекции; видишь «0 красных» или «зелёный под заплатой»; пишешь вакуумный ассерт или негатив | строки «Канон» (инъекции: 28, 30, 32, 33, 37, 38, 41–43, 45–49) + 150, 153–155, 160–161 из «Перенесено» + весь раздел «Вакуумные тесты и ассерты» (53–75) | 32 | 9884 |
| `CRAFT-tests.md` | пишешь тест, дублёр, фикстуру, сторожа; гейт зелёный подозрительно | остаток «Канон» (11–15, 20–21, 29, 31, 34–36, 39–40, 44, 50–51) + «Предохранители и механизмы» (76–91) + 151–152 | 28 | 8578 |
| `CRAFT-verdict.md` | выносишь вердикт ревью или приёмки; пишешь «не может сломаться»; разбираешь живой дефект | 17–19, 22–27 из «Канон» + «Классы дефектов (живьём)» (92–108) + 156–159, 162–164 из «Перенесено» | 28 | 8004 |
| `CRAFT-config-qt.md` | правишь конфиг или схему Pydantic; трогаешь Qt-виджет; гоняешь qt-mcp | «Конфиг и схемы» (109–124) + «Qt / GUI» (125–145) | 26 | 7476 |

Сумма после чистки: 33942 Б против 40 233 Б сегодня. Разница — 17 удалённых строк, шапки, пустые строки и пересчёт разделов.

Правила разреза:
1. Каждый файл начинается тремя строками: триггер, «ядро — в MEMORY.md и `.claude/CLAUDE.md` «Test authorship»», ссылка на соседей.
2. Раздел «Перенесено из ядра MEMORY.md 2026-09-05» исчезает: его 18 ссылок разложены по четырём файлам по теме (строки выше). Это закрывает замечание R3 («ситуативные записи, не доказавшие ценность»): они теперь стоят рядом со своим триггером, а не отдельной свалкой.
3. Строка из нескольких ссылок, где часть файлов слита, остаётся. Ссылки на слитые и архивные файлы переписываются на `_archive/<имя>.md` скриптом (шаг 12 рецепта). Список таких ссылок — раздел 3.
4. Каждая строка CRAFT получает префикс-тег `[module: …] [mechanism: …]` только если в файле-цели есть такие теги во frontmatter; иначе не трогать. Не вводить новый формат строки при разрезе.

## 2. Строки, которые CRAFT теряет (17)

Строка исчезает, когда все её ссылки ведут на архивные или слитые файлы. Смысл строки переезжает в выжившего (колонка «куда»). Выживший обязан получить в `description` ключевую фразу строки.

| Строка CRAFT | Заголовок | Куда уходит смысл |
|---|---|---|
| 17 | Три роли авторства | ARCHIVE: `.claude/CLAUDE.md` «Independent tester — on every task»; ARCHIVE: `.claude/CLAUDE.md` «Test authorship» |
| 22 | Ревью ловит стык своих кусков | ARCHIVE: `.claude/CLAUDE.md` «Task launch convention», стадия 0; → feedback_three_lenses_three_defect_classes.md |
| 30 | Заплата на лок вешает ВЫХОД, а не тест | → feedback_inject_only_after_the_work_is_committed.md |
| 32 | Тест не доказан без красного | ARCHIVE: `.claude/CLAUDE.md` «Break-injection is the proof» |
| 36 | Дублёр глушит имена, которые код ЧИТАЕТ | → feedback_a_faithful_fake_still_lacks_the_protocol.md |
| 41 | База инъекций = число собранных | → feedback_injection_zero_may_mean_the_guards_were_not_collected.md |
| 43 | Покрытие на ПРОВЕРКУ ≠ покрытие на утверждение | → feedback_a_guard_that_counts_at_least_once_is_blind.md |
| 45 | Откат — восстановлением | → feedback_a_faithful_fake_still_lacks_the_protocol.md; → feedback_inject_only_after_the_work_is_committed.md |
| 47 | У нуля красных ТРИ чтения | → feedback_injection_zero_may_mean_the_guards_were_not_collected.md |
| 57 | Страж-обходчик не видит удалённого элемента | → feedback_a_guard_that_counts_at_least_once_is_blind.md |
| 85 | Одна дверь — две дороги | → feedback_property_unchecked_at_the_second_party.md; → feedback_test_params_hide_defect_window.md |
| 103 | Шаговая операция требует вычерпывания | → feedback_sqlite_pragma_fails_silently.md |
| 112 | Dict at Boundary GUI | ARCHIVE: .rules/gui.md и корневой CLAUDE.md правило 1 (Dict at Boundary) |
| 120 | Ключ из уже едущей секции | → feedback_recipe_knob_must_be_named_in_from_recipe.md |
| 142 | Сторож ниже заявления охраняет слой, а не заявление | → feedback_a_handmade_readback_leaves_its_producer_unguarded.md |
| 156 | «Сверено» отвечает за вызов, не за охват | → feedback_a_control_reproduces_the_defect_it_was_built_to_catch.md |
| 161 | Общее дерево делает инъекции флейками | → feedback_a_peer_session_shares_the_tree.md |

## 3. Ссылки в оставшихся строках, которые надо переписать (14)

Файл переезжает в `_archive/` или вливается в выжившего. Для таких ссылок скрипт пишет `_archive/<файл>`; выживший уже стоит в CRAFT собственной строкой или добавляется к строке слитого.

| Файл-цель | Строка CRAFT | Ссылка | Статус | Выживший |
|---|---|---|---|---|
| CRAFT-injection | 42 | feedback_broken_injection_is_not_a_vacuous_test.md | MERGE | feedback_injection_zero_may_mean_the_guards_were_not_collected.md |
| CRAFT-injection | 46 | feedback_zero_reds_can_mean_a_useless_layer.md | MERGE | feedback_injection_zero_may_mean_the_guards_were_not_collected.md |
| CRAFT-injection | 59 | feedback_silent_detector_proves_nothing.md | MERGE | feedback_zero_observations_looks_like_a_result.md |
| CRAFT-injection | 61 | feedback_absence_assertion_under_extra_ignore_is_vacuous.md | MERGE | feedback_an_absence_assertion_needs_a_reachability_check.md |
| CRAFT-injection | 62 | feedback_test_values_near_defaults_test_the_default.md | MERGE | feedback_test_params_hide_defect_window.md |
| CRAFT-injection | 63 | feedback_parametrization_built_from_the_subject_collapses_with_it.md | MERGE | feedback_a_guard_that_counts_at_least_once_is_blind.md |
| CRAFT-injection | 64 | feedback_fake_that_always_succeeds_mutes_the_gate.md | MERGE | feedback_a_faithful_fake_still_lacks_the_protocol.md |
| CRAFT-injection | 71 | feedback_tests_invisible_to_testpaths.md | MERGE | feedback_zone_guard_never_closes_the_class.md |
| CRAFT-tests | 78 | feedback_two_safeguards_hide_which_one_holds.md | MERGE | feedback_test_reddens_only_under_a_paired_injection.md |
| CRAFT-tests | 81 | feedback_guard_on_existence_is_not_a_guard_on_content.md | MERGE | feedback_zone_guard_never_closes_the_class.md |
| CRAFT-tests | 82 | feedback_guard_threshold_hides_partial_blindness.md | MERGE | feedback_a_guard_that_counts_at_least_once_is_blind.md |
| CRAFT-tests | 86 | feedback_seam_must_fire_on_full_release.md | MERGE | feedback_test_survived_its_own_break.md |
| CRAFT-config-qt | 114 | feedback_config_delivery_shape_differs.md | MERGE | feedback_fakes_feed_config_flat_so_key_address_defects_are_invisible.md |
| CRAFT-config-qt | 128 | feedback_qt_mcp_always_probe.md | MERGE | feedback_qt_mcp_flag_value_is_compared_verbatim.md |

## 4. Что добавить в CRAFT при разрезе (из разбора STATE-файлов)

- `CRAFT-tests.md`: новый урок `feedback_test_the_door_the_production_caller_uses` (раздел 1 CONSOLIDATED.md, L1).
- `CRAFT-verdict.md`: новый урок `feedback_getattr_default_hides_a_phantom_attribute` (L2); дополнение к `feedback_three_lenses_three_defect_classes` (4.9: 2152 зелёных юнита пропустили мульти-лист merge).
- `CRAFT-injection.md`: закон матриц «расхождение в опасную сторону несёт находку» (дополнение к `feedback_predict_injections_after_writing_tests`, L10).
- `CRAFT-config-qt.md`: без добавлений.

## 5. Что ненадёжно в этом предложении

- Распределение 11 строк «Канон» по файлам сделано по заголовкам и первым строкам, без чтения тел. Спорные: 33 (неубиваемая правка), 43 (покрытие на проверку), 44 (вырожденное значение). Распределение меняет только место строки, не смысл.
- Размеры посчитаны скриптом по строкам с ссылками. Строки без ссылок (шапка, подзаголовки, строка 162 с составным текстом) в сумму не вошли.
- Живость самих ссылок проверена по именам файлов в `merged/`, не по содержимому.
