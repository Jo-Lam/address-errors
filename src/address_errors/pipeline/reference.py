"""Canonical reference from an OS NGD address order (pipeline step 1).

Reads an OS NGD order folder (add_gb_{builtaddress,prebuildaddress,historicaddress,nonaddressableobject,
royalmailaddress}.zip; zips are read, never extracted in place) and writes into a NEW directory:
  reference.csv       true_uprn, abp_address, abp_postcode (+ feature_type, la_gss, in_council_la)
  components.csv.gz   one row per UPRN: NGD components, hierarchy, classification, floor, derived sub-unit and
                      number typing, primary Royal Mail (PAF) rendering. This is the corruptor's input.
  renderings.csv.gz   every rendering of each UPRN (NGD current/alternative/historical, PAF, multiple residence)
  build_audit.json    counts and checks

From study/reference/build_reference.py (12 Oct 2026), generalised: any OS order folder, any local authority code,
and an optional list of UPRNs a council (or other source) carries. UPRNs stay text throughout.

    address-errors build-reference --os-order OS_data/Wigan --la-gss E08000010 --output ref/wigan \
        [--labels council_data/clean_v1_20261012/wigan/clean_records.csv]
"""
import argparse, io, json, re, zipfile
from pathlib import Path

FEATURES = ['builtaddress', 'prebuildaddress', 'historicaddress', 'nonaddressableobject']
NGD_KEEP = ['uprn', 'organisationname', 'poboxnumber', 'subname', 'name', 'number', 'streetname', 'locality', 'townname',
            'postcode', 'fulladdress', 'floorlevel', 'lowestfloorlevel', 'highestfloorlevel', 'classificationcode',
            'classificationdescription', 'primaryclassificationdescription', 'buildstatus', 'buildstatusdate',
            'addressstatus', 'postcodesource', 'parentuprn', 'rootuprn', 'hierarchylevel', 'usrn',
            'lowertierlocalauthoritygsscode', 'easting', 'northing', 'effectivestartdate', 'effectiveenddate']
RM_KEEP = ['udprn', 'organisationname', 'departmentname', 'subbuildingname', 'buildingname', 'buildingnumber',
           'dependentthoroughfare', 'thoroughfare', 'doubledependentlocality', 'dependentlocality', 'posttown',
           'postcode', 'fulladdress', 'uprn', 'primaryuprnmatch', 'matchtype']
FLOOR = r'(GROUND|FIRST|SECOND|THIRD|FOURTH|FIFTH|TOP|BASEMENT|LOWER GROUND|UPPER GROUND|UPPER|LOWER|\d+(ST|ND|RD|TH))\b'
GENERIC = (r'^(THE )?(OLD )?(BUNGALOW|COTTAGE|FLAT|LODGE|COACH HOUSE|ANNEXE?|BARN|STABLES|GATEHOUSE|GATE HOUSE|'
           r'FARMHOUSE|FARM HOUSE|HOUSE|MAISONETTE|GRANARY|SCHOOL|VICARAGE|RECTORY|MEWS|STUDIO|DAIRY|SMITHY|'
           r'CHAPEL|BAKEHOUSE|FOLD|CROFT|HAYLOFT|LOFT|BOTHY|GARDEN COTTAGE|GARDEN FLAT)$')


def read_member(zpath, member, usecols=None):
    import pandas as pd
    with zipfile.ZipFile(zpath) as z, z.open(member) as f:
        return pd.read_csv(io.TextIOWrapper(f, encoding='utf-8'), dtype=str, keep_default_na=False, usecols=usecols)


def strip_pc(addr, pc):
    return addr[:-len(pc) - 2] if pc and addr.endswith(', ' + pc) else addr


def sao_type(s):
    if not s: return ''
    if re.search(r'\bANNEXE?\b', s): return 'annex'
    if re.search(r'\bROOMS?\b', s): return 'room'
    if re.search(r'\bBEDSIT', s): return 'bedsit'
    if re.search(FLOOR + r'.*\b(FLOOR|FLAT)\b', s) or re.search(r'\bFLOOR\b', s): return 'floor_descriptor'
    if re.fullmatch(r'(FLAT|APARTMENT|APT|UNIT|MAISONETTE|STUDIO|SUITE)S? [0-9A-Z/.-]+', s):
        return re.match(r'\w+', s).group(0).lower().rstrip('s') + '_id'
    if re.match(r'(FLAT|APARTMENT|UNIT|MAISONETTE|STUDIO|SUITE)', s): return 'unit_word_other'
    if re.search(r'\b(FRONT|REAR|LEFT|RIGHT|MIDDLE|BACK|SIDE)\b', s): return 'position'
    if re.fullmatch(r'[0-9]+[A-Z]?', s): return 'bare_number'
    if re.fullmatch(r'[A-Z]', s): return 'bare_letter'
    if re.match(r'BLOCK\b', s): return 'block'
    return 'other_name'


