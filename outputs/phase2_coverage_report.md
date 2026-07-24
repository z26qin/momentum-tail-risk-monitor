# Phase 2 GDELT coverage report

- Trading-date coverage: 2017-01-03 through 2026-06-30 (2,385 rows).
- Rows with complete prior-only 126-day volume normalization history: 2,244.
- Trading dates with an unresolved GDELT-wide source gap: 15; these rows are excluded from both models rather than encoded as zero news.
- Timing rule: a UTC calendar-day bucket is attached to the first US trading close strictly after that calendar date. Friday through Sunday therefore pool into Monday when Monday is open; holiday buckets roll to the next open date.
- Timestamp assumption: DOC 2.0 daily timeline labels identify UTC calendar buckets. A bucket is treated as complete only at 00:00 UTC on the following calendar day, which precludes same-day-close use.
- Zero matching articles are recorded as a zero count/volume and undefined tone. A request or parse failure sets an explicit failure state and is never converted to zero.
- Every z-score requires a full 126-row calendar history. Volume uses at least 101 observed prior days (80% of the window) so a documented vendor outage does not erase otherwise usable later dates; tone uses at least 20 observed-tone days because zero-match tone is undefined.

## Query coverage

| Query | First normalized date | Volume missing | Tone-z missing | Zero-match trading dates |
|---|---:|---:|---:|---:|
| Q_PANIC | 2017-07-05 | 5.9% | 16.1% | 10.2% |
| Q_ROTATION | 2017-07-05 | 5.9% | 38.9% | 33.4% |
| Q_POLICY | 2017-07-05 | 5.9% | 5.9% | 0.0% |
| Q_CROWDING | 2017-07-05 | 5.9% | 16.6% | 10.8% |
| Q_RISKOFF | 2017-07-05 | 5.9% | 9.5% | 3.6% |

## Feature distributions

| Feature | Count | Mean | Std | 5% | Median | 95% |
|---|---:|---:|---:|---:|---:|---:|
| q_panic_vol_z | 2244 | 0.096 | 1.747 | -0.927 | -0.233 | 1.727 |
| q_rotation_vol_z | 2244 | 0.068 | 1.447 | -0.737 | -0.303 | 1.930 |
| q_policy_vol_z | 2244 | 0.053 | 1.191 | -0.967 | -0.305 | 2.340 |
| q_crowding_vol_z | 2244 | 0.039 | 1.535 | -1.000 | -0.252 | 1.794 |
| q_riskoff_vol_z | 2244 | 0.043 | 1.353 | -0.755 | -0.309 | 1.824 |
| q_panic_tone_z | 2002 | -0.009 | 1.055 | -1.679 | 0.007 | 1.614 |
| q_rotation_tone_z | 1457 | 0.013 | 1.045 | -1.587 | 0.017 | 1.595 |
| q_policy_tone_z | 2244 | -0.040 | 1.094 | -1.895 | 0.034 | 1.613 |
| q_crowding_tone_z | 1988 | 0.008 | 1.060 | -1.884 | 0.055 | 1.672 |
| q_riskoff_tone_z | 2158 | -0.002 | 1.041 | -1.651 | -0.011 | 1.707 |
| attention_max | 2244 | 1.395 | 2.661 | -0.255 | 0.681 | 4.910 |
| narrative_breadth | 2244 | 0.518 | 0.742 | 0.000 | 0.000 | 2.000 |
| tone_min | 2244 | -1.043 | 0.937 | -2.705 | -0.920 | 0.216 |

## Largest absolute feature correlations

| Feature 1 | Feature 2 | Correlation |
|---|---|---:|
| q_panic_vol_z | attention_max | 0.595 |
| attention_max | narrative_breadth | 0.534 |
| q_policy_tone_z | tone_min | 0.529 |
| q_riskoff_tone_z | tone_min | 0.455 |
| q_crowding_vol_z | attention_max | 0.438 |
| q_riskoff_vol_z | attention_max | 0.432 |
| q_policy_vol_z | narrative_breadth | 0.430 |
| q_panic_tone_z | tone_min | 0.418 |
| q_rotation_vol_z | attention_max | 0.410 |
| q_riskoff_vol_z | narrative_breadth | 0.397 |
| q_rotation_tone_z | tone_min | 0.390 |
| q_crowding_tone_z | tone_min | 0.386 |

