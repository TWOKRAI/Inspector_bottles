# CRAFT-config-qt — читать, когда: правишь конфиг или схему Pydantic; трогаешь Qt-виджет; гоняешь qt-mcp
Ядро — в [MEMORY.md](MEMORY.md) и в `.claude/CLAUDE.md` «Test authorship»; здесь детали, оплаченные конкретными провалами.
Соседи: [CRAFT-injection](CRAFT-injection.md) · [CRAFT-tests](CRAFT-tests.md) · [CRAFT-verdict](CRAFT-verdict.md) · [CRAFT-by-module](CRAFT-by-module.md)

## Конфиг и схемы
- [Классифицировать лист по РАЗНИЦЕ двух значений](feedback_classify_a_leaf_by_the_difference_of_two_values.md) — один полюс путает «не потребляется» с «равно дефолту» (24 ложных имени); отпечаток ПЕРЕСЕЧЕНИЕМ полюсов, объединение обвиняет нетронутых соседей
- [Dict at Boundary GUI](feedback_dict_at_boundary_gui.md) — виджеты только dict, не live SchemaBase
- [model_copy не валидирует](feedback_model_copy_does_not_validate.md) — dict вместо схемы молча · [материализованный дефолт](feedback_materialized_default_hides_absence.md) — сверять с model_fields[].default
- [Merge меняет ФОРМУ](feedback_merge_changes_the_form.md) · [форма доставки различается](feedback_fakes_feed_config_flat_so_key_address_defects_are_invisible.md) — PM плоско, ребёнок весь proc_dict
- [update_config мёртв при живом handler](feedback_config_update_dead_with_handler.md) — читать как потребители
- [Ручка-из-env читает свою запись](feedback_env_knob_reads_its_own_write.md) — снимок env на старте · [runtime-конфиг умирает с процессом](feedback_runtime_config_dies_with_the_process.md) — рестарт берёт с диска
- [Дефолт сверху отключает защиту снизу](feedback_upper_layer_default_disables_the_guard_below.md) — молчание вниз как молчание
- [Фасад — белый список](feedback_facade_is_a_whitelist_not_a_passthrough.md) — три точки: схема, фасад+expand, readback
- [Ручка рецепта — в extras](feedback_recipe_knob_must_be_named_in_from_recipe.md) — metadata не доезжает; доказывать сборкой · [путь сверять с публикатором](feedback_default_path_must_match_publisher.md) — drops_count vs drops
- [«Не деградировало» = идентичность сборки](feedback_no_regression_proved_by_identical_build.md) — proc_dict ключ-в-ключ
- [Сравнивать ВАЛИДИРОВАННЫЕ значения, не сырой YAML](feedback_compare_validated_values_not_raw_config.md) — «равно ли дефолту» спрашивают у модели; замер по сырому файлу занижает (4 вместо 5). Пространств имён два: 5 потерь секции = 9 листьев провенанса

## Qt / GUI и смежное
- [Qt widget patterns](feedback_widget_qt_patterns.md) — setFlags recursion, blockSignals, EditTriggers
- [qt-mcp smoke+probe](feedback_qt_mcp_smoke_verification.md) — QT_MCP_PROBE=1:9142; чистка по PID · [зонд только с env](reference_qt_mcp_launch.md) · [стенд всегда с зондом](feedback_qt_mcp_flag_value_is_compared_verbatim.md) · [флаг сравнивается дословно](feedback_qt_mcp_flag_value_is_compared_verbatim.md) — «1:9142» промолчало, рендер не проверялся 3 раунда
- [Живость зонда ≠ рендер](feedback_probe_liveness_is_not_render.md) — окно «невидимо»; snapshot=0 виджетов; кадр только ref-грабом
- [GUI-save сносит yaml-комменты](feedback_gui_save_strips_yaml_comments.md) — git diff перед add
- [Инъекция зелёная, когда подмена совпала с фактом](feedback_injection_green_when_the_substitute_equals_the_fact.md) — «зашить константу» ничего не сторожит, пока нет фикстуры с ТРЕТЬИМ значением
- [Критерий, где тест сам преобразует](feedback_a_criterion_that_transforms_observes_the_library.md) — наблюдает библиотеку, неисполним ничем; чинить швом, не подгонкой
- [Зонд обязан перечислить до того, как спросит](feedback_a_probe_must_enumerate_before_it_asks.md) — пустой ответ про несуществующее имя = «ничего нет»
- [Вторую половину пары мог сделать таймер](feedback_the_off_half_of_a_pair_can_be_done_by_a_timer.md) — success подтверждает доставку, не причину; атрибуцию доказывать журналом адресата
- [Выключил писателя — заглушка стала утверждением](feedback_switching_off_a_writer_promotes_its_placeholder_to_a_claim.md) — посев 0.0 при погашенной публикации = уверенное враньё; семь ложных аномалий
- [Дублёры подают конфиг плоским](feedback_fakes_feed_config_flat_so_key_address_defects_are_invisible.md) — класс «ключ по неверному адресу» тестам структурно невидим; нужен тест на настоящем ProcessConfigHandler
- [Решение осиротило то, что кодировало прежнее](feedback_a_decision_orphans_what_encoded_the_previous_one.md) — одна правка конфига дала ТРИ протухших артефакта; корневой гейт был красен две недели
- [Критерий гейта спорит с решением владельца](feedback_gate_criterion_can_contradict_an_owner_decision.md) — три класса провалов, у каждого свой адресат; третий кодом не чинится
- [Контрол воспроизводит дефект, который заведён ловить](feedback_a_control_reproduces_the_defect_it_was_built_to_catch.md) — «значение успеха, не зависящее от факта» трижды за фазу на трёх этажах; новому счётчику задавать ТОТ ЖЕ вопрос, что убил старый
- [Правило избегания может быть ложным предохранителем](feedback_an_avoidance_rule_can_be_a_false_safety_catch.md) — «не гонять два модуля вместе» неверно: гейт держит их в одном процессе и зелен; 20 красных даёт «эти два БЕЗ остального дерева»
- [Общий дроссель роняет запись, а не голос](feedback_a_shared_throttle_swallows_the_record_not_the_line.md) — `_safe_track` внутри `if should_log`: плоскость не получает НИ трассы, ни полей; «зато счётчик считает все» компенсирует только число. Каноничная дорога — ErrorManager, у неё окна нет
- [Маркер дедупа — утверждение о ЧУЖОМ поведении](feedback_a_dedup_marker_is_an_assertion_about_someone_else.md) — ставился безусловно; без адресата промолчали ОБА и инцидент исчез (1 строка → 0). Ловится числом строк, не наличием маркера. Контрольный вопрос: есть ли конфигурация, где промолчали все?
