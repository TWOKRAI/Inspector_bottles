---
name: project-owner-push-and-tools-decisions
description: "Owner 2026-10-05: push to origin and test PRs are standing-approved once the other sessions agree; credit first to Atlas; serena and graphify stay but must earn their keep / решения владельца: push, кредит, инструменты"
mechanism: [owner-decision]
metadata:
  type: project
---

Решения владельца 2026-10-05 (сессия лида Атласа, после слияния 2.4e `a040b55f6`).

1. **Push в `origin` и тестовые PR — разрешены постоянно** («да, всегда готов»), условие одно: договориться с
   остальными сессиями. Порядок: `ListAgents` → сообщение каждой живой сессии «пушу main, есть ли незавершённое
   слияние?» → push после ответов. Push без договорённости — нет. `gh` на этой машине не авторизован (2026-10-05):
   PR — через `gh auth login` владельцем или ссылкой GitHub после push.
2. **Облачный кредит ($250 до 2026-11-04) — сначала Атлас.** Остаток, возможно, на ревью `.claude` и `claude_seed`;
   решение позже, пилот P1.1 идёт по своему плану.
3. **serena и graphify остаются** («нужно, чтобы инструменты приносили пользу»): не выключать, а сделать полезными
   и безопасными. Сейчас serena запрещён всем ролям dev (2.4e: сервер привязан к main-checkout, мутатор из worktree
   пишет в main); вернуть пользу — отдельной задачей, а не снятием запрета.

**Why:** владелец снимает ручной шаг «спросить про push» и ставит планку для инструментов — польза, а не наличие.
**How to apply:** перед push — договорённость с сессиями, не вопрос владельцу; инструмент, который мешает,
чинить до полезного, не выключать. Связано: [[feedback_framework_first]], [[project_priority_engine_first]].
