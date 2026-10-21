---
name: feedback-windows-realpath-returns-extended-prefix-during-concurrent-mkdir
description: "На Windows `Path.resolve()`/`os.path.realpath` отдаёт путь с префиксом `\\?\`, пока соседний поток создаёт каталог; сравнение resolved-путей для проверки «не вышел из каталога» ложно отказывает на валидном ключе"
module: [services/robot_comm]
mechanism: [concurrency, windows-env]
metadata:
  type: feedback
---

**Замер 2026-10-19, T5.3c c2, `Services/robot_comm/store.py`.** 8 потоков, первая запись в ещё не созданный
каталог устройства: 32–40 ложных `InvalidStoreKey` на 20 раундов. Зонд-обёртка над `os.path.realpath` в той же гонке:
вход `C:\...\robot\r1\programs\p1.yaml` → выход `\?\C:\...\programs\p1.yaml` (23 раза за 15 раундов). В тихом потоке
и пост-фактум — 0 расхождений: первые три зонда «ничего не показали», причину дал только зонд внутри гонки.

**Фикс:** снять `\?\` и `\?\UNC\` с обеих сторон сравнения (`_resolved`), проверку выхода (`..`, ссылки) не ослаблять.

**Триггер:** containment-проверка через `resolve()` + сравнение путей, к которой ходят из нескольких потоков на Windows.
Причину ловить зондом в самой гонке, не чтением и не одиночным прогоном.
