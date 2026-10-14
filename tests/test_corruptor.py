import os
from pathlib import Path

import pytest

from address_errors import Controls, Corruptor, Noise, OUTPUT_FIELDS, Profile
from address_errors.profile import FORBIDDEN, UNCONFIRMED_LICENCE


@pytest.fixture(scope='module')
def prof():
    return Profile.load()


def run(prof, gaz, targets, style='leeds', seed=1, n=8, **controls):
    out = []
    for k in range(n):   # several seeds so rare mechanisms show up on a small gazetteer
        g = Corruptor(prof, style=style, seed=seed + k, controls=Controls(**controls) if controls else None)
        g.index(gaz)
        out += g.generate(targets)
    return out


def test_bundled_profile_is_portable(prof):
    s = prof.summary()
    assert s['portable'] and not s['per_street_lookups']
    assert prof.all_councils                      # default: fitted on all six councils, declared in fitted_on
    assert not set(UNCONFIRMED_LICENCE) & set(prof.styles())
    assert Profile.disclosure_scan(prof.data) == []
    assert not any(k.split('|')[0] in UNCONFIRMED_LICENCE for k in prof.data['core']['rates_by_council_stratum'])
    frozen = Profile.load('frozen')               # the externally tested profile never holds the external-test councils
    assert not frozen.all_councils and not set(FORBIDDEN) & set(frozen.styles())
    assert not any(k.split('|')[0] in FORBIDDEN for k in frozen.data['core']['rates_by_council_stratum'])


def test_output_shape_and_truth(prof, gazetteer, targets):
    rows = run(prof, gazetteer, targets, n=2)
    assert len(rows) == 2 * len(targets)
    for r in rows:
        assert set(OUTPUT_FIELDS) <= set(r)
        assert (r['source_uprn'] != r['assigned_uprn']) == bool(r['label_drift_relation'])
        assert r['recorded_address']


def test_deterministic(prof, gazetteer, targets):
    assert run(prof, gazetteer, targets, n=1) == run(prof, gazetteer, targets, n=1)


def test_default_controls_are_a_no_op(prof, gazetteer, targets):
    a = run(prof, gazetteer, targets, n=2)
    b = run(prof, gazetteer, targets, n=2, prevalence=1.0, label_drift=1.0, variation_multiplier=1.0)
    assert a == b


def test_prevalence(prof, gazetteer, targets):
    none = run(prof, gazetteer, targets, prevalence=0.0)
    assert not any(r['requested_bundle'] for r in none)
    base = sum(bool(r['requested_bundle']) for r in run(prof, gazetteer, targets))
    high = sum(bool(r['requested_bundle']) for r in run(prof, gazetteer, targets, prevalence=5.0))
    assert high > base


def test_composition_switches_a_mechanism_off(prof, gazetteer, targets):
    rows = run(prof, gazetteer, targets, prevalence=5.0, composition={'SU': 0})
    assert not any(m.startswith('SU') for r in rows for m in r['requested_bundle'].split('|') if m)


def test_noise_is_labelled(prof, gazetteer, targets):
    rows = run(prof, gazetteer, targets, n=1, noise=Noise(rate=1.0))
    assert sum(bool(r['noise_ops']) for r in rows) > 0.7 * len(rows)
    plain = run(prof, gazetteer, targets, n=1)
    # noise uses its own stream: profile edits are unchanged
    assert [r['applied_rules'] for r in rows] == [r['applied_rules'] for r in plain]


def test_sy1_cap(prof, gazetteer, targets):
    rows = run(prof, gazetteer, targets, n=1, style='wigan', sy1_cap=30)
    for r in rows:
        full = r['recorded_address'] + (', ' + r['recorded_postcode'] if r['recorded_postcode'] else '')
        assert len(full) <= 30
    assert any(r['sy1_truncated'] for r in rows)


def test_postcodes(prof, gazetteer, targets):
    assert all(r['recorded_postcode'] == '' for r in run(prof, gazetteer, targets, n=1, style='leeds'))
    assert any(r['recorded_postcode'] for r in run(prof, gazetteer, targets, n=1, style='wigan'))
    wrong = run(prof, gazetteer, targets, n=2, style='wigan', postcode_error_multiplier=200)
    assert any(r['postcode_edit'] for r in wrong)


def test_pooled_unseen_source(prof, gazetteer, targets):
    g = Corruptor(prof, style=None, seed=3)
    g.index(gazetteer)
    rows = g.generate(targets)
    assert g.rates_key == 'pooled' and g.intensity == 1.0
    assert rows and all(r['source_style'] == 'pooled' for r in rows)


def test_every_required_flag_is_computed(prof, gazetteer):
    """A bundle naming a flag the generator does not compute could never fire."""
    from address_errors.flags import flags_of
    have = set(flags_of(gazetteer[0]))
    need = {k for b in prof.data['core']['bundles'].values() for k in b['requires']}
    assert need <= have, sorted(need - have)
