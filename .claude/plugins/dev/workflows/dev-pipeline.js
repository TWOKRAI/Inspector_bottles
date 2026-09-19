export const meta = {
  name: 'dev-pipeline',
  description: 'Run independent plan Tasks through RED -> GREEN -> Review with worktree isolation',
  whenToUse:
    'Three or more independent Tasks from one approved plan, when the owner explicitly asked for the workflow transport (/dev:pipeline --workflow). Fewer Tasks, or dependent ones, stay on subagents.',
  phases: [
    { title: 'RED', detail: 'tester writes the failing test for each Task, isolated in a worktree' },
    { title: 'GREEN', detail: 'developer or teamlead makes it pass, isolated when more than one Task runs' },
    { title: 'Review', detail: 'reviewer issues a structured verdict per Task; read-only, no isolation' },
  ],
}

// ---------------------------------------------------------------------------
// Contract with the caller (Director).
//
// The script has NO filesystem access: it never reads the plan. The Director
// reads it and passes the work list as JSON:
//
//   args = {
//     plan:  'plans/YYYY-MM-DD_<slug>.md',
//     tasks: [{ id: '3.2', level: 'Middle+', files: ['src/a.py'], acceptance: ['...'] }],
//   }
//
// The script returns { plan, results, branches, dropped } — `branches` is the
// merge-back list the Director consumes; work committed inside a worktree is
// lost unless those branches are merged.
// ---------------------------------------------------------------------------

// Token headroom kept in reserve so a run cannot die mid-Task with no verdict.
const BUDGET_FLOOR = 50_000

const BRANCH_FIELD = {
  type: 'string',
  description:
    'The git branch this agent committed on, verbatim from `git branch --show-current` inside its worktree. Empty string only if nothing was committed.',
}

const RED_SCHEMA = {
  type: 'object',
  properties: {
    branch: BRANCH_FIELD,
    red_confirmed: {
      type: 'boolean',
      description: 'True only if the new test was run and observed to FAIL against the current code.',
    },
    test_files: { type: 'array', items: { type: 'string' } },
    failing_output: {
      type: 'string',
      description: 'Verbatim tail of the failing run (assertion line included), not a paraphrase.',
    },
    notes: { type: 'string' },
  },
  required: ['branch', 'red_confirmed', 'test_files', 'failing_output'],
}

const GREEN_SCHEMA = {
  type: 'object',
  properties: {
    branch: BRANCH_FIELD,
    green_confirmed: {
      type: 'boolean',
      description: 'True only if the RED test was re-run and observed to PASS.',
    },
    changed_files: { type: 'array', items: { type: 'string' } },
    passing_output: { type: 'string', description: 'Verbatim tail of the passing run.' },
    left_open: {
      type: 'string',
      description: 'What is unfinished or unreliable in this work. Empty string only if genuinely nothing.',
    },
  },
  required: ['branch', 'green_confirmed', 'changed_files', 'passing_output', 'left_open'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['APPROVED', 'CHANGES_REQUESTED', 'BLOCKED'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          input: { type: 'string', description: 'The exact input, file:line or command the finding is about.' },
          observed: { type: 'string', description: 'What was actually observed for that input — not what is feared.' },
        },
        required: ['input', 'observed'],
      },
    },
    injections: {
      type: 'array',
      description:
        'Fault injections used to prove the new test really guards the property: break the property on purpose, predict red, observe.',
      items: {
        type: 'object',
        properties: {
          property: { type: 'string' },
          predicted_red: { type: 'boolean' },
          observed_red: { type: 'boolean' },
        },
        required: ['property', 'predicted_red', 'observed_red'],
      },
    },
    summary: { type: 'string' },
  },
  required: ['verdict', 'findings', 'injections', 'summary'],
}

// ---------------------------------------------------------------------------
// Input normalisation. Anything unusable is dropped LOUDLY (log per task) —
// a silently shortened work list reads as "everything covered" when it wasn't.
// ---------------------------------------------------------------------------

const plan = (args && args.plan) || null
const rawTasks = (args && Array.isArray(args.tasks) && args.tasks) || []
const dropped = []

