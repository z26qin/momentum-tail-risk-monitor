# Momentum portfolio snapshot — 2026-06-30

## Snapshot contract

- **Portfolio formation date:** 2026-06-30
- **Effective holding month:** July 2026
- **Signal:** 12-1 price momentum
- **Signal formula:** `adjusted_close[m-1] / adjusted_close[m-12] - 1`
- **Signal start date:** 2025-06-30
- **Signal end date:** 2026-05-29
- **Most recent month skipped:** June 2026
- **Rankable universe:** 500 securities
- **Long leg:** top 10, equal weighted, gross exposure `+1.0`
- **Short leg:** bottom 10, equal weighted, gross exposure `-1.0`
- **Net exposure:** `0.0`
- **Membership status:** `current_snapshot_proxy`
- **Survivorship bias:** `true`

The signal uses no June 2026 price return. The ranking is finalized after the
2026-06-30 close and applies during July 2026.

## Long leg

| Price momentum rank | Symbol | Company | 12-1 momentum | Weight |
|---:|---|---|---:|---:|
| 1 | SNDK | SanDisk Corp | +3,637.55% | +10% |
| 2 | LITE | Lumentum Holdings Inc | +799.39% | +10% |
| 3 | WDC | Western Digital Corp | +732.18% | +10% |
| 4 | MU | Micron Technology Inc | +689.72% | +10% |
| 5 | CIEN | Ciena Corp | +613.43% | +10% |
| 6 | STX | Seagate Technology Holdings | +514.17% | +10% |
| 7 | INTC | Intel Corp | +411.96% | +10% |
| 8 | ECHO | EchoStar Corp Class A | +366.39% | +10% |
| 9 | TER | Teradyne Inc | +317.34% | +10% |
| 10 | COHR | Coherent Corp | +305.19% | +10% |
| **Total** |  |  |  | **+100%** |

## Short leg

| Price momentum rank | Symbol | Company | 12-1 momentum | Weight |
|---:|---|---|---:|---:|
| 491 | ZTS | Zoetis Inc | -49.41% | -10% |
| 492 | GDDY | GoDaddy Inc Class A | -52.33% | -10% |
| 493 | PODD | Insulet Corp | -53.87% | -10% |
| 494 | BSX | Boston Scientific Corp | -55.02% | -10% |
| 495 | INTU | Intuit Inc | -57.57% | -10% |
| 496 | IT | Gartner Inc | -59.87% | -10% |
| 497 | CSGP | CoStar Group Inc | -59.95% | -10% |
| 498 | CHTR | Charter Communications Inc Class A | -64.76% | -10% |
| 499 | FISV | Fiserv Inc | -67.19% | -10% |
| 500 | TTD | The Trade Desk Inc Class A | -70.05% | -10% |
| **Total** |  |  |  | **-100%** |

## Data-quality and interpretation warnings

1. The universe is the State Street SPY holdings snapshot dated 2026-07-24,
   applied as a current-constituent proxy. It is not point-in-time S&P 500
   membership as of 2026-06-30.
2. The portfolio therefore contains survivorship and index-membership
   look-ahead bias.
3. Extreme signals, especially SNDK, require corporate-action, ticker-history,
   split, and adjusted-price review before the snapshot is used for an
   investment interpretation.
4. This is a deterministic research-monitor snapshot, not a trade
   recommendation.

## Machine-readable source

The exact unrounded values, signal dates, ranks, weights, and audit fields are
stored in:

- `data/processed/momentum_portfolio_holdings.parquet`
- rows where `formation_date == 2026-06-30`
