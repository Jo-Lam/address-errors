"""Quick example: corrupt the bundled invented town with the default (all6) profile, then turn two controls.

    pip install address-errors
    python examples/quickstart.py

Runs in a few seconds with the standard library only. Nothing here is a real address.
"""
from collections import Counter

from address_errors import Controls, Corruptor, Noise, Profile, example_path, load_components

# 1. The profile: the frozen v3 profile, bundled in portable form (rates and parameters, no address strings).
prof = Profile.load()
print('house styles:', prof.styles())

# 2. Clean canonical addresses with known UPRNs. Use your own components.csv.gz from build-reference here.
gazetteer = load_components(example_path())
targets = [r['uprn'] for r in gazetteer if r['classificationcode'] != 'RD02']   # dwellings, not parent buildings

# 3. Corrupt them as Leeds records its addresses (Leeds house style and Leeds rates).
gen = Corruptor(prof, style='leeds', seed=1)
gen.index(gazetteer)
rows = gen.generate(targets)

canonical = {r['uprn']: r for r in gazetteer}
print(f'\n{len(rows)} records; a few that were changed:')
for r in [r for r in rows if r['applied_rules']][:6]:
    c = canonical[r['source_uprn']]
    clean = ', '.join(x for x in (c['subname'], c['name'], c['number'] + ' ' + c['streetname'], c['townname']) if x.strip())
    print(f"  {r['source_uprn']}  {clean:45.45}  ->  {r['recorded_address']}   [{r['applied_rules']}]")


def touched(rows):
    return sum(1 for r in rows if r['applied_rules']) / len(rows)


# 4. Tune it. Each control defaults to the profile, so change one at a time.
print(f"\nshare of records with a profile error, default:        {touched(rows):.1%}")
more = Corruptor(prof, style='leeds', seed=1, controls=Controls(prevalence=2.0))
more.index(gazetteer)
print(f"with Controls(prevalence=2.0):                        {touched(more.generate(targets)):.1%}")

noisy = Corruptor(prof, style='leeds', seed=1, controls=Controls(noise=Noise(rate=0.3, max_ops=2)))
noisy.index(gazetteer)
noisy_rows = noisy.generate(targets)
print('extra noise, Controls(noise=Noise(rate=0.3)):', sum(1 for r in noisy_rows if r['noise_ops']), 'records,',
      dict(Counter(op.split(':')[-1] for r in noisy_rows for op in r['noise_ops'].split('|') if op).most_common(4)))

# 5. A source the profile has never seen: pooled rates at intensity 1.0, the study's default for new councils.
pooled = Corruptor(prof, rates='pooled', seed=1)
pooled.index(gazetteer)
print(f"pooled rates (unseen source):                         {touched(pooled.generate(targets)):.1%}")
print('intensity band to report as sensitivity:', prof.intensity_band())
