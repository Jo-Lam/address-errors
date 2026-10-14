"""Recipient flags for profile v2: one definition shared by the fit (fit_profile_v2.py) and the generator.

A bundle in profile v2 lists `requires: {flag: bool}`. The generator must compute these flags with this module
(`flags_of(row)`, where row is a dict of OS NGD component columns as in reference/*/components.csv.gz) so that a
bundle is offered only to records where every member's rule can fire. The structural flags mirror the
preconditions of the prototype_loop generator_v1 rules (vocabulary copied below and written into the profile).
"""
import re

UNIT_RE = re.compile(r'^(FLAT|APARTMENT|APT|UNIT|MAISONETTE|STUDIO|SUITE)\b\s*(.*)$')
# broader than generator.py's FLOOR_RE on purpose: real and NGD sub-units use "1ST FLOOR", "GRD FLR" etc.
FLOOR_RE = re.compile(r'\b(LOWER GROUND|UPPER GROUND|GROUND|GRD|GND|BASEMENT|BSMT|FIRST|1ST|SECOND|2ND|THIRD|3RD|FOURTH|4TH|'
                      r'FIFTH|5TH|TOP)(\s*(FLOOR|FLR|FL)\b)?|\bBASEMENT\b')
POS_RE = re.compile(r'\b(FRONT|REAR|LEFT|RIGHT|MIDDLE)\b')
ABBR = {'ROAD': 'RD', 'STREET': 'ST', 'AVENUE': 'AVE', 'LANE': 'LN', 'DRIVE': 'DR', 'CLOSE': 'CL', 'CRESCENT': 'CRES',
        'GARDENS': 'GDNS', 'GROVE': 'GR', 'TERRACE': 'TCE', 'PLACE': 'PL', 'COURT': 'CT', 'SQUARE': 'SQ', 'MOUNT': 'MT',
        'HOUSE': 'HSE', 'COTTAGES': 'COTTS', 'COTTAGE': 'COTT', 'FARM': 'FM', 'BUILDINGS': 'BLDGS', 'SAINT': 'ST',
        'APARTMENTS': 'APTS', 'RESIDENCES': 'RES', 'NORTH': 'N', 'SOUTH': 'S', 'EAST': 'E', 'WEST': 'W',
        'UPPER': 'UPR', 'LOWER': 'LWR', 'FIRST': '1ST', 'SECOND': '2ND', 'THIRD': '3RD', 'GROUND': 'GRD',
        'FLOOR': 'FLR', 'APARTMENT': 'APT', 'MAISONETTE': 'MAIS', 'UNIVERSITY': 'UNIV', 'SCHOOL': 'SCH',
        'CHURCH': 'CH', 'GREEN': 'GRN', 'PARK': 'PK', 'BRIDGE': 'BR', 'HALL': 'HL', 'MANCHESTER': 'MANC'}
EXPAND = {v: k for k, v in ABBR.items()}
# taxonomy slot -> component column (generator D field in brackets): dstreet is the PAF dependent thoroughfare,
# which the NGD rendering does not carry, so a generator must take it from rm_dependentthoroughfare.
SLOT_COLUMN = {'street': 'streetname', 'town': 'townname', 'loc': 'locality', 'name': 'name', 'sub': 'subname',
               'org': 'organisationname', 'num': 'number', 'dstreet': 'rm_dependentthoroughfare'}

BASE = ['has_sao', 'has_suffix', 'has_range', 'has_name', 'has_number', 'has_parent', 'has_children', 'has_org', 'has_locality']
STRUCT = ['sao_unit_word_id', 'sao_unit_word', 'sao_multiword', 'sao_numberless', 'sao_ends_id', 'sao_floor', 'sao_ends_at',
          'sao_position', 'sao_letter_end', 'num_numeric', 'num_suffix', 'num_range', 'name_has_digit', 'name_multiword',
          'name_generic', 'su13_add_ok', 'pn4_ok', 'pn6_ok', 'st5_ok', 'street_multiword', 'has_street', 'has_town']
TEXT_OPS = ['abbr', 'exp', 'join', 'split', 'typo']
TEXT = [f'{s}_{op}' for s in SLOT_COLUMN for op in TEXT_OPS]
FLAGS = BASE + STRUCT + TEXT


def _num(s):
    m = re.match(r'^(\d+)([A-Z]?)$', s or '')
    return (int(m.group(1)), m.group(2)) if m else (None, None)


def text_ops(v):
    w = (v or '').split()
    return {'abbr': any(t in ABBR for t in w), 'exp': any(t in EXPAND for t in w),
            'join': any(not w[i].isdigit() and not w[i + 1].isdigit() for i in range(len(w) - 1)),
            'split': '-' in (v or '') or any(len(t) >= 8 and t.isalpha() for t in w),
            'typo': any(len(t) >= 4 and t.isalpha() for t in w)}


