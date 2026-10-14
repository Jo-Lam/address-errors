"""Fit the house-style block of the corruption profile for ONE council, from that council's own strings.

The core of the profile is never touched. Used two ways:
  * by fit_profile_v3.py for each development council (training split only), and
  * standalone, for an external-test council after the profile is frozen (EVALUATION_PLAN.md, external test step 2):

    python fit_house_style.py --council <name> --pairs <mined pairs csv.gz> --components <components.csv.gz>
        --clean <clean_records.csv> --output <new empty dir> [--profile <frozen profile.json>] [--train-uprns <csv.gz>]

Writes house_style.json (the same keys as profile.house_style[<council>] in a v3 profile) and three non-portable lookups:
locality_other_by_usrn.csv.gz, locality_other_by_sector.csv.gz, street_variant_by_usrn.csv.gz.
--train-uprns restricts fitting to the listed UPRNs (columns council, uprn, split; rows with split=train), which is how
the development councils were fitted; --profile with a development council checks the result against the frozen block.
This script reads only the files it is given. It never opens another council's data.
"""
import argparse, csv, gzip, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
import duckdb, numpy as np
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).parent))
import fit_profile as v0
import flags_v2 as F

COUNTY_WORDS = ['LANCASHIRE', 'LANCS', 'CHESHIRE', 'MERSEYSIDE', 'GREATER MANCHESTER', 'WEST YORKSHIRE', 'YORKSHIRE', 'YORKS',
                'HAMPSHIRE', 'HANTS', 'BERKSHIRE', 'BERKS', 'WILTSHIRE', 'WILTS', 'SURREY',
                'CORNWALL', 'KERNOW', 'DERBYSHIRE', 'DERBYS']
COUNTY_TOKEN = re.compile(r'^(LANCASHIRE|LANCS|CHESHIRE|MERSEYSIDE|YORKSHIRE|YORKS|WEST|HANTS|HAMPSHIRE|BERKS|BERKSHIRE|GREATER|'
                          r'MANCHESTER|WILTS|WILTSHIRE|SURREY|CORNWALL|KERNOW|DERBYSHIRE|DERBYS)$')
# a county is the last element of the string (", Cornwall" / " LANCASHIRE"), never a street such as CORNWALL ROAD
COUNTY_RE = re.compile(r'(?:^|[\s,])(' + '|'.join(COUNTY_WORDS) + r')[\s,.]*(?:[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}[\s,.]*)?$')
FLOOR_RE = re.compile(r'\b(lower ground|upper ground|ground|grd|gnd|basement|bsmt|first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|top|upper|lower|attic)'
                      r'(\s*(?:floor|flr|fl)\b\.?)?', re.I)
FLOOR_LEVEL = [(r'^(LOWER GROUND|BASEMENT|BSMT|LOWER)', '-1'), (r'^(UPPER GROUND|GROUND|GRD|GND)', '0'), (r'^(FIRST|1ST)', '1'),
               (r'^(SECOND|2ND)', '2'), (r'^(THIRD|3RD)', '3'), (r'^(FOURTH|4TH)', '4'), (r'^(FIFTH|5TH)', '5'),
               (r'^(TOP|UPPER|ATTIC)', 'top')]
UNIT_WORD_RE = re.compile(r'\b(FLAT|FLT|APARTMENT|APPT|APT|UNIT|MAISONETTE|STUDIO|SUITE|ROOM|BEDSIT)\b\.?\s*\d')
# --lookup-fix (off by default, so the v3e output is unchanged): found in realism run 4 on fitted_v3e_20261013
SUBUNIT_TEXT = re.compile(r'\b(FLOOR|FLR|FLAT|FLATS|APARTMENT|APT|UNIT|ROOM|ROOMS|GROUND|BASEMENT|MAISONETTE)\b')
STREET_SHRINK = 5        # per-street variant share = k / (n + 5): two of two records is not a certain convention
SECTOR_MIN = 2
STYLE_LABELS = {'SU11:component_order': 'sub_and_name', 'SU11:subunit_after_street': 'sub', 'SU11:word_order': 'sub',
                'SU13:unit_word_added': 'sub_without_unit_word', 'SU4:floor_descriptor_added': 'sub_without_floor',
                'DQ4:brackets': 'any', 'SU9:room_added': 'any', 'FM6:leading_zero': 'sub',
                # ST3 under the taxonomy's names, measured by the miner's labels for the same edit
                'ST3:access_road_off_added': 'street', 'ST3:dependent_or_estate_name_added': 'dstreet'}
