---
name: cyrillic-numeral-word-substring-collision
description: "восемь" (eight) contains "семь" (seven) as a literal substring (во-СЕМЬ) — a bare `word in text` scan for RU numeral-words double-counts, need \b word-boundary regex
metadata:
  type: feedback
---

Writing a text-scanner test (Task 2.7, `observability-closure`) that greps the
tree for lines spelling out a count as a Russian word (`шесть`, `семь`,
`восемь`, ...), a plain `if word in low` membership check for each numeral
against the same line produced TWO hits on one real line — both `"семь"` (7)
and `"восемь"` (8) matched the same sentence, because "восемь" literally
contains "семь" as a contiguous substring (в-о-**семь**). This looked like a
second, spurious mismatch in the assertion output before I noticed the
duplicate line/text.

**Why:** caught only by reading the actual failure text closely (`-vv` output)
and noticing the SAME line number and SAME quoted text appeared twice with two
different "found number" values — an easy thing to miss if you only skim the
assertion count ("N mismatches") instead of the individual lines.

**How to apply:** when scanning Russian text for numeral-words as plain
substrings, always match on a word boundary (`re.search(rf"\b{word}\b", text)`
in Python 3 — `\b` is Unicode-aware for `str` patterns by default), never bare
`in`. Known collision in this codebase's vocabulary: `восемь` ⊃ `семь`. Worth
checking any other numeral list for the same trap before trusting a "no
substring collisions" assumption — don't just fix the one instance found.
