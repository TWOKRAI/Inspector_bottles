export const meta = {
  name: 'comm-plan-review',
  description: 'Честное профессиональное ревью плана comm-system-target-architecture (+ сверка с первым/промежуточным)',
  phases: [
    { title: 'Review', detail: '5 ревьюеров под разными углами: читают все файлы + спот-чек кода' },
    { title: 'Verify', detail: 'Адверсариальная проверка спорных находок ревьюеров по коду' },
    { title: 'Verdict', detail: 'Senior-синтез: честный вердикт, оценка, must-fix, рекомендация' },
  ],
}

const QEX_GUARD = `КРИТИЧНО: индекс qex СВЕЖИЙ. ЗАПРЕЩЕНО переиндексировать — НЕ вызывай mcp__qex__index_codebase / clear_index / download_model и /qex-rebuild /qex-reindex. Только mcp__qex__search_code для ПОИСКА. ИСКЛЮЧИ из анализа multiprocess_prototype_backup/.`

const DOCS = `Файлы (рабочая директория d:\\PROJECT_INNOTECH\\Inspector_vision\\Inspector_bottles):
- ГЛАВНЫЙ предмет ревью (НОВЫЙ план): plans/comm-system-target-architecture.md
- Контракт-справочник (часть деливерабла): multiprocess_framework/docs/COMMUNICATION_ARCHITECTURE.md
- Первый аудит (для сравнения): plans/comm-system-consolidation.md
- Промежуточный (SUPERSEDED, для сравнения): plans/comm-system-consolidation-v2.md`

// ─────────────────────────────────────────────────────────────────────────
// SCHEMAS
// ─────────────────────────────────────────────────────────────────────────

const REVIEW = {
  type: 'object', additionalProperties: false,
  required: ['lens', 'overall', 'grade', 'strengths', 'weaknesses', 'missing', 'claims_to_verify', 'recommendation'],
  properties: {
    lens: { type: 'string' },
    overall: { type: 'string', description: 'Честная общая оценка по этой грани (2-4 фразы)' },
    grade: { type: 'string', description: 'Оценка по этой грани: A+..F или 1-10' },
    strengths: { type: 'array', items: { type: 'string' } },
    weaknesses: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['issue', 'severity'],
        properties: {
          issue: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
          evidence: { type: 'string', description: 'file:line или §раздел' },
          doc_location: { type: 'string' },
        },
      },
    },
    missing: { type: 'array', items: { type: 'string' }, description: 'Пропущенное покрытие/сценарии/подсистемы' },
    claims_to_verify: {
      type: 'array', description: 'Утверждения ПЛАНА, которые ты подозреваешь и которые надо проверить по коду',
      items: {
        type: 'object', additionalProperties: false,
        required: ['claim', 'why'],
        properties: { claim: { type: 'string' }, why: { type: 'string' } },
      },
    },
    recommendation: { type: 'string', enum: ['approve', 'approve-with-changes', 'needs-work', 'reject'] },
  },
}

const VERDICT = {
  type: 'object', additionalProperties: false,
  required: ['claim', 'verdict', 'evidence', 'confidence', 'correction'],
  properties: {
    claim: { type: 'string' },
    verdict: { type: 'string', enum: ['confirmed', 'refuted', 'partial'] },
    evidence: { type: 'array', items: { type: 'string' } },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    correction: { type: 'string' },
  },
}

// ─────────────────────────────────────────────────────────────────────────
// PHASE 1 — multi-lens review
// ─────────────────────────────────────────────────────────────────────────

phase('Review')

