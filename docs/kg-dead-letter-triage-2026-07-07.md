# KG extraction dead-letter triage — 2026-07-07

Overnight investigation triggered by cservinl noticing a steady stream of
"truncated" dead letters in the KG progress page across many different
papers. Goal: find the real root cause(s), not just note the symptom, and
propose evaluated fixes.

## Scope: this is not occasional — it's most of the vault

37 dead letters were written between 2026-07-07T00:03 and 21:50 (still
running at investigation time), covering **14 distinct source files** out
of 27 papers in `thesis/Resources/Papers/`. Several files failed
repeatedly across the day (`Fedus_2022_Switch_Transformers.md` 4 times,
`Sharma_2023_Sycophancy_in_LLMs.md` 4 times, `Liang_2022_...` 4 times) —
confirmed **deterministic**, not flaky: two dead letters for the same file
hours apart contain byte-identical chunk content (`diff` on the two Fedus
dead letters showed zero difference). This matches the current
taint-and-stop design (`_extract_file` taints a file and stops on its
first chunk failure — see `TODO.md`'s 2026-07-05/06 correctness work) —
every full sync retries every tainted file from scratch, and a
deterministic failure just fails again at the same chunk, every cycle.

Breakdown of the 37: **34 "truncated"** (`IncompleteOutputException`,
`max_tokens=4000` hit before the model finished, not retried — retries=0
in every case, matching `_call_ollama_extract`'s comment that a
length-truncated response is treated as immediately fatal) and **3
"invalid"** (`InstructorRetryException`, JSON validation kept failing
across all 4 attempts — all 3 are the same paper,
`Bricken_2023_Towards_Monosemanticity`).

Live server stats at investigation time: `chunk_avg_duration_ms: 76066`
(~76s/chunk average), `dropped_chunks_total: 37`, and — most concerning —
the KG service was found mid-way through **re-processing
`Bricken_2023_Towards_Monosemanticity.md` (249 sections) for the 4th time
today**, at chunk 54/249. At ~76s/chunk, reaching the same failing chunk
each cycle burns real hours of GPU time re-doing already-known-good work
before hitting the same deterministic wall again.

## Root cause 1 (dominant, 34/37): no bound on how much the model tries to enumerate

Every single "truncated" dead letter's chunk content is either:
- **A long author/reference list** — e.g. the `Huang_2024_Hallucination_Survey.md`
  dead letter is literally ~200 consecutive author names from a cited
  Gemini technical report; `Sharma_2023_Sycophancy_in_LLMs.md` and
  `Liang_2022_...`'s dead letters are the same shape (bibliography/author
  lists).
- **A dense data table** — `Hoffmann_2022_Chinchilla_Compute_Optimal.md`'s
  chunk is a BIG-bench results table (dozens of task names + numbers);
  `Bramerdorfer_2022_...`'s chunk is dense with KPI/MOE table references.
- **Dense technical prose** — `Elhage_2021_Mathematical_Framework_Transformer_Circuits.md`
  (heavy math/LaTeX notation, many named circuit concepts per paragraph),
  `Akyurek_2022_...` (dense variable-heavy math).

`_EXTRACTION_SYSTEM`'s current rules explicitly say to extract "Authors
and their institutional affiliations, when given" with no cap — so when a
~1000-token chunk (`token_budget=1000`, working as intended) happens to be
a 200-name author list, the model dutifully tries to emit ~200 node
objects + edges, which cannot fit in `max_tokens=4000` (or any reasonable
budget) and isn't useful KG content even when it does fit.

**Confirmed empirically, live, against production `qwen2.5:7b-32k`:**
re-running the exact `Huang_2024_Hallucination_Survey.md` dead-letter
chunk through the real Instructor call path:

