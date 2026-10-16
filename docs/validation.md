# Validation and code provenance

The package was ported from the study's code. This document records checks
performed during that port and identifies the source of the package modules.

The regression checks below compare package output with the study implementation
on study data. They assess implementation equivalence under the tested
configurations; they do not establish that generated addresses reproduce real
recording errors accurately.

The supporting regression reports and study inputs are retained in the study
workspace under `package/validation/`. That directory is not included in the
public repository or distributed package. Paths to those reports below are
provenance references, not downloadable files. Consequently, users cannot
independently reproduce these study-data checks from the public package alone.

The generator's empirical realism assessments, including their limitations and
external-test results, are summarised in the README under “How well it works”.
Results belong to the profile and generator configuration evaluated; they
should not automatically be attributed to later releases or modified settings.

## Checks against the study code

- **All-six profile (`all6`, 14 October 2026):** `refit_general_frozen_20261014/` shows the generalised chain with
  the default four councils reproduces `profile/frozen_20261013` on every compared section (only `status` differs).
  `all6/all6_regression_20261014.json`: on the all-six profile, the package and `generator_v3.py` give identical
  output on all 167,374 held-out development records. `all6/fit_extras_all6.py` builds its style extras. The
  portable copy was scanned for every three-word sequence in Derby's (128,620) and Cornwall's (388,552) real strings:
  none from Derby; four from Cornwall, all generic ("LOWER GROUND FLOOR", "LOWER GROUND FLR", "SECOND FLOOR 1",
  "OUT OF THE"), as the external test found for the frozen profile.
- **Study re-run, 13 October 2026, after the documentation and pipeline changes:**
  `recheck_frozen_regression_20261013.json`, `recheck_frozen_pooled_regression_20261013.json` (frozen profile vs
  `generator_v3.py` SHA-256 `06addb88…50d6`, council rates and pooled) and `recheck_v2_regression_20261013.json`
  (profile v2 vs run 3b): identical on all 167,374 held-out records in each.
- `v3_regression_20261013.json` and `v3_stored_run_20261013.json`: with profile v3, seed
  20261012 and the postcode layer off, the package gives **identical output** to the prototype v3 generator
  (`prototype_loop/code/generator_v3.py`), both rerun and as stored in `prototype_loop/run_v3_20261013`, on all
  167,374 held-out records, including the collision verify step (249 records).
- `frozen_regression_20261013.json` and `frozen_pooled_regression_20261013.json`: the frozen
  profile `profile/frozen_20261013` against `generator_v3.py` SHA-256 `06addb88…50d6`: identical on all 167,374
  held-out records, with council rates and in the pooled external-test setting.
- `v3e_run6_regression_20261013.json` and `v3e_run6_pooled_regression_20261013.json`: against
  `generator_v3.py` as of 13:37 on 13 October (SHA-256 `06addb88…50d6`, realism run 6: same-building clustering of
  house-style edits and non-convention bundles, building adoption 0.92): identical on all 167,374 records, with
  council rates and in the pooled external-test setting.
- `v3e_run5_regression_20261013.json`: against `generator_v3.py` as of 09:02 on 13 October
  (SHA-256 `2cb5e4ba…1fca`, realism run 5: sub-unit text kept out of the locality lookups, per-street lookup rows
  seen at least twice, sector place text from the style extras, no "another street" route): identical on all
  167,374 records.
- `v3e_pooled_regression_20261013.json` (run 5 code): the external-test setting (pooled core rates and collision
  modifiers at intensity 1.0; `rates='pooled'` here, `pooled_rates=True` in the prototype): identical on all 167,374.
- `v3e_regression_20261013.json`: the same check on the corrected candidate `fitted_v3e_20261013`
  against `generator_v3.py` as of 07:04 on 13 October (SHA-256 `2c289750…9c09`, ST3 per eligible record): identical
  on all 167,374 records. This and the two v3 files above are against earlier generator versions.
- `fit_house_style_wigan_20261013.json`: `address-errors fit-house-style` on Wigan's training split
  reproduces Wigan's block in the frozen profile exactly.
