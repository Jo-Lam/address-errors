"""A small invented gazetteer (no real addresses) for tests that run anywhere."""
import pytest

from address_errors.context import COLUMNS, add_context
from address_errors.pipeline.reference import derive_columns


def _row(uprn, **kw):
    r = {c: '' for c in COLUMNS}
    r.update(uprn=uprn, feature_type='builtaddress', classificationcode='RD04', townname='EXAMPLETOWN',
             lowertierlocalauthoritygsscode='E00000000', easting='400000', northing='400000')
    r.update(kw)
    return r


@pytest.fixture(scope='session')
def gazetteer():
    rows, u = [], 900000000000
    for n in range(1, 81):
        u += 1
        rows.append(_row(str(u), number=str(n) + ('A' if n % 17 == 0 else ''), streetname='ACORN ROAD', usrn='1001',
                         postcode=f'ZZ1 {n % 4}AB', locality='NORTHSIDE' if n % 2 else ''))
    parent = str(u + 1)
    rows.append(_row(parent, name='MAPLE COURT', number='90', streetname='ACORN ROAD', usrn='1001', postcode='ZZ1 9AA',
                     classificationcode='RD02', rootuprn=parent))
    u += 1
    for k in range(1, 25):
        u += 1
        sub = f'FLAT {k}' if k < 20 else ['GROUND FLOOR FLAT', 'FIRST FLOOR FLAT', 'FLAT A', 'FLAT B', 'ROOM 1'][k - 20]
        rows.append(_row(str(u), subname=sub, name='MAPLE COURT', number='90', streetname='ACORN ROAD', usrn='1001',
                         postcode='ZZ1 9AA', parentuprn=parent, rootuprn=parent, classificationcode='RD06',
                         floorlevel=str(k // 8), rm_subbuildingname=sub, rm_buildingname='MAPLE COURT',
                         rm_buildingnumber='90', rm_thoroughfare='ACORN ROAD', rm_posttown='EXAMPLETOWN'))
    for k, nm in enumerate(['ROSE COTTAGE', 'THE BUNGALOW', 'HILL FARM', 'OLD MILL HOUSE', 'THE LODGE', 'BRAMBLE END']):
        u += 1
        rows.append(_row(str(u), name=nm, streetname='BIRCH LANE', usrn='1002', postcode='ZZ2 1CD',
                         locality='SOUTHFIELD', classificationcode='RD03'))
    derive_columns(rows)
    return add_context(rows)


@pytest.fixture(scope='session')
def targets(gazetteer):
    return [r['uprn'] for r in gazetteer if r['classificationcode'] != 'RD02']