# ST3 under the taxonomy's names. "Off ..." is the miner's DQ1:off_street_reference; the dependent street written in
# the string is measured directly (PAF dependent thoroughfare present in the recorded string), as the miner has no label for it
MINER_LABEL = {'ST3:access_road_off_added': 'DQ1:off_street_reference',
               'ST3:dependent_or_estate_name_added': 'string: PAF dependent thoroughfare written'}


def toks(s):
    return re.findall(r'[A-Z0-9]+', (s or '').upper())


def find_seq(tk, seq, start=0):
    if not seq:
        return -1
    for i in range(len(tk) - len(seq), start - 1, -1):
        if tk[i:i + len(seq)] == seq:
            return i
    return -1


def classify_variant(v, s):
    if ''.join(v) == ''.join(s):
        return 'joined_or_split'
    if len(v) == len(s):
        if [F.ABBR.get(t, t) for t in s] == v:
            return 'abbreviated'
        if [F.EXPAND.get(t, t) for t in s] == v:
            return 'expanded'
    def subseq(a, b):
        it = iter(b); return all(x in it for x in a)
    if len(v) < len(s) and subseq(v, s):
        return 'words_dropped'
    if len(v) > len(s) and subseq(s, v):
        return 'words_added'
    return 'spelling'


def find_street(tk, st, rm_st, own_names):
    """(start, end, kind, text); kind exact | rm_thoroughfare | variant kind | None when the street is not found."""
    i = find_seq(tk, st)
    if i >= 0:
        return i, i + len(st), 'exact', None
    if rm_st and rm_st != st:
        i = find_seq(tk, rm_st)
        if i >= 0:
            return i, i + len(rm_st), 'rm_thoroughfare', ' '.join(rm_st)
    target = ' '.join(st); best = (0, None)
    if len(target) < 6:
        return None, None, None, None
    for L in (len(st) - 1, len(st), len(st) + 1):
        if L < 1:
            continue
        for j in range(len(tk) - L, -1, -1):
            win = tk[j:j + L]
            if win in own_names or any(t.isdigit() for t in win):
                continue
            sc = 100 if ''.join(win) == ''.join(st) else fuzz.ratio(' '.join(win), target)
            if sc > best[0]:
                best = (sc, (j, j + L))
    if best[0] >= 85:
        j, k = best[1]
        return j, k, classify_variant(tk[j:k], st), ' '.join(tk[j:k])
    return None, None, None, None


def load_council(council, components, pairs, train_uprns):
    con = duckdb.connect()
    con.execute(f"create table comp as select '{council}' council, * from read_csv('{components}', all_varchar=true)")
    v0.build_context(con)
    q = """select c.uprn, x.dwelling_type, x.rural, c.subname, c.name, c.number, c.streetname, c.locality, c.townname, c.postcode,
                  c.usrn, c.organisationname, c.rm_udprn, c.rm_subbuildingname, c.rm_buildingname, c.rm_buildingnumber,
                  c.rm_thoroughfare, c.rm_dependentthoroughfare, c.rm_dependentlocality, c.rm_posttown, c.rm_organisationname
           from comp c join ctx x on x.council=c.council and x.uprn=c.uprn"""
    cols = [d[0] for d in con.execute(q + ' limit 0').description]
    meta = {}
    for t in con.execute(q).fetchall():
        r = dict(zip(cols, t))
        dw = toks(r['subname']) + toks(r['name']) + toks(r['number'])
        rmw = toks(r['rm_subbuildingname']) + toks(r['rm_buildingname']) + toks(r['rm_buildingnumber'])
        meta[r['uprn']] = dict(
            stratum=f"{r['dwelling_type']}|{'rural' if r['rural'] else 'urban'}", usrn=r['usrn'], street=r['streetname'],
            loc=r['locality'], town=r['townname'], dloc=r['rm_dependentlocality'], ptown=r['rm_posttown'],
            rm_street=r['rm_thoroughfare'], dstreet=r['rm_dependentthoroughfare'], sector=(r['postcode'] or '')[:-2].strip(),
            sub=(r['subname'] or '').upper(), name=(r['name'] or '').upper(),
            rm_differs=bool(r['rm_udprn']) and dw != rmw, has_rm=bool(r['rm_udprn']),
            names=[x for x in (toks(r['name']), toks(r['subname']), toks(r['organisationname']), toks(r['rm_buildingname']),
                               toks(r['rm_subbuildingname']), toks(r['rm_organisationname'])) if x])
    streets = {' '.join(toks(m['street'])) for m in meta.values() if m['street']}
    recs = con.execute(f"select record_id, label_uprn, recorded_address, nearest_canonical, coalesce(labels_vs_ngd,'')||'|'||coalesce(format_flags,''), postcode_label "
                       f"from read_csv('{pairs}', all_varchar=true)").fetchall()
    if train_uprns is not None:
        recs = [r for r in recs if r[1] in train_uprns]
    return meta, streets, recs


