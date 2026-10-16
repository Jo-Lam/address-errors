# address-errors

Generate tunable, realistic UK address recording errors from your own structured addresses, using bundled learned
error profiles. **No UPRN and no OS data are needed to apply corruption.** Keep your own record identifiers and the
output is a labelled synthetic benchmark: every corrupted string says which input record it came from, which errors
were requested, which were applied and which could not be.

Training a new empirical error profile is a separate, advanced workflow. It needs paired reference and recorded
addresses whose correspondence you trust; the supplied OS workflow uses UPRNs for that pairing.

```bash
pip install address-errors
address-errors corrupt --components example --seed 1 --output demo.csv
```

The second line corrupts a bundled, invented town of 261 addresses, so you can see the output before you use any of
your own data.

Status, 16 October 2026: **version 0.1.1** (documentation and metadata update of 0.1.0; the generator is unchanged).

Contents: [What you need](#what-you-need) · [Corrupt your own addresses](#corrupt-your-own-addresses) ·
[Quick example](#quick-example) · [Controls](#controls) · [Output](#output-truth-table-and-audit) ·
[Starting from an OS NGD order](#starting-from-an-os-ngd-order) · [House style and rates](#house-style-and-rates) ·
[What it reproduces](#what-it-reproduces) · [How well it works](#how-well-it-works) · [Profiles](#profiles) ·
[Training your own profile](#training-your-own-profile-advanced) · [Data, licences and disclosure](#data-licences-and-disclosure).

## What you need

| You want to... | Input | UPRN needed? |
|---|---|---|
| Corrupt structured addresses | A CSV of address components with any unique record ID ([below](#corrupt-your-own-addresses)) | **No.** Any unique ID works |
| Corrupt address strings (one free-text field) | Not supported in 0.1.x: split the string into components first. Planned for 0.2 | No |
| Corrupt a raw OS NGD order | The order's zips, converted with `address-errors build-reference` (`[pipeline]` extra) | Already in the OS data; carried through |
| Learn an empirical error profile | Paired reference and recorded addresses | Reliable pairing needed; the supplied OS workflow uses UPRNs |
| Score an address-to-UPRN matcher on the output | Synthetic queries, a reference with UPRNs, the retained truth | Yes, for that evaluation only |

You need Python 3.9 or later. The corruptor uses the standard library only, so `pip install address-errors` has no
dependencies. If `address-errors` is not found after installing, the environment you installed into is not active;
`python -m address_errors.cli --help` works either way.

## Corrupt your own addresses

Make a CSV with these columns, one row per address. Empty cells are fine.

| Column | Required | Notes |
|---|---|---|
| `uprn` | yes | **Your record ID.** Any unique text: `1`, `patient_0042`, a UPRN. The column name is historical; 0.2 will accept `source_record_id` |
| `subname` | yes | sub-building, e.g. `FLAT 2` |
| `name` | yes | building name, e.g. `ROSE COTTAGE` |
| `number` | yes | building number, e.g. `18`, `18A`, `18-20` |
| `streetname` | yes | |
| `townname` | yes | |
| `postcode`, `locality` | no | postcode errors, rural/urban context, locality edits |
| `parentuprn` | no | the record ID of the building a flat sits in (your own IDs again). Enables building-level conventions and parent/sibling label drift |
| `usrn` | no | any street identifier. Enables neighbour label drift |

UPRNs are treated as text throughout; never cast IDs to numbers.

Example (`my_addresses.csv`, invented addresses):

```
uprn,subname,name,number,streetname,townname,postcode
rec1,FLAT 2,,18,HIGH STREET,EXAMPLETOWN,ZZ1 2CD
rec2,,ROSE COTTAGE,,MILL LANE,EXAMPLETOWN,ZZ1 3EF
rec3,,,7,HIGH STREET,EXAMPLETOWN,ZZ1 2CD
```

Command line:

```bash
address-errors corrupt --components my_addresses.csv --seed 1 --output corrupted.csv
```

Python:

```python
from address_errors import Profile, Corruptor, Controls, load_components

recs = load_components('my_addresses.csv')            # or example_path() for the invented town
gen = Corruptor(Profile.load(), seed=1)               # pooled rates of the bundled profile
gen.index(recs)
rows = gen.generate([r['uprn'] for r in recs])        # one dict per input record
print(gen.stats)                                      # records, touched, applied and failed edits
```

`source_uprn` and `assigned_uprn` in the output hold **your** IDs. Join them back to your data to keep any other
fields. On the command line, records are taken as residential when `classificationcode` is empty or starts with `R`;
pass `--uprns ids.txt` (one ID per line) to choose them yourself.

### What changes when you supply less

The corruptor works on whatever you give it, but some mechanisms need information you may not have:

- **No `parentuprn`.** Flats are still recognised from `subname`, but there are no building conventions (all units of a
  block written the same way) and no parent or sibling label drift.
- **No `usrn`.** No neighbour label drift.
- **No `postcode`.** No postcode errors, and every record is treated as urban for its rates.
- **Collision checks only see your table.** `collision` compares each corrupted dwelling and street with the other
  rows you supplied. `no_match` on a sample means "no collision with these rows", not "no collision in the real
  world"; `not_tested` means there was no street to compare. Corrupt a full reference (for example an OS extract)
  when collisions matter to your benchmark.
- **Edits that cannot happen are recorded, not hidden.** They appear in `failed_rules`, and `gen.stats` counts them.

## Quick example

The invented town has houses, converted houses, blocks of flats and rural named properties, with record IDs from
`900000000001` and postcodes in the non-existent ZZ area.

```python
from address_errors import Profile, Corruptor, Controls, Noise, load_components, example_path

prof = Profile.load()                                     # bundled all-six profile; Profile.load('frozen') for the tested one
town = load_components(example_path())
gen = Corruptor(prof, style='leeds', seed=1)              # Leeds house style and Leeds rates
gen.index(town)
rows = gen.generate([r['uprn'] for r in town])
print(gen.stats)

gen = Corruptor(prof, style='leeds', seed=1, controls=Controls(prevalence=2.0, noise=Noise(rate=0.1)))
```

The same on the command line, with tuned controls:

```bash
address-errors corrupt --components example --style leeds --seed 1 --output demo.csv
echo '{"prevalence": 2, "noise": {"rate": 0.1}}' > controls.json
address-errors corrupt --components example --rates pooled --controls controls.json --output demo_tuned.csv
```

At the default settings about 6% of the town's records carry a profile error; `Controls(prevalence=2.0)` gives about
17%. The town is small, so these percentages move between seeds. Use a full address list for anything you report.

## Controls

Every default is a no-op: `Controls()` reproduces the profile. Change one at a time.

| Control | Effect |
|---|---|
| `prevalence` | multiplies every touch probability (records and building conventions) |
| `intensity` | council intensity; default from the profile (1.0 for pooled). Set it per source for high-error councils (see [guidance](#guidance-for-a-new-source)) |
| `composition` | per-mechanism multipliers by family, ID or subtype, e.g. `{"SU7": 3, "TX": 0}`; it also scales the per-eligible style edits (SU13, SU4, SU9, FM6, SU11, DQ4) |
| `variation_multiplier`, `error_multiplier` | scale the identity-preserving vs identity-shifting share of each bundle (severity) |
| `building_conventions` | turn off the one-convention-per-building dependency, and the building-shared style edits and per-record draws |
| `collision_modifiers` | turn off the collision modifiers (drops land on records whose drop would equal another address at the real rate, and such collisions are kept at the real share) |
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
| `source_uprn` | the input record (your ID) whose address the string was generated from |
| `assigned_uprn` | the record ID the output carries; differs from `source_uprn` only under label drift |
| `source_style`, `stratum` | house style used; the record's dwelling type and rural/urban |
| `touch_route` | `record`, `building_convention`, `building_other`, `record_in_building`, `paf_rendering`, or empty (clean) |
| `requested_bundle`, `applied_rules`, `failed_rules` | planned edits, edits that happened, edits that could not happen on this record |
| `label_drift_relation` | `to_neighbour`, `to_parent`, `to_sibling` when the label moved |
| `postcode_edit` | PC1 to PC5 when the postcode was mis-keyed |
| `noise_ops` | extra noise operations (only when the noise control is on) |
| `sy1_truncated` | the string was cut at the source's field length |
| `collision`, `collision_uprn`, `collision_relation` | does the corrupted dwelling + street equal another record in the input, which one, and how they are related |

The command line adds `record_id` (one per output row) and `copy`, and prints the run's counts (records, touched,
applied and failed edits) to standard error.

### What the truth columns mean

`source_uprn` always identifies the input record that was corrupted. That stays true when the corruption removed the
information needed to identify it (a dropped flat number leaves the building's address) or produced a string equal to
another address. It does not mean the string still describes that property unambiguously. When you score a matcher,
use `collision` and `failed_rules` to separate such records and report them on their own. `assigned_uprn` answers a
different question, "reproduce the register's label"; the two differ only under label drift.

## Starting from an OS NGD order

If you have an OS NGD order (Address GB built address, alternate addresses and Royal Mail tables, as zips), convert it
to the components table. UPRNs, parent UPRNs, USRNs and the building hierarchy are carried through:

```bash
pip install "address-errors[pipeline]"
address-errors build-reference --os-order OS_data/Wigan --la-gss E08000010 --output ref/wigan
address-errors corrupt --components ref/wigan/components.csv.gz --style leeds --n 50000 --copies 3 --output synthetic.csv.gz
```

A full reference gives the most complete output: building conventions, label drift and collision checks against every
address in the area. `--copies` makes several independent synthetic sources of the same addresses. Output built from
OS data falls under your own OS licence terms.

## House style and rates

`style` is one of `prof.styles()` (`wigan`, `bradford`, `leeds`, `derby`, `cornwall`): how that council writes
addresses, with its own error rates. With no `style`, or for a source the profile has never seen, use
`rates='pooled'` (pooled rates at intensity 1.0, the study's setting for unseen councils) and report results across
the intensity band `prof.intensity_band()` (0.35 to 1.44 for `all6`; 0.49 to 1.59 for `frozen`).

### Guidance for a new source

- **Separators.** Generate and score the same string a matcher will see. If your source has separate fields, decide
  how they are joined before anything else, or set `Controls(commas=True)` to match. If you compare against real
  records, check punctuation first: a classifier that wins on commas alone is telling you about your cleaning.
- **Intensity.** Pooled intensity 1.0 suits a council like the development ones. For a rural or high-error source,
  measure its touch rate on a labelled sample and set `intensity` (or `prevalence`) to match. Report results across
  `prof.intensity_band()` either way, and say when your source is outside it.
- **Same-building sharing.** Results that depend on blocks of flats (sub-unit errors, collisions with the parent
  building) are the least certain. Report them with `Controls(building_conventions=False)` as a sensitivity.
- **House style.** With a few thousand labelled records from your source, you can refit its house style against the
  profile's core ([training your own profile](#training-your-own-profile-advanced)).

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
- **Label drift.** A small pooled share of clean strings carries a neighbour's, parent's or sibling's ID.
- **Collisions.** Edits that make a string equal another address (a dropped flat number that leaves the parent
  building's address) happen at the real rate.
- **Systemic truncation (SY1)**, applied last, for single-field sources with a length cap.

Also in the package, not realism-checked yet: postcode errors (PC1 to PC5; off with `Controls(postcode='clean')`),
an inline collision check on every record, extra noise (off by default), and `source_id`, which fixes source-level
conventions per synthetic source so that `--copies` gives each copy its own source.

## How well it works

Two profiles are bundled. **`all6` (the default)** is fitted on all six study councils (Wigan, Bradford, Leeds,
Basingstoke and Deane, Derby and Cornwall); its check is leave-one-council-out. **`frozen`** was fixed before an
external test on two councils it had never seen; the external-test results belong to it.

**Default `all6` profile, leave one council out** (refit on five councils, test on the whole sixth with its own house
style and pooled rates at intensity 1.0; full table: [loco_results.md](https://github.com/Jo-Lam/address-errors/blob/main/docs/loco_results.md)):

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

**Frozen profile, on the development councils** (held-out buildings in Wigan, Bradford, Leeds and Basingstoke), a
gradient-boosting classifier separates real from synthetic records with AUC 0.65 on all records and 0.83 on records
with a discrepancy (0.5 means indistinguishable).

**Frozen profile, on two councils never used in its development**, each run once with pooled rates at intensity 1.0:

| | Derby (within the development range) | Cornwall (rural, high error: extrapolation) |
|---|---|---|
| Touch rate, real ÷ synthetic | 1.28 (pass) | 2.15: real 12.9%, synthetic 6.0%; still 1.54 at intensity 1.59 |
| Mechanism mix | 0.43 of 14 mechanisms match (pass); SU13 unit word, SU10, PN2, DQ3, BN6 under-produced, BN1 name added over-produced | 0.13 of 23 |
| Exact collisions | 0.135% vs 0.123% real (pass) | 0.42% vs 0.35% real |
| Same-building sharing (building-average identical share) | 0.68 vs 0.83 real (fail); other units of a touched building touched 0.41 vs 0.94 real | 0.75 vs 0.60 real (synthetic more clustered) |
| Real-vs-synthetic AUC (n-grams) | 1.00 (fail); 0.56 with commas removed | 1.00; 0.74 with commas removed |
| Verdict | **fail, 3 of 5 criteria** | no pass claim |

Nothing was refitted on either council. What the results mean:

- **Rates and collisions transfer** to a council like the development ones.
- **Punctuation does not transfer.** Both AUCs of 1.00 come from commas: the real strings had commas from the study's
  cleaning that the synthetic ones did not. With commas removed (a post hoc analysis), Derby is harder to tell apart
  than any development council.
- **Same-building sharing is the weakest part**, and it varies by council more than the development councils showed.
- **Rural, high-error councils need their own intensity.** Pooled rates give Cornwall half its real error rate.

Validation detail and code provenance: [validation.md](https://github.com/Jo-Lam/address-errors/blob/main/docs/validation.md).

## Profiles

```python
Profile.load()                                          # bundled portable profile, fitted on all six councils
Profile.load('frozen')                                  # bundled portable frozen profile (external-test evidence)
Profile.load('v2')                                      # bundled portable v2
Profile.load().with_style('mysource', 'fit/mysource')   # add a house style you refitted
prof.export_portable('my_portable_profile')             # how the bundled ones were built
```

Profile v2 keys house style by section, then source; v3 keys it by source, so a source's whole style can be refitted
and swapped in on its own, and adds style rates per eligible record, collision modifiers, building-name
abbreviations and place text by postcode sector.

The **bundled portable profiles** contain mechanism IDs, rates, eligibility flags, clustering, label-drift and
house-style parameters, and generic vocabulary. They contain **no addresses and no UPRNs**. Compared with the full
study profile they leave out the per-street lookups (locality text and street spellings per USRN) and place names by
postcode sector. The v3 profiles also ship building-name words with their short forms (single words, each seen at
least 3 times). Without the lookups, locality text a source adds beyond NGD and PAF is not produced, and street
spelling conventions are drawn generically. Each profile's `PORTABLE.json` lists what was removed.

## Training your own profile (advanced)

You only need this to learn how a particular source records addresses. It needs your recorded addresses paired with
reference addresses you trust. The supplied workflow (`stage-records`, `mine`, `fit-house-style`, `refit-profile`,
`realism-check`) takes the pairing from UPRN labels against an OS NGD reference. Any reliable pairing would serve in
principle, but the scripts expect UPRNs.

```bash
pip install "address-errors[pipeline]"     # staging, mining and refitting
pip install "address-errors[evaluate]"     # the real-vs-synthetic realism check
```

Full guide: [pipeline.md](https://github.com/Jo-Lam/address-errors/blob/main/docs/pipeline.md).

## Data, licences and disclosure

- Rates are **discrepancies under the council's UPRN label**, not verified error rates.
- Council records used, all under the Open Government Licence v3.0:
  - **Wigan, Bradford, Leeds:** published under OGL; profile development.
  - **Basingstoke and Deane:** released by the council under OGL v3; profile development.
  - **Derby:** the council confirms that information it owns is available for reuse under OGL, with no separate
    reuse request needed (FOI938460154, 18 August 2026); external test and the `all6` refit.
  - **Cornwall:** the council states that its Council Tax dataset is open data under OGL; external test and the
    `all6` refit.

  The bundled profiles hold aggregated parameters only; Basingstoke and Deane's council-level house style is not
  bundled.
- The study uses these records to estimate address discrepancy patterns and to evaluate linkage. Third-party address
  rights, and publication of outputs derived using OS reference data, remain subject to clarification under the
  project's OS agreement.
- Contains public sector information licensed under the Open Government Licence v3.0
  (https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/), from Wigan, Bradford, Leeds,
  Basingstoke and Deane, Derby and Cornwall councils.
- Contains OS data © Crown copyright and database rights 2026; Royal Mail data © Royal Mail copyright and database
  right 2026; GeoPlace data © Local Government Information House Limited copyright and database right 2026.
- The example town is invented: its addresses, record IDs and ZZ postcodes do not exist.
- Address-level outputs you build from OS data fall under your own OS licence terms.
