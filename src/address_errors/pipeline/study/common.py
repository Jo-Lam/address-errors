"""Shared loading for the prototype loop: NGD components, recipient context and the building split.

Development councils with an OS reference only (Wigan, Bradford, Leeds). Cornwall and Derby are never read.
"""
import gzip, csv, os, re
from pathlib import Path
import pandas as pd

STUDY = Path(os.environ.get('STUDY', '/mnt/project-files/UPRN_corrupt_address_study'))
LOOP = STUDY / 'prototype_loop'
SNAP = LOOP / 'inputs_snapshot'
REF = STUDY / 'reference' / 'ngd_20261001'
PAIRS = STUDY / 'mined_error_pairs' / 'v2_20261012'
COUNCILS = ['wigan', 'bradford', 'leeds']
COUNCILS_V1 = ['wigan', 'bradford', 'leeds', 'basingstoke']
REFS = {c: STUDY / 'reference' / 'ngd_20261001' / c for c in COUNCILS}
REFS['basingstoke'] = STUDY / 'reference' / 'ngd_20261001_v2_new_councils' / 'basingstoke'
PAIR_FILES = {c: PAIRS / f'pairs_{c}.csv.gz' for c in COUNCILS}
PAIR_FILES['basingstoke'] = STUDY / 'mined_error_pairs' / 'v3_basingstoke_20261012' / 'pairs_basingstoke.csv.gz'
FORBIDDEN = {'cornwall', 'derby'}
RURAL_MAX_POSTCODE_SIZE = 5

COMP_COLS = ['uprn', 'feature_type', 'subname', 'name', 'number', 'streetname', 'locality', 'townname', 'postcode',
             'floorlevel', 'classificationcode', 'parentuprn', 'rootuprn', 'usrn', 'n_children', 'n_siblings',
             'parent_in_extract', 'sao_type', 'number_type', 'number_int', 'number_suffix', 'number_range_end',
             'name_is_generic', 'rm_subbuildingname', 'rm_buildingname', 'rm_buildingnumber',
             'rm_dependentthoroughfare', 'rm_thoroughfare', 'rm_dependentlocality', 'rm_posttown',
             'organisationname', 'easting', 'northing', 'lowertierlocalauthoritygsscode']


def load_components(council):
    assert council not in FORBIDDEN
    c = pd.read_csv(REFS[council] / 'components.csv.gz', dtype=str, keep_default_na=False, usecols=COMP_COLS)
    return c


def dwelling_type(r):
    """Same rule as profile/code/fit_profile.py (first match wins)."""
    st = r['sao_type']
    if st in ('room', 'bedsit'):
        return 'room'
    if st in ('floor_descriptor', 'position'):
        return 'floor_flat'
    if st == 'annex':
        return 'annex'
    if r['subname'] or r['parentuprn']:
        return 'flat'
    if r['name'] and r['number']:
        return 'named_number'
    if r['name']:
        return 'named_only'
    if r['number']:
        return 'numbered'
    return 'other'


def add_context(c):
    built = c[c.feature_type == 'builtaddress']
    pcsize = built[built.postcode != ''].groupby('postcode').size()
    c = c.copy()
    c['dwelling_type'] = [dwelling_type(r) for r in c[['sao_type', 'subname', 'parentuprn', 'name', 'number']].to_dict('records')]
    c['rural'] = c.postcode.map(pcsize).fillna(99) <= RURAL_MAX_POSTCODE_SIZE
    c['stratum'] = c.dwelling_type + '|' + c.rural.map({True: 'rural', False: 'urban'})
    return c


def load_split():
    s = pd.read_csv(SNAP / 'split_assignments.csv.gz', dtype=str, keep_default_na=False)
    assert not FORBIDDEN & set(s.council)
    return s


def load_pairs(council):
    assert council not in FORBIDDEN
    return pd.read_csv(PAIR_FILES[council], dtype=str, keep_default_na=False)


SPLIT_SALT = 'uprn-profile-split-v1'   # profile/code/fit_profile.py
TEST_PERCENT = 20


def compute_split(c, council):
    """Building split exactly as profile/code/fit_profile.py: root:<rootuprn> in a hierarchy, else usrn, else uprn;
    salted SHA-256 bucket < 20 -> test. c: components with add_context()."""
    import hashlib
    nch = pd.to_numeric(c.n_children, errors='coerce').fillna(0)
    key = c.uprn.radd('uprn:')
    key = key.where(c.usrn == '', 'usrn:' + c.usrn)
    key = key.where(~((c.parentuprn != '') | (nch > 0)), 'root:' + c.rootuprn)
    b = key.map(lambda k: int(hashlib.sha256(f'{SPLIT_SALT}|{council}|{k}'.encode()).hexdigest()[:8], 16) % 100)
    return pd.DataFrame({'council': council, 'uprn': c.uprn, 'split_key': key,
                         'split': b.map(lambda x: 'test' if x < TEST_PERCENT else 'train')})
