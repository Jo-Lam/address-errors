"""Refit the whole profile from the study's development data (pipeline steps 4 and 5b).

Runs the study's own chain, vendored unchanged in pipeline/study/ (SHA-256 in package/README.md):

  4a. align.py         Basingstoke strings aligned with their canonical rendering, edit by edit (discovery/code)
  4b. classify_edits.py  every aligned edit gets exactly one taxonomy v2 mechanism ID, with rates (taxonomy/v2)
  4c. build_v2.py      mechanisms.yaml and the summary tables
  5b. fit_profile_v3.py  bundles, rates, clustering, label drift, collision modifiers and per-council house style

The scripts expect the study folder's layout, so this builds a working root under <output>/root by copying in the
development councils' cleaned records, reference components and mined pairs, taxonomy/mechanisms.yaml (v1) and the
bottom-up discovery run (discovery/v1_20261012: the Wigan, Bradford and Leeds alignment and its hand-curated edit
families, which give SU14). Everything the chain writes goes under <output>; nothing in the study folder changes.

    address-errors refit-profile --study <study folder> --output <new dir> [--compare profile/frozen_20261013]

--compare checks the refitted core (bundles, rates, clustering, label drift, collision modifiers) and house style
against a frozen profile. The development councils are fixed by the study code (Wigan, Bradford, Leeds,
Basingstoke); Cornwall and Derby are never read. Fitting a profile on other councils needs the study code
generalised first (council lists, discovery families): for a new source, refit its house style instead
(address-errors fit-house-style), which keeps the frozen core.

--chain general runs the generalised copy in pipeline/study_general/ instead, with the councils listed in a config
(--councils <json>; default: the same four, which reproduces the frozen profile). Each separately aligned council gets
its own align.py run; only the inputs the config names are copied. Councils named cornwall or derby are refused
unless --allow-external-test is given. See pipeline/study_general/GENERALISATION.md.

The working root holds address-level files (aligned strings, real examples): keep <output> inside your data folder.
Needs pandas, numpy, duckdb, rapidfuzz, PyYAML, scipy and scikit-learn (pip install address-errors[pipeline]).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CODE = Path(__file__).parent / 'study'
CODE_GENERAL = Path(__file__).parent / 'study_general'
DEV = ('wigan', 'bradford', 'leeds', 'basingstoke')
FORBIDDEN = ('cornwall', 'derby')
# Only the development councils' inputs are copied into the working root (the study code is fixed to them), so the
# external-test councils never reach it. copy2 keeps modification times: align.py picks the newest pairs file.
INPUTS = ([f'council_data/clean_v1_20261012/{c}' for c in DEV]
          + [f'reference/ngd_20261001/{c}' for c in DEV[:3]]
          + ['reference/ngd_20261001_v2_new_councils/basingstoke',
             'mined_error_pairs/v2_20261012', 'mined_error_pairs/v3_basingstoke_20261012',
             'taxonomy/mechanisms.yaml', 'discovery/v1_20261012'])


def _general_councils(config, allow_external):
    """The generalised chain's council module, loaded with this config (None = its default four councils)."""
    if allow_external:
        os.environ['ADDRESS_ERRORS_ALLOW_EXTERNAL_TEST'] = '1'
    sys.path.insert(0, str(CODE_GENERAL))
    import councils
    sys.path.pop(0)
    try:
        cfg = councils.load(str(config) if config else None)
    except AssertionError as e:
        sys.exit(f'council config refused: {e}')
    names = [c['name'] for c in cfg['councils']]
    if not allow_external:
        bad = [n for n in names if any(f in n.lower() for f in FORBIDDEN)]
        if bad:
            sys.exit(f'refusing external-test councils {bad} (use --allow-external-test to override)')
    return councils, cfg


