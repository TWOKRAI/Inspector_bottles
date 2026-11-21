# Заявка на слияние: ветка test/defects-c99-env-leak (Д2, C-99)

Дата: 2026-11-21. Автор: лид полосы Д2 (сессия inspector-bottles-e7). Отчёт: `docs/reports/2026-11-21_lane-D2_C-99.md`.

- **Ветка:** `test/defects-c99-env-leak`, основа `main` `96fb1ea59`; дерево `Inspector_bottles--lane-D2-c99`. Коммиты: `83e6e281a`, `6f238e165`, `b8f9103d6`, `a9ae013cc` (тесты, Layer: tests) и docs-коммит (реестр дефектов C-99/C-102, `OPEN_QUESTIONS.md`, отчёт, эта заявка; Layer: docs).
- **Что входит:** `conftest.py` (+`_APP_ENV_KEYS`, `_restore_app_env_keys`), `multiprocess_prototype/backend/tests/{test_run_app_prototype.py, test_env_alias_isolation.py, test_env_leak_acceptance.py}`, `plans/queue/defects.md`, `docs/claude/OPEN_QUESTIONS.md`, два файла в `docs/reports/`. Код приложения и framework не менялись.
- **Условие слияния — НЕ выполнено:** полный корневой прогон до/после (шаг 6 брифа C-99) ещё не сделан (остановлен 2026-11-21 на ~74 %, окно стенда Пульта 6.5). Сливать после него: красный набор «после» ⊆ «до» минус `test_boot_foundation_names_from_real_manifest`, новых красных нет. Результат допишу в отчёт и в эту заявку.
- **Проверено:** пара писатель → жертва `2 passed`; радиус 7 файлов `66 passed, 2 skipped` (+7 тестов tester = 73); инъекции 17 из 17 совпали; ревью Sonnet 2 итерации, находки закрыты; `ruff check` и `ruff format --check` чисто.
- **Слияние:** тип коммита `feat`, не `merge` (хук режет `merge(...)`); тема вида `feat(tests): merge test/defects-c99-env-leak — откат env приложения между тестами` + `Why:`/`Layer:`/`Refs: plans/queue/defects.md`; сообщение из файла, `git merge -F -` не читает stdin. Пересечений с зонами Ф/К/Пульт/Р2 нет (файлы выше).

**Исполнено 2026-11-21:** слияние сделано по прямому слову владельца («давай в main») до полного корневого прогона; условие выше НЕ выполнено и остаётся открытым — C-99 влит, не закрыт.
