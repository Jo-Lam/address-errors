# study_general: the study chain with a configurable council list

`pipeline/study/` holds the study's fitting chain vendored unchanged; it is hard-wired to the four development
councils (Wigan, Bradford, Leeds, Basingstoke). This folder is a copy of it in which every council-specific spot takes
its value from one council configuration (`councils.py`). With the default configuration the chain gives the same
profile as the study chain: `refit_profile.py --chain general --compare profile/frozen_20261013` reproduces every
compared section (validation/refit_general_frozen_20261014/refit_summary.json).

## Configuration

`councils.py` holds `DEFAULT` (the four councils). A JSON file with the same shape, named by the environment variable
`ADDRESS_ERRORS_COUNCILS`, replaces it; `refit_profile.py --chain general --councils <json>` sets that variable and
writes the configuration it used to `<output>/councils_used.json`. Paths are relative to the study root.

```json
{"discovery_dir": "discovery/v1_20261012", "taxonomy_v1": "taxonomy/mechanisms.yaml",
 "councils": [
  {"name": "wigan", "reference": "reference/ngd_20261001/wigan",
   "pairs": "mined_error_pairs/v2_20261012/pairs_wigan.csv.gz",
   "clean_records": "council_data/clean_v1_20261012/wigan/clean_records.csv", "epoch": "2025-11",
   "alignment": "discovery", "background_weight": 38.07875, "core_pairs": true, "postcode_model": true},
  {"name": "basingstoke", "reference": "reference/ngd_20261001_v2_new_councils/basingstoke",
   "pairs": "mined_error_pairs/v3_basingstoke_20261012/pairs_basingstoke.csv.gz",
   "clean_records": "council_data/clean_v1_20261012/basingstoke/clean_records.csv", "epoch": "2025",
   "alignment": "separate", "background_weight": null, "core_pairs": false, "postcode_model": true}]}
```

