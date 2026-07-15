---
name: project-f7-g7-num-consumers
description: G.7 num_consumers проведён из топологии + разнос двух ролей loan-протокола (fix fe0f4d41)
metadata:
  type: project
---

Ф7 G.7 резидуал `num_consumers` ЗАКРЫТ (fix `fe0f4d41`, ветка feat/mem-module-consolidation, 2026-07-15).

**Симптом (live webcam_sketch, Windows, флаги on):** процесс с fan-out ТОЛЬКО в GUI (`points→[gui]`) вечно копил `free-list исчерпан` (1200+ дропов на источнике), дисплей точек пуст, FPS проседал.

**Корень + урок — loan-протокол (В3) = ДВЕ роли, НЕ ПУТАТЬ:**
1. **КОНСЬЮМЕР** — дочитав входной zero-copy view, шлёт release ВВЕРХ владельцу. Зависит ТОЛЬКО от флага `FW_SHM_LOAN_PROTOCOL`, НЕ от своего fan-out (points читает кадры lines и обязан их релизить, даже если сам фанится лишь в GUI). → `loan_protocol_enabled` = сырой флаг.
2. **ВЛАДЕЛЕЦ** — держит пул слотов на СВОЁМ выходе (commit refcount=num_consumers). Осмыслен только при ≥1 loan-aware потребителе. → пул создаётся только при `num_consumers>0`.

**Проводка:** `generic_process._count_loan_aware_consumers(chain_targets)` = число целей минус copy-out (`_COPY_OUT_TARGETS={'gui'}` — копируют кадр, release НЕ шлют). 0 loan-aware → пул не создан → round-robin (В1: seqlock+глубокое кольцо защищают copy-out чтение). Дизайн: g5-execution-plan §8.2.1 («занижение безопасно — В1 re-check дропнет; завышение → loan-exhaustion»).

**Грабли (первый заход сломал):** если завязать release-гейт консьюмера (`_loan_active` в pipeline_executor) на `num_consumers>0` своего выхода — GUI-only процесс перестаёт релизить upstream, и upstream (lines) начинает голодать (600+ дропов). Роли ОБЯЗАНЫ быть разнесены. write-path ключится на `self._pool is not None`, не на флаге — поэтому пул=None безопасен.

Verified live: 0 дропов lines/points, дисплей точек заполнен; 1361 (router+process+shared_resources) + 50 (loan/pool/wiring) passed; ruff+pyright чисто. Связано: [[project_f7_g4_done]], [[project_app_module_windows_test_debt]], [[feedback_no_shm_hacks]].