def parse_number(n):
    m = re.fullmatch(r'(\d+)([A-Z]?)(?:-(\d+)([A-Z]?))?', n)
    if not n: return 'none', '', '', ''
    if not m: return 'other', '', '', ''
    if m.group(3): return 'range', m.group(1), m.group(2), m.group(3) + m.group(4)
    return ('letter_suffix' if m.group(2) else 'plain'), m.group(1), m.group(2), ''




def derive_columns(rows):
    """Add the derived typing columns to a user's own component rows (list of dicts, values as text), so a
    gazetteer that is not an OS NGD order can be corrupted. Hierarchy counts come from parentuprn."""
    kids = {}
    for r in rows:
        if r.get('parentuprn'):
            kids[r['parentuprn']] = kids.get(r['parentuprn'], 0) + 1
    for r in rows:
        for k in ('subname', 'name', 'number', 'streetname', 'locality', 'townname'):
            r[k] = ' '.join((r.get(k) or '').upper().split())
        r['n_children'] = str(kids.get(r['uprn'], 0))
        r['n_siblings'] = str(kids.get(r['parentuprn'], 1) - 1) if r.get('parentuprn') else '0'
        if not r.get('rootuprn'):
            r['rootuprn'] = r.get('parentuprn') or r['uprn']
        r['sao_type'] = sao_type(r['subname'])
        r['number_type'], r['number_int'], r['number_suffix'], r['number_range_end'] = parse_number(r['number'])
        r['name_is_generic'] = 'true' if re.match(GENERIC, r['name']) else 'false'
    return rows


