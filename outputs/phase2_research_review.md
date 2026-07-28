# Phase 2 research review

## 1. Research question

Does aggregate, timestamped public-news narrative add incremental early-warning value beyond the Phase 1 market-state model on an identical common sample?

## 2. Economic intuition

Panic and broad risk-off attention can rise before forced exposure reduction, while policy or liquidity surprises can trigger regime changes. Rotation, crowding, deleveraging, and squeeze narratives are especially relevant to momentum because reversals often combine falling recent winners with sharp rebounds in prior losers. Aggregate text can nevertheless fail: it is generic, duplicated across outlets, contemporaneous rather than leading, and only loosely connected to the specific holdings driving a momentum portfolio.

## 3. Data design

GDELT UTC calendar buckets are attached only to the first US trading close strictly after the bucket date. Weekend and holiday observations pool into the next open date. Volume uses pooled matched counts divided by pooled monitored-news counts; tone is matched-count weighted. Zero matches remain zero volume with undefined tone, while failed requests remain explicit failures and are excluded. Every z-score uses a 126-trading-row window shifted by one row, so the current observation never normalizes itself.

B2c refits the exact 24 Phase 1 B2 market features on the Phase 2 common sample. B3 adds only `attention_max`, `narrative_breadth`, and `tone_min`. Both models use identical purged splits and training-fold-only median imputation and scaling. The model class and L2 regularization are unchanged.

Governance note: an initial dry run was rejected during calendar audit because a 120/126 observed-volume requirement delayed the usable final-test start until December 2025 and fold anchoring omitted the last development year. Before accepting any result, the coverage rule was refrozen at 101/126 observed prior days (80%) and folds were anchored to the fixed 2017-01-01 research start. This correction used only vendor coverage and dates, not labels, but the final test is not perfectly pristine because incomplete-sample metrics had been displayed.

After excluding unresolved vendor-gap rows, the accepted final-test common sample begins on 2025-07-03.

The mature common sample ends on 2026-04-30 for h=20 and 2026-05-21 for h=5.

## 4. Results

Negative differences are better for log loss and Brier score; positive differences are better for PR-AUC and episode capture. Episode capture is a retrospective top-decile warning diagnostic over the prior 10 trading dates, not an optimized rule.

| Scope | Horizon | Model | Log loss | Brier | PR-AUC | ROC-AUC | Episode capture |
|---|---:|---|---:|---:|---:|---:|---:|
| development | 20 | B2c | 2.2727 | 0.2195 | 0.1772 | 0.6401 | 31.6% |
| development | 20 | B3 | 2.2346 | 0.2224 | 0.1789 | 0.6418 | 31.6% |
| development | 20 | difference_B3_minus_B2c | -0.0382 | 0.0029 | 0.0017 | 0.0017 | 0.0% |
| development | 20 | paired log-loss 95% block-bootstrap CI | [-0.0920, 0.0081] |  |  |  |  |
| development | 5 | B2c | 0.8974 | 0.1160 | 0.1517 | 0.5153 | 27.8% |
| development | 5 | B3 | 0.9282 | 0.1190 | 0.1467 | 0.5136 | 27.8% |
| development | 5 | difference_B3_minus_B2c | 0.0307 | 0.0030 | -0.0050 | -0.0017 | 0.0% |
| development | 5 | paired log-loss 95% block-bootstrap CI | [0.0101, 0.0559] |  |  |  |  |
| final_test | 20 | B2c | 0.2143 | 0.0674 | NA | NA | NA |
| final_test | 20 | B3 | 0.2153 | 0.0678 | NA | NA | NA |
| final_test | 20 | difference_B3_minus_B2c | 0.0010 | 0.0004 | NA | NA | NA |
| final_test | 20 | paired log-loss 95% block-bootstrap CI | [-0.0011, 0.0042] |  |  |  |  |
| final_test | 5 | B2c | 0.2489 | 0.0746 | 0.1913 | 0.7380 | 16.7% |
| final_test | 5 | B3 | 0.2468 | 0.0737 | 0.1353 | 0.7389 | 16.7% |
| final_test | 5 | difference_B3_minus_B2c | -0.0021 | -0.0009 | -0.0560 | 0.0009 | 0.0% |
| final_test | 5 | paired log-loss 95% block-bootstrap CI | [-0.0061, 0.0012] |  |  |  |  |

## 5. Interpretation

Log loss and Brier score assess probability quality and calibration; PR-AUC and ROC-AUC assess event ranking; the episode diagnostic asks whether a PM would have seen an elevated score before an episode. These are different claims. A small improvement in one metric is not treated as economically meaningful unless it is directionally supported by the paired uncertainty estimate, final-test behavior, and episode evidence.

The primary h=20 final test contains no positive event days. Its log loss still measures the cost of assigned probabilities on non-event days, but PR-AUC, ROC-AUC, and episode capture are not estimable, so it cannot validate early-warning usefulness.

## 6. Two examples

### Useful warning candidate

For h=5, on 2026-05-08, B2c was 55.8% and B3 was 58.7%. The text increment coincided with `attention_max=0.32`, `narrative_breadth=0`, and `tone_min=0.27` before a labelled episode.
This is a retrospective illustration, and the benign-looking aggregate text values make it weak economic evidence despite the elevated B3 score.

### False-positive candidate

On 2026-04-08, B2c was 73.4% and B3 was 75.4%, with `attention_max=-0.12`, `narrative_breadth=0`, and `tone_min=-1.84`, but no labelled event followed in the next 10 trading rows.

## 7. Conclusion

**mixed.** The compact aggregate narrative specification showed some incremental signal, but the probability and/or episode evidence was not consistent enough to claim reliable value.

This result concerns only the tested aggregate specification. It does not establish that article-level retrieval, RAG, embeddings, or a larger text model would work.

## 8. PM use

The prototype is best viewed as a secondary risk-review trigger that asks the PM to inspect momentum exposure, crowding, and squeeze-sensitive positions—not as an automatic trade signal.