def build_root_general(study, root, councils, cfg, allow_external):
    """Copy only the inputs the council config names (reference dirs, pairs files, clean records, taxonomy v1 and,
    when any council is a discovery-run council, the discovery run) and the generalised code."""
    forbidden = () if allow_external else FORBIDDEN
    root.mkdir(parents=True)
    names = {c['name'] for c in cfg['councils']}
    for c in cfg['councils']:
        for rel, is_dir in ((c['reference'], True), (c['pairs'], False), (c['clean_records'], False)):
            if any(f in rel.lower() for f in forbidden):
                sys.exit(f'refusing external-test input {rel}')
            if rel == c['clean_records'] and c.get('raw_from_joined'):
                _copy_joined(study / rel, root / rel)
            else:
                _copy(study / rel, root / rel, is_dir, forbidden)
    shared = [(cfg['taxonomy_v1'], False)]
    if any(c['alignment'] == 'discovery' for c in cfg['councils']):
        shared.append((cfg['discovery_dir'], True))
    for rel, is_dir in shared:
        if any(f in rel.lower() for f in forbidden):
            sys.exit(f'refusing external-test input {rel}')
        _copy(study / rel, root / rel, is_dir, forbidden)
    ignore = shutil.ignore_patterns('__pycache__', '*.md')
    shutil.copytree(CODE_GENERAL, root / 'discovery' / 'code', ignore=ignore, dirs_exist_ok=True)
    v2 = root / 'taxonomy' / 'v2_20261012'
    shutil.copytree(CODE_GENERAL, v2 / 'code', ignore=ignore)
    return v2


def _copy_joined(src, dst):
    """Copy clean records with recorded_address_raw set to recorded_address (the delimited fields joined with ", ").

    For a source whose raw field is delimited (Derby and Cornwall: pipe-delimited), the study's cleaning joined the
    fields with ", " into recorded_address, while the house-style fit reads recorded_address_raw. Fitting on the raw
    field gave synthetic strings without the commas a matcher sees (the external test's comma artefact). The original
    raw field is kept in source_fields_raw, as stage-records does. The study's own file is not changed."""
    import csv
    dst.parent.mkdir(parents=True, exist_ok=True)
    csv.field_size_limit(10 ** 9)
    with open(src, newline='', encoding='utf-8') as fi, open(dst, 'w', newline='', encoding='utf-8') as fo:
        r = csv.DictReader(fi)
        fields = list(r.fieldnames) + (['source_fields_raw'] if 'source_fields_raw' not in r.fieldnames else [])
        w = csv.DictWriter(fo, fieldnames=fields)
        w.writeheader()
        for row in r:
            row.setdefault('source_fields_raw', row['recorded_address_raw'])
            row['recorded_address_raw'] = row['recorded_address']
            w.writerow(row)


def _copy(src, dst, is_dir, forbidden):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if is_dir:
        shutil.copytree(src, dst, copy_function=shutil.copy2, dirs_exist_ok=True,
                        ignore=lambda d, names: [n for n in names if any(f in n.lower() for f in forbidden)])
    else:
        shutil.copy2(src, dst)


def build_root(study, root):
    root.mkdir(parents=True)
    for rel in INPUTS:
        src, dst = study / rel, root / rel
        assert not any(f in rel for f in FORBIDDEN)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, copy_function=shutil.copy2,
                            ignore=lambda d, names: [n for n in names if any(f in n.lower() for f in FORBIDDEN)])
        else:
            shutil.copy2(src, dst)
    ignore = shutil.ignore_patterns('__pycache__')
    shutil.copytree(CODE, root / 'discovery' / 'code', ignore=ignore)         # classify_edits imports families from here
    v2 = root / 'taxonomy' / 'v2_20261012'
    shutil.copytree(CODE, v2 / 'code', ignore=ignore)                         # build_v2 imports spec_v2 from <v2>/code
    return v2


def run(args, log, env):
    print('$', ' '.join(str(a) for a in args), flush=True)
    with open(log, 'a') as fh:
        fh.write('$ ' + ' '.join(str(a) for a in args) + '\n')
        fh.flush()
        r = subprocess.run([sys.executable] + [str(a) for a in args], stdout=fh, stderr=subprocess.STDOUT, env=env)
    if r.returncode:
        sys.exit(f'step failed ({r.returncode}); see {log}')


