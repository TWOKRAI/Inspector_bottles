---
name: feedback_server_file_in_home_needs_dir_autouse_isolation
description: "Сервер, пишущий файл в HOME при старте (токен порта управления ~/.multiprocess_framework/ctl_<порт>.token), требует autouse-изоляции HOME/USERPROFILE на уровне КАТАЛОГА тестов, с отключением для session-фикстуры живого бэкенда; server writing a file under HOME needs a directory-wide autouse HOME isolation"
module: [process_manager_module]
mechanism: [fixtures, test-infra]
metadata:
  type: feedback
  last-verified: 2026-11-22
---

Задача 0.12b: ПМ при старте пишет токен в `~/.multiprocess_framework/ctl_<порт>.token`. Офлайн-прогон `backend_ctl/tests` писал такие файлы в НАСТОЯЩИЙ HOME (5 файлов при SIGKILL ПМ). Метки изоляции по отдельным файлам и общая фикстура `tmp_home` дыру не закрыли: любой новый тест, поднимающий сервер, снова писал в HOME.

**Why:** изоляция «по файлам» забывается ровно в новом тесте; а изоляция «всегда» ломает живой режим: session-фикстура бэкенда пишет токен под одним HOME, а клиент теста читает под другим.
**How to apply:** `conftest.py` каталога — autouse-фикстура ставит `HOME` и `USERPROFILE` во временный каталог; она выключается для `--backend-live`, `headless_backend` и маркера `harness_smoke` (цена маркера — такие тесты идут под настоящим HOME, записать в OPEN_QUESTIONS). Проверка: `ls -la ~/.multiprocess_framework` до и после офлайн-прогона одинаково. Каталоги тестов вне изоляции (`app_module`, `examples/minimal_app`, `apps/line_sim`) всё ещё пишут — перечислять в OPEN_QUESTIONS, а не считать закрытыми. Инъекция «изоляция снята» (J10 в 0.12b) показывает дыру числом файлов.

Related: [[feedback_injection_must_cover_all_check_sites]]