const LENSES = [
  {
    key: 'correctness',
    focus: 'КОРРЕКТНОСТЬ И ЧЕСТНОСТЬ. Верны ли фактические утверждения плана? Спот-чекни по коду самые смелые/последствийные claim-ы (например: ActionBus 0 prod; Modbus prefix-баг = INBOUND мимо хаба; _route_to_worker silent drop теряет process.stop; register_message_handler = полный relay; queue_type НЕ обходит _select_queue_type; SQL вне хаба; release_process_memory отсутствует). Если что-то не сходится — claim в weaknesses + в claims_to_verify. Прошлый аудит уже выдавал ложь — не доверяй тексту плана, проверяй.',
  },
  {
    key: 'completeness',
    focus: 'ПОЛНОТА ПОКРЫТИЯ. Все ли comm-подсистемы и сценарии учтены? Сверь с реальным списком модулей (multiprocess_framework/modules/*, Services/, multiprocess_prototype/). Что НЕ попало в матрицу §9 / каноны §2 / правила? local_channel честно отмечен как пропущенный — есть ли ещё такие дыры? Нет ли сценария коммуникации без канона.',
  },
  {
    key: 'architecture',
    focus: 'АРХИТЕКТУРНАЯ ЗДРАВОСТЬ. Действительно ли целевой дизайн хорош/современен/элегантен и служит видению «конструктор для мощных распределённых систем» (серверные, машинное зрение с НС, микро/макросервисы, cross-machine, контроллеры)? Валиден ли тезис RouterManager-хаб + IMessageChannel? Нет ли over-engineering, ложных абстракций, либо наоборот — упрощений, которые не масштабируются? Push-канон для контроллеров, два канона state/events, SHM как отдельный hot-path — обоснованы?',
  },
  {
    key: 'consistency',
    focus: 'ВНУТРЕННЯЯ КОНСИСТЕНТНОСТЬ И ИСПОЛНИМОСТЬ. Согласованы ли 4 файла между собой (план §13 решения ↔ контракт ↔ §9 матрица ↔ §12 этапы)? Нет ли противоречий (например статус capability-to-build vs absorbed; решения Q1-Q9 vs тело плана). Исполним ли план P0→P3: верен ли порядок рисков, соблюдён ли паритет (не ломать кадры/телеметрию), что параллельно/последовательно, есть ли инвариант приёмки. Достаточно ли file:line для исполнителя.',
  },
  {
    key: 'evolution',
    focus: 'ЭВОЛЮЦИЯ vs ПЕРВОИСТОЧНИКИ. Сравни НОВЫЙ план с первым аудитом (comm-system-consolidation.md) и промежуточным (v2). Реально ли он лучше и в чём? Не потерял ли он что-то ценное из первых документов (находки, быстрые победы, пункты обсуждения)? Не появились ли регрессии/раздувание? Оправдан ли объём (457 строк) или есть вода.',
  },
]

const reviewPrompt = (l) => `Ты — старший код-ревьюер. Дай ЧЕСТНУЮ, профессиональную оценку НОВОГО плана архитектуры коммуникаций по своей грани. Без реверансов: цель владельца — лучшая архитектура-конструктор, простая и отлаживаемая; плохую оценку дать НЕ стыдно, если заслужена.

ГРАНЬ: ${l.key}
ФОКУС: ${l.focus}

${DOCS}

ОБЯЗАТЕЛЬНО:
- Прочитай главный план целиком + контракт; первый/промежуточный — по релевантности грани.
- Где план делает утверждение о коде — ПРОВЕРЬ по коду (Read + Grep + mcp__qex__search_code + mcp__codegraph__callers), не верь на слово.
- weaknesses помечай severity (critical/major/minor) и давай evidence (file:line или §раздел).
- claims_to_verify — спорные утверждения плана, которые требуют отдельной адверсариальной проверки фазы 2.
- recommendation — честный вердикт по грани.
${QEX_GUARD}

Верни ТОЛЬКО структурированный объект (REVIEW).`

const reviews = (await parallel(
  LENSES.map((l) => () =>
    agent(reviewPrompt(l), { label: `review:${l.key}`, phase: 'Review', schema: REVIEW, agentType: 'reviewer' })),
)).filter(Boolean)

log(`Фаза 1: ${reviews.length}/${LENSES.length} ревью-граней готово`)

// ─────────────────────────────────────────────────────────────────────────
// PHASE 2 — adversarial verification of reviewers' contested claims
// ─────────────────────────────────────────────────────────────────────────

phase('Verify')