## Label-blind title sanity check

### Q_PANIC

Query: `("stock market crash" OR "market panic" OR "forced selling" OR "margin call") (stocks OR equities) sourcecountry:US sourcelang:english`

- Will the Stock Market Crash Again in 2025 ? Here What History Shows .
- Financial markets may be the last guardrail on Trump
- Financial Markets May Be The Last Guardrail On Trump
- Financial markets may be the last guardrail on Trump
- Financial markets may be the last guardrail on Trump

Sanity decision: Retains only explicit market-panic or forced-selling phrases combined with stocks/equities; generic crash and panic terms were excluded.

### Q_ROTATION

Query: `("sector rotation" OR "factor rotation" OR "value rotation") sourcecountry:US sourcelang:english`

- Anfield U . S . Equity Sector Rotation ETF ( BATS : AESR ) Trading 0 . 6 % Higher – Time to Buy ?
- SPDR SSGA US Sector Rotation ETF ( NYSEARCA : XLSR ) Stock Position Lowered by GeoWealth Management LLC
- SPDR SSGA US Sector Rotation ETF ( NYSEARCA : XLSR ) Position Raised by Envestnet Asset Management Inc .
- Envestnet Asset Management Inc . Purchases 196 , 292 Shares of SPDR SSGA US Sector Rotation ETF ( NYSEARCA : XLSR )
- SPDR SSGA US Sector Rotation ETF ( NYSEARCA : XLSR ) Sees Large Volume Increase – Time to Buy ?

Sanity decision: The initial sample contained incidental portfolio and single-stock mentions. The frozen query keeps only explicit factor/sector/value-rotation phrases; generic rotation and growth-to-value wording were excluded. A repeat-count operator was rejected because it made the historical request unnecessarily expensive.

### Q_POLICY

Query: `("Federal Reserve" OR Fed) ("rate hike" OR "rate cut" OR liquidity OR hawkish OR dovish) (stocks OR markets) sourcecountry:US sourcelang:english`

- Markets Need More Than Rate Cuts to Recover
- Bitcoin Next Big Catalyst : Why May could be the most volatile month of 2025
- Analyst who called 2024 rally warns of yield shock
- Veteran fund manager who predicted drop updates stock market forecast
- Why Marvell Technology , Inc . ( MRVL ) is Among the Best Oversold NASDAQ Stocks to Buy Right Now

Sanity decision: The initial shock-only query returned too few titles. The frozen query still requires an explicit Fed reference and stocks/markets, but uses interpretable policy and liquidity terms broad enough to form a daily aggregate.

### Q_CROWDING

Query: `("crowded trade" OR "forced deleveraging" OR "short squeeze" OR "quant unwind") (stocks OR equities OR "hedge fund") sourcecountry:US sourcelang:english`

- Why Elong Power Holding Limited ( ELPW ) Is Up the Most So Far in 2025
- Credit a  short squeeze  for the stock market big two - day bounce – NBC New York
- How the mother of all  short squeeze helped drive stocks to historic gains Wednesday
- Apple Inc . ( AAPL ): Jim Cramer Braces for Earnings  We Think Theyre Going to Miss
- Amazon . com , Inc . ( AMZN ): Jim Cramer Questions the Downgrade  Too Much Value to Ignore ?

Sanity decision: The unquoted deleveraging term made the initial request excessively broad. The frozen query requires forced deleveraging or an explicit crowding/squeeze/unwind phrase plus an equity or hedge-fund context.

### Q_RISKOFF

Query: `("risk off" OR "flight to safety" OR "market turmoil") (stocks OR equities OR "Wall Street") sourcecountry:US sourcelang:english`

- Wall Street banks cash in on Trump tariff chaos
- Trump tariffs were expected to boost the dollar , but theyre not
- Trump tariffs were expected to boost the dollar , but recession fears are dragging it down
- Trump tariffs were expected to boost the dollar , but recession fears are dragging it down
- Trump tariffs were expected to boost the dollar , but recession fears are dragging it down

Sanity decision: Requires explicit market-risk phrases plus an equity or Wall Street context; generic investor fear and standalone turmoil were excluded.