def flags_of(r):
    g = lambda k: (r.get(k) or '').strip().upper()
    sub, name, num, street = g('subname'), g('name'), g('number'), g('streetname')
    mu = UNIT_RE.match(sub)
    n, s = _num(num)
    dwelling = r.get('dwelling_type')
    f = {'has_sao': bool(sub), 'has_suffix': r.get('number_type') == 'letter_suffix', 'has_range': r.get('number_type') == 'range',
         'has_name': bool(name), 'has_number': bool(num), 'has_parent': bool(g('parentuprn')),
         'has_children': int(float(r.get('n_children') or 0)) > 0, 'has_org': bool(g('organisationname')),
         'has_locality': bool(g('locality'))}
    f.update({
        'sao_unit_word_id': bool(mu and mu.group(2)) or bool(re.fullmatch(r'FLAT( AT| OVER| ABOVE)?', sub)),
        'sao_unit_word': bool(mu),
        'sao_multiword': len(sub.split()) > 2,
        'sao_numberless': bool(sub) and not re.search(r'\d', sub),
        'sao_ends_id': bool(re.search(r'\d+[A-Z]?$', sub)),
        'sao_floor': bool(FLOOR_RE.search(sub)),
        'sao_ends_at': bool(re.search(r'\bAT$', sub)),
        'sao_position': bool(POS_RE.search(sub)),
        'sao_letter_end': bool(re.search(r'\d[A-Z]$|\b[A-Z]$', sub)),
        'num_numeric': n is not None,
        'num_suffix': bool(s),
        'num_range': bool(re.match(r'^\d+[A-Z]?-\d+[A-Z]?$', num)),
        'name_has_digit': bool(re.search(r'\d', name)),
        'name_multiword': len(name.split()) >= 2,
        'name_generic': (r.get('name_is_generic') or '').lower() == 'true',
        'su13_add_ok': bool(re.fullmatch(r'[0-9]+[A-Z]?|[A-Z]', sub)) or (not sub and bool(num) and bool(name) and f['has_parent'])
                       or (not sub and dwelling in ('flat', 'room', 'floor_flat')),
        'pn4_ok': bool(num) and bool(name or sub),
        'pn6_ok': bool(mu and not mu.group(2)) or (not sub and f['has_parent']),
        'st5_ok': bool(street) and bool(name or sub),
        'street_multiword': len(street.split()) > 1,
        'has_street': bool(street), 'has_town': bool(g('townname')),
    })
    for slot, col in SLOT_COLUMN.items():
        for op, v in text_ops(g(col)).items():
            f[f'{slot}_{op}'] = v
    return f


# ------------------------------------------------------------------ explicit structural requirements
# What each subtype's generator rule needs. These are added on top of the requirements learned from the data
# and win where they disagree. Keys are v2 subtypes or a mechanism ID prefix ("TX1:abbreviated_" + slot).