| field | meaning |
|---|---|
| `alignment` | `discovery`: aligned in the bottom-up discovery run (`discovery_dir`, study: Wigan, Bradford, Leeds), which also holds its hand-curated clusters; `background_weight` is the fixed number from that run (the study's `BG_W`). `separate`: aligned on its own by `align.py` into `<taxonomy v2>/<name>_align` (study: Basingstoke); the weight comes from that run's `align_audit.json` and `background_weight` must be `null`. |
| `core_pairs` | profile v0 only (`fit_profile.py`): `true` = core pairs council (`PAIR_COUNCILS`), `false` = style only (`STYLE_COUNCILS`). From v1 on every listed council is core, as in the study. |
| `postcode_model` | `fit_profile_v1.postcode_model` fits PC labels for it (study: Wigan and Basingstoke). |
| `epoch` | provenance in the v0/v1 `fitted_on.epochs`. |

The council list order is the order of every per-council loop and output key (study order: wigan, bradford, leeds,
basingstoke). Councils whose name or paths contain `cornwall` or `derby` are refused (`councils.validate`, and
`refit_profile.py` before anything is copied) unless `refit_profile.py --allow-external-test` is given, which sets
`ADDRESS_ERRORS_ALLOW_EXTERNAL_TEST=1` for the chain.

## Council-specific spots and how each is handled

Line numbers are in the vendored originals, `pipeline/study/<file>`.

| file:line | what it does (study) | generalised as |
|---|---|---|
| align.py:21 | default council list `["wigan","bradford","leeds"]` when no council argument | `CFG.DISCOVERY` (same three by default); refit always passes the council |
| align.py:22, 309 | refuse cornwall/derby | `CFG.FORBIDDEN` (empty only with `--allow-external-test`) |
| align.py:25-30 | `find_pairs`: newest `pairs_<c>.csv.gz` anywhere under `mined_error_pairs/` by mtime | the config's `pairs` path (for Basingstoke the same file: v2_20261012 has no Basingstoke pairs) |
| align.py:33-38 | `find_components`: tries `ngd_20261001` then `ngd_20261001_v2_new_councils` | the config's `reference` dir |
| align.py:322 | clean records path `council_data/clean_v1_20261012/<c>` | the config's `clean_records`; SY1 rows (`clean_tags` containing `systemic_truncation`) excluded for any council, as before |
| classify_edits.py:17-19 | `REFDIR`, `PAIRS` dicts (W/B/L in v2_20261012, Basingstoke in v3) | from the config |
| classify_edits.py:21-22 | `CO` list, discovery dir | `CFG.NAMES`, `CFG.DISCOVERY_DIR` |
| classify_edits.py:132-141 | discovery edits + one `basingstoke_align` run, concatenated | discovery edits filtered to the config's discovery councils (no-op by default), then every `separate` council's `<c>_align` in config order (same row order as the study) |
| classify_edits.py:137, 142 | `BG_W`: fixed weights 38.07875 / 52.92925 / 89.37525 for W/B/L, Basingstoke from `align_audit.json` | `background_weight` for discovery councils; `align_audit.json` for separate ones |
| classify_edits.py:201-203 | SY1-truncated rows dropped from the rate denominator, Basingstoke only | every council with a clean_records file; W/B/L carry no `systemic_truncation` tag (checked: 0 rows), so the result is unchanged |
| classify_edits.py:16, 143, 163, 168 | discovery family F23 (hand-curated cluster to family map) marks building recodes as SU14 | unchanged; only discovery councils have clusters (see below) |
| build_v2.py:9-11, 26-31 | same `REFDIR`/`PAIRS` and the Basingstoke-only SY1 filter | as classify_edits |
| build_v2.py:52 | `fit per council` needs >= 30 clusters in each of `len(e) == 4` councils | `len(e) == len(CO)` (all listed councils) |
| build_v2.py:74 | ST3 fit_status text "(Bradford 'Off' convention)" | kept: descriptive text, and "house style" in it is what marks ST3 as a style ID downstream |
| build_v2.py:111 | `development_councils` list with Basingstoke's SY1 note; `external_test_never_used` | built from the config; the SY1 note goes on every council whose clean records carry SY1 tags (Basingstoke); external-test list = cornwall/derby not in the config |
| build_v2.py:116, 119 | examples: discovery + `basingstoke_align` | as classify_edits (same order, so rows line up with `edit_v2_labels`) |
| fit_profile.py:20-22 | `PAIR_COUNCILS` (W/B/L), `STYLE_COUNCILS` (all four) | `core_pairs` flag; v0 is not run by refit_profile |
| fit_profile.py:40-44 | comp/pairs read by glob over `ngd_20261001/*` and `v2_20261012/pairs_*` | union of the `core_pairs` councils' files (same tables) |
| fit_profile.py:306 | clean records path | config |
| fit_profile.py:380 | split file restricted to `('wigan','bradford','leeds')` | `PAIR_COUNCILS` |
| fit_profile.py:470-473 | `fitted_on` paths, `councils_style_only: ['basingstoke']`, epochs | derived from the config; epochs follow config order (keys leeds, wigan, bradford in the study: same values, different key order) |
| fit_profile_v1.py:32-37 | `COUNCILS`, `REF`, `PAIRS` | config (same strings, so `fitted_on.reference/pairs` are unchanged) |
| fit_profile_v1.py:402, 417; fit_profile_v2.py:383; fit_profile_v3.py:31, 213 | clean records path template | `v1.CLEAN` from the config |
| fit_profile_v1.py:415 | `postcode_model` for `('wigan', 'basingstoke')` | `postcode_model` flag |
| fit_profile_v1.py:539 | epochs dict | config (key order as above) |
| fit_profile_v3.py:300 | debug print of Leeds modifiers | unchanged (print only; `d.get('leeds')` is `None` without Leeds) |
| common.py:12-20 | `COUNCILS`, `COUNCILS_V1`, `REFS`, `PAIR_FILES` | config (`core_pairs` councils and all councils) |
| discriminate.py:201 | council list for a run directory | all config councils |
| v1/v2/v3 LOCO and in-distribution loops | over `COUNCILS` | unchanged code; a new council adds a fold |

`fit_house_style.py`, `families.py`, `spec_v2.py`, `flags_v2.py` take no council list and are copied as they are.

## What does not generalise cleanly to a new council

- **Discovery clusters and families (F01-F24, `families.py`).** They were curated by hand from the Wigan, Bradford and
  Leeds clusters. A new council aligned by `align.py` has no clusters, so it gets what Basingstoke got: no F23 building
  recode branch. Its SU14 comes only from the `id_*`/`letter_digit_*` relations and `unit_id_rewritten`; the INS/DEL
  id fragments of a recode go to PN6/SU7/SU15 instead of SU14. A council with many recoded buildings (student halls)
  will show less SU14 and more of those mechanisms than a discovery council would.
- **Fixed background weights.** Only the three discovery councils have them; a new council's weight is computed by its
  own `align.py` run (pool / sampled), which is the Basingstoke route.
- **Constants fitted or chosen on the development councils**: 4,000 background rows per council, `REQ_SHARE`,
  `REQ_MIN_ROWS`, `REQ_MAX_BASE`, `BUNDLE_MIN_ROWS`, `NEVER_CONVENTION`, `MOD_PRIOR`/`MOD_RANGE`, the smoothing grids,
  `RURAL_MAX_POSTCODE_SIZE`, the 30-cluster `fit_status` rule, and the classify_edits lexicons (UNIT, FLOOR, GENERIC,
  DQ words). A new council is fitted with them as they are.
- **County vocabularies.** `fit_house_style.COUNTY_WORDS` already includes Cornwall/Kernow and Derbyshire and is what
  the v3 chain uses. The older lists (`fit_profile.COUNTY`, `fit_profile_v1.COUNTY`, `discriminate.COUNTY`) cover only
  the development counties; they feed v0-v2 outputs and the discriminator, not the v3 profile.
- **Text written for the four**: `spec_v2.py` notes (rates per council in prose), build_v2's ST3 "Bradford" wording,
  profile ids, dates and the `intensity_decision` note. They are labels, not fitted values.
- **Adding any council refits the core.** Every listed council is in the v1-v3 core and in leave-one-council-out
  tuning, so the bundles, rates, smoothing and house style of all councils change; only the default configuration
  reproduces the frozen profile.
- **Inputs a new council must have**: a reference built the same way (components.csv.gz with the NGD and `rm_*` PAF
  columns), mined pairs from the same miner version (columns such as `nearest_canonical`, `dwelling_diff`, `collision`,
  `labels_vs_ngd`, `postcode_label`), and clean records with `recorded_address_raw`, `recorded_postcode`, `clean_tags`.
