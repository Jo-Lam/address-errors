"""Command line: address-errors <command> ...

  corrupt          clean canonical components in, corrupted records + truth table out
  profile-info     summary of a profile (styles, bundles, intensity band, portability)
  export-profile   write a portable copy of a profile (no lookups, no address-like text)
  build-reference  OS NGD order -> components.csv.gz (the corruptor's input)          [pipeline extra]
  stage-records    a source's own address records with UPRN labels -> staged + cleaned [pipeline extra]
  mine             recorded vs canonical discrepancy pairs, labelled by mechanism      [pipeline extra]
  fit-house-style  refit one source's house style against the frozen core            [pipeline extra]
  refit-profile    refit the whole profile from the study's development data          [pipeline extra]
  realism-check    re-mine synthetic output and train a real-vs-synthetic discriminator [evaluate extra]
"""
import argparse
import csv
import gzip
import json
import random
import sys
from pathlib import Path

from . import Controls, Corruptor, OUTPUT_FIELDS, Profile, example_path, load_components


def _profile(a):
    prof = Profile.load(a.profile, extras=getattr(a, 'extras', None)) if a.profile else Profile.load()
    for spec in getattr(a, 'add_style', None) or []:
        name, _, d = spec.partition('=')
        prof = prof.with_style(name, d)
    return prof


def cmd_corrupt(a):
    prof = _profile(a)
    controls = Controls.from_dict(json.loads(Path(a.controls).read_text()) if a.controls else {})
    recs = load_components(example_path() if a.components == 'example' else a.components)
    if a.uprns:
        targets = [l.strip() for l in open(a.uprns) if l.strip() and l.strip() != 'uprn']
    else:
        targets = [r['uprn'] for r in recs if r['feature_type'] == 'builtaddress' and
                   (r.get('in_council_la', 'true') in ('true', '')) and r['classificationcode'][:1] in ('R', '')]
    if a.n and a.n < len(targets):
        keep = set(random.Random(a.seed).sample(targets, a.n))
        targets = [u for u in targets if u in keep]
    opener = gzip.open if a.output.endswith('.gz') else open
    n = 0
    with opener(a.output, 'wt', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, ['record_id', 'copy'] + OUTPUT_FIELDS)
        w.writeheader()
        for k in range(a.copies):
            sid = None if k == 0 else f'{a.style or "pooled"}#{k}'   # each copy is its own synthetic source
            gen = Corruptor(prof, style=a.style, seed=a.seed + k, controls=controls, rates=a.rates, source_id=sid)
            gen.index(recs)
            for i, r in enumerate(gen.generate(targets)):
                w.writerow(dict(r, record_id=f'synth:{gen.src}:{k}:{i}', copy=k))
                n += 1
            print(json.dumps({'copy': k, **gen.stats}), file=sys.stderr)
    print(f'wrote {n} records to {a.output}', file=sys.stderr)


def cmd_info(a):
    print(json.dumps(_profile(a).summary(), indent=1))


def cmd_export(a):
    out = _profile(a).export_portable(a.output, exclude_councils=tuple(x for x in a.exclude.split(',') if x))
    print(Path(out, 'PORTABLE.json').read_text())


def main(argv=None):
    p = argparse.ArgumentParser(prog='address-errors', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('corrupt', help='generate corrupted records')
    c.add_argument('--components', required=True, help='components.csv(.gz) from build-reference, your own table, or "example" (an invented town)')
    c.add_argument('--output', required=True, help='CSV or CSV.gz')
    c.add_argument('--profile', help='profile directory, or a bundled name: all6 (default: fitted on all six councils), frozen (the externally tested profile; also v3), v2')
    c.add_argument('--extras', help='style_extras.json (default: the one in the profile directory)')
    c.add_argument('--style', help='house style, e.g. leeds; default: the profile default with pooled rates')
    c.add_argument('--add-style', action='append', metavar='NAME=DIR',
                   help='add a house style refitted from your own strings (a v3 profile; DIR holds house_style.json). '
                        'Use it with --style NAME: the core is unchanged, rates pooled at intensity 1.0')
    c.add_argument('--rates', choices=['council', 'pooled'], default='council')
    c.add_argument('--controls', help='JSON file of Controls fields, e.g. {"prevalence": 2, "noise": {"rate": 0.1}}')
    c.add_argument('--uprns', help='file with one target UPRN per line (default: residential built UPRNs)')
    c.add_argument('--n', type=int, help='sample this many targets')
    c.add_argument('--copies', type=int, default=1, help='independent corrupted versions per target')
    c.add_argument('--seed', type=int, default=0)
    c.set_defaults(fn=cmd_corrupt)
    i = sub.add_parser('profile-info', help='summarise a profile')
    i.add_argument('--profile')
    i.add_argument('--add-style', action='append', metavar='NAME=DIR')
    i.set_defaults(fn=cmd_info)
    e = sub.add_parser('export-profile', help='write a portable copy of a profile')
    e.add_argument('--profile', required=True)
    e.add_argument('--extras')
    e.add_argument('--output', required=True, help='new directory')
    e.add_argument('--exclude', default='basingstoke', help='councils whose council-level entries are left out')
    e.set_defaults(fn=cmd_export)
    passthrough = {'build-reference': 'reference', 'stage-records': 'records', 'mine': 'mine',
                   'fit-house-style': 'fit_style', 'refit-profile': 'refit_profile', 'realism-check': 'realism'}
    for name in passthrough:
        sub.add_parser(name, help=f'pipeline step (see address-errors {name} --help)', add_help=False)
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in passthrough:
        import importlib
        return importlib.import_module(f'.pipeline.{passthrough[argv[0]]}', __package__).main(argv[1:])
    a, rest = p.parse_known_args(argv)
    if rest:
        p.error(f'unrecognised arguments: {rest}')
    return a.fn(a)


if __name__ == '__main__':
    main()