const tasks = rawTasks.filter((task, i) => {
  if (!task || typeof task !== 'object' || !task.id) {
    const reason = `entry #${i} has no id — cannot address a Task without one`
    dropped.push({ index: i, id: (task && task.id) || null, stage: 'intake', reason })
    log(`dropped ${reason}`)
    return false
  }
  return true
})

if (!plan) log('no plan path in args — agents will work from the Task fields alone, which is weaker')
if (!tasks.length) log('no usable Tasks in args — nothing to run')

// Isolation costs a worktree per agent: pay it for GREEN only when Tasks can
// actually collide with each other.
const ISOLATE_GREEN = tasks.length > 1

const state = tasks.map((task, i) => ({
  index: i,
  id: String(task.id),
  level: task.level || 'unspecified',
  agentType: implementerFor(task.level),
  branches: [],
  red: null,
  green: null,
  review: null,
  dropped: null,
}))

function implementerFor(level) {
  return /senior|opus|teamlead|architect/i.test(String(level || '')) ? 'teamlead' : 'developer'
}

function planLine() {
  return plan ? `Plan: ${plan} (read the Task section yourself; it is the source of truth).` : 'No plan file was passed; work from the Task fields below.'
}

function taskBlock(task) {
  const files = Array.isArray(task.files) ? task.files.join(', ') : String(task.files || 'not listed')
  const acceptance = Array.isArray(task.acceptance) ? task.acceptance : [task.acceptance].filter(Boolean)
  return [
    `Task ${task.id} (Level: ${task.level || 'unspecified'})`,
    planLine(),
    `Files in scope: ${files}`,
    acceptance.length ? `Acceptance criteria:\n${acceptance.map((a) => `  - ${a}`).join('\n')}` : 'Acceptance criteria: not passed — say so in your report instead of inventing them.',
  ].join('\n')
}

// A worktree agent's work is invisible to everyone until its branch is merged,
// so every isolated agent is told to report the branch, and to check its venv
// before believing any test result it produces (the false-green trap).
const WORKTREE_RULES = [
  'You are in your own git worktree. Commit your work there — uncommitted work in a worktree is lost.',
  'Do NOT merge, rebase, push, or touch any branch but your own. The Director merges, one branch at a time.',
  'Report your branch verbatim from `git branch --show-current` in the `branch` field.',
  'Before you believe ANY test result here: sync the environment in the worktree, then print the resolved path of the package under test and confirm it is inside this worktree, not the main checkout.',
].join('\n')

function halted(s, stage) {
  if (s.dropped) return true
  if (budget.total && budget.remaining() < BUDGET_FLOOR) {
    s.dropped = `budget floor: ${Math.round(budget.remaining() / 1000)}k left before ${stage}`
    dropped.push({ index: s.index, id: s.id, stage, reason: s.dropped })
    log(`Task ${s.id}: stopped before ${stage} — ${s.dropped}`)
    return true
  }
  return false
}

function recordBranch(s, branch) {
  const name = typeof branch === 'string' ? branch.trim() : ''
  if (name && !s.branches.includes(name)) s.branches.push(name)
}

function drop(s, stage, reason) {
  s.dropped = reason
  dropped.push({ index: s.index, id: s.id, stage, reason })
  log(`Task ${s.id}: dropped at ${stage} — ${reason}`)
  return s
}

// ---------------------------------------------------------------------------
// Stages. Each is tagged with opts.phase — NOT the global phase(), which races
// inside pipeline() because items sit in different stages at the same moment.
// ---------------------------------------------------------------------------

async function red(_prev, task, i) {
  const s = state[i]
  if (halted(s, 'RED')) return s
  const out = await agent(
    [
      `MODE: red. Write the failing test for this Task and prove it fails.`,
      taskBlock(task),
      WORKTREE_RULES,
      'You are blind to the implementation on purpose: write the test from the contract and the acceptance criteria, never from the code that would satisfy it.',
      'One test targets one property — but pin that property where it can actually break: the boundary on each side, empty and maximal input, the step where rounding or a unit changes. A single example assertion per test is what review rejects: it passes for the wrong reason and pins nothing.',
      'Run it, and put the verbatim failing output in `failing_output`. Set red_confirmed only if you observed the failure yourself.',
    ].join('\n\n'),
    { phase: 'RED', label: `RED ${task.id}`, agentType: 'tester', schema: RED_SCHEMA, isolation: 'worktree' },
  )
  if (out === null) return drop(s, 'RED', 'tester returned nothing (skipped by the user, or died after retries)')
  s.red = out
  recordBranch(s, out.branch)
  if (!out.red_confirmed) return drop(s, 'RED', 'failing test was never demonstrated — GREEN on an unproven test is worthless')
  return s
}