- `v2_regression_20261013.json`: with profile v2, seed 20261012 and the postcode layer off, the package
  gives **identical output** to the realism-checked prototype generator (`prototype_loop` run 3b) on all 167,374
  held-out records of the four development councils, on every truth-table and audit field.
- `pipeline_wigan_20261013.json`: cleaning reproduces the study's Wigan and Basingstoke counts exactly
  (Basingstoke's 70-character cap is found from the length spike alone: 3,375 rows). Mining reproduces the study's
  Wigan pairs: dwelling-layer labels and collisions are 100% identical, and 0.6% of locality-tail labels differ
  because the study mined three councils in one database.
- `tests/`: an invented gazetteer (no real addresses) exercising each control, the truth table and both portable
  profiles.
- `refit_frozen_20261013/refit_summary.json`: `address-errors refit-profile` reruns the whole chain (alignment,
  taxonomy classification, taxonomy build, profile fit) from the study folder and reproduces `profile/frozen_20261013`
  exactly: core, clustering, label drift, strata, flag vocabulary, smoothing and all four councils' house style.
- `realism_run6_20261013/`: `address-errors realism-check` on the stored run 6 output (`prototype_loop/run_v3e3_20261013`)
  reproduces the study's discriminator exactly: AUC 0.6504 on all records and 0.8264 on discrepancies, and every
  council's AUC. Its `examples_extreme.csv` (address strings) was removed from this copy.
- `examples/quickstart.py` runs on the bundled invented town and prints the output shown in the README.

## Code provenance

| Module | From |
|---|---|
| `rules.py`, `style.py`, `corruptor.py` | `prototype_loop/code/generator.py`, `generator_v1.py`, `generator_v2.py` (run 3b) and `generator_v3.py`, flattened; same random stream |
| `flags.py` | `profile/code/flags_v2.py` with the v3 collision flags, copied on 13 Oct 2026 (SHA-256 `72370701…eff4`, as in `profile/FROZEN.md`) |
| `context.py` | `prototype_loop/code/common.py`, `profile/code/fit_profile.py` (dwelling type, rural proxy, building split) |
| `pipeline/reference.py` | `reference/build_reference.py`, generalised to any OS order and authority |
| `pipeline/records.py` | `council_data/clean_councils.py` rules; generic staging; SY1 detection |
| `pipeline/fit/` | `profile/code/fit_house_style.py` (SHA-256 `0f83abb5…f1db`; its `--lookup-fix` option is off by default) and `fit_profile.py` (`6b5445cf…1516`), unchanged; `flags_v2.py` is a shim to `flags.py` |
| `pipeline/mine.py`, `pipeline/miner/` | `prototype_loop/code/build_miner_db.py`, `mined_error_pairs/v3_basingstoke_20261012/code/` (one edit: which sources carry postcodes) |
| `pipeline/study/` | run as scripts, unchanged: `discovery/code/align.py` (`4651f895…1fbb`), `families.py` (`1f7866ae…5f23`); `taxonomy/v2_20261012/code/classify_edits.py` (`645188b1…4d65`), `spec_v2.py` (`dc8640c4…bd33`), `build_v2.py` (`efaa7efe…69df`); `profile/code/fit_profile.py` (`6b5445cf…1516`), `fit_profile_v1.py` (`1cc2a252…f68c`), `fit_profile_v2.py` (`bcbfbe17…3306`), `fit_profile_v3.py` (`c7db5b41…783c`: the frozen fit plus an optional `--lookup-fix`, off by default; `profile/FROZEN.md` lists the earlier `0fc7bac`), `fit_house_style.py` (`0f83abb5…f1db`); `prototype_loop/code/discriminate.py` (`fdec70b5…1a87`), `common.py` (`974648d3…0ac4`). `flags_v2.py` is a shim to `flags.py` |
| `pipeline/refit_profile.py`, `pipeline/realism.py` | new wrappers: build the study layout from the development councils only, run the scripts above, compare |
| `data/example/` | invented, written by `examples/make_example_gazetteer.py` |
