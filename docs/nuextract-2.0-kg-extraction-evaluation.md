# NuExtract-2.0-4B evaluation for KG extraction

Closes a gap flagged in `docs/kg-extraction-context-length.md` and
`docs/qwen3-family-evaluation.md`: both prior investigations tested generic
instruct-tuned chat models (qwen2.5:3b/7b, qwen3 family) prompted for
extraction — neither ever tested a model actually specialized for structured
extraction. NuExtract-2.0 (NuMind, built on Qwen2.5) is exactly that. Run
2026-07-24 on Anvil (Radeon 840M, Vulkan), `NuExtract-2.0-4B-Q4_K_M` served
via `llama-swap`.

## Method

Real, manually-verifiable content: title/authors/abstract/introduction of
"Attention Is All You Need" (Vaswani et al. 2017), fetched from arXiv —
clearly entity-rich (Transformer, BLEU, WMT 2014, named authors, etc.),
same kind of source material the prior docs used. Tested three ways.

## Round 1: Prisma's real extraction pipeline, unmodified

Ran through the actual `KnowledgeGraphService`/`instructor` pipeline (same
`_EXTRACTION_SYSTEM` natural-language prompt every other model in this
project's docs was tested with), via `/mark_stale` + `/entities_for_file`,
both on a fresh vault and after a full `/drop_index` reset (to rule out
stale/orphaned graph data from an unrelated vault-restore issue this
session).

**Result: 0 entities, 0 edges — both times.** No error, no dead-letter, no
validation failure — `Extraction.model_validate()` happily accepted an
empty `{"nodes": [], "edges": []}`-shaped response. Same content, tested
against `qwen2.5-3b` earlier the same session, produced 4 correct entities
and 3 correct edges without issue.

Inspecting the raw (non-Instructor-validated) response for this same call
explained why:

```
{"model": {"name": "string", "architecture": "string"}, "tasks": [{"task_name": "verbatim-string", "score": "number"}], "entities": ["verbatim-string"]}
```

NuExtract-2.0 wasn't attempting extraction at all — it echoed back a
schema-shaped guess with literal type placeholders (`"string"`,
`"verbatim-string"`, `"number"`) instead of real values. This is the
model's own expected *input* format leaking into its output: NuExtract-2.0
is trained to take a JSON **template** (field names + type placeholders)
as part of the prompt and fill it with real extracted values — Prisma's
natural-language rule-based prompt (EXTRACTED/INFERRED/AMBIGUOUS
confidence tiers, inclusion/exclusion rules, `<untrusted_source>` wrapping)
gives it nothing resembling that template, so it appears to have
hallucinated a plausible-looking template shape instead of extracting.

## Round 2: proper template-based prompting, verified working

NuExtract's real usage convention passes the template via
`extra_body.chat_template_kwargs.template` (an OpenAI-API extension some
serving frameworks support by injecting the template into the model's
Jinja chat template at render time). Confirmed `llama-server` honors this
correctly with the official minimal example first, before trusting any
result on harder content:

```python
extra_body={"chat_template_kwargs": {"template": '{"store": "verbatim-string"}'}}
messages=[{"role": "user", "content": "Yesterday I went shopping at Bunnings"}]
# → {"store": "Bunnings"}  — exactly right, mechanism genuinely works
```

With the templating mechanism verified working, ran the same real paper
content (abstract + introduction, ~1500-2000 chars) against two template
shapes:

| Template | Result |
|---|---|
| `{"entities": [{"name": "verbatim-string", "type": "string"}], "relations": [{"source": "verbatim-string", "relation": "string", "target": "verbatim-string"}]}` | `{"entities": [], "relations": []}` |
| `{"entities": ["verbatim-string"]}` (simplest possible) | `{"entities": []}` |

**Both empty**, despite: (a) the templating mechanism itself confirmed
correct via the control test above, (b) the simplest possible schema tried
in the second row, (c) content that unambiguously contains extractable
entities a human (or qwen2.5-class model) finds immediately — "Transformer",
"BLEU", "WMT 2014", the paper's own named authors.

## Conclusion

**NuExtract-2.0-4B (Q4_K_M) does not work for this task, with either
prompting convention tried.** This isn't a "wrong prompt format" problem
(Round 1's hypothesis going in) — Round 2 ruled that out directly by using
NuExtract's own real convention, verified functional on a trivial case,
and it still failed on real content. Possible explanations not
distinguished by this test: the 4B/Q4_K_M combination may be too degraded
for open-ended "find all the entities" extraction (as opposed to
NuExtract's likely stronger suited use case — pulling a few specific known
fields out of semi-structured documents, e.g. invoices, forms), or
open-ended multi-entity/multi-relation KG construction may simply be
outside what NuExtract's fine-tuning targeted at all, regardless of
quantization.

**Recommendation**: don't adopt NuExtract-2.0-4B for Prisma's KG extraction.
Combined with `docs/qwen3-family-evaluation.md`'s verdict (nothing in the
Qwen3 generation beat it either), `qwen2.5:7b-32k`-class remains the only
model that has actually demonstrated reliable KG extraction quality across
every controlled test in this project to date. Untested: NuExtract at
higher precision (Q8/F16) or the 8B variant — not tried here since the 4B
Q4_K_M result was unambiguous enough (verified-correct templating,
simplest-possible schema, still empty) that a quantization/size argument
alone seems unlikely to fully explain it, though not proven impossible.
