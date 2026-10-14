"""Realism check (pipeline step 6): can a classifier tell synthetic records from real ones?

Runs the study's discriminator (prototype_loop/code/discriminate.py with common.py, vendored unchanged in
pipeline/study/; SHA-256 in package/README.md). Both sides are labelled by the same miner, so every feature is
computed the same way for real and synthetic strings:

  real       the study's mined pairs for each development council (mined_error_pairs/)
  synthetic  <run>/synthetic_<council>.csv.gz, the generator's output for the held-out buildings, and
             <run>/pairs_synth_<council>.csv.gz, the same records re-mined (address-errors mine, or the prototype loop)
  split      <run>/test_split.csv.gz, the held-out buildings (the profile's 20% split)

Two tasks: A all held-out records (each real record vs the synthetic record for the same UPRN) and B discrepancies
only. Gradient boosting, 5-fold cross-validation grouped by building, out-of-fold AUC (0.5 = indistinguishable), plus
an ablation by feature group and a ranked list of what gives synthetic records away.

    address-errors realism-check --study <study folder> --run <run dir> --output <new dir>

The run's inputs are copied to <output> and the results written to <output>/discriminator; <run> is not changed.
The councils are the study's development councils (Wigan, Bradford, Leeds, Basingstoke); Cornwall and Derby are never
read. Checking another source needs the discriminator's loaders generalised (common.py reads the study layout).
Needs pandas, numpy, rapidfuzz, lightgbm and scikit-learn (pip install address-errors[evaluate]).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CODE = Path(__file__).parent / 'study'
DEV = ('wigan', 'bradford', 'leeds', 'basingstoke')
FORBIDDEN = ('cornwall', 'derby')


def main(argv=None):
    p = argparse.ArgumentParser(prog='address-errors realism-check', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--study', required=True, type=Path, help='the study folder (UPRN_corrupt_address_study)')
    p.add_argument('--run', required=True, type=Path, help='synthetic_<c>, pairs_synth_<c> and test_split files')
    p.add_argument('--output', required=True, type=Path, help='new directory')
    a = p.parse_args(argv)
    run, out = a.run.resolve(), a.output.resolve()
    names = [f for c in DEV for f in (f'synthetic_{c}.csv.gz', f'pairs_synth_{c}.csv.gz')] + ['test_split.csv.gz']
    if any(any(f in n.lower() for f in FORBIDDEN) for n in os.listdir(run)):
        sys.exit(f'{run} holds external-test files; the realism check runs on development councils only')
    have = [n for n in names if (run / n).exists()]
    if 'test_split.csv.gz' not in have or not any(n.startswith('pairs_synth_') for n in have):
        sys.exit(f'{run} needs test_split.csv.gz and at least one pairs_synth_<council>.csv.gz')
    out.mkdir(parents=True, exist_ok=False)
    for n in have:
        shutil.copy2(run / n, out / n)
    env = dict(os.environ, STUDY=str(a.study.resolve()), PYTHONPATH=str(CODE))
    with open(out / 'realism_log.txt', 'w') as log:
        r = subprocess.run([sys.executable, str(CODE / 'discriminate.py'), str(out)], stdout=log,
                           stderr=subprocess.STDOUT, env=env)
    if r.returncode:
        sys.exit(f'discriminator failed ({r.returncode}); see {out / "realism_log.txt"}')
    for n in have:                                    # keep the results, not a second copy of the address-level inputs
        (out / n).unlink()
    res = json.loads((out / 'discriminator' / 'discriminator_results.json').read_text())
    print(json.dumps({'run': str(run), 'auc': res['auc']}, indent=1))


if __name__ == '__main__':
    main()