async function green(prev, task, i) {
  const s = state[i]
  if (halted(s, 'GREEN')) return s
  const opts = { phase: 'GREEN', label: `GREEN ${task.id}`, agentType: s.agentType, schema: GREEN_SCHEMA }
  if (ISOLATE_GREEN) opts.isolation = 'worktree'
  const redBranch = (prev && prev.red && prev.red.branch) || ''
  const out = await agent(
    [
      `Make the failing test from RED pass. Task ${task.id}.`,
      taskBlock(task),
      ISOLATE_GREEN ? WORKTREE_RULES : 'You are NOT isolated: you work in the main checkout. Commit on the current branch and report it in `branch`.',
      redBranch ? `The RED test was committed on branch \`${redBranch}\` — start from it (\`git merge ${redBranch}\` into your own branch, or branch off it) so the test you must satisfy is actually present.` : 'The RED branch was not reported; find the failing test before writing code.',
      `Failing output to satisfy:\n${(prev && prev.red && prev.red.failing_output) || '(not reported)'}`,
      'Do not weaken, delete or rewrite the RED test to make it pass. If the test itself is wrong, stop and say so in `left_open` instead of editing it.',
      'Stay inside the listed files. Name anything unfinished or unverified in `left_open` — an empty `left_open` is a claim that nothing is open.',
    ].join('\n\n'),
    opts,
  )
  if (out === null) return drop(s, 'GREEN', 'implementer returned nothing (skipped by the user, or died after retries)')
  s.green = out
  recordBranch(s, out.branch)
  if (!out.green_confirmed) return drop(s, 'GREEN', 'test was never observed passing')
  return s
}

async function review(prev, task, i) {
  const s = state[i]
  if (halted(s, 'Review')) return s
  const out = await agent(
    [
      `Review Task ${task.id} against its acceptance criteria.`,
      taskBlock(task),
      `Branches to read (read-only; do not merge, do not edit): ${s.branches.join(', ') || '(none reported — say so as a finding)'}`,
      `Implementer's own open items: ${(prev && prev.green && prev.green.left_open) || '(none reported)'}`,
      'For every finding give the exact input and what you OBSERVED for it — a finding without an observation is a guess.',
      'Then prove the new test actually guards its property: break that property on purpose, predict red, run, and record predicted_red vs observed_red in `injections`. A test that stays green under injection is a false guard — report it as a finding, not as approval.',
    ].join('\n\n'),
    { phase: 'Review', label: `Review ${task.id}`, agentType: 'reviewer', schema: VERDICT_SCHEMA },
  )
  if (out === null) return drop(s, 'Review', 'reviewer returned nothing — the Task has code but no verdict')
  s.review = out
  return s
}

// ---------------------------------------------------------------------------
// Run. pipeline() keeps each Task moving through all three stages on its own —
// no barrier, so a slow RED never holds back another Task's review.
// ---------------------------------------------------------------------------

if (tasks.length) {
  log(`${tasks.length} Task(s), GREEN isolation ${ISOLATE_GREEN ? 'on' : 'off (single Task)'}${budget.total ? `, budget ${Math.round(budget.total / 1000)}k` : ', no budget ceiling set'}`)
  await pipeline(tasks, red, green, review)
}

const branches = []
for (const s of state) {
  for (const b of s.branches) if (!branches.includes(b)) branches.push(b)
}

const approved = state.filter((s) => s.review && s.review.verdict === 'APPROVED').length
log(`done: ${approved}/${state.length} approved, ${dropped.length} dropped, ${branches.length} branch(es) to merge back`)

return {
  plan,
  results: state.map((s) => ({
    id: s.id,
    level: s.level,
    implementer: s.agentType,
    branches: s.branches,
    dropped: s.dropped,
    red: s.red,
    green: s.green,
    review: s.review,
  })),
  branches,
  dropped,
}
