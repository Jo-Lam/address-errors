# LOCO results: all-six refit, leave one council out

Written 2026-10-14T14:55+00:00 by package/validation/loco/summarise.py. Aggregates only.

Each fold: profile refitted on the other five councils (`refit_profile.py --chain general`, config `configs/councils_minus_<H>.json`), then the LOCO copy of the external-test harness (`package/validation/loco/code/`, changes in `package/validation/loco/CHANGES.md`) on the held-out council's whole data: house style refitted from its own strings (Derby and Cornwall from the joined, comma-carrying string), pooled core rates at intensity 1.0, same miner labels, scored with criteria v2 (verdict) and v1 (absolute).

| Held out | Records | C1 touch ratio real/synth (real/synth touch) | C2 mechanisms covered (paired CI covers 0) | C3 exact collision real / synth | C4 building-avg identical share real / synth | C5 n-gram AUC with / without commas | v2 C1-C5 | v1 C1-C5 |
|---|---|---|---|---|---|---|---|---|
| derby | 115,496 | 0.893 (0.033/0.037) | 0.71 of 14 | 0.123% / 0.167% | 0.826 / 0.793 | 0.575 / 0.566 | PPPPP (5/5) | PFFPP (3/5) |
| cornwall | 287,118 | 2.117 (0.129/0.061) | 0.17 of 23 | 0.354% / 0.417% | 0.595 / 0.793 | 0.822 / 0.737 | FFPFF (1/5) | FFPPF (2/5) |
| wigan | 153,689 | 0.305 (0.009/0.029) | 0.15 of 13 | 0.079% / 0.103% | 0.813 / 0.879 | 0.663 / 0.645 | FFPPF (2/5) | FFPPF (2/5) |
| bradford | 224,200 | 1.102 (0.056/0.051) | 0.42 of 19 | 0.422% / 0.166% | 0.714 / 0.753 | 0.617 / 0.576 | PPPPP (5/5) | PFFPP (3/5) |
| leeds | 375,835 | 0.791 (0.049/0.062) | 0.45 of 22 | 0.121% / 0.212% | 0.757 / 0.788 | 0.585 / 0.586 | PPPPP (5/5) | PFFPP (3/5) |
| basingstoke | 82,011 | 0.926 (0.043/0.046) | 0.31 of 13 | 0.212% / 0.096% | 0.638 / 0.811 | 0.643 / 0.589 | PFPFP (3/5) | PFFPP (3/5) |

P = pass, F = fail. Thresholds (criteria v2): C1 in [0.43, 1.49]; C2 >= 0.40; C3 synthetic within +/-89% of real; C4 within +/-0.10; C5 AUC <= 0.65 (all records, with commas). v1: C1 [0.43, 1.39]; C2 real inside synthetic 95% interval >= 0.75; C3 +/-35%; C4 pair-weighted share +/-0.10; C5 same.

## Derby and Cornwall: LOCO fold vs the frozen external test

| Council | Profile | C1 | C2 | C3 real / synth | C4 real / synth | C5 with / without commas | v2 | v1 |
|---|---|---|---|---|---|---|---|---|
| derby | frozen_20261013 (external test) | 1.275 | 0.43 of 14 | 0.123% / 0.135% | 0.826 / 0.675 | 1.000 / 0.562 | PPPFF | PFPPF |
| derby | LOCO fold (five other councils) | 0.893 | 0.71 of 14 | 0.123% / 0.167% | 0.826 / 0.793 | 0.575 / 0.566 | PPPPP | PFFPP |
| cornwall | frozen_20261013 (external test) | 2.153 | 0.13 of 23 | 0.354% / 0.423% | 0.595 / 0.754 | 1.000 / 0.737 | FFPFF | FFPPF |
| cornwall | LOCO fold (five other councils) | 2.117 | 0.17 of 23 | 0.354% / 0.417% | 0.595 / 0.793 | 0.822 / 0.737 | FFPFF | FFPPF |

Frozen-profile no-comma AUCs are the post-hoc D2 values from external_test/RESULTS.md.

## Supporting numbers

| Held out | C5 discrepant only, with / without commas | LightGBM AUC (all / discrepant) | C1 at sensitivity intensities | Disclosure: 3-word sequences of its strings in fold profile |
|---|---|---|---|---|
| derby | 0.744 / 0.693 | 0.608 / 0.921 | 1.00: 0.89, 0.43: 1.77, 1.39: 0.65, 0.33: 2.26, 1.42: 0.64 | 0 |
| cornwall | 0.886 / 0.828 | 0.837 / 0.944 | 1.00: 2.12, 0.43: 3.95, 1.39: 1.66, 0.52: 3.51, 1.70: 1.40 | 1 |
| wigan | 0.775 / 0.755 | 0.698 / 0.894 | 1.00: 0.30, 0.43: 0.58, 1.39: 0.21, 0.69: 0.42, 1.41: 0.21 | 0 |
| bradford | 0.753 / 0.732 | 0.655 / 0.877 | 1.00: 1.10, 0.43: 1.84, 1.39: 0.86, 0.34: 2.16, 1.40: 0.85 | 1 |
| leeds | 0.735 / 0.733 | 0.677 / 0.872 | 1.00: 0.79, 0.43: 1.38, 1.39: 0.60, 0.30: 1.54, 1.34: 0.63 | 1 |
| basingstoke | 0.842 / 0.785 | 0.703 / 0.956 | 1.00: 0.93, 0.43: 1.66, 1.39: 0.71, 0.34: 1.97, 1.49: 0.69 | 0 |

Miner sensitivity (development councils): real pairs are the development miner's, synthetic pairs are labelled with the external-test miner copy. Real C3 under the miner copy (external-test rehearsal re-mine, same records): wigan 0.079% (vs 0.079%); bradford 0.422% (vs 0.422%); leeds 0.121% (vs 0.121%); basingstoke 0.212% (vs 0.212%).