def build(os_order, out, la_gss=None, labels=None, label_column='label_uprn', name=None):
    """os_order: folder holding the five NGD zips. la_gss: the authority's GSS code (marks in_council_la).
    labels: optional CSV whose label_column lists the UPRNs a source carries (context only, never truth)."""
    import pandas as pd
    src = Path(os_order)
    la = la_gss or ''
    out = Path(out)
    audit = {'name': name or src.name, 'os_folder': str(src), 'council_la_gss': la}
    frames, alts = [], []
    for ft in FEATURES:
        z = src / f'add_gb_{ft}.zip'
        d = read_member(z, f'add_gb_{ft}.csv', NGD_KEEP)
        d.insert(1, 'feature_type', ft)
        frames.append(d)
        a = read_member(z, f'add_gb_{ft}_altadd.csv')
        a['feature_type'] = ft
        alts.append(a)
        audit[f'rows_{ft}'] = len(d)
    ngd = pd.concat(frames, ignore_index=True)
    assert not ngd.uprn.duplicated().any(), 'UPRN repeated across NGD feature types'
    assert ngd.uprn.str.fullmatch(r'[1-9]\d{0,11}').all(), 'unexpected UPRN format'
    ngd['abp_address'] = [strip_pc(a, p) for a, p in zip(ngd.fulladdress, ngd.postcode)]
    ngd['in_council_la'] = (ngd.lowertierlocalauthoritygsscode == la).map({True: 'true', False: 'false'})

    # hierarchy
    kids = ngd.loc[ngd.parentuprn != '', 'parentuprn'].value_counts()
    ngd['n_children'] = ngd.uprn.map(kids).fillna(0).astype(int)
    ngd['n_siblings'] = (ngd.parentuprn.map(kids).fillna(1).astype(int) - 1).where(ngd.parentuprn != '', 0)
    ngd['parent_in_extract'] = ngd.parentuprn.isin(set(ngd.uprn)).where(ngd.parentuprn != '', False).map({True: 'true', False: 'false'})

    # derived typing
    ngd['sao_type'] = ngd.subname.map(sao_type)
    parsed = ngd.number.map(parse_number)
    ngd['number_type'] = [p[0] for p in parsed]
    ngd['number_int'] = [p[1] for p in parsed]
    ngd['number_suffix'] = [p[2] for p in parsed]
    ngd['number_range_end'] = [p[3] for p in parsed]
    ngd['name_is_generic'] = ngd['name'].str.match(GENERIC).map({True: 'true', False: 'false'})
    ngd['name_has_digit'] = ngd['name'].str.contains(r'\d').map({True: 'true', False: 'false'})
    ngd['has_name_and_number'] = ((ngd['name'] != '') & (ngd.number != '')).map({True: 'true', False: 'false'})

    # Royal Mail
    rmz = src / 'add_gb_royalmailaddress.zip'
    rm = read_member(rmz, 'add_gb_royalmailaddress.csv', RM_KEEP)
    rm['rm_address'] = [strip_pc(a, p) for a, p in zip(rm.fulladdress, rm.postcode)]
    audit['rm_rows'] = len(rm); audit['rm_unmatched_rows'] = int((rm.uprn == '').sum())
    prim = rm[(rm.uprn != '') & (rm.primaryuprnmatch == 'Yes')].drop_duplicates('uprn')
    rmcols = ['udprn', 'organisationname', 'subbuildingname', 'buildingname', 'buildingnumber', 'dependentthoroughfare',
              'thoroughfare', 'dependentlocality', 'posttown', 'postcode', 'rm_address', 'matchtype']
    prim = prim[['uprn'] + rmcols].rename(columns={c: ('rm_' + c if not c.startswith('rm_') else c) for c in rmcols})
    ngd = ngd.merge(prim, on='uprn', how='left').fillna('')
    ngd['rm_n_delivery_points'] = ngd.uprn.map(rm.loc[rm.uprn != '', 'uprn'].value_counts()).fillna(0).astype(int)
    mr = read_member(rmz, 'add_gb_royalmailaddress_multires.csv')
    mr['uprn_resolved'] = mr.uprn.where(mr.uprn != '', mr.udprn.map(rm.drop_duplicates('udprn').set_index('udprn').uprn)).fillna('')
    ngd['rm_n_multires_own'] = ngd.uprn.map(mr.loc[mr.uprn != '', 'uprn'].value_counts()).fillna(0).astype(int)
    ngd['rm_n_multires_behind_dp'] = ngd.uprn.map(mr.loc[(mr.uprn == '') & (mr.uprn_resolved != ''), 'uprn_resolved'].value_counts()).fillna(0).astype(int)

    # council presence (context only; not truth)
    cu = set()
    if labels:
        cr = pd.read_csv(labels, dtype=str, keep_default_na=False, usecols=[label_column])
        cu = set(cr[label_column][cr[label_column] != ''])
    ngd['in_council_ct_list'] = ngd.uprn.isin(cu).map({True: 'true', False: 'false'})
    audit['council_label_uprns'] = len(cu)
    audit['council_label_uprns_in_reference'] = int(ngd.uprn.isin(cu).sum())
    audit['council_label_uprns_by_feature_type'] = ngd[ngd.uprn.isin(cu)].feature_type.value_counts().to_dict()
    audit['council_label_uprns_missing_from_reference'] = len(cu - set(ngd.uprn))

    out.mkdir(parents=True, exist_ok=False)
    ref = ngd[['uprn', 'abp_address', 'postcode', 'feature_type', 'lowertierlocalauthoritygsscode', 'in_council_la']].rename(
        columns={'uprn': 'true_uprn', 'postcode': 'abp_postcode', 'lowertierlocalauthoritygsscode': 'la_gss'})
    ref.to_csv(out / 'reference.csv', index=False)
    comp_cols = (['uprn', 'feature_type', 'in_council_la', 'in_council_ct_list', 'abp_address'] +
                 [c for c in NGD_KEEP if c not in ('uprn', 'fulladdress')] +
                 ['n_children', 'n_siblings', 'parent_in_extract', 'sao_type', 'number_type', 'number_int', 'number_suffix',
                  'number_range_end', 'name_is_generic', 'name_has_digit', 'has_name_and_number'] +
                 [c for c in ngd.columns if c.startswith('rm_')])
    ngd[comp_cols].to_csv(out / 'components.csv.gz', index=False, compression='gzip')

    # renderings (long)
    R = []
    R.append(pd.DataFrame({'uprn': ngd.uprn, 'source': 'ngd_current', 'status': ngd.feature_type, 'address': ngd.abp_address,
                           'postcode': ngd.postcode, 'subname': ngd.subname, 'name': ngd['name'], 'number': ngd.number,
                           'street': ngd.streetname, 'start_date': ngd.effectivestartdate, 'end_date': ngd.effectiveenddate}))
    al = pd.concat(alts, ignore_index=True)
    R.append(pd.DataFrame({'uprn': al.uprn, 'source': 'ngd_altadd_' + al.addressstatus.str.lower(), 'status': al.feature_type,
                           'address': [strip_pc(a, p) for a, p in zip(al.fulladdress, al.postcode)], 'postcode': al.postcode,
                           'subname': al.alternatesubname, 'name': al.alternatename, 'number': al.alternatenumber,
                           'street': al.streetname, 'start_date': al.effectivestartdate, 'end_date': al.effectiveenddate}))
    rmu = rm[rm.uprn != '']
    R.append(pd.DataFrame({'uprn': rmu.uprn, 'source': rmu.primaryuprnmatch.map({'Yes': 'rm_primary'}).fillna('rm_secondary'),
                           'status': rmu.matchtype, 'address': rmu.rm_address, 'postcode': rmu.postcode,
                           'subname': rmu.subbuildingname, 'name': rmu.buildingname, 'number': rmu.buildingnumber,
                           'street': rmu.thoroughfare, 'start_date': '', 'end_date': ''}))
    mru = mr[mr.uprn_resolved != '']
    # PAF-style rendering: building number attaches to the dependent thoroughfare when present, else the thoroughfare
    parts = []
    for org, dept, sub, bname, num, dep, thr, ddl, dl, pt in zip(
            mru.multiresorganisationname, mru.multiresdepartmentname, mru.multiressubbuildingname, mru.multiresbuildingname,
            mru.multiresbuildingnumber, mru.multiresdependentthoroughfare, mru.multiresthoroughfare,
            mru.multiresdoubledependentlocality, mru.multiresdependentlocality, mru.multiresposttown):
        dep_s = f'{num} {dep}'.strip() if dep else ''
        thr_s = thr if dep else f'{num} {thr}'.strip()
        parts.append(', '.join(x for x in (org, dept, sub, bname, dep_s, thr_s, ddl, dl, pt) if x))
    # multires rows without their own UPRN are resolved via the shared delivery point (UDPRN): the rendering then
    # describes a sub-unit behind that UPRN's letterbox, NOT the UPRN itself -> separate source label
    mr_src = mru.uprn.map(lambda u: 'rm_multires' if u else 'rm_multires_subunit_of_delivery_point')
    R.append(pd.DataFrame({'uprn': mru.uprn_resolved, 'source': mr_src, 'status': mru.udprn, 'address': parts,
                           'postcode': mru.multirespostcode, 'subname': mru.multiressubbuildingname, 'name': mru.multiresbuildingname,
                           'number': mru.multiresbuildingnumber, 'street': mru.multiresthoroughfare, 'start_date': '', 'end_date': ''}))
    rend = pd.concat(R, ignore_index=True).fillna('')
    rend.to_csv(out / 'renderings.csv.gz', index=False, compression='gzip')

    audit['reference_rows'] = len(ref)
    audit['reference_rows_in_council_la'] = int((ngd.in_council_la == 'true').sum())
    audit['renderings_by_source'] = rend.source.value_counts().to_dict()
    audit['uprns_with_rm_primary'] = int((ngd.rm_udprn != '').sum())
    audit['uprns_with_parent'] = int((ngd.parentuprn != '').sum())
    audit['parents_with_children'] = int((ngd.n_children > 0).sum())
    audit['uprn_text_check'] = 'all UPRNs match [1-9][0-9]{0,11}; no duplicates across feature types'
    (out / 'build_audit.json').write_text(json.dumps(audit, indent=2))
    return audit



def main(argv=None):
    p = argparse.ArgumentParser(prog='address-errors build-reference', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--os-order', required=True, help='folder with the OS NGD order zips')
    p.add_argument('--output', required=True, help='new, empty directory')
    p.add_argument('--la-gss', default='', help='GSS code of the local authority, e.g. E08000010')
    p.add_argument('--labels', help='CSV listing the UPRNs a source carries (context only)')
    p.add_argument('--label-column', default='label_uprn')
    a = p.parse_args(argv)
    out = Path(a.output)
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Use a new output directory')
    print(json.dumps(build(a.os_order, out, a.la_gss, a.labels, a.label_column), indent=2))


if __name__ == '__main__':
    main()
