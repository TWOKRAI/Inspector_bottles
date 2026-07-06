---
description: Scan dependencies for known CVEs via OSV-Scanner (lockfile → OSV.dev advisories)
---

Просканируй зависимости проекта на известные уязвимости (CVE/GHSA) через OSV-Scanner —
сверка lockfile'ов с базой OSV.dev. Дополняет SAST (`/security:scan`): SAST смотрит
код, CVE-скан — транзитивные зависимости.

```bash
osv-scanner --recursive .
```

Скан по конкретному lockfile:

```bash
osv-scanner --lockfile=uv.lock        # или poetry.lock / requirements.txt / package-lock.json / go.sum / Cargo.lock
```

Для opt-in pre-push / CI-гейта используй skip-if-absent обёртку (тихо пропускает, если бинарь не установлен):

```bash
bash .claude/plugins/security/hooks/osv-scan.sh
```

**Exit-коды (osv-scanner):** `0` — уязвимостей нет, `1` — найдены уязвимости (gate должен падать), `127`/skip — бинарь не установлен.

**Когда использовать:**
- Как гейт в `/dev:ship` перед релизом и в CI на каждый PR.
- После `uv add` / bump зависимостей — проверить, не притащили ли уязвимую транзитивку.

**Замечания:**
- Нужен бинарь `osv-scanner` (`brew install osv-scanner` или `go install github.com/google/osv-scanner/cmd/osv-scanner@latest`). Без него — no-op (проект остаётся зелёным).
- Формат для CI: `osv-scanner --format json --recursive .`.
- SBOM-driven скан: сгенерируй `/security:sbom`, затем `osv-scanner --sbom=sbom.cdx.json`.

$ARGUMENTS
