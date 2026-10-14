"""Profile v3 (schema 3, council-keyed house style) through the corruptor, on the invented gazetteer."""
import json
from pathlib import Path

import pytest

from address_errors import Controls, Corruptor, OUTPUT_FIELDS, Profile
from address_errors.profile import FORBIDDEN, UNCONFIRMED_LICENCE

V3 = Path(__file__).parents[1] / 'src' / 'address_errors' / 'data' / 'profile_v3_frozen_portable'


@pytest.fixture(scope='module')
def prof3():
    assert V3.exists()
    return Profile.load('v3')


def run(prof, gaz, targets, style='leeds', n=6, **controls):
    out = []
    for k in range(n):
        g = Corruptor(prof, style=style, seed=1 + k, controls=Controls(**controls) if controls else None)
        g.index(gaz)
        out += g.generate(targets)
    return out


def test_v3_portable(prof3):
    assert prof3.v3 and prof3.summary()['schema'] == 3
    assert prof3.summary()['portable'] and not prof3.summary()['per_street_lookups']
    assert Profile.disclosure_scan(prof3.raw) == []
    raw = dict(prof3.raw)
    raw.pop('fitted_on')
    raw.pop('portable')
    hits = []

    def walk(x, path):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in FORBIDDEN + UNCONFIRMED_LICENCE:
                    hits.append(f'{path}/{k}')
                walk(v, f'{path}/{k}')
    walk(raw, '')
    assert hits == []


def test_v3_output(prof3, gazetteer, targets):
    rows = run(prof3, gazetteer, targets)
    assert len(rows) == 6 * len(targets)
    for r in rows:
        assert set(OUTPUT_FIELDS) <= set(r)
        assert (r['source_uprn'] != r['assigned_uprn']) == bool(r['label_drift_relation'])
    assert any(r['touch_route'] for r in rows)
    assert run(prof3, gazetteer, targets, n=2) == run(prof3, gazetteer, targets, n=2)
    assert run(prof3, gazetteer, targets, n=2) == run(prof3, gazetteer, targets, n=2, collision_modifiers=True)


def test_v3_collision_flags_and_switch(prof3, gazetteer, targets):
    g = Corruptor(prof3, style='bradford', seed=3)
    g.index(gazetteer)
    assert g.cmod and g._collflags
    assert all('hit_if_sub_dropped' in g.flags(r) for r in gazetteer)
    off = Corruptor(prof3, style='bradford', seed=3, controls=Controls(collision_modifiers=False))
    off.index(gazetteer)
    assert not off.cmod
    assert len(off.generate(targets)) == len(targets)


def test_v3_style_rates_follow_composition(prof3, gazetteer, targets):
    rows = run(prof3, gazetteer, targets, n=3, composition={'SU13': 1e4, 'DQ4': 1e4})
    flats = [r for r in rows if r['stratum'].startswith(('flat', 'floor_flat', 'room'))]
    assert any('(' in r['recorded_address'] for r in rows)
    assert flats


def test_v3_pooled(prof3, gazetteer, targets):
    g = Corruptor(prof3, style='somewhere_new', seed=1)
    g.index(gazetteer)
    rows = g.generate(targets)
    assert {r['source_style'] for r in rows} == {'pooled'} and g.intensity == 1.0


def test_v3_refitted_style(prof3, gazetteer, targets, tmp_path):
    # a refitted style as fit-house-style writes it (here: the bundled Wigan block under a new name)
    block = {k: v for k, v in prof3.raw['house_style']['bradford'].items() if k != 'style_edit_rates_taxonomy'}
    (tmp_path / 'house_style.json').write_text(json.dumps({'council': 'newsource', 'house_style': block}))
    q = prof3.with_style('newsource', tmp_path)
    assert 'newsource' in q.styles() and 'newsource' not in prof3.styles()
    g = Corruptor(q, style='newsource', seed=1, rates='pooled')
    g.index(gazetteer)
    rows = g.generate(targets)
    assert g.intensity == 1.0 and {r['source_style'] for r in rows} == {'newsource'}
    assert g.style_rates == {} and g.per_elig.get('ST3:access_road_off_added', 0) > 0   # v3e: ST3 per eligible record
    with pytest.raises(ValueError):
        prof3.with_style('cornwall', tmp_path)
    ext = prof3.with_style('cornwall', tmp_path, allow_external_test=True)
    with pytest.raises(ValueError):
        ext.export_portable(tmp_path / 'out')
