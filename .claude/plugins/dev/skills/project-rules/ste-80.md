# Explanation style — STE-80 (was project-rules §9)

For prose that explains: reports, ADR text, handoffs, answers to the owner. Not for code, commands,
logs, quoted output, commit trailers. Source: ASD-STE100 (Simplified Technical English), relaxed for
readability. "STE-80" means exactly the 8 hard rules plus the relaxations below; nothing else from
ASD-STE100 applies (no 900-word dictionary, no approved-verb list). The rules are about structure, so they hold in any language — the owner
still gets Russian (§6).

**Hard rules**
1. One idea per sentence. Description ≤25 words, instruction ≤20.
2. Instruction = imperative, one action per sentence, in execution order. A `Warning:` goes
   before the step it protects.
3. Active voice, simple tense. Name the actor: "the router drops the message", not "the message is dropped".
4. One word, one meaning. Pick one term per thing and keep it through the whole text
   (process ≠ channel — see `ROUTING_GLOSSARY.md`). Never vary a term for style.
5. Repeat the noun instead of "it / this / that" when the referent is not in the same sentence.
6. Answer first, reason after. No filler: no intro recap, no "it is worth noting", no closing summary
   of what the text just said.
7. Literals, not adjectives: "3 of 40 tests fail", not "some tests fail".
8. Paragraph ≤6 sentences. Lists for steps and parallel facts.

**Relaxations**
- Project terms and identifiers stay as they are (`SchemaBase`, `ProcessModule`); no dictionary check.
- One `because` clause is fine when the reason is the point of the sentence.
- Noun clusters up to 3 words; perfect tense when it states a result ("already merged").
- Quotes, ADR wording fixed by the owner, and the owner's own text are not rewritten.

**Check before sending:** delete every sentence that changes neither the reader's understanding nor
their next action. STE is clarity, not compression — if the owner asks for `caveman`, `caveman` wins.
