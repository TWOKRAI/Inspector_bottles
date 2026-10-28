ОТЧЁТ: Полоса Р2 · Task SPI хаба · inspector-bottles-69 (до перезапуска сессий — inspector-bottles-00)

Суть: драйвер объявляет свои операции явным `Protocol` и `OpSpec`, команды хаба строятся из них и исполняются через
исполнитель `device_io` по имени. Каталог из одного источника — таблица видов `kinds.py`. Новый вид добавляется строкой
таблицы или подклассом плагина. Костыли сняты: `_bound`, `getattr` по драйверу, опции «на весь вид»; `stop_aware` сверяется по MRO.

Итог: 72 имени команд прежние, 34 получили описания; `robot_point_list {}` → `key_missing` (видимое изменение). Стенд v2
S0–S3: ветка 3 PASS, до `disconnected` 1,18–1,25 с; база main ×3 1,20–1,36 с — не хуже. SERVO/DO 0, SOFT 1/1.

Числа: слепая приёмка А1–А27 (238 тестов, 122 красных на старом коде); инъекции 38 (22 да / 11 частично / 5 нет,
выжившие закрыты тестами) + 9 на SPI.h2/h3; device_hub 922/0/3, плагин 339/0, process_module 3412/0,
process_manager_module 1348/0; validate 0/0; backend/tests 244/0; framework suite 12234/2 — C-4 и
`test_t45a_pacer_late_stays_zero_without_work` (новый флейк под нагрузкой, поодиночке зелёные, вне диффа ветки).

Решения владельца: без костылей, архитектура на рост; В1 «SPI.d сейчас» (C-47 executors из топологии); set_servo v1 — immediate.

Открыто: C-57 (`introspect.*` «No handler» сразу после старта) и C-58 (циклический импорт ProcessHeartbeat) — на main, не SPI;
флейк t45a FramePacer.late под нагрузкой — новая строка реестра;
C-56 (v1-имена GUI → v2) не проверен; 4/64 исполнителя не замерены под нагрузкой; успешный `vfd_get_status` на стенде не наблюдался.

Модели: manager Opus 340k; tech-writer Sonnet 148k; reviewer Sonnet стадия 0 413k; tester Sonnet 281k; teamlead Opus a–d2 419k;
developer Sonnet c2–g 348k; reviewer Sonnet задача ×2 327k; developer Sonnet матрица 252k; developer Sonnet стенд 380k;
reviewer Opus ветка ×3 297k; teamlead Opus SPI.h–h3 320k. Решение нужно: нет.
