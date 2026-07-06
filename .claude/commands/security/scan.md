---
description: Run Semgrep SAST (deterministic code-vuln gate) — injection, deserialization, unsafe crypto, hardcoded secrets
---

Запусти детерминированный SAST-скан (Semgrep) — дополняет LLM-ревью `/security-review`
машинно-проверяемым гейтом, который не «забывает» известные паттерны.

```bash
python .claude/plugins/security/scripts/sast_scan.py
```

Что ловит (ruleset `auto`): SQL/command/template injection, небезопасная
десериализация, path traversal, слабая криптография, hardcoded secrets, unsafe
`eval`/`exec`, SSRF и др. — по правилам community-реестра Semgrep под язык проекта.

Полезные варианты:
- `python .claude/plugins/security/scripts/sast_scan.py --root src` — только подкаталог.
- `python .claude/plugins/security/scripts/sast_scan.py --format json` — для CI/нотификаций.
- `python .claude/plugins/security/scripts/sast_scan.py --config p/python` — конкретный ruleset вместо `auto`.
- `python .claude/plugins/security/scripts/sast_scan.py --no-strict` — отчёт без падения (exit 0 даже при находках).
- `--exclude '<glob>'` — добавить путь в исключения (поверх дефолтных `.venv/node_modules/...`).

**Exit-коды:** `0` — чисто (или `semgrep` не установлен → skip), `1` — есть находки (strict), `2` — ошибка запуска semgrep.

**Когда использовать:**
- Перед коммитом / в `pre-push` (вместе с `/core:quality:secrets-audit` и sentrux).
- В CI как gate перед merge в main (`--format json`).

**Замечания:**
- Inline-suppression: добавь `# sast: ignore` в строке с находкой для разовых исключений (рядом с нативным `# nosemgrep`).
- Нужен бинарь `semgrep` (`pipx install semgrep`). Без него скан — no-op (exit 0), проект остаётся зелёным.
- Per-edit вариант (PostToolUse-хук `hooks/semgrep-scan.sh`) по умолчанию **выключен** — медленный/шумный, opt-in через `.claude/settings.json`.

$ARGUMENTS
