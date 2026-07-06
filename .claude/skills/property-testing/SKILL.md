---
name: property-testing
description: >
  Property-based testing with Hypothesis. Activates when a test would assert a
  *property* that must hold across a whole class of inputs — round-trips
  (encode/decode, save/load), invariants (sorted output stays ordered), oracles
  (a fast impl agrees with a slow reference), or idempotence — rather than a
  handful of hand-picked examples. Use to harden parsers, serializers, numeric
  code, data-structure logic, and any pure function with a clear contract.
  Triggers: "property test", "property-based", "Hypothesis", "@given", "fuzz
  this function", "generate random inputs", "find edge cases".
---

# Property-based testing (Hypothesis)

Example-based tests check the inputs *you* thought of. Property-based tests
state a rule that must hold for *every* input in a domain and let Hypothesis
hunt for a counter-example — then shrink it toward a minimal failing case. One
`@given` test routinely replaces a dozen `parametrize` rows and finds the edge
cases you would never have written by hand.

This **complements** example-based tests; it does not replace them. Keep a few
concrete examples for documentation/regression, add properties for the contract.

## When to reach for a property (and which kind)

Look for a relationship that holds regardless of the specific input:

| Pattern | Property | Typical target |
|---------|----------|----------------|
| **Round-trip** | `decode(encode(x)) == x` | serializers, parsers, codecs |
| **Invariant** | output always satisfies P | `sorted()` is ordered; balance ≥ 0 |
| **Idempotence** | `f(f(x)) == f(x)` | normalization, dedup, sanitizers |
| **Oracle / model** | `fast(x) == reference(x)` | optimized code vs naive reference |
| **Metamorphic** | `f(t(x))` relates to `f(x)` | `len(a + b) == len(a) + len(b)` |
| **Never crashes** | no unexpected exception on valid input | input validation, public API |

If you cannot name a property, that input is probably an example test — write it
as one and move on. Do not force a property where there isn't one.

## Workflow

1. **Pick one property** from the table for the function under test.
2. **Choose a strategy** describing the *valid* input domain — as wide as the
   contract allows, no wider (constrain with `min_value`/`max_value`,
   `min_size`, `st.text(alphabet=...)`, ...). An over-wide strategy reports
   false failures on inputs the function never promised to handle.
3. **Write the test** with `@given`; assert the property, not a specific value.
4. **Run it.** On failure, read the shrunk minimal example Hypothesis prints —
   that *is* the bug report. Decide: code bug (fix the code) or wrong property
   (fix the test).
5. **Pin regressions.** Hypothesis records failing examples in its local database
   and replays them; for a permanent, in-source regression also add
   `@example(...)`.

## Core API

```python
from hypothesis import given, settings, strategies as st


@given(st.lists(st.integers()))
def test_sorting_is_idempotent(xs):
    once = sorted(xs)
    assert sorted(once) == once          # idempotence: sort twice == sort once
```

Common strategies: `st.integers(min_value=, max_value=)`,
`st.floats(allow_nan=False, allow_infinity=False)`, `st.text()`,
`st.lists(elem, min_size=, max_size=)`, `st.dictionaries(keys, values)`,
`st.booleans()`, `st.none()`, `st.sampled_from([...])`, `st.one_of(...)`. Build
domain objects with `st.builds(MyClass, field=strategy)`, or `@st.composite` for
inputs with internal constraints. Tune runs with
`@settings(max_examples=..., deadline=...)`.

See `tests/test_property_example.py` (shipped by the `lang-python` template) for
a runnable, copy-to-adapt starting point covering each property pattern above.

## Boundaries

- **Pure / deterministic functions first.** Side-effecting code needs a model or
  `hypothesis.stateful` rule-based state machines — higher cost, use deliberately.
- **Keep it fast.** Mind `deadline`; lower `max_examples` for slow properties so
  the suite stays green in CI.
- **HypoFuzz is opt-in.** For coverage-guided, long-running fuzzing of these same
  `@given` tests, run them under [HypoFuzz](https://hypofuzz.com) separately — it
  is a fuzzing harness, not a default test dependency.
