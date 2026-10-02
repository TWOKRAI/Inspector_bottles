# Task 1b.2d — независимый тестер (RED), отчёт

Ветка `tests/gs-1b2d-blind` @ addadf7de. Файлы: `multiprocess_prototype/adapters/tests/test_1b2d_copy_agrees_with_original.py`, `.../test_1b2d_no_python_validators_contract.py`.

## Прогон (команда лида)
`26 failed, 29 passed` за ~9 с. Все красные — AssertionError (0 ImportError/collection), все на стороне «копия» (в сообщениях 0 вхождений «оригинал: »).

| Красные | Кол-во | AC |
|---|---|---|
| test_container_element_types_rejected_like_original (10 полей) | 10 | AC1 |
| test_line_filter_cross_field_rule (margin_below_radius, radius_above_margin) | 2 | AC2 |
| test_otel_endpoint_blank_rejected (blank, empty) | 2 | AC2 |
| test_otel_endpoint_without_signal_path_rejected (no_path, no_scheme) | 2 | AC2 |
| test_otel_endpoint_whitespace_normalized_identically | 1 | AC2 |
| test_otel_headers_only_env_placeholders (literal, tail) | 2 | AC2 |
| test_otel_unknown_level_rejected (bogus, warn->WARNING, debug->DEBUG) | 3 | AC2 |
| test_otel_batch_must_fit_queue (batch>queue, queue<batch) | 2 | AC2 |
| test_oracle_copy_agrees_with_original_for_all_registers | 1 | AC3 |
| test_register_classes_have_no_python_validators | 1 | AC4 |

Зелёные (29): 10 якорей «оригинал отвергает» (`..._anchor`), 10 положительных контролей, граничные «разрешено» (line_filter ×2, batch/queue ×2), env-placeholder принят, `test_pinned_literals_hold_on_original`, `test_oracle_no_divergence_outside_known_list`, 2 контроля обходчика AC4.

## Проверка, что тесты не «красные навсегда»
Throwaway-плагин (scratchpad, не в репо) подменил `from_catalog` на `from_registry` (копия = оригинал): `52 passed` в файле AC1-3. То есть красное — именно разрыв копии, а не неверный литерал/харнесс.

## AC4: прогноз vs факт
Прогноз до запуска: 6 деклараций в 2 регистрах (line_filter 1 model_validator; otel_export 4 field_validator + 1 model_validator, унаследованные от OtelExportConfig). Факт: ровно 6 в 2 — `line_filter: _check_hysteresis`; `otel_export: _endpoint_not_blank, _endpoint_carries_signal_path, _level_is_known, _headers_only_env_placeholders, _batch_fits_queue`.
Первый прогон дал 98 (потом 55) — прогноз был неполон по двум причинам, обе исправлены в тесте: (1) `SchemaBase` сам несёт `model_validator _check_field_constraints` — он есть и у копии (база `SchemaBase`), вычтен; (2) `Decorator.cls_ref` перепривязан pydantic к потомку (унаследованный валидатор «объявлен» в каждом подклассе) — владелец определяется по `vars(klass)`.

## AC3 расхождения (измерено)
92 расхождения в 9 регистрах == литерал `KNOWN_DIVERGENT_REGISTERS` (blob_detector, center_crop, chain_executor, circle_detector, circle_draw, line_filter, modbus_sink, otel_export, overlay_draw). Т.е. сверх AC1/AC2 других разрывов фиксированный набор проб не нашёл.

## Что я интерпретировал, а не следовал
1. «Хранимое после отказа не тронуто» НЕ верно для межполевых правил на ОРИГИНАЛЕ: `max_export_batch_size <- 4096` отклонено (False), но хранится 4096 (pydantic кладёт значение, затем зовёт after-валидатор; не откатывает). Для таких 4 случаев ожидание хранимого — `_OneOf(до, отвергнутое)`; оракул AC3 сравнивает хранимое только когда обе стороны приняли. Для полевых отказов (AC1) хранимое = дефолт-литерал, проверено на оригинале.
2. Присваивание — через `RegistersManager.set_field_value` на обеих сторонах (оригинал = `from_registry(PluginRegistry)`), не голый setattr.
3. Вычитание валидаторов `SchemaBase` в AC4 — моё решение (иначе контракт нереализуем: копия строится на SchemaBase).
4. Добавлено сверх брифа: подслучаи (границы `==`, `""`, `localhost:4318` без схемы, `${X} tail`, нормализация уровня `warn`->`WARNING`, `debug`->`DEBUG`), 3 якоря/контроля. Нормализация уровня — моё чтение «normalizes» из заголовка задачи, в AC2 лида её нет.

## Что оставил открытым / ненадёжно
- Оракул AC3 — фиксированный набор проб (~40 литералов + min/max±1), не доказательство полноты; нестандартные значения (NaN, огромные строки, вложенные структуры глубже 1) не пробованы.
- Поле, где тип расходится только на значении, которого нет в пробах, пройдёт незамеченным.
- Харнесс передаёт payload без JSON/pickle-прогона (как в test_catalog_registers_editing_acceptance); реальная IPC-граница не воспроизведена.
- `KNOWN_DIVERGENT_REGISTERS` — мой прогноз, совпавший с замером; поддержка списка — на разработчике.
- Не делал break-injection против своих файлов (по правилам проекта это делает лид); единственная проверка «зелёный при правильной реализации» — подмена from_catalog на from_registry.
- Консоль Windows (cp1251) искажает русский текст в выводе pytest без `PYTHONUTF8=1`; на вердикты не влияет.
- В venv нет pytest-timeout — `@pytest.mark.timeout` убран; тесты чисто CPU, весь файл ~9 с, потоки с join-дедлайном не нужны (блокирующих вызовов нет).
