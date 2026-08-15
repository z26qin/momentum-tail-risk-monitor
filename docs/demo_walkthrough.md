# Demo runbook walkthrough — 15–20 minutes

## Pre-demo check

```bash
uv sync --locked --all-groups
uv run python -m src.mvp.demo_smoke_test
```

Open:

```bash
uv run --with jupyterlab jupyter lab notebooks/final_mvp_demo.ipynb
```

The notebook is a **step-by-step runbook**: the PPT tells the story, the
runbook produces and shows the numbers for the 2026-05-29 case. It defaults to
`USE_LLM=True` (live DeepSeek if `DEEPSEEK_API_KEY` is present); without a key
it fail-closes to deterministic text and never changes metrics. Set
`USE_LLM=False` at the top of `notebooks/demo_setup.py` for a fully offline run.

## Minute 0–3 — Opening and runbook map

Use the first two cells to frame the demo:

- the system combines two momentum-crash mechanisms with an AI-assisted
  evidence layer;
- the workflow is monitor → inspect → challenge → discuss escalation;
- AI is evidence interpretation, not a replacement for the deterministic
  monitors;
- the PPT presents the story; this notebook produces the numbers.

## Minute 3–6 — Step 1: Market regime

Walk the deterministic UMD / Daniel–Moskowitz context:

- market return, drawdown, recovery and volatility conditions;
- historical analogs with tail-loss frequency and forward-return percentiles.

Emphasize: regime state is **comparison context only**, never a PM-book crash
probability.

## Minute 6–9 — Step 2: Quant signals

Show the four scorecard indicators with value, threshold, status, and change
vs the comparison date:

- status is **triggered / not triggered**, not a probability;
- the scorecard is deterministic and unchanged by the LLM.

## Minute 9–12 — Step 3: Structural and mechanical unwind

Cover the three mechanism scenarios, then the concentration and market
footprint layers:

- theme concentration and residual loss;
- factor footprint, turnover, and liquidity absorption;
- unwind scorecard rows.

Read these layers separately from the quant scorecard.

## Minute 12–15 — Step 4: AI evidence layer

Show the narrative interpretation plus supporting / contradicting / missing
evidence. With `DEEPSEEK_API_KEY` this is live DeepSeek; without a key it
fail-closes to deterministic text. Then open the frozen 2026-05-29 evidence
challenge (supported / unconfirmed / why broad action may be premature).

## Minute 15–18 — Step 5: Final PM read and cross-case comparison

Collapse all layers into the integrated read table:

- current state, main vulnerability, why not act yet;
- what would change the reading and the conditional response;
- close with `outputs/cross_case_comparison.md` to show the same rules are
  selective across cases.

## Minute 18–20 — Limitations and close

End with the short limitations list and the production path. Do not present
UMD tail frequencies as the PM book’s probability, and do not claim forced
deleveraging unless the evidence supports it.
