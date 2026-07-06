# Rubric: signal-to-noise

**Dimension:** Does the review surface real problems without drowning them in noise
(nitpicks, style opinions, or findings on correct code)?

This rubric is read by the deferred LLM-judge path (`run_evals.py --judge`). The judge
sees only this rubric + the reviewer output + the case ground truth. Score at
temperature 0. If the evidence is insufficient to score, output **Unknown** rather than
guessing — ambiguous scores (0.4–0.6) route to the human-review queue.

| Score | Anchor |
|-------|--------|
| 1.0 | Every finding is a real, actionable defect. Zero findings on correct/intentional code. No subjective style opinions. |
| 0.75 | All real defects flagged; at most one borderline-but-defensible nit. |
| 0.5 | Real defects flagged but mixed with one clear false positive or a subjective opinion. |
| 0.25 | Noise dominates: multiple false positives or style opinions obscure the real issue. |
| 0.0 | The review flags correct code as broken, or is mostly subjective opinion. |
| Unknown | Cannot tell from the output whether a flagged item is real (need the surrounding code). |

**Calibration note:** a finding on a `must_not_flag` decoy is, by definition, noise —
the deterministic grader already penalises it; the judge scores the *prose* quality
(did the reviewer explain why something is or is not a problem).
