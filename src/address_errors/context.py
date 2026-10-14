"""Canonical records: loading, recipient context (dwelling type x rural) and the building split.

A canonical record is one row per UPRN of OS NGD address components, as written by
`address_errors.pipeline.reference` (components.csv.gz). All values are text; UPRNs are never cast to numbers.
"""
import csv
import gzip
import hashlib
import io
from collections import Counter

RURAL_MAX_POSTCODE_SIZE = 5          # rural proxy: NGD postcode with <= 5 built UPRNs (profile v0 onwards)
SPLIT_SALT = 'uprn-profile-split-v1'  # building split salt used by every profile fit
TEST_PERCENT = 20

# Columns the corruptor reads. Missing optional columns are filled with ''.
REQUIRED = ['uprn', 'subname', 'name', 'number', 'streetname', 'townname']
COLUMNS = ['uprn', 'feature_type', 'subname', 'name', 'number', 'streetname', 'locality', 'townname', 'postcode',
           'floorlevel', 'classificationcode', 'parentuprn', 'rootuprn', 'usrn', 'n_children', 'n_siblings',
           'parent_in_extract', 'sao_type', 'number_type', 'number_int', 'number_suffix', 'number_range_end',
           'name_is_generic', 'rm_subbuildingname', 'rm_buildingname', 'rm_buildingnumber',
           'rm_dependentthoroughfare', 'rm_thoroughfare', 'rm_dependentlocality', 'rm_posttown',
           'organisationname', 'easting', 'northing', 'lowertierlocalauthoritygsscode']


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


def add_context(records):
    """Add dwelling_type, rural and stratum to each record (in place); returns the list."""
    pcsize = Counter(r['postcode'] for r in records if r['feature_type'] == 'builtaddress' and r['postcode'])
    for r in records:
        r['dwelling_type'] = dwelling_type(r)
        r['rural'] = pcsize.get(r['postcode'], 99) <= RURAL_MAX_POSTCODE_SIZE
        r['stratum'] = r['dwelling_type'] + '|' + ('rural' if r['rural'] else 'urban')
    return records


def _open(path):
    path = str(path)
    if path.endswith('.gz'):
        return io.TextIOWrapper(gzip.open(path, 'rb'), encoding='utf-8', newline='')
    return open(path, encoding='utf-8', newline='')


def load_components(path, derive=True):
    """Read a components table (CSV or CSV.gz) into a list of dicts with context columns.

    Tables written by pipeline.reference have every column. A user's own table needs at least REQUIRED; with
    derive=True the typing columns (sao_type, number_type, ...) are computed when missing.
    """
    with _open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return []
    missing = [c for c in REQUIRED if c not in rows[0]]
    if missing:
        raise ValueError(f'components table lacks required columns: {missing}')
    have = set(rows[0])
    for r in rows:
        for c in COLUMNS:
            if c not in have:
                r[c] = ''
        if 'feature_type' not in have:
            r['feature_type'] = 'builtaddress'
    if derive and not {'sao_type', 'number_type'} <= have:
        from .pipeline.reference import derive_columns
        derive_columns(rows)
    return add_context(rows)


def split_key(r, n_children=None):
    """Building key: root:<rootuprn> inside a hierarchy, else usrn:<usrn>, else uprn:<uprn>."""
    nch = n_children if n_children is not None else float(r.get('n_children') or 0)
    if r['parentuprn'] or nch > 0:
        return 'root:' + r['rootuprn']
    if r['usrn']:
        return 'usrn:' + r['usrn']
    return 'uprn:' + r['uprn']


def split_of(council, key, test_percent=TEST_PERCENT, salt=SPLIT_SALT):
    b = int(hashlib.sha256(f'{salt}|{council}|{key}'.encode()).hexdigest()[:8], 16) % 100
    return 'test' if b < test_percent else 'train'
