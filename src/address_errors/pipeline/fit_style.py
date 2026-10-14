"""Refit one source's house style against the frozen core (pipeline step 5a).

Runs the study's profile/code/fit_house_style.py (vendored unchanged in pipeline/fit/) on the source's own mined
pairs, canonical components and cleaned records. Writes <output>/house_style.json plus three lookups
(locality_other_by_usrn, locality_other_by_sector, street_variant_by_usrn), which are address-level: keep them with
your data. Use the result with Profile.with_style() or `address-errors corrupt --add-style NAME=DIR`.

    address-errors fit-house-style --council mysource --pairs work/pairs/pairs_mysource.csv.gz \\
        --components ref/mysource/components.csv.gz --clean records/mysource/clean_records.csv --output fit/mysource \\
        [--profile profile.json] [--train-uprns split.csv.gz]

Needs duckdb, numpy, rapidfuzz and PyYAML (pip install address-errors[pipeline]).
"""
import os
import subprocess
import sys
from pathlib import Path


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        if not argv:
            return 2
    script = Path(__file__).parent / 'fit' / 'fit_house_style.py'
    src = str(Path(__file__).parents[2])
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([src] + [p for p in [os.environ.get('PYTHONPATH')] if p]))
    return subprocess.run([sys.executable, str(script)] + argv, env=env).returncode


if __name__ == '__main__':
    sys.exit(main())
