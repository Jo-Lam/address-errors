# address-errors

A tunable generator of **realistic UK address recording errors** with known UPRNs, plus the pipeline that learned
it, so anyone with their own messy address data can repeat the process.

Clean canonical addresses (OS NGD / AddressBase-style components) go in. Recorded-style addresses come out, with a
truth table that says which property each string describes, which UPRN it carries, which errors were requested
and applied, and whether the result collides with another real address. The use it was built for is labelled
training and test data for address-to-UPRN matchers.

Status, 14 October 2026: **version 0.1.0**. Two profiles are bundled:

- **`all6` (the default):** fitted on all six councils the study has (Wigan, Bradford, Leeds, Basingstoke, Derby and
  Cornwall), after the external test was spent. It has no untouched test of its own; its check is
  leave-one-council-out (see [How well it works](#how-well-it-works)).
- **`frozen`:** the profile frozen before the external test (`profile/frozen_20261013`, see `profile/FROZEN.md`),
  fitted on the four development councils only. The external-test results belong to this profile; load it with
  `Profile.load('frozen')`.

The package reproduces the study's generator exactly on both. **Not yet for publication outside the study:**
Basingstoke's re-use terms are unconfirmed (see [Data, licences and disclosure](#data-licences-and-disclosure)).

Contents: [Setup](#setup) · [Quick example](#quick-example) · [Your own addresses](#your-own-addresses) ·
[Controls](#controls) · [Output](#output-truth-table-and-audit) · [What it reproduces](#what-it-reproduces) ·
[How well it works](#how-well-it-works) · [Profiles](#profiles) · [Data, licences and disclosure](#data-licences-and-disclosure).
Fitting your own profile: [docs/pipeline.md](docs/pipeline.md). Validation and code provenance:
[docs/validation.md](docs/validation.md).

## Setup

You need Python 3.9 or later. The corruptor uses the standard library only, so the basic install has no
dependencies. Install into a virtual environment from the `package` folder (or from the wheel, if you were given one).

Windows (PowerShell):

```powershell
cd UPRN_corrupt_address_study
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install .\package                        # or: pip install address_errors-0.1.0-py3-none-any.whl
address-errors profile-info                  # prints the bundled profile: "status": "all_councils", styles wigan ... cornwall
```

macOS or Linux:

```bash
cd UPRN_corrupt_address_study
python3 -m venv .venv && source .venv/bin/activate
pip install ./package
address-errors profile-info
```

Optional extras, only needed for the pipeline steps in [docs/pipeline.md](docs/pipeline.md):

| Extra | Adds | For |
|---|---|---|
| `pip install "./package[pipeline]"` | pandas, numpy, duckdb, rapidfuzz, PyYAML, scipy, scikit-learn | building a reference from an OS order, staging and mining your records, refitting |
| `pip install "./package[evaluate]"` | pandas, numpy, duckdb, rapidfuzz, PyYAML, lightgbm, scikit-learn | the realism check (real-vs-synthetic discriminator) |
| `pip install "./package[test]"` | pytest | `pytest package/tests` (invented addresses only) |

If `address-errors` is not found after installing, the virtual environment is not active; `python -m
address_errors.cli profile-info` works either way.

## Quick example

The package ships an invented town of 261 addresses (houses, converted houses, blocks of flats and rural named
properties; postcodes in the non-existent ZZ area), so you can try it before you have any data.

```bash
python package/examples/quickstart.py
```

It loads the default profile, corrupts the town as Leeds records addresses, prints a few changed records, then turns
two controls. The seed is fixed, so you should see this:

```
house styles: ['wigan', 'bradford', 'leeds', 'derby', 'cornwall']

253 records; a few that were changed:
  900000000122  14 CHESTNUT AVENUE, EXAMPLETOWN  ->  2ND FLOOR FLAT 14 CHESTNUT AVENUE NORTHSIDE EXAMPLETOWN   [SU15:subunit_added_on_building_uprn]
  900000000163  19 DAMSON CLOSE, EXAMPLETOWN     ->  OLD MILL HOUSE 19 DAMSON CLOSE EXAMPLETOWN   [BN1:name_added]
  900000000175  11 ELDER GROVE, EXAMPLETOWN      ->  THE OLD SCHOOL 11 ELDER GROVE EASTWOOD EXAMPLETOWN   [BN1:name_added]
  ...
share of records with a profile error, default:        5.9%
with Controls(prevalence=2.0):                        16.6%
extra noise, Controls(noise=Noise(rate=0.3)): 76 records, {'typo': 48, 'abbreviate': 19, 'tokens_joined': 16, 'tokens_swapped': 12}
pooled rates (unseen source):                         8.7%
intensity band to report as sensitivity: (0.345, 1.436)
```

The same in a few lines of Python:

```python
from address_errors import Profile, Corruptor, Controls, Noise, load_components, example_path

prof = Profile.load()                                     # bundled all-six profile; Profile.load('frozen') for the tested one
town = load_components(example_path())                   # or your own components table
gen = Corruptor(prof, style='leeds', seed=1)              # Leeds house style and Leeds rates
gen.index(town)
rows = gen.generate([r['uprn'] for r in town])            # one dict per target UPRN: see "Output"

gen = Corruptor(prof, style='leeds', seed=1, controls=Controls(prevalence=2.0, noise=Noise(rate=0.1)))
```

And on the command line (`--components example` is the invented town):

```bash
address-errors corrupt --components example --style leeds --seed 1 --output demo.csv
echo '{"prevalence": 2, "noise": {"rate": 0.1}}' > controls.json
address-errors corrupt --components example --rates pooled --controls controls.json --output demo_tuned.csv
```

The town is small, so its percentages move a lot between seeds. Use a real gazetteer for anything you report.

## Your own addresses

1. **Get clean canonical addresses.** From an OS NGD order (Address GB built address, alternate addresses and Royal
   Mail tables, as zips), build the components table:

   ```bash
   address-errors build-reference --os-order OS_data/Wigan --la-gss E08000010 --output ref/wigan
   ```

   Or bring your own CSV with at least `uprn, subname, name, number, streetname, townname` (see [Input](#input)).
2. **Pick a house style and rates.** `style` is one of `prof.styles()` (`wigan`, `bradford`, `leeds`, `derby`,
   `cornwall` Basingstoke'): how that
   council writes addresses, with its own error rates. For a source the profile has never seen, use
   `rates='pooled'` (pooled rates at intensity 1.0, the study's setting for unseen councils), and report results
   across the intensity band `prof.intensity_band()` (0.35 to 1.44 for `all6`; 0.49 to 1.59 for `frozen`). Read the
   [guidance](#guidance-for-a-new-source) first.
3. **Generate.** Several independent synthetic sources of the same addresses:

   ```bash
   address-errors corrupt --components ref/wigan/components.csv.gz --style leeds --n 50000 --copies 3 \
       --output synthetic.csv.gz
   ```

4. **Score a matcher** on `recorded_address` and `recorded_postcode`, against `source_uprn` or `assigned_uprn`
   (see [Output](#output-truth-table-and-audit)).

If you have real records from your source with UPRN labels, you can fit its house style, or check realism, with the
pipeline: [docs/pipeline.md](docs/pipeline.md).

## Controls

Every default is a no-op: `Controls()` reproduces the profile. Change one at a time.

| Control | Effect |
|---|---|
| `prevalence` | multiplies every touch probability (records and building conventions) |
| `intensity` | council intensity; default from the profile (1.0 for pooled). Set it per source for high-error councils (see [guidance](#guidance-for-a-new-source)) |
| `composition` | per-mechanism multipliers by family, ID or subtype, e.g. `{"SU7": 3, "TX": 0}`; it also scales the per-eligible style edits (SU13, SU4, SU9, FM6, SU11, DQ4) |
| `variation_multiplier`, `error_multiplier` | scale the identity-preserving vs identity-shifting share of each bundle (severity) |
| `building_conventions` | turn off the one-convention-per-building dependency, and the building-shared style edits and per-record draws |
| `collision_modifiers` | turn off the collision modifiers (drops land on records whose drop would equal another UPRN at the real rate, and such collisions are kept at the real share) |
| `label_drift`, `lb_lambda` | scale the label-drift rate; override the label vs string drift split |
| `case` (`'upper'`, `'title'`), `commas` (`True`, `False`), `sy1_cap`, `postcode`, `postcode_error_multiplier`, `street_variant_scale` | source-style overrides |
| `noise` | extra noise beyond the profile: `Noise(rate=0.1, ops={...}, max_ops=2)` (typos, abbreviation, dropped or swapped tokens, joined words). Own random stream, labelled per record |

```python
Controls(prevalence=2.0)                         # more records touched, same mix
Controls(intensity=1.59)                         # the top of the development band
Controls(composition={'SU7': 3})                 # more dropped sub-units (the main to-parent collision route)
Controls(error_multiplier=3)                     # same volume of variation, three times the identity-shifting errors
Controls(commas=True)                            # match a source whose fields are joined with commas
Controls(sy1_cap=70)                             # a single 70-character field
Controls(noise=Noise(rate=0.2, max_ops=2))       # stress test beyond what councils do
```

On the command line, pass the same fields as JSON: `--controls controls.json`.

## Output (truth table and audit)

| Column | Meaning |
|---|---|
| `recorded_address`, `recorded_postcode` | what a matcher sees |
| `source_uprn` | the property whose address the string was generated from |
| `assigned_uprn` | the UPRN the record carries; differs from `source_uprn` only under label drift |
| `source_style`, `stratum` | house style used; the recipient's dwelling type and rural/urban |
| `touch_route` | `record`, `building_convention`, `building_other`, `record_in_building`, `paf_rendering`, or empty (clean) |
| `requested_bundle`, `applied_rules`, `failed_rules` | planned edits, edits that happened, edits that could not happen on this record |
| `label_drift_relation` | `to_neighbour`, `to_parent`, `to_sibling`, ... when the label moved |
| `postcode_edit` | PC1 to PC5 when the postcode was mis-keyed |
| `noise_ops` | extra noise operations (only when the noise control is on) |
| `sy1_truncated` | the string was cut at the source's field length |
| `collision`, `collision_uprn`, `collision_relation` | does the dwelling + street equal another real UPRN's rendering, and how is it related |

The right answer for a matcher depends on the question: `source_uprn` for "find the property described",
`assigned_uprn` for "reproduce the register". They differ exactly in the label-drift and collision cases.

## What it reproduces

Errors are applied as named mechanisms from the study taxonomy (v2): sub-unit (SU), building name (BN), number
(PN), qualifiers (DQ), street (ST), text edits (TX), format (FM), label drift (LB), postcode (PC) and systemic
truncation (SY1). Each output follows the study's design:

- **Bundles, not single errors.** Edits that occur together in real records are drawn together, and only offered to
  records where every edit can happen (a flat-number edit only lands on flats).
- **Context.** Rates depend on dwelling type, rural or urban, and the source council.
- **Buildings are recorded one way.** If one unit of a block is written differently, most of its other units are
  too, with the same edits. House-style edits (unit and floor wording, component order, brackets) and per-record
  edits are also shared within a building at the profile's measured concordance.
- **House style.** Case, commas, which locality, town and county words a source writes, street spelling conventions,
  floor wording, component order, Royal Mail vs NGD rendering.
- **Label drift.** A small pooled share of clean strings carries a neighbour's, parent's or sibling's UPRN.
- **Collisions.** Edits that make a string equal another real address (a dropped flat number that leaves the parent
  building's address) happen at the real rate.
- **Systemic truncation (SY1)**, applied last, for single-field sources with a length cap.

Also in the package, not realism-checked yet: postcode errors (PC1 to PC5; off with `Controls(postcode='clean')`),
an inline collision check on every record, extra noise (off by default), and `source_id`, which fixes source-level
conventions per synthetic source so that `--copies` gives each copy its own source.

## How well it works

**Default `all6` profile, leave one council out** (refit on five councils, test on the whole sixth with its own house
style and pooled rates at intensity 1.0; full table in [docs/loco_results.md](docs/loco_results.md)):

| Held out | Touch ratio real ÷ synthetic | n-gram AUC | Criteria passed (v2) |
|---|---|---|---|
| Derby | 0.89 | 0.58 | 5 of 5 |
| Leeds | 0.79 | 0.59 | 5 of 5 |
| Bradford | 1.10 | 0.62 | 5 of 5 |
| Basingstoke | 0.93 | 0.64 | 3 of 5 (mechanism mix, building clustering) |
| Wigan | 0.30 (about 3× too many errors) | 0.66 | 2 of 5 |
| Cornwall | 2.12 (about half the real errors) | 0.82 | 1 of 5 |

Fitting house style on the joined string removed the comma artefact: Derby's AUC is 0.58 here against 1.00 in the
external test. Pooled rates fit typical councils; the quietest (Wigan) and noisiest (Cornwall) need their own
`intensity`. This is not an external test: every fold's profile saw the other five councils.

**Frozen profile, on the development councils** (held-out buildings in Wigan, Bradford, Leeds and Basingstoke), a gradient-boosting
classifier separates real from synthetic records with AUC 0.65 on all records and 0.83 on records with a
discrepancy (0.5 means indistinguishable). You can rerun this with `address-errors realism-check`
([docs/pipeline.md](docs/pipeline.md)).

**Frozen profile, on two councils never used in its development**, each run once and pooled rates at intensity
1.0 (`external_test/RESULTS.md`):

| | Derby (within the development range) | Cornwall (rural, high error: extrapolation) |
|---|---|---|
| Touch rate, real ÷ synthetic | 1.28 (pass) | 2.15: real 12.9%, synthetic 6.0%; still 1.54 at intensity 1.59 |
| Mechanism mix | 0.43 of 14 mechanisms match (pass); SU13 unit word, SU10, PN2, DQ3, BN6 under-produced, BN1 name added over-produced | 0.13 of 23 |
| Exact collisions | 0.135% vs 0.123% real (pass) | 0.42% vs 0.35% real |
| Same-building sharing (building-average identical share) | 0.68 vs 0.83 real (fail); other units of a touched building touched 0.41 vs 0.94 real | 0.75 vs 0.60 real (synthetic more clustered) |
| Real-vs-synthetic AUC (n-grams) | 1.00 (fail); 0.56 with commas removed | 1.00; 0.74 with commas removed |
| Verdict | **fail, 3 of 5 criteria** | no pass claim |

These are the frozen profile's results as they stand; nothing was refitted on either council. What they mean:

- **Rates and collisions transfer** to a council like the development ones.
- **Punctuation does not transfer.** Both AUCs of 1.00 come from commas. The councils' files were delimited, the
  study's cleaning joined the fields with ", ", and the house-style refit read the raw field, so the real strings
  had commas that the synthetic ones did not. With commas removed (a post hoc analysis), Derby is harder to tell
  apart than any development council.
- **Same-building sharing is the weakest part**, and it varies by council more than the development councils showed.
- **Rural, high-error councils need their own intensity.** Pooled rates give Cornwall half its real error rate.

### Guidance for a new source

- **Separators.** Generate and score the same string a matcher will see. If your source has separate fields, decide
  how they are joined before anything else, and fit the house style on that joined string (`stage-records
  --address-col` once per field does this), or set `Controls(commas=True)` to match. If you compare against real
  records, check punctuation first: a classifier that wins on commas alone is telling you about your cleaning.
- **Intensity.** Pooled intensity 1.0 suits a council like the development ones. For a rural or high-error source,
  measure its touch rate on a labelled sample and set `intensity` (or `prevalence`) to match. Report results across
  `prof.intensity_band()` either way, and say when your source is outside it.
- **Same-building sharing.** Results that depend on blocks of flats (sub-unit errors, collisions with the parent
  building) are the least certain. Report them with `Controls(building_conventions=False)` as a sensitivity.
- **House style.** With a few thousand labelled records from your source, refit its house style against the
  profile's core (`fit-house-style`, [docs/pipeline.md](docs/pipeline.md)). This is the cheapest route and keeps everything else
  as validated.

## Input

`load_components(path)` reads `components.csv.gz` from `build-reference`, or your own CSV with at least
`uprn, subname, name, number, streetname, townname` (also used if present: `locality, postcode, parentuprn,
rootuprn, usrn, classificationcode, floorlevel, organisationname, easting, northing` and the Royal Mail `rm_*`
fields). Missing typing columns are derived. UPRNs are text throughout; never cast them to numbers.

## Profiles

```python
Profile.load()                                          # bundled portable profile, fitted on all six councils
Profile.load('frozen')                                  # bundled portable frozen profile (external-test evidence)
Profile.load('v2')                                      # bundled portable v2
Profile.load('profile/frozen_20261013', extras='prototype_loop/run_v3_20261013/style_extras.json')
Profile.load().with_style('mysource', 'fit/mysource')   # add a house style you refitted
prof.export_portable('my_portable_profile')             # how the bundled ones were built
```

Both profile layouts are read. Profile v2 keys house style by section, then source; v3 keys it by source, so a
source's whole style can be refitted and swapped in on its own, and adds style rates per eligible record, collision
modifiers, building-name abbreviations and place text by postcode sector.

The **bundled portable profile** contains mechanism IDs, rates, eligibility flags, clustering, label-drift and
house-style parameters, and generic vocabulary. It contains no address strings. Compared with the full profile it
leaves out the per-street lookups (other locality text and street spellings per USRN) and place names by postcode
sector, which are address-level and stay inside the study folder. The v3 profile also ships 67 building-name words
with their short forms (each seen at least 3 times), flagged for review because a few are distinctive local names.
Without the lookups, locality text a source adds beyond NGD and PAF is not produced, and street spelling conventions
are drawn generically. `PORTABLE.json` lists exactly what was removed and what still needs review.

## Data, licences and disclosure

- Rates are **discrepancies under the council's UPRN label**, not verified error rates.
- Fitted on Wigan, Bradford, Leeds (OGL) and Basingstoke and Deane. 
  The bundled profile leaves out its council-level rates and house style, but the pooled and stratum rates (and the
  intensity band) still include its rows. Confirm its terms before publishing this package outside the study.
- Contains OS data © Crown copyright and database rights 2026; Royal Mail data © Royal Mail copyright and database
  right 2026; GeoPlace data © Local Government Information House Limited copyright and database right 2026. The
  bundled profile holds aggregated parameters only. The example town is invented.
- Address-level outputs built from OS data fall under your own OS licence terms.