def strings_style(clean):
    """v0 string-level shares, SY1 detection and postcode format, with the extended county list."""
    n = 0; f = Counter(); lengths = Counter(); trunc = 0; pc_n = pc_bad = 0; county = Counter(); trunc_ids = set()
    with open(clean, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            s = r['recorded_address_raw']; n += 1; lengths[len(s)] += 1
            letters = [ch for ch in s if ch.isalpha()]
            f['upper'] += bool(letters) and all(ch.isupper() for ch in letters)
            f['has_comma'] += ',' in s
            f['comma_after_leading_number'] += bool(re.match(r'^\s*\d+[A-Za-z]?,', s)) or bool(re.search(r',\s*\d+[A-Za-z]?,', s))
            f['double_comma_or_empty_field'] += bool(re.search(r',\s*,', s))
            m = COUNTY_RE.search(s.upper())
            f['county_word'] += bool(m)
            if m: county[m.group(1)] += 1
            f['brackets'] += '(' in s
            f['leading_zero_unit'] += bool(re.search(r'\b0\d+\b', s))
            if 'systemic_truncation' in (r.get('clean_tags') or ''):
                trunc += 1; trunc_ids.add(r['record_id'])
            pc = (r.get('recorded_postcode') or '').strip()
            if pc:
                pc_n += 1; pc_bad += not v0.PC_RE.match(pc.upper())
    mx = max(lengths); spike = lengths[mx] / max(1, lengths.get(mx - 1, 0))
    cap = mx if spike >= 1.5 and lengths[mx] / n >= 0.005 else None
    cw = sum(county.values())
    return dict(records=n, shares={k: round(v / n, 5) for k, v in sorted(f.items())},
                length={'mean': round(sum(k * v for k, v in lengths.items()) / n, 1), 'max': mx,
                        'count_at_max_over_max_minus_1': round(spike, 2), 'share_at_max': round(lengths[mx] / n, 5)},
                systemic={'SY1': {'max_field_length': cap, 'applies_to': 'single_concatenated_field' if cap else None,
                                  'records_tagged': trunc, 'share_tagged': round(trunc / n, 5)}},
                postcode_recorded_share=round(pc_n / n, 5),
                postcode_format_nonstandard_share=round(pc_bad / pc_n, 5) if pc_n else None,
                county_words={k: round(v / cw, 4) for k, v in county.most_common()} if cw else {}), trunc_ids


def floor_style(clean):
    forms = Counter(); lev = defaultdict(Counter); br = n = 0
    with open(clean, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            s = r['recorded_address_raw']
            for m in FLOOR_RE.finditer(s):
                if not (m.group(2) or m.group(1).lower() in ('ground', 'grd', 'gnd', 'basement', 'bsmt')):
                    continue
                forms[re.sub(r'\s+', ' ', m.group(0).strip())] += 1
                form = re.sub(r'\s+', ' ', m.group(0).strip()).upper().rstrip('.')
                L = next((lv for rx, lv in FLOOR_LEVEL if re.match(rx, form)), 'other')
                lev[L][form] += 1; n += 1
                br += s[:m.start()].rstrip().endswith('(')
    tot = sum(forms.values()) or 1
    return ({'n': sum(forms.values()), 'forms': {k: round(v / tot, 4) for k, v in forms.most_common(25)}},
            {'n': n, 'bracketed_share': round(br / max(n, 1), 4),
             'by_level': {L: {'n': sum(v.values()), 'forms': {k: round(x / sum(v.values()), 4) for k, x in v.most_common(8)}}
                          for L, v in sorted(lev.items())}})


def fit_council(council, components, pairs, clean, train_uprns=None, lookup_fix=False):
    """Return (house_style block, lookups {file: rows}) for one council.
    lookup_fix: drop sub-unit text from the locality lookups, keep per-street texts seen at least twice, and write no
    per-sector table (the generator's miner-recognised sector localities did better in run 4)."""
    meta, streets, recs = load_council(council, components, pairs, train_uprns)
    strings, trunc_ids = strings_style(clean)
    names_by_usrn = defaultdict(set)
    for m in meta.values():
        for nm in m['names']:
            names_by_usrn[m['usrn']].add(tuple(nm))
    patt = defaultdict(Counter); patt3 = defaultdict(Counter); other_by_usrn = defaultdict(Counter); other_by_sector = defaultdict(Counter)
    other_kind = Counter(); moved = 0; n = nf = 0
    street_kind = Counter(); street_var = defaultdict(Counter); street_n = Counter(); rm_cnt = defaultdict(Counter)
    lab_n = Counter(); elig_n = Counter(); unit_words = Counter(); pc = Counter(); pc_excl = 0
    for rid, uprn, addr, nearest, labels, pclab in recs:
        m = meta.get(uprn)
        if m is None:
            continue
        n += 1
        labs = set((labels or '').split('|'))
        dst = toks(m['dstreet'])
        if dst and dst != toks(m['street']) and find_seq(toks(addr), dst) >= 0:
            labs.add(MINER_LABEL['ST3:dependent_or_estate_name_added'])
        # per-eligible style rates from the miner's own labels
        has_unit = bool(F.UNIT_RE.match(m['sub'])); has_floor = bool(F.FLOOR_RE.search(m['sub']))
        el = {'any': True, 'sub': bool(m['sub']), 'sub_and_name': bool(m['sub'] and m['name']), 'street': bool(m['street']),
              'dstreet': bool(m['dstreet']), 'sub_without_unit_word': bool(m['sub']) and not has_unit,
              'sub_without_floor': not has_floor}
        for lab, e in STYLE_LABELS.items():
            if el[e]:
                elig_n[lab] += 1; lab_n[lab] += MINER_LABEL.get(lab, lab) in labs
        if 'SU13:unit_word_added' in labs:
            for w in UNIT_WORD_RE.findall((addr or '').upper()):
                unit_words[w] += 1
        if rid in trunc_ids:
            pc_excl += 1
        elif pclab:
            pc[pclab] += 1
        if m['has_rm']:
            rm_cnt[(m['stratum'], 'differs' if m['rm_differs'] else 'same')]['rm' if nearest == 'rm' else 'ngd'] += 1
        tk = toks(addr); st = toks(m['street'])
        if not st:
            continue
        own = [list(x) for x in names_by_usrn.get(m['usrn'], ())]
        s0, s1, kind, text = find_street(tk, st, toks(m['rm_street']), own)
        street_kind[kind or 'not_found'] += 1; street_n[m['usrn']] += 1
        if kind not in (None, 'exact'):
            street_var[m['usrn']][(text, kind)] += 1
        if s0 is None:
            nf += 1
            continue
        tail = tk[s1:]
        cands = []
        for lab, val in (('ngd_locality', m['loc']), ('paf_dep_locality', m['dloc']), ('ngd_town', m['town']), ('paf_post_town', m['ptown'])):
            vv = toks(val)
            if vv and all(vv != x[1] for x in cands):
                cands.append((lab, vv))
        labels_ = [None] * len(tail)
        for lab, vv in sorted(cands, key=lambda x: -len(x[1])):
            j = find_seq(tail, vv)
            if j >= 0 and all(labels_[k] is None for k in range(j, j + len(vv))):
                for k in range(j, j + len(vv)): labels_[k] = lab
        for nm in sorted(names_by_usrn.get(m['usrn'], ()), key=len, reverse=True):
            j = find_seq(tail, list(nm))
            if j >= 0 and all(labels_[k] is None for k in range(j, j + len(nm))):
                for k in range(j, j + len(nm)): labels_[k] = 'moved_component'
                moved += 1
        end = len(tail)                       # county words only in the final run of the tail
        while end > 0 and labels_[end - 1] is None and COUNTY_TOKEN.match(tail[end - 1]):
            end -= 1
        for k, t in enumerate(tail):
            if labels_[k] is None and k >= end:
                labels_[k] = 'county'
            elif labels_[k] is None and re.search(r'\d', t):
                labels_[k] = 'moved_component'
        seq, other = [], []
        for k, lab in enumerate(labels_):
            lab = lab or 'other'
            if lab == 'moved_component':
                continue
            if lab == 'other':
                other.append(tail[k])
            if not seq or seq[-1] != lab:
                seq.append(lab)
        has_loc = 'yes' if toks(m['loc']) else 'no'
        teq = 'yes' if toks(m['town']) == toks(m['ptown']) else 'no'
        dl = 'yes' if toks(m['dloc']) and toks(m['dloc']) not in (toks(m['loc']), toks(m['town'])) else 'no'
        pk = '>'.join(seq) or '(nothing)'
        patt[f'ngd_locality={has_loc}|town_equals_post_town={teq}'][pk] += 1
        patt3[f'ngd_locality={has_loc}|town_equals_post_town={teq}|paf_dep_locality={dl}'][pk] += 1
        if other:
            txt = ' '.join(other)
            other_kind['another_street_name' if txt in streets else 'place_name'] += 1
            if m['usrn']: other_by_usrn[m['usrn']][txt] += 1
            if m['sector']: other_by_sector[m['sector']][txt] += 1

    def pat(d):
        out = {}
        for cond, cnt in d.items():
            tot = sum(cnt.values())
            out[cond] = {'n': tot, 'p': {k: round(v / tot, 4) for k, v in cnt.most_common(15)},
                         'p_rest': round(1 - sum(v for _, v in cnt.most_common(15)) / tot, 4)}
        return out
    if lookup_fix:
        for d in (other_by_usrn, other_by_sector):
            for key in list(d):
                d[key] = Counter({t: k for t, k in d[key].items() if not SUBUNIT_TEXT.search(t)})
                if not d[key]: del d[key]
        lk_usrn = [[council, u, t, k, round(k / sum(c.values()), 3)] for u, c in other_by_usrn.items() for t, k in c.most_common(3) if k >= 2]
        lk_sector = []
        other_by_usrn = {u: c for u, c in other_by_usrn.items() if any(k >= 2 for k in c.values())}
        other_by_sector = {}
    else:
        lk_usrn = [[council, u, t, k, round(k / sum(c.values()), 3)] for u, c in other_by_usrn.items() for t, k in c.most_common(3)]
        lk_sector = [[council, s, t, k, round(k / sum(c.values()), 3)] for s, c in other_by_sector.items() for t, k in c.most_common(8) if k >= SECTOR_MIN]
    lk_street = []
    for u, c in street_var.items():
        for (t, kind), k in c.most_common(2):
            if k >= 2 and kind != 'rm_thoroughfare':
                lk_street.append([council, u, t, kind, k, round(k / (street_n[u] + STREET_SHRINK), 3)])
    streets3 = [u for u, v in street_n.items() if v >= 3]
    var_streets = Counter(); within = []
    for u in streets3:
        sv = street_var.get(u)
        if sv:
            (t, kind), k = sv.most_common(1)[0]
            if k >= 2:
                var_streets[kind] += 1; within.append(k / street_n[u])
    tot_st = sum(street_kind.values()) or 1
    rm_by = {}
    for (s, diff), v in rm_cnt.items():
        rm_by.setdefault(diff, {})[s] = {'n': sum(v.values()), 'p_rm': round(v['rm'] / sum(v.values()), 4)}
    rm_all = Counter()
    for (s, diff), v in rm_cnt.items():
        if diff == 'differs': rm_all.update(v)
    floor_vocab, floor_level = floor_style(clean)
    ow = sum(other_kind.values()) or 1
    uw = sum(unit_words.values()) or 1
    pct = sum(pc.values())
    block = {
        'from_strings': strings,
        'style_rates_per_eligible': {lab: {'eligible': e, 'miner_label': MINER_LABEL.get(lab, lab), 'n_eligible': elig_n[lab],
                                           'rate': round(lab_n[lab] / elig_n[lab], 6) if elig_n[lab] else None}
                                     for lab, e in STYLE_LABELS.items()},
        'locality_choice': {'records_train': n, 'street_not_found_share': round(nf / max(n, 1), 4), 'names_after_street_excluded': moved,
                            'patterns': pat(patt), 'patterns_v2': pat(patt3),
                            'other_text_kind': {k: round(v / ow, 4) for k, v in other_kind.items()}},
        'locality_other_lookup': {'file': 'locality_other_by_usrn.csv.gz', 'streets': len(other_by_usrn), 'portable': False,
                                  'rows': 'up to 3 texts per street, share among that street\'s "other" texts'},
        'locality_other_by_sector': {'file': 'locality_other_by_sector.csv.gz', 'sectors': len({r[1] for r in lk_sector}), 'portable': False,
                                     'use': 'fallback when the street has no row: draw by share within the postcode sector'},
        'street_variants': {'records_with_street': tot_st, 'share_by_kind': {k: round(v / tot_st, 5) for k, v in street_kind.most_common()},
                            'streets_3plus_records': len(streets3),
                            'share_of_streets_with_variant_convention': {k: round(v / max(len(streets3), 1), 5) for k, v in var_streets.most_common()},
                            'within_street_share_given_convention': {'mean': round(float(np.mean(within)), 4) if within else None,
                                                                     'median': round(float(np.median(within)), 4) if within else None}},
        'street_variant_lookup': {'file': 'street_variant_by_usrn.csv.gz', 'streets': len({r[1] for r in lk_street}), 'portable': False,
                                  'use': f'per street: write variant_text on share_of_street_records of its records (k / (n + {STREET_SHRINK}))'},
        'paf_rendering': {'p_rm_given_dwelling_differs': round(rm_all['rm'] / max(sum(rm_all.values()), 1), 4),
                          'n_dwelling_differs': sum(rm_all.values()), 'by_stratum': rm_by},
        'unit_word_added_vocabulary': {k: round(v / uw, 4) for k, v in unit_words.most_common(10)},
        'floor_vocabulary': floor_vocab,
        'floor_by_level': floor_level,
        'postcode': {'n': pct, 'excluded_truncated': pc_excl, 'p': {k: round(v / pct, 6) for k, v in pc.most_common()}} if pct else None,
    }
    return block, {'locality_other_by_usrn.csv.gz': (['council', 'usrn', 'other_text', 'n', 'share'], lk_usrn),
                   'locality_other_by_sector.csv.gz': (['council', 'sector', 'other_text', 'n', 'share'], lk_sector),
                   'street_variant_by_usrn.csv.gz': (['council', 'usrn', 'variant_text', 'kind', 'n', 'share_of_street_records'], lk_street)}


def write_lookups(out_dir, lookups, append=False):
    for fname, (header, rows) in lookups.items():
        p = out_dir / fname
        new = not (append and p.exists())
        with gzip.open(p, 'wt' if new else 'at', newline='') as fh:
            w = csv.writer(fh)
            if new: w.writerow(header)
            w.writerows(rows)


def read_train(path, council):
    out = set()
    with gzip.open(path, 'rt', newline='') as fh:
        for r in csv.DictReader(fh):
            if r['council'] == council and r['split'] == 'train':
                out.add(r['uprn'])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--council', required=True)
    ap.add_argument('--pairs', required=True, type=Path)
    ap.add_argument('--components', required=True, type=Path)
    ap.add_argument('--clean', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--profile', type=Path, help='frozen profile.json; if it holds this council, compare the blocks')
    ap.add_argument('--train-uprns', type=Path, help='split file (council, uprn, split): fit on split=train only')
    ap.add_argument('--lookup-fix', action='store_true', help='next-version locality lookups (see fit_council); off reproduces v3e')
    a = ap.parse_args()
    if a.output.exists() and any(a.output.iterdir()):
        sys.exit('output directory is not empty')
    a.output.mkdir(parents=True, exist_ok=True)
    train = read_train(a.train_uprns, a.council) if a.train_uprns else None
    block, lookups = fit_council(a.council, a.components, a.pairs, a.clean, train, lookup_fix=a.lookup_fix)
    (a.output / 'house_style.json').write_text(json.dumps({'council': a.council, 'house_style': block}, indent=1))
    write_lookups(a.output, lookups)
    print('wrote', a.output)
    if a.profile:
        prof = json.loads(a.profile.read_text())
        ref = (prof.get('house_style') or {}).get(a.council)
        if ref is None:
            print('profile has no house-style block for', a.council, '(nothing to compare)')
        else:
            # style_edit_rates_taxonomy comes from the taxonomy's labelled rows, not from the council's strings: not refitted here
            ref = {k: v for k, v in ref.items() if k != 'style_edit_rates_taxonomy'}
            same = json.dumps(ref, sort_keys=True) == json.dumps(json.loads(json.dumps(block)), sort_keys=True)
            diff = [k for k in set(ref) | set(block) if json.dumps(ref.get(k), sort_keys=True) != json.dumps(json.loads(json.dumps(block)).get(k), sort_keys=True)]
            print('reproduces frozen block:', same, '' if same else f'differs in {sorted(diff)}')
            if not same:
                sys.exit(1)


if __name__ == '__main__':
    main()
