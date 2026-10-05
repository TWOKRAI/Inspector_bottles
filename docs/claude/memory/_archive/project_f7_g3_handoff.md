---
name: f7-g3-handoff
description: "Ф7 G.3 (FrameShm seqlock) ЗАКРЫТ 2026-07-14 merge b54b4689 — целостность кадра torn→0 + видимость деградаций + SHM-cleanup + единый header под пул G.4, всё за dark-launch флагами; 5 пост-merge нитов Fable"
metadata:
  node_type: memory
  type: project
  originSessionId: d14cfa5d-6a6e-4c85-8b24-b008c0e6ee63
---

Ф7 G.3 (FrameShm seqlock) — **ЗАКРЫТ 2026-07-14, merge `b54b4689` (--no-ff) в main** (ветка `feat/constructor-f7`, 26 коммитов от `2eeeed7c`). Весь чек-лист g3-review §4 выполнен; правда — `plans/2026-07-06_constructor-master/g3-review-2026-07-14.md`.

**Что приземлилось:** (a) единое ядро записи FrameShm (снят сломанный find_free_index); (b) seqlock generation-счётчик в 8-байтном SLOT-header, torn 24.8%→0 (гонка = drop, не порча); (c) startup prefix-cleanup сирот SHM из config-регионов+output_frames за флагом (Linux); (d) громкий pickle-fallback — счётчики fallback/torn/drop → RouterManager.get_stats → heartbeat → `state.shm.*` + throttled log_error; header ЕДИНЫЙ под пул G.4 (generation/state/refcount-резерв, не два формата).

**4 механизма за env-флагами default-off (dark-launch):** `FW_SHM_SEQLOCK` / `FW_SHM_OWNER_INCARNATION` / `FW_SHM_PREFIX_CLEANUP` / cache-handles. Прод-флип — ПОСЛЕ soak, tie-in G.7. Дефолт = прежнее поведение, откат бит-в-бит.

**Уроки сессии:** (1) исполнитель гонял тесты точечно, не весь suite → пропустил РЕГРЕСС стух-тестов H7 (write_frames_to_shm снял find_free_index, старые Mock-тесты падали) и ФЛАК full-HD теста; оба пойманы полным прогоном + Sonnet-углами. Правило: перед merge ВСЕГДА полный `run_framework_tests.py`, не точечно. (2) liveness-тесты (valid>0) под нагрузкой suite флачат (голодание потока по GIL); на hot-path safety-инвариант (torn==0) load-независим — liveness выносить на малый кадр/отдельно.

**5 пост-merge нитов Fable (не блокеры, → G.4/отдельно):** (1) GUI-consumer `multiprocess_prototype/frontend/process.py:44` `_recv_frame_mw` не зарегистрирован → torn/drop на дисплей-пути невидимы (safety работает, метрика нет); (2) Linux prefix-cleanup не прогнан на Windows — WSL/CI до прод-флипа; (3) heartbeat молчит про `state.shm.*` при нулевых счётчиках — семантику задокументировать; (4) G.4: refcount(u8) → атомарный RMW cross-process (выбрать примитив).

Ревью-модель подтверждена: 8 Sonnet-углов нашли 8 HIGH у Opus-исполнителя; Fable = merge-вердикт APPROVE-WITH-NITS. [[model-economy-scheme]]. **G.4 (QoS-профили kind + пул per-camera) строится прямо на seqlock-header — следующая фаза** (исполнитель Opus по схеме).