| Prompt | Result |
|---|---|
| Current `_EXTRACTION_SYSTEM` (unmodified) | Non-deterministic — one run truncated (the original failure); a second run "succeeded" at 242s but produced **148 nodes, 0 edges** (all disconnected author-name stubs, no relationships — useless even when it doesn't truncate) |
| `_EXTRACTION_SYSTEM` + an explicit output-budget clause (below) | Succeeded cleanly in 242s, **22 nodes, 21 edges**, retries=0 |

The fix tested (appended to the existing system prompt, not a rewrite):

> "Output budget: extract at most 15 of the most important entities and at
> most 20 of the most important relationships from this section. If the
> section contains a long enumeration (e.g. a reference list with many
> authors, a long list of citations, a table with many rows), do NOT
> enumerate every item — that is a signal to select only the few most
> central ones (or extract none), never to list them all."

This directly targets the actual mechanism (the model over-enumerating),
which raising `max_tokens` alone cannot fix — a 200-author list will blow
past 4000, 6000, or 10000 tokens just as reliably, and even a "successful"
run under a higher cap still produces zero-value output (author-name
stubs with no edges).

**Also confirmed on the dense-math-prose failure class**: re-running the
exact `Elhage_2021_Mathematical_Framework_Transformer_Circuits.md` dead-
letter chunk (the Q/K/V-composition paragraph, heavy LaTeX notation) with
the capped prompt succeeded cleanly — 430.2s, retries=0, **5 nodes, 5
edges** (a small, sane extraction of the real named concepts:
Q-Composition, K-Composition, V-Composition, QK circuit, OV circuit —
not an attempt to transcribe every matrix variable in the LaTeX). Original
prompt on this same chunk had hit `max_tokens=4000` and failed outright.

**Control check — does capping hurt a normal, already-succeeding chunk?**
Ran both prompts against a real, ordinary prose chunk from
`Lieberum_2022_Engineering_Monosemanticity_Toy_Models.md` (a paper with no
dead letters today, picked specifically because it wasn't already a known
failure): original prompt → 7 nodes/7 edges; capped prompt → 6 nodes/6
edges. Essentially unchanged (one borderline entity dropped, noise-level
difference) — the cap of 15/20 only bites on genuinely pathological
enumeration-shaped content, not on normal dense prose that was already
producing a reasonable, small entity count.

## Root cause 2 (3/37, but higher-effort each): adversarial escape-sequence content

All 3 "invalid" dead letters are `Bricken_2023_Towards_Monosemanticity.md`
— a real Anthropic interpretability paper whose appendix is a literal
table of raw byte-sequence descriptions ("Hebrew: `\xd6`?", "Arabic:
Unicode start `\xd8`?", "`\xc2` in UTF-8 as latin1 mojibake of Chinese?").
This is genuine paper content (a feature-visualization index), not
garbage, but it's adversarial for JSON-mode generation: the model tries to
preserve these escape-like sequences as entity labels and produces
literally malformed JSON (`Invalid JSON: unexpected end of hex escape`) —
a lone/malformed `\uXXXX` sequence, not a schema mismatch.

Each failure escalates for 4 full retries (`max_retries=3`) before giving
up: `completion_tokens` grew 1889 → 3768 → 5646 → 7540 and `prompt_tokens`
grew 3019 → 8028 → 15017 → 23985 across the 4 generations of a single
dead letter — because Instructor's default reask behavior re-sends the
full prior (invalid) completion plus the validation error back into the
next attempt's context, asking the model to fix it. For genuinely
adversarial source content, this doesn't converge — the model keeps
reproducing variations of the same malformed escape, burning ~4x the
latency of the first attempt alone for a fixed, predictable failure.

**Also notable**: `completion_tokens=7540` on the 4th generation, despite
`max_tokens=4000` configured and `finish_reason='stop'` (not `'length'`)
— i.e. the model was not cut off by the cap at all; it decided the
response was complete at nearly double the configured max. This needs its
own follow-up (see Outstanding) — it may mean Ollama's OpenAI-compat
endpoint doesn't strictly enforce `max_tokens` across Instructor's
internal reask calls the way it does on a fresh single call.

**Confirmed: the output-budget prompt clause (proposal 1, root cause 1)
does NOT fix this class.** Re-ran the exact same Bricken adversarial chunk
with the capped prompt — same outcome: 4 retries, 923.7s, same error
family (`Invalid JSON: unexpected end of hex escape at line 33 column 47`,
just a different line/column than the original run). This confirms
proposal 1 only closes root cause 1 (34/37 today); root cause 2 needs its
own, separate fix (see proposals 4/5 below) — capping entity *count*
doesn't touch a content-shape JSON-escaping bug.

## Root cause 3 (efficiency, not correctness): duplicate ingestion

`Bricken_2023_Towards_Monosemanticity` exists in the vault **twice**:
`thesis/Resources/Papers/Bricken_2023_Towards_Monosemanticity.md` (a
cleaned/PDF-derived version) and
`thesis/Resources/Papers/html/Bricken_2023_Towards_Monosemanticity/index.md`
(a raw HTML-scrape version) — confirmed near-identical (29368 vs. 29373
lines, `diff` on the first 50 lines shows only a YAML frontmatter
difference). The KG service walks all `.md` files in the vault with no
dedup, so this one paper gets extracted **twice**, doubling both its
compute cost and its dead-letter count. The same `html/<slug>/index.md`
pattern exists for two other papers, and **both confirmed near-identical
to their plain `.md` sibling** (line counts differ only by YAML
frontmatter, same as Bricken): `Olah_2020_Zoom_In_Circuits` (399 vs. 394
lines) and `Elhage_2021_Mathematical_Framework_Transformer_Circuits`
(1699 vs. 1694 lines — this is the same Elhage paper that hit Root cause 1
above, so it's silently double-indexed too, doubling its dead-letter risk
specifically).

## Root cause 4 (efficiency): no memory of "this exact chunk always fails"

Because a tainted file is fully re-processed from chunk 0 on every sync
cycle, a large file with a genuinely-unfixable chunk (Bricken's Unicode
table, root cause 2) wastes the *entire* file's earlier successful chunks'
worth of GPU time every single cycle just to reach the same wall again —
confirmed live, the sync was 54/249 chunks into re-processing Bricken for
(at least) the 4th time today. There's currently no persisted memory of
"this exact chunk (by content hash) has already dead-lettered N times" to
skip past a known-permanent failure while still processing the rest of
the file.

## What was fixed tonight (implemented, tested, safe)

**Dead-letter header corruption** — `_record_dropped_chunk` wrote the raw
`error` string directly into a fixed 5-line header
(`# source_file / # reason / # error / # retries / # time`), but
`InstructorRetryException.__str__()` is a multi-page dump of every failed
generation's full completion. This broke the header's line-based format
(the `# retries` / `# time` lines ended up ~50 lines down, and the actual
failed chunk content start became impossible to find without knowing the
error's exact length) and dumped the same wall of text directly into the
KG progress page's dropped-chunks table cell (`+page.svelte`'s
`<td>{d.error}</td>`).

Fixed in `prisma/services/knowledge_graph_service.py`: new
`_summarize_error()` extracts just the final validation message (from
inside the last `<last_exception>...</last_exception>` block Instructor's
dump already delimits, or the raw string for the already-short
truncated/connection cases) as a single line, capped at 300 chars. The
short summary is used for the disk header's `# error:` line and the
in-memory/status()/UI record; the full raw error is preserved verbatim in
the dead-letter file body, clearly delimited between
`--- full error detail ---` / `--- end full error detail ---` markers,
before the actual failed chunk content. New test added:
`test_dropped_chunk_summarizes_multiline_error_but_keeps_full_detail_on_disk`
in `tests/unit/services/test_knowledge_graph_service.py`. Full unit suite
(399 tests) passes. Not yet committed/pushed — left for your review since
it's part of the same investigation as the proposals below.

## Proposals for cservinl to decide on

1. **Add the output-budget clause to `_EXTRACTION_SYSTEM`** (empirically
   validated above on the dominant failure class). Low risk — additive
   prompt text, no schema change. Recommended first move; should collapse
   most of the 34 "truncated" failures. Not yet applied to production code
   — waiting on your review since it changes extraction behavior/output
   shape (fewer entities per chunk, by design).
2. **Exclude `html/<slug>/index.md` from KG extraction scope**, or dedupe
   by content hash against the cleaner `.md` sibling, to stop double-
   indexing the 3 known papers. Simple if you confirm these
   `html/*/index.md` files are always redundant scrape mirrors and never
   the *only* copy of a paper's content — I did not verify this holds for
   every paper in the vault, only the 3 observed.
3. **Persist a "this chunk's content hash has already dead-lettered"
   skip-list**, checked before re-submitting a chunk on a retry sync, so a
   large file with one permanently-bad chunk doesn't re-burn its earlier
   good chunks' compute every cycle. Bigger design change than 1-2 — would
   need a decision on where it lives (a new file under `kg-out/`?
   in-memory only, reset on restart?) and how many failures before a chunk
   is considered "permanent" vs. "worth retrying" (a transient connection
   failure should still retry; the same validation error twice on
   identical content should not).
4. **Investigate the `max_tokens` non-enforcement finding** (Root cause
   2's `completion_tokens=7540 > max_tokens=4000` with `finish_reason='stop'`)
   separately — this could mean Instructor's reask/retry calls aren't
   reliably passing `max_tokens` through to Ollama's OpenAI-compat
   endpoint, which would matter beyond just this one adversarial-content
   case.
5. **Consider capping `max_retries` lower (e.g. 1) specifically for JSON
   validation failures**, since the observed pattern (retrying against
   escalating, re-injected invalid context) doesn't converge for
   genuinely adversarial content — it only quadruples latency for a fixed
   outcome. Would need care not to also weaken retries for the more
   common, actually-recoverable validation failures.

## Outstanding — now resolved

All empirical tests planned at write time have completed:

- **Root cause 1 (proposal 1)**: fully validated — fixes the author-list
  class (Huang, 148/0 → 22/21), the dense-math-prose class (Elhage, hard
  failure → 5/5), and doesn't regress a normal chunk (7/7 → 6/6). Confident
  recommendation to adopt.
- **Root cause 2 (Bricken adversarial Unicode)**: confirmed the capped
  prompt does **not** help — re-ran the exact chunk under the capped
  prompt, got the same outcome (4 retries, 923.7s, same
  `Invalid JSON: unexpected end of hex escape` error family, just a
  different line/column). This is a genuinely separate problem from root
  cause 1 and needs its own fix (proposals 4/5), not just the prompt
  clause. Confirms the overall picture: proposal 1 alone would have closed
  34/37 of today's failures, not all 37.
- Implementation note for proposal 2 (duplicate `html/index.md` exclusion):
  the KG service sources its file list via `self._vault._all_md_files()`
  in `_full_index()` (`knowledge_graph_service.py:936`), a call shared
  with other vault consumers — the exclusion should be a KG-local filter
  on that result (e.g. skip paths matching `html/*/index.md`), not a
  change to `VaultService` itself, since chroma/chat search may have
  legitimate reasons to still see the raw HTML-scrape version.
