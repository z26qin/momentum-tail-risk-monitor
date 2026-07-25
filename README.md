# Momentum Tail-Risk Research Prototype

This repository estimates the probability of sharp reversals in the US equity
momentum factor. Phase 1 is deliberately market-only: it uses momentum,
broad-market, volatility, and momentum-leg information. Text and positioning
data are deferred.

The fixed research vintage is `AS_OF_DATE=2026-05-29`. The model sample begins
on 1990-01-02, when unfilled VIX observations become available. This is a lean
research prototype, not a trading system or investment recommendation.

## Research target

For horizons of 5 and 20 momentum trading days, the primary target is a
forward compounded UMD return below its point-in-time historical fifth
percentile. A historical label enters the threshold sample only after its
entire forward window has matured. The primary target is unconditional on
prior momentum strength so it continues to represent losses that affect
momentum P&L; prior state enters through features instead.

Positive event days are grouped into episodes. A new episode begins only
after at least five consecutive valid non-event assessment days.

The nested baselines are:

- B0: constant event rate in the purged training rows;
- B1: unweighted logistic regression on bear state, 126-day market variance,
  and their interaction;
- B2: unweighted L2-regularized logistic regression on all 24 market features.

All imputation, standardization, and model fitting occur inside a new
training-fold-only scikit-learn pipeline. No alert or classification threshold
is selected.

## Reproduce Phase 1

