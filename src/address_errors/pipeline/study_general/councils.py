"""Council configuration for the generalised study chain (study_general/).

Every script in this folder takes its council list from here instead of hard-coded names. The configuration is the
JSON file named by the environment variable ADDRESS_ERRORS_COUNCILS, or DEFAULT below (the study's four development
councils, which reproduces the frozen profile profile/frozen_20261013 exactly). All paths are relative to the study
root the scripts are given (the working root refit_profile builds).

Per council:
  name             council key used everywhere (lower case)
  reference        reference dir holding components.csv.gz
  pairs            mined pairs file (pairs_<name>.csv.gz)
  clean_records    clean_records.csv (recorded strings, clean_tags; SY1 rows tagged systemic_truncation*)
  epoch            council extract date (provenance only)
  alignment        "discovery": aligned in the bottom-up discovery run (discovery_dir), whose hand-curated clusters and
                   families exist only for these councils; background_weight is then a fixed number from that run.
                   "separate": aligned on its own by align.py into <taxonomy v2>/<name>_align; its background weight is
                   read from that run's align_audit.json (background_weight must be null).
  core_pairs       true: a core pairs council in profile v0 (fit_profile.py PAIR_COUNCILS); false: style only in v0
                   (STYLE_COUNCILS only). From profile v1 on every listed council is in the core.
  raw_from_joined  optional, true: the source's raw field is delimited; refit_profile copies its clean records with
                   recorded_address_raw set to the joined recorded_address, so house style is fitted on the string
                   a matcher sees
  postcode_model   true: fit_profile_v1.postcode_model fits PC labels for it (pairs carry postcode labels)

Top level: discovery_dir (only needed when a council has alignment "discovery"), taxonomy_v1.
"""
import json
import os
from pathlib import Path

EXTERNAL_TEST = ('cornwall', 'derby')

DEFAULT = {
    'discovery_dir': 'discovery/v1_20261012',
    'taxonomy_v1': 'taxonomy/mechanisms.yaml',
    'councils': [
        {'name': 'wigan', 'reference': 'reference/ngd_20261001/wigan',
         'pairs': 'mined_error_pairs/v2_20261012/pairs_wigan.csv.gz',
         'clean_records': 'council_data/clean_v1_20261012/wigan/clean_records.csv', 'epoch': '2025-11',
         'alignment': 'discovery', 'background_weight': 38.07875, 'core_pairs': True, 'postcode_model': True},
        {'name': 'bradford', 'reference': 'reference/ngd_20261001/bradford',
         'pairs': 'mined_error_pairs/v2_20261012/pairs_bradford.csv.gz',
         'clean_records': 'council_data/clean_v1_20261012/bradford/clean_records.csv', 'epoch': '2025-12',
         'alignment': 'discovery', 'background_weight': 52.92925, 'core_pairs': True, 'postcode_model': False},
        {'name': 'leeds', 'reference': 'reference/ngd_20261001/leeds',
         'pairs': 'mined_error_pairs/v2_20261012/pairs_leeds.csv.gz',
         'clean_records': 'council_data/clean_v1_20261012/leeds/clean_records.csv', 'epoch': '2024-10',
         'alignment': 'discovery', 'background_weight': 89.37525, 'core_pairs': True, 'postcode_model': False},
        {'name': 'basingstoke', 'reference': 'reference/ngd_20261001_v2_new_councils/basingstoke',
         'pairs': 'mined_error_pairs/v3_basingstoke_20261012/pairs_basingstoke.csv.gz',
         'clean_records': 'council_data/clean_v1_20261012/basingstoke/clean_records.csv', 'epoch': '2025',
         'alignment': 'separate', 'background_weight': None, 'core_pairs': False, 'postcode_model': True},
    ],
}
REQUIRED = ('name', 'reference', 'pairs', 'clean_records', 'epoch', 'alignment', 'core_pairs')


def forbidden():
    """External-test councils refused by every script, unless refit_profile --allow-external-test set the override."""
    return set() if os.environ.get('ADDRESS_ERRORS_ALLOW_EXTERNAL_TEST') == '1' else set(EXTERNAL_TEST)


def validate(cfg):
    names = [c['name'] for c in cfg['councils']]
    assert len(names) == len(set(names)), 'duplicate council names'
    bad = forbidden()
    for c in cfg['councils']:
        miss = [k for k in REQUIRED if k not in c]
        assert not miss, f"council {c.get('name')}: missing {miss}"
        low = ' '.join(str(c[k]) for k in ('name', 'reference', 'pairs', 'clean_records')).lower()
        assert not any(f in low for f in bad), f"external-test council refused: {c['name']}"
        assert c['alignment'] in ('discovery', 'separate'), c['alignment']
        if c['alignment'] == 'discovery':
            assert isinstance(c.get('background_weight'), (int, float)), f"{c['name']}: discovery councils need a fixed background_weight"
        else:
            assert c.get('background_weight') is None, f"{c['name']}: separately aligned councils take the weight from align_audit.json"
    if any(c['alignment'] == 'discovery' for c in cfg['councils']):
        assert cfg.get('discovery_dir'), 'discovery_dir needed for alignment "discovery"'
    return cfg


def load(path=None):
    path = path or os.environ.get('ADDRESS_ERRORS_COUNCILS')
    cfg = json.loads(Path(path).read_text()) if path else json.loads(json.dumps(DEFAULT))
    cfg.setdefault('discovery_dir', DEFAULT['discovery_dir'])
    cfg.setdefault('taxonomy_v1', DEFAULT['taxonomy_v1'])
    for c in cfg['councils']:
        c.setdefault('postcode_model', False)
        c.setdefault('background_weight', None)
    return validate(cfg)


CFG = load()
BY_NAME = {c['name']: c for c in CFG['councils']}
NAMES = [c['name'] for c in CFG['councils']]
CORE_PAIRS = [c['name'] for c in CFG['councils'] if c['core_pairs']]
STYLE_ONLY = [c['name'] for c in CFG['councils'] if not c['core_pairs']]
DISCOVERY = [c['name'] for c in CFG['councils'] if c['alignment'] == 'discovery']
SEPARATE = [c['name'] for c in CFG['councils'] if c['alignment'] == 'separate']
POSTCODE = [c['name'] for c in CFG['councils'] if c['postcode_model']]
REF = {c['name']: c['reference'] for c in CFG['councils']}
PAIRS = {c['name']: c['pairs'] for c in CFG['councils']}
CLEAN = {c['name']: c['clean_records'] for c in CFG['councils']}
EPOCH = {c['name']: c['epoch'] for c in CFG['councils']}
FIXED_BG_W = {c['name']: c['background_weight'] for c in CFG['councils'] if c['alignment'] == 'discovery'}
DISCOVERY_DIR = CFG['discovery_dir']
TAXONOMY_V1 = CFG['taxonomy_v1']
FORBIDDEN = forbidden()


def align_dir(v2_dir, council):
    """Where align.py writes a separately aligned council (Basingstoke: <v2>/basingstoke_align, as in the study)."""
    return os.path.join(str(v2_dir), f'{council}_align')


def inputs():
    """Study-relative inputs the chain reads, for refit_profile.build_root: (path, is_dir)."""
    out = []
    for c in CFG['councils']:
        out += [(c['reference'], True), (c['pairs'], False), (c['clean_records'], False)]
    out.append((TAXONOMY_V1, False))
    if DISCOVERY:
        out.append((DISCOVERY_DIR, True))
    return out