def structural_requirement(sub):
    m, _, st = sub.partition(':')
    R = {
        'SU13:unit_word_dropped': {'sao_unit_word_id': True},
        'SU13:unit_word_added': {'su13_add_ok': True},
        'SU13:other_subunit_text_dropped': {'sao_multiword': True},
        'SU10:unit_word_swapped': {'sao_unit_word': True},
        'SU10:subunit_text_replaced': {'has_sao': True},
        'SU10:unit_or_floor_word_swapped': {'has_sao': True},
        'SU7:numberless_subunit_dropped': {'sao_numberless': True},
        'SU7:unit_id_dropped': {'sao_unit_word_id': True},
        'SU7:unit_id_lost_in_rewrite': {'sao_unit_word_id': True},
        'SU7:unit_span_dropped': {'has_sao': True},
        'SU7:whole_subunit_with_id_dropped': {'has_sao': True},
        'SU4:floor_descriptor_dropped': {'sao_floor': True},
        'SU4:floor_descriptor_added': {'sao_floor': False},
        'SU6:position_added': {'has_sao': True, 'sao_position': False},
        'SU6:position_dropped': {'sao_position': True},
        'SU1:suffix_dropped': {'num_suffix': True},
        'SU1:suffix_swapped': {'num_suffix': True},
        'SU1:suffix_added': {'num_numeric': True, 'num_suffix': False},
        'SU1:letter_id_dropped': {'sao_letter_end': True},
        'PN2:range_collapsed': {'num_range': True}, 'PN2:range_collapsed_unit': {'num_range': True},
        'PN2:range_vs_other_single': {'num_range': True}, 'PN2:range_vs_other_single_unit': {'num_range': True},
        'PN2:range_extended': {'num_numeric': True}, 'PN2:range_extended_unit': {'num_numeric': True},
        'PN4:number_in_name_dropped': {'name_has_digit': True},
        'PN4:number_dropped': {'pn4_ok': True},
        'PN6:unit_id_added': {'pn6_ok': True}, 'PN6:unit_id_added_in_rewrite': {'pn6_ok': True},
        'PN6:number_added': {'has_number': False},
        'FM8:at_connective_dropped': {'sao_ends_at': True},
        'FM8:at_connective_added': {'has_sao': True, 'sao_ends_at': False},
        'FM9:punctuation_num': {'num_range': True},
        'FM9:punctuation_name': {'has_name': True},
        'FM9:punctuation_sub': {'sao_letter_end': True},
        'ST2:street_words_dropped': {'street_multiword': True},
        'ST4:street_replaced': {'has_street': True},
        'ST5:street_omitted': {'st5_ok': True},
        'BN1:name_dropped': {'has_name': True},
        'BN1:name_added': {},              # generator writes a second name when one exists
        'BN3:generic_name_added': {'has_name': False},
        'BN3:generic_name_dropped': {'name_generic': True},
        'BN2:name_shortened': {'name_multiword': True},
        'BN2:name_elaborated': {'has_name': True},
        'BN4:name_replaced': {'has_name': True},
        'BN8:organisation_dropped': {'has_org': True},
        'BN8:organisation_replaced': {'has_org': True},
    }
    if sub in R:
        return R[sub]
    if m in ('SU14', 'PN8'):
        return {'sao_ends_id': True}
    if m == 'SU5':
        return {'sao_floor': True}
    if m in ('PN3', 'PN7'):
        return {'num_numeric': True}
    if m == 'TX1':
        kind, _, slot = st.partition('_')
        if slot in SLOT_COLUMN:
            return {f'{slot}_{"abbr" if kind == "abbreviated" else "exp"}': True}
    if m == 'TX2':
        kind, _, slot = st.rpartition('_')
        if slot in SLOT_COLUMN:
            return {f'{slot}_{"join" if kind.startswith("tokens_joined") else "split"}': True}
    if m == 'TX3':
        _, _, slot = st.partition('_')
        if slot in SLOT_COLUMN:
            return {f'{slot}_typo': True}
    return {}


# ------------------------------------------------------------------ collision flags (profile v3)
# Whether dropping one component makes the record's canonical dwelling+street equal to ANOTHER UPRN's.
# These need every record of the council at once. Used as rate modifiers (profile.core.collision_modifiers), never as
# requirements: within the eligible records, a subtype lands on a record that would collide at the real relative rate.

COLLISION_FLAGS = ['hit_if_sub_dropped', 'hit_if_name_dropped', 'hit_if_number_dropped', 'hit_if_suffix_dropped']


def _key(sub, name, number, street):
    n = lambda s: ' '.join(re.findall(r'[A-Z0-9]+', (s or '').upper()))
    return (n(sub), n(name), n(number), n(street))


def collision_flags(rows):
    """rows: iterable of dicts with uprn, subname, name, number, streetname. Returns {uprn: {flag: bool}}."""
    rows = list(rows)
    idx = {}
    for r in rows:
        idx.setdefault(_key(r.get('subname'), r.get('name'), r.get('number'), r.get('streetname')), set()).add(r['uprn'])
    def hit(u, k):
        return bool(idx.get(k, set()) - {u})
    out = {}
    for r in rows:
        u, sub, name, num, st = r['uprn'], r.get('subname'), r.get('name'), r.get('number'), r.get('streetname')
        n, s = _num((num or '').upper())
        out[u] = {'hit_if_sub_dropped': bool(sub) and hit(u, _key('', name, num, st)),
                  'hit_if_name_dropped': bool(name) and hit(u, _key(sub, '', num, st)),
                  'hit_if_number_dropped': bool(num) and hit(u, _key(sub, name, '', st)),
                  'hit_if_suffix_dropped': bool(s) and hit(u, _key(sub, name, str(n), st))}
    return out


# subtype -> the collision flag that decides whether it lands on another UPRN
COLLISION_FLAG_OF = {'SU7:numberless_subunit_dropped': 'hit_if_sub_dropped', 'SU7:whole_subunit_with_id_dropped': 'hit_if_sub_dropped',
                     'SU7:unit_span_dropped': 'hit_if_sub_dropped', 'SU4:floor_descriptor_dropped': 'hit_if_sub_dropped',
                     'BN1:name_dropped': 'hit_if_name_dropped', 'PN4:number_dropped': 'hit_if_number_dropped',
                     'SU1:suffix_dropped': 'hit_if_suffix_dropped'}