Python 3.11–3.14 and [`uv`](https://docs.astral.sh/uv/) are required. Run from
the repository root:

```bash
uv sync --locked --extra test
export MTR_AS_OF_DATE=2026-05-29

uv run python -m src.data.french --as-of-date "$MTR_AS_OF_DATE"
uv run python -m src.data.vix \
  --as-of-date "$MTR_AS_OF_DATE" \
  --write-fill-sensitivity
uv run python -m src.features.legs
uv run python -m src.features.labels --as-of-date "$MTR_AS_OF_DATE"
uv run python -m src.features.market_features --as-of-date "$MTR_AS_OF_DATE"

uv run python -m src.modeling.validation --as-of-date "$MTR_AS_OF_DATE"
uv run python -m src.modeling.baselines \
  --stage development \
  --as-of-date "$MTR_AS_OF_DATE"
uv run python -m src.modeling.baselines \
  --stage holdout \
  --as-of-date "$MTR_AS_OF_DATE"

uv run jupyter-execute \
  --inplace \
  --timeout=120 \
  notebooks/01_baseline_eda.ipynb
uv run python -m src.modeling.audit
uv run pytest
```

The raw cache and its SHA256 provenance sidecars are already under `data/raw`.
For a network-restricted rebuild, add `--offline-dir data/raw` to the French
and VIX commands. Do not use `--force` unless intentionally replacing the
frozen raw snapshots.

The holdout command is included for exact reconstruction of this completed
run. During new research it must be run only after development choices are
frozen. Routine integrity checks should use `src.modeling.audit`, which reads
saved results without fitting or predicting.

## Public data sources

| Input | Source | Use |
|---|---|---|
| Daily UMD factor | [Ken French momentum factor ZIP](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip) | Published momentum return and label calendar |
| Daily research factors | [Ken French research factors ZIP](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip) | Broad US market total-return proxy, constructed as `Mkt-RF + RF` |
| Six size–momentum portfolios | [Ken French six portfolios ZIP](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/6_Portfolios_ME_Prior_12_2_Daily_CSV.zip) | Winner and loser leg reconstruction |
| Ten momentum deciles | [Ken French ten portfolios ZIP](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/10_Portfolios_Prior_12_2_Daily_CSV.zip) | Decile-based formation spread |
| VIX close | [FRED VIXCLS](https://fred.stlouisfed.org/series/VIXCLS) and [CSV endpoint](https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS) | Option-implied market stress and model-sample boundary |

Ken French returns are converted from percent to decimal. VIX remains in
index points.

## Validation design and outputs

The originally requested three-year tests failed the minimum-five-episodes
gate for two 20-day folds. With explicit approval, development validation uses
three non-overlapping six-year tests after an initial ten-year training
window. Training expands from 1990-01-02, and every row with
`label_end_date >= test_start` is purged. The final three calendar years form
the retained holdout.

Important artifacts:

- `docs/DECISIONS.md`: complete research contract and judgment log;
- `outputs/phase1_review.md`: compact Phase 1 evidence review;
- `outputs/split_manifest.csv`: development split and episode audit;
- `outputs/baseline_metrics.csv`: development and holdout metrics;
- `outputs/calibration_table.csv`: probability buckets and realized rates;
- `outputs/model_coefficients.csv`: standardized logistic coefficients;
- `outputs/preprocessing_statistics.csv`: fold-local medians and scales;
- `outputs/baseline_predictions.parquet`: saved probabilities and outcomes;
- `outputs/task4_validation_audit.json`: independent metric and integrity audit;
- `notebooks/01_baseline_eda.ipynb`: executed 12-cell visual review.

## Tests

The seven-test suite covers:

- forward-return alignment with a planted crash;
- point-in-time threshold maturity and future-data invariance;
- five-quiet-day episode de-clustering;
- strict walk-forward ordering and label-window purging;
- fold-specific imputation/scaling statistics;
- real-data winner/loser reconstruction against published UMD;
- stable Parquet and audit hashes under a fixed `AS_OF_DATE`.

## Limitations

- **Market proxy naming:** `mkt_total_return = Mkt-RF + RF` is a broad US
  market total-return proxy. It must not be represented as a named cash index.
- **VIX boundary and timing:** VIX begins on 1990-01-02 and therefore bounds
  the model sample. Three valid momentum dates have missing VIX values:
  1991-03-01, 1997-01-31, and 1997-11-26. They remain missing in the primary
  data and are imputed only inside training folds. Daily source files do not
  provide exact historical publication timestamps; the approved convention is
  a post-close assessment for earliest action next session.
- **Formation spread:** this is the compounded decile-10 return minus the
  compounded decile-1 return over 252 observations ending at `t−21`. The most
  recent 21 trading rows are skipped, so the full input span is 273 rows. It
  is not a beta or correlation measure.
- **Sparse independent events:** overlapping daily labels are serially
  dependent. Episode counts are much smaller than event-day counts. Only one
  20-day episode appears in the retained holdout, making its metrics highly
  uncertain.
- **Calibration:** B2 shows useful ranking in some periods but unstable
  probability levels and poor development log loss. Phase 1 does not claim a
  production-calibrated alert model.
- **Holdout limitation:** aggregate holdout counts were exposed during an
  early split-gate implementation. No predictions or performance metrics were
  used for tuning, and the limited contamination was explicitly accepted
  before the one-time evaluation.
- **Source revisions:** raw snapshots and hashes make this run reproducible,
  but public vendors can revise later downloads.
- **Deferred information:** no text or positioning information is ingested.
  The separate GDELT feasibility spike remains deferred and is not part of
  Phase 1.

## Alternative-data overlays

Two overlays inform monitoring and feed the downstream evidence layer. **Neither
alters the risk number.** There is no fitted model in this project: the risk
state is adopted directly from Daniel–Moskowitz (2016) and the risk probability
is a point-in-time empirical conditional frequency. Phase 1 sections above
describe an abandoned modelling architecture and are retained as history.

- **Structured — loser-leg crowding** (`data/processed/positioning_panel.parquet`).
  FINRA short interest joined on **publication date**, plus FINRA daily
  short-sale volume, measured across a monthly-rebalanced proxy loser decile.
- **Unstructured — narrative attention and tone** (`data/processed/narrative_panel.parquet`).
  GDELT DOC 2.0 timelines across five frozen mechanism queries. **Not built in
  the current run** — see `BLOCKERS.md`.

Read `outputs/data_review.md` first: it carries the coverage tables, the match
rates, every limitation, and the self-review.

### Reproduce the overlays

```bash
uv sync --locked --extra test
uv run python -m src.data.universe
uv run python -m src.data.prices
uv run python -m src.data.finra --stage all
uv run python -m src.features.positioning_panel
uv run python -m src.data.gdelt
uv run python -m src.data.gdelt_sanity
uv run python -m src.features.narrative_panel
uv run pytest
```

Every network artifact is cached under `data/raw/` with a SHA-256 provenance
sidecar, so a second run makes **zero** network calls. The determinism tests
assert this by hard-disabling the network and rebuilding.

The large raw caches (`data/raw/finra/daily/`, `data/raw/prices/`, GDELT
payloads) are git-ignored: they total roughly 150 MB on disk while their
provenance sidecars and the processed extracts are tracked.

### Alternative-data sources

| Input | Source | Use |
|---|---|---|
| Consolidated short interest | [FINRA Query API `otcMarket/consolidatedShortInterest`](https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest) | Loser-leg short position, joined on publication date |
| Daily short sale volume | [FINRA CNMS daily files](https://cdn.finra.org/equity/regsho/daily/) | Off-exchange shorting flow, from 2018-08-01 |
| Short interest reporting dates | [FINRA schedule page](https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest) plus archived snapshots | Settlement → publication mapping (the point-in-time gate) |
| Universe | [Nasdaq stock screener](https://api.nasdaq.com/api/screener/stocks) | 200 large caps, current membership — survivorship-biased |
| Prices and volume | [Yahoo Finance chart API](https://query1.finance.yahoo.com/v8/finance/chart/) | 12-2 momentum ranking and as-traded volume |
| News attention and tone | [GDELT DOC 2.0](https://api.gdeltproject.org/api/v2/doc/doc) | Narrative overlay |

### Alternative-data limitations

Full list in `outputs/data_review.md` §7. The three that matter most:

- **The narrative overlay does not exist** in this run. GDELT applied a
  sustained IP block; the code and tests are complete and the cache is empty.
- **`days_to_cover` mechanically falls during crashes**, because volume is its
  denominator and volume explodes under stress. Measured mean `days_to_cover_z`
  was **−2.23 in March 2020**. Reading low days-to-cover as low squeeze risk
  during a volume spike is backwards.
- **The universe is current membership applied historically** and large-cap
  dominated, so it is survivorship-biased and *understates* crowding relative to
  a true momentum loser decile.
