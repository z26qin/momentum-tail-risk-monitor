# Limitations

This document lists what the MVP deliberately does **not** claim.

## Scope

- Prototype / take-home research monitor, not a production trading platform.
- No portfolio sizing, execution, or investment recommendation.
- No causal identification of why a momentum crash occurs.
- No aggregate crash probability or opaque composite score.

## PM portfolio vs UMD comparison

- The **primary object** is the PM momentum portfolio (default: S&P 500 12-1
  long-10 / short-10). Scorecard, unwind, and mechanism scenarios refer to
  that book.
- **UMD / Daniel–Moskowitz** inputs are a **comparison benchmark** only. They
  provide published-factor context and state-conditioned UMD outcome
  statistics.
- Do not read the UMD comparison state as a score for the PM book, and do not
  blend the two layers into one risk number.

## Data and universe

- The default PM book uses a current SPY membership snapshot as a historical
  stand-in and is therefore survivorship-biased. It is not yet a plug-in for an
  arbitrary live PM book.
- Public-vendor price histories can contain ticker or corporate-action
  discontinuities; extreme momentum observations need investigation before
  economic interpretation.
- Industry classification is unavailable and reported as missing rather than
  invented.
- Crowding monitoring uses book-structure proxies (concentration, breadth,
  correlated-theme unwind) plus optional FINRA / GDELT side notes. It does not
  observe ownership, leverage, financing, or forced selling. See
  `Future_To_DO.md` for T2–T4 production imagination.
- The mechanical-unwind / market-absorption layer infers possible crowding from
  factor footprints, momentum-extreme abnormal turnover, and short-horizon
  price absorption. It uses daily public data only. Size control depends on
  SEC shares outstanding coverage and may fall back to MomRank+Vol. Extreme
  baskets are the PM L10∪S10 book, not French deciles.
- The module detects factor-aligned trading footprints, not actual hedge-fund
  liquidations. It should be interpreted as a mechanical-unwind proxy rather
  than direct positioning evidence.
- SEC fundamental coverage for the unwind anchor remains degraded / often
  unavailable under the approved feasibility audit.

## Evidence layer

- Default demo evidence is an exact-date validated cache replay.
- The preview makes no network or model call and cannot rewrite deterministic
  facts.
- When date-matched validated evidence is absent, status is `unavailable`.
- `historical_analogs` in the card payload are state-conditioned UMD
  **comparison** statistics, not nearest-neighbor analog retrieval and not
  outcomes of the PM’s customized book.

## Mechanism scenarios

- The three crash mechanisms are independent descriptive rules on the PM book.
- They are not calibrated crash forecasts and have not been out-of-sample
  validated as predictive signals.
- The correlated-theme calculation is a return-correlation proxy; it does not
  observe common ownership, leverage, financing, or forced selling.
- `outputs/research_validation/episode_fingerprints.*` are interpretability
  checks only. Research priors never enter computation and must not be used to
  retune thresholds after the table is seen.
- There is not yet a persisted historical mechanism/scorecard state series, so
  a descriptive PM-book forward-outcome table is deferred (see
  `pm_book_outcomes.md` and `Future_To_DO.md`).

## Interpretation

- Optional LLM interpretation is evidence-ID constrained and narrative-only.
- Without credentials or an injected interpreter, the path falls back to a
  deterministic narrative and records that LLM was not used.
- Interpretation cannot change values, thresholds, triggers, or risk state.