const claimSet = new Map()
const add = (t) => { const s = (t || '').trim(); if (s.length > 8 && !claimSet.has(s)) claimSet.set(s, true) }
for (const r of reviews) {
  for (const c of (r.claims_to_verify || [])) add(c.claim)
  for (const w of (r.weaknesses || [])) {
    if ((w.severity === 'critical' || w.severity === 'major') && /код|file|\.py|claim|неверн|ложн|отсутству|есть|нет |мёртв|дубл|обход/i.test(w.issue + ' ' + (w.evidence || ''))) {
      add(`[${r.lens}/${w.severity}] ${w.issue}${w.evidence ? ' (заявлено: ' + w.evidence + ')' : ''}`)
    }
  }
}
const claims = Array.from(claimSet.keys())
log(`Фаза 2: проверка ${claims.length} спорных находок ревьюеров по коду`)

const verifyPrompt = (claim) => `Ты — скептик-верификатор. Ревьюер плана сделал утверждение — проверь его по РЕАЛЬНОМУ коду (d:\\PROJECT_INNOTECH\\Inspector_vision\\Inspector_bottles). Ревьюер тоже может ошибаться — проверяй, не подтверждай на веру.

УТВЕРЖДЕНИЕ РЕВЬЮЕРА: «${claim}»

- Grep + mcp__qex__search_code + mcp__codegraph__callers; ИСКЛЮЧИ multiprocess_prototype_backup/.
- evidence строго как file:line факты.
- confidence high только если лично видел доказательства.
${QEX_GUARD}

Верни ТОЛЬКО структурированный объект (VERDICT).`

const verdicts = claims.length
  ? (await parallel(claims.map((c) => () =>
      agent(verifyPrompt(c), { label: `verify:${c.slice(0, 36)}`, phase: 'Verify', schema: VERDICT, model: 'sonnet' })))).filter(Boolean)
  : []

const refuted = verdicts.filter((v) => v.verdict === 'refuted')
log(`Фаза 2 готова: ${verdicts.length} вердиктов · опровергнуто находок ревьюеров ${refuted.length}`)

// ─────────────────────────────────────────────────────────────────────────
// PHASE 3 — senior synthesis verdict
// ─────────────────────────────────────────────────────────────────────────

phase('Verdict')

const corpus = { reviews, verdicts }

const verdictDoc = await agent(
  `Ты — ведущий архитектор-ревьюер. Сведи мнения 5 граней и их верификацию в ЕДИНЫЙ честный профессиональный вердикт по НОВОМУ плану (plans/comm-system-target-architecture.md).

ДАННЫЕ РЕВЬЮ (граней + верификация находок):
${JSON.stringify(corpus, null, 1)}

ВАЖНО про честность в обе стороны:
- Если находка ревьюера ОПРОВЕРГНУТА верификацией (verdict refuted) — НЕ включай её как недостаток плана; наоборот, отметь, что план тут прав.
- Если находка подтверждена (confirmed) — это реальный недостаток, в must-fix/should-fix по severity.
- Не сглаживай: если план слаб в чём-то — скажи прямо. Если силён — тоже прямо.

НАПИШИ ДОКУМЕНТ НА РУССКОМ (user-facing). Структура:
1. **Вердикт одной строкой + итоговая оценка** (буква/10) + рекомендация (approve / approve-with-changes / needs-work / reject).
2. **Сильные стороны** (что сделано профессионально).
3. **MUST-FIX до исполнения** (critical/major, ТОЛЬКО подтверждённые верификацией) — с file:line/§.
4. **SHOULD-FIX** (minor / улучшения).
5. **Пробелы покрытия** (что не учтено; включая local_channel и прочее).
6. **Архитектурное мнение** — здрав ли целевой дизайн для конструктора распределённых систем; риски масштабирования.
7. **Эволюция vs первоисточники** — лучше ли новый план первого/промежуточного, что потеряно/приобретено.
8. **Находки ревьюеров, которые сами оказались неверны** (опровергнуты верификацией) — честно, чтобы не чинили несуществующее.
9. **Готов ли план к исполнению P0** — да/нет и при каких условиях.

Плотно, по делу, без воды. Верни ТОЛЬКО markdown документа.`,
  { label: 'verdict', phase: 'Verdict' },
)

return {
  review: verdictDoc,
  stats: {
    lenses: reviews.length,
    grades: reviews.map((r) => ({ lens: r.lens, grade: r.grade, rec: r.recommendation })),
    verdicts: verdicts.length,
    refuted_reviewer_findings: refuted.length,
  },
}
