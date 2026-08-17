# Public narrative-shift POC

Isolated exploratory experiment. It is **not** part of the deterministic
scorecard, portfolio construction, market-regime logic, or frozen case
conclusions.

## Research question

Did the publicly retrievable narrative around **AI infrastructure and
semiconductor momentum** change between two fixed windows around the frozen
**2026-05-29** current-semi-unwind case?

The POC asks DeepSeek to search the baseline window and the recent window
separately, then compare source-backed public language. It is a presentation
aid for the research idea, not a validated social-media factor.

## What it uses

- DeepSeek **Responses API** through the OpenAI Python SDK
- Model default: `deepseek-v4-flash` (`DEEPSEEK_RESPONSES_MODEL`)
- Server-side `web_search` (no local crawler, Tavily, vector store, or agent)
- Frozen case cutoff `2026-05-29` (unchanged)
- Baseline window `2026-04-01` through `2026-04-30` (through the pack comparison date)
- Recent window `2026-05-01` through `2026-05-29`

The existing Chat Completions DeepSeek path (`deepseek-chat` via
`src/evidence/deepseek_explainer.py`) is unchanged.

## How to run

```bash
uv sync --locked --all-groups

# Inspect the planned call. Does not spend API credits.
python scripts/run_narrative_shift_poc.py --dry-run

# Live call. Requires DEEPSEEK_API_KEY. Spends credits.
python scripts/run_narrative_shift_poc.py
```

Optional flags: `--output-dir`, `--overwrite`. Existing output is not replaced
unless `--overwrite` is passed.

Environment:

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_RESPONSES_MODEL=deepseek-v4-flash
```

Never commit the API key. Never log it.

## Expected output

```text
outputs/narrative_shift_poc/
├── narrative_shift_poc.md
└── narrative_shift_poc_metadata.json
```

The Markdown file is a PM-facing note with an executive read, baseline vs
recent narratives, a change table, supporting and contradicting evidence, and
explicit non-findings. The JSON file stores case dates, model, token usage if
returned, and limitation flags.

Generated files are gitignored.

## Limitations

This POC is exploratory only. It does **not**:

- measure complete social-media attention;
- claim representative investor sentiment;
- infer institutional positioning or forced deleveraging;
- validate predictive value or a crash probability;
- change any deterministic monitor output.

General web search is not a complete Reddit, X, or StockTwits dataset.
Treat the result as a secondary confirmation sketch, not a standalone risk
signal.
