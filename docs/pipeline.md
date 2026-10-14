# Pipeline: fit a profile on your own data

The corruptor needs only the bundled profile. This pipeline is for people who have **real recorded addresses with
UPRN labels** (a council tax or electoral register, a service's client records) and want to measure how that source
records addresses, refit its house style, or check how realistic the synthetic output is. Install the extras first:

```bash
pip install "./package[pipeline]"     # steps 1 to 5
pip install "./package[evaluate]"     # step 6
```

| Step | Command | Status |
|---|---|---|
| 1. Canonical reference from an OS NGD order | `address-errors build-reference` | ready |
| 2. Stage and clean your labelled records (rules R1, R2, R4, R5; SY1 found from a length spike) | `address-errors stage-records` | ready |
| 3. Mine recorded-vs-canonical pairs, labelled by mechanism, with the collision test | `address-errors mine` | ready |
| 4. Align edits and classify them into taxonomy v2 IDs, with rates | `address-errors refit-profile` (runs 4 and 5b together) | study data; any council list with `--chain general` |
| 5a. Refit only a new source's house style against the profile's core | `address-errors fit-house-style`, then `--add-style` | ready, any source |
| 5b. Fit the whole profile | `address-errors refit-profile` | study data; any council list with `--chain general` |
| 6. Realism check: re-mine synthetic output and train a real-vs-synthetic discriminator | `address-errors realism-check` | study councils only |

Every command takes `--help`. Each writes to a new output directory and refuses to overwrite one. Address-level
files (staged records, mined pairs, lookups) stay where you put them: keep them inside your own data folder.

**"Study data"** means the step runs the study's own code. With `--chain study` (the default) it is the code
vendored unchanged, fixed to the four development councils (Wigan, Bradford, Leeds, Basingstoke), and it reproduces
the frozen profile exactly. With `--chain general` it is a copy that takes the council list from a JSON config
(`pipeline/study_general/`, every change listed in its `GENERALISATION.md`); with the default four councils it
reproduces the frozen profile too, and `study_general/councils_all6.json` is the config the bundled `all6` profile
was fitted with. A new council follows the route Basingstoke took (aligned on its own, no hand-curated discovery
families), and every council in the list joins the core. For a source you only want to imitate, step 5a is the
cheaper route: it keeps the core and refits only how the source writes addresses.

## 1 to 3: reference, records, pairs

```bash
address-errors build-reference --os-order OS_data/MySource --la-gss E06000000 --output ref/mysource
address-errors stage-records --input my_records.csv --uprn-col UPRN --address-col ADDRESS --postcode-col POSTCODE \
    --source mysource --output records/mysource
address-errors mine --work work/ --source mysource=OS_data/MySource:records/mysource/clean_records.csv
```

**A source with several address fields** (house, street, town in separate columns, or pipe-delimited): pass
`--address-col` once per field to `stage-records`. The fields are joined with ", " and that string is used everywhere
downstream, so the style refit learns the commas a matcher will actually see. In the external test, the study's
cleaning joined Derby's and Cornwall's fields with commas while the house-style refit read the raw field; the
synthetic strings then had no commas and a classifier told them apart perfectly on that alone (see the README, "How
well it works").

## 5a: a new source's house style

The cheapest route: keep the profile's core and refit only how the source writes addresses (case, commas, locality
choice, street spellings, floor and unit wording, PAF rendering, postcode errors, SY1 cap) from its own mined pairs.

```bash
address-errors fit-house-style --council mysource --pairs work/pairs/pairs_mysource.csv.gz \
    --components ref/mysource/components.csv.gz --clean records/mysource/clean_records.csv --output fit/mysource
address-errors corrupt --add-style mysource=fit/mysource --style mysource --rates pooled ...
```

```python
prof = Profile.load().with_style('mysource', 'fit/mysource')
gen = Corruptor(prof, style='mysource', rates='pooled')     # core unchanged, pooled rates at intensity 1.0
```

- The refitted lookups (other locality text and street spellings per street) are address-level: keep them with your
  data.
- The style changes how addresses are written, not how often errors happen. For a high-error source, also set
  `Controls(intensity=...)` from its touch rate (see the README guidance).
- ST3 edits (off-street references, PAF dependent street written) use the style's rates per eligible record, as for
  the development councils. A refitted style without county-by-district extras draws county words from its own
  strings.
- With the `frozen` profile, Cornwall and Derby are refused unless `allow_external_test=True` is passed (only for
  the study's external test), and such a profile can never be exported. The `all6` profile already holds both.

## 4 and 5b: refit the whole profile

```bash
address-errors refit-profile --study UPRN_corrupt_address_study --output UPRN_corrupt_address_study/refits/new \
    --compare UPRN_corrupt_address_study/profile/frozen_20261013
```

This runs the study chain in order: `align.py` (Basingstoke strings aligned with their canonical rendering, edit by
edit), `classify_edits.py` (every aligned edit gets one taxonomy v2 mechanism ID, with rates), `build_v2.py`
(`mechanisms.yaml` and summary tables) and `fit_profile_v3.py` (bundles, rates, clustering, label drift, collision
modifiers and per-council house style). It copies only the development councils' inputs into a working folder under
`--output`, so Cornwall and Derby never reach it, and deletes that folder afterwards unless `--keep-work`.
`--compare` reports, section by section, whether the refit equals a given profile; `refit_summary.json` has the
answer.

Any council list (how the bundled `all6` profile was fitted):

```bash
address-errors refit-profile --chain general --councils councils_all6.json --allow-external-test \
    --study UPRN_corrupt_address_study --output UPRN_corrupt_address_study/profile_all6/fitted_all6_<date>
```

Each council in the config names its reference, mined pairs and clean records. `raw_from_joined: true` (Derby and
Cornwall, whose raw field is pipe-delimited) fits house style on the comma-joined string, so the commas a matcher sees
are learned. The six-council fit peaks at about 8 GB of memory in `fit_profile_v3.py`: run one fit at a time.
`--allow-external-test` is needed for any list holding Cornwall or Derby.

## 6: realism check

```bash
address-errors realism-check --study UPRN_corrupt_address_study --run <run dir> --output <new dir>
```

`<run dir>` holds, for each development council, the synthetic records for the held-out buildings
(`synthetic_<council>.csv.gz`), the same records re-mined with the study's miner (`pairs_synth_<council>.csv.gz`), and
the held-out split (`test_split.csv.gz`), as the study's prototype loop writes them. Real and synthetic records are
labelled by the same miner, so every feature is computed the same way on both sides. The discriminator reports
out-of-fold AUC on all records and on discrepancies only (0.5 = indistinguishable), an ablation by feature group, and
a ranked list of what gives synthetic records away (`discriminator/`).

It takes about half an hour on the four development councils. `discriminator/examples_extreme.csv` holds real
address strings: keep it with your data.

Before trusting a low or high AUC on your own data, compare punctuation and separators on both sides first.
