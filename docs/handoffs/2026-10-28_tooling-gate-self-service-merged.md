# Handoff: самообслуживание окон и merge через гейт (полоса tooling, 2026-10-28)

Отчёт: docs/reports/2026-10-28_tooling-gate-self-service_task-1.1.md. Ветка `feat/tooling-gate-self-service`.

- Окно: `machine_gate.sh request <s> quiet|heavy|stand <min> <what…>` только когда готов стартовать СЕЙЧАС; `wait <s>` в фоне; `release <s>`; `extend <s> <min>`.
- Слияние: `merge-begin <s> <branch>` / `merge-end <s>` вместо «сливаю» / «ок». Без `machine.lock` подкоманды дают rc=2 — окно не нужно.
- Сообщения между чатами: только вопрос владельцу, владение файлом, находка в чужом коде. Без «принято». Отчёт — файл полосы.
- Находки реестра — файл в `plans/queue/inbox/` (формат — README там); координатор или любая сессия сворачивает раз в полдня и присваивает C-NN. Первый файл — `2026-10-28_inspector-bottles-dd_1.md` (`read_lock` изредка видит пустой замок).
- Координатору: снять ручные `waiting:` (в замке `inspector-bottles-78 | stand`), иначе автовыдача откроет их первой.
- Открыто: «now читается один раз», реальный дедлайн `wait --timeout N>0`, гонка двух реклеймеров — тестами не закрыты.
- Следующая полоса: следующая строка `plans/queue/ORDER.md`; сессия tooling после влития — `/clear` по этому handoff.