def compare(new, ref):
    """Section-by-section comparison of two profile.json files (ignoring provenance fields)."""
    a, b = json.loads(Path(new).read_text()), json.loads(Path(ref).read_text())
    out = {}
    for k in ('core', 'clustering', 'label_drift', 'strata', 'flag_vocabulary', 'smoothing'):
        out[k] = json.dumps(a.get(k), sort_keys=True) == json.dumps(b.get(k), sort_keys=True)
    hs_a, hs_b = a.get('house_style', {}), b.get('house_style', {})
    out['house_style'] = {c: json.dumps(hs_a.get(c), sort_keys=True) == json.dumps(hs_b.get(c), sort_keys=True)
                          for c in sorted(set(hs_a) | set(hs_b))}
    if not out['core']:
        out['core_sections_differing'] = sorted(k for k in set(a['core']) | set(b['core'])
                                                if json.dumps(a['core'].get(k), sort_keys=True)
                                                != json.dumps(b['core'].get(k), sort_keys=True))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog='address-errors refit-profile', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--study', required=True, type=Path, help='the study folder (UPRN_corrupt_address_study)')
    p.add_argument('--output', required=True, type=Path, help='new directory')
    p.add_argument('--compare', type=Path, help='a profile directory to compare the refit against')
    p.add_argument('--keep-work', action='store_true', help='keep the working root (address-level files)')
    p.add_argument('--chain', choices=('study', 'general'), default='study',
                   help='study: the vendored study chain (fixed four councils); general: pipeline/study_general with --councils')
    p.add_argument('--councils', type=Path, help='council config JSON for --chain general (default: the four development councils)')
    p.add_argument('--allow-external-test', action='store_true',
                   help='with --chain general: allow councils named cornwall or derby (external test; off by default)')
    a = p.parse_args(argv)
    if a.chain == 'study' and (a.councils or a.allow_external_test):
        p.error('--councils and --allow-external-test need --chain general')
    study, out = a.study.resolve(), a.output.resolve()
    if a.chain == 'general':
        councils, cfg = _general_councils(a.councils.resolve() if a.councils else None, a.allow_external_test)
    out.mkdir(parents=True, exist_ok=False)
    log = out / 'refit_log.txt'
    root = out / 'root'
    if a.chain == 'study':
        code = CODE
        v2 = build_root(study, root)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(CODE), str(Path(__file__).parents[2])]))
        separate = ['basingstoke']
    else:
        code = CODE_GENERAL
        (out / 'councils_used.json').write_text(json.dumps(cfg, indent=1))
        v2 = build_root_general(study, root, councils, cfg, a.allow_external_test)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(CODE_GENERAL), str(Path(__file__).parents[2])]),
                   ADDRESS_ERRORS_COUNCILS=str(out / 'councils_used.json'))
        if a.allow_external_test:
            env['ADDRESS_ERRORS_ALLOW_EXTERNAL_TEST'] = '1'
        else:
            env.pop('ADDRESS_ERRORS_ALLOW_EXTERNAL_TEST', None)
        separate = [c['name'] for c in cfg['councils'] if c['alignment'] == 'separate']
    for c in separate:
        run([code / 'align.py', root, v2 / f'{c}_align', 4000, c], log, env)
    run([code / 'classify_edits.py', root, v2 / 'rates'], log, env)
    run([code / 'build_v2.py', root, v2], log, env)
    run([code / 'fit_profile_v3.py', '--study', root, '--output', out / 'profile'], log, env)
    for f in ('mechanisms.yaml',):
        shutil.copy(v2 / f, out / 'profile' / f'taxonomy_{f}')
    res = {'study': str(study), 'output': str(out / 'profile')}
    if a.chain == 'general':
        res.update(chain='general', councils=[c['name'] for c in cfg['councils']], councils_config=str(out / 'councils_used.json'))
    if a.compare:
        res['compare_with'] = str(a.compare)
        res['same'] = compare(out / 'profile' / 'profile.json', a.compare / 'profile.json')
    if not a.keep_work:
        shutil.rmtree(root)
    (out / 'refit_summary.json').write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
