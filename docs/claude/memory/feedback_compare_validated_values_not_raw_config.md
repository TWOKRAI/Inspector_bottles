---
name: feedback-compare-validated-values-not-raw-config
description: "To ask 'is this config key equal to the schema default', compare VALIDATED model fields — raw YAML vs a default model_dump answers a different question and undercounts"
metadata:
  node_type: memory
  type: feedback
  originSessionId: a7409bf7-0364-44aa-849b-c277ab5d4aa0
  modified: 2026-08-18T12:16:03.884Z
---

**Вопрос «равно ли значение ключа дефолту схемы» задаётся ВАЛИДИРОВАННОЙ модели, а не
сырому конфигу.** `exclude_defaults` / `exclude_unset` сравнивают поля модели после
валидации; сравнение сырого YAML с `Model().model_dump()` — это другой вопрос
(«совпадает ли написанный литерал с полным дампом дефолта»), и он систематически
**занижает** ответ.

Измерено 2026-08-18 (S-26): в боевом `system.yaml` ключей, записанных со значением,
равным дефолту, — **пять**, а мой замер дал **четыре**. Промахнулся `errors`: секция
в файле частичная (`enabled`, `level`), полный дамп дефолта ей не равен НИКОГДА, хотя
после валидации `sys_config.observability.errors == ObservabilityConfig().errors`.
Метод, который работает: `getattr(validated, k) == getattr(Defaults(), k)`.

**Второй капкан рядом — пространств имён два, и они не совпадают.** Исправление «просто
добавь `errors` в список свидетелей» сделало тест ВЕЧНО красным: `errors` — контейнер, в
плоской карте провенанса его нет вовсе, есть листья `errors.enabled`, `errors.level`,
`errors.include_stacktrace`. И наоборот: `stats` из верхнего списка не выпадает, а два
его листа выпадают — `exclude_defaults` рекурсивен и режет внутри под-моделей. Пять
потерь верхнего уровня = **девять** потерянных листьев.

**Как применять:** правя список ключей в тесте — перечислить обе карты заново
(секция конфига и карта провенанса/листьев), а не переносить имя из одной в другую.
Правило [[feedback_a_probe_must_enumerate_before_it_asks]] действует и на ПРАВКУ теста,
не только на первую его редакцию; здесь оно сработало на первом заходе и было забыто
на втором.

Связано: [[feedback_facade_is_a_whitelist_not_a_passthrough]],
[[feedback_model_copy_does_not_validate]].
