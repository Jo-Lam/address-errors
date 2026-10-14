"""Write the bundled example gazetteer: an invented town (no real addresses, UPRNs or postcodes).

Postcodes use the non-existent ZZ area and UPRNs start at 900000000000, so nothing collides with a real address.
Run from the package folder:  python examples/make_example_gazetteer.py
"""
import csv
import random
from pathlib import Path

from address_errors.context import COLUMNS
from address_errors.pipeline.reference import derive_columns

OUT = Path(__file__).resolve().parents[1] / 'src' / 'address_errors' / 'data' / 'example' / 'components.csv'
TOWN = 'EXAMPLETOWN'
rng = random.Random(20261013)
rows, uprn = [], [900000000000]


def add(**kw):
    uprn[0] += 1
    r = {c: '' for c in COLUMNS}
    r.update(uprn=str(uprn[0]), feature_type='builtaddress', classificationcode='RD04', townname=TOWN,
             lowertierlocalauthoritygsscode='E00000000', easting=str(400000 + rng.randrange(3000)),
             northing=str(400000 + rng.randrange(3000)))
    r.update(kw)
    if not r['rm_posttown']:
        r.update(rm_subbuildingname=r['subname'], rm_buildingname=r['name'], rm_buildingnumber=r['number'],
                 rm_thoroughfare=r['streetname'], rm_posttown=TOWN)
    rows.append(r)
    return r['uprn']


# terraced and semi-detached streets
for usrn, (street, loc, n, cls) in enumerate([('ACORN ROAD', 'NORTHSIDE', 60, 'RD04'), ('BEECH STREET', '', 48, 'RD04'),
                                             ('CHESTNUT AVENUE', 'NORTHSIDE', 36, 'RD03'), ('DAMSON CLOSE', '', 20, 'RD03'),
                                             ('ELDER GROVE', 'EASTWOOD', 30, 'RD04')], start=1001):
    for k in range(1, n + 1):
        num = str(k) + ('A' if k % 23 == 0 else '')
        add(number=num, streetname=street, usrn=str(usrn), locality=loc, classificationcode=cls,
            postcode=f'ZZ1 {usrn % 10}{"ABCDEF"[k % 6]}{"GHJ"[k % 3]}')

# converted houses and purpose-built blocks of flats
for usrn, street, num, bname, units in [(1006, 'FIR LANE', '12', 'MAPLE COURT', 24), (1006, 'FIR LANE', '30', 'HOLLY HOUSE', 6),
                                         (1001, 'ACORN ROAD', '70', '', 3), (1007, 'GORSE TERRACE', '5', 'WILLOW MILL', 18)]:
    parent = add(name=bname, number=num, streetname=street, usrn=str(usrn), classificationcode='RD02',
                 postcode=f'ZZ2 {usrn % 10}AB')
    rows[-1]['rootuprn'] = parent
    for k in range(1, units + 1):
        if units <= 6:
            sub = ['GROUND FLOOR FLAT', 'FIRST FLOOR FLAT', 'SECOND FLOOR FLAT', 'FLAT A', 'FLAT B', 'ROOM 1'][k - 1]
        else:
            sub = f'FLAT {k}' if k % 9 else f'APARTMENT {k}'
        add(subname=sub, name=bname, number=num, streetname=street, usrn=str(usrn), postcode=f'ZZ2 {usrn % 10}AB',
            parentuprn=parent, rootuprn=parent, classificationcode='RD06', floorlevel=str(k // 8))

# rural named properties
for k, nm in enumerate(['ROSE COTTAGE', 'THE BUNGALOW', 'HILL FARM', 'OLD MILL HOUSE', 'THE LODGE', 'BRAMBLE END',
                        'IVY COTTAGE', 'MEADOW VIEW', 'THE OLD SCHOOL', 'LOW BARN', 'HIGHFIELD', 'ORCHARD HOUSE']):
    add(name=nm, streetname='BIRCH LANE' if k < 6 else 'MOOR ROAD', usrn='1008' if k < 6 else '1009',
        locality='SOUTHFIELD' if k < 6 else 'WESTMOOR', classificationcode='RD03' if k % 3 else 'RD02',
        postcode=f'ZZ3 {k // 4}CD', easting=str(410000 + 400 * k), northing=str(410000 + 300 * k))
derive_columns(rows)
OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT, 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(len(rows), 'rows ->', OUT)
