"""The bundled invented town and the quick example run anywhere."""
import runpy
from pathlib import Path

from address_errors import Controls, Corruptor, Profile, example_path, load_components


def test_example_town_is_invented():
    rows = load_components(example_path())
    assert len(rows) == 261
    assert all(r['uprn'].startswith('9000000') for r in rows)
    assert all(r['postcode'].startswith('ZZ') for r in rows)


def test_example_corrupts_and_tunes():
    town = load_components(example_path())
    targets = [r['uprn'] for r in town]
    base = Corruptor(Profile.load(), style='leeds', seed=1)
    base.index(town)
    more = Corruptor(Profile.load(), style='leeds', seed=1, controls=Controls(prevalence=3.0))
    more.index(town)
    n = lambda rows: sum(1 for r in rows if r['applied_rules'])
    assert n(more.generate(targets)) > n(base.generate(targets)) > 0


def test_quickstart_runs(capsys):
    runpy.run_path(str(Path(__file__).parents[1] / 'examples' / 'quickstart.py'), run_name='__main__')
    out = capsys.readouterr().out
    assert 'house styles' in out and 'pooled rates' in out
