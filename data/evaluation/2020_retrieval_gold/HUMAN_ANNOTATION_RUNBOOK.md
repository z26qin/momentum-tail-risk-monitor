# Human annotation runbook

## Step 1 — Generate or refresh the candidate pool

From the repository root:

```bash
# Rebuild from the committed, hashed candidate manifest.
uv run python -m src.evaluation.retrieval_gold build

# Intentionally reacquire the small official archive slice.
uv run python -m src.evaluation.retrieval_gold build --refresh-sources
```

Refreshing sources refuses to overwrite an annotated queue unless
`--overwrite-annotations` is supplied intentionally. The production provider
still uses its 120-day window; March 9–24 is only the annotation sampling
window.

## Step 2 — Review the teaching examples

Open `annotation/teaching_examples.md`. Discuss the provisional examples, but
remember that every suggestion is marked **NOT GOLD**.

## Step 3 — Fill the CSV

Edit `annotation/annotation_queue.csv` in batches of 10. Do not change the
candidate metadata columns. For each completed row fill:

`timestamp_validity`, `relevance_label`, `mechanism_labels`,
`evidence_direction`, `supporting_passage`, `reviewer_rationale`,
`reviewer_confidence`, and set `review_status=completed`.

Use semicolons between multiple mechanism labels. Leave unreviewed rows blank.

## Step 4 — Validate each completed batch

```bash
uv run python -m src.evaluation.retrieval_gold validate   --annotations data/evaluation/2020_retrieval_gold/annotation/annotation_queue.csv
```

Validation permits the remaining blank rows but rejects malformed completed
rows, duplicate IDs, unsupported mechanisms, ungrounded passages, and
future/relevance conflicts.

## Step 5 — Resolve difficult cases

- choose the lower relevance score when evidence is weak;
- use timestamp `uncertain` when availability cannot be proven;
- use `contextual` instead of `supporting` when the passage does not directly
  connect to the mechanism;
- do not infer momentum-position unwinds from a generic market rally;
- record disagreement with `review_status=needs_discussion` rather than forcing
  certainty.

Resolve disagreements in a second pass and record the final rationale. Never
use future returns, later event summaries, retrieval rank, or a model label.

## Step 6 — Run the final retrieval evaluation

Only after all rows are completed:

```bash
uv run python -m src.evaluation.retrieval_gold evaluate   --annotations data/evaluation/2020_retrieval_gold/annotation/annotation_queue.csv   --retrieval-results data/evaluation/2020_retrieval_gold/retrieval_results.json
```

## Step 7 — Interpret conservatively

Precision and nDCG describe this small, deliberately sampled March 2020 slice,
not production performance or incremental alpha. Timestamp and passage metrics
are control checks. Mechanism coverage is breadth of human-labeled evidence,
not proof that every mechanism occurred. `not_reported` is the correct result
when the strict sample is too small.
