---
description: Generate a CycloneDX SBOM (Software Bill of Materials) via syft/cdxgen — Trivy avoided
---

Сгенерируй SBOM (Software Bill of Materials) в формате CycloneDX JSON — машинный
инвентарь зависимостей, который потом скармливается CVE-сканеру (`/security:cve`),
Dependency-Track или GitHub dependency-review.

```bash
python .claude/plugins/security/scripts/sbom_gen.py            # -> sbom.cdx.json
```

Варианты:
- `python .claude/plugins/security/scripts/sbom_gen.py --output -` — в stdout (для пайпа).
- `python .claude/plugins/security/scripts/sbom_gen.py --root . --output build/sbom.json` — путь артефакта.

Связка с CVE-сканом:

```bash
python .claude/plugins/security/scripts/sbom_gen.py --output sbom.cdx.json
osv-scanner --sbom=sbom.cdx.json
```

**Exit-коды:** `0` — SBOM записан (или генератор не установлен → skip), `2` — генератор упал.

**Когда использовать:**
- При подготовке релиза/поставки — приложить SBOM к артефактам (compliance, supply-chain аудит).
- Для воспроизводимого CVE-аудита по зафиксированному снимку зависимостей.

**Замечания:**
- Генератор: `syft` (предпочтительно) или `cdxgen` — берётся первый найденный в PATH. Установка: `brew install syft` / `npm i -g @cyclonedx/cdxgen`. Без них — no-op.
- ⚠️ **Trivy намеренно не используется** как генератор — supply-chain компрометация фев–мар 2026. Если нужен Trivy — пинни проверенный digest и сверяй подпись.
- Генерация **opt-in** (артефакт нужен не всегда), но команда всегда доступна.

$ARGUMENTS
