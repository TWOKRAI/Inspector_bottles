# skills-base — стартовые умения для планирования и верификации

**Категория:** skill · **Default:** on · мигрировано в Phase 3 из `skills/brainstorm/`, `skills/verify-done/`.

Четыре skill'а:

- **brainstorm** — подготовка к планированию, расширение идеи;
- **verify-done** — gate перед завершением задачи, контроль выполнения;
- **property-testing** — property-based тесты (Hypothesis) по инвариантам;
- **context-budget** — read-only аудит токен-бюджета `.claude/` (что грузит контекст-окно
  каждую сессию) с приоритизированным prune-list'ом. Дополняет `caveman` (тот сжимает
  *вывод*, а context-budget аудитит *always-loaded baseline*).
