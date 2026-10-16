"""Fit the corruption profile v2: v1 plus the fixes from realism check run 2 (prototype_loop/README.md, run 2).

Design: ../DESIGN.md section 14. Changes from v1 (code/fit_profile_v1.py, kept unchanged and reused):
  * Eligibility flags follow the generator's rule preconditions (code/flags_v2.py, shared with the generator):
    a bundle is rated per record on which every member rule can fire, so requested bundles stop failing.
  * Background rows (the weighted 4,000-per-council sample) no longer feed street, locality and town text edits
    (ST2, TX1-TX3 on street/loc/town/dstreet) into core bundles. Those are now fitted on every paired record in
    two string layers: street variants (per council, per street) and locality choice.
  * Street variant layer: how often a council writes the street differently from NGD (joined/split, abbreviated,
    expanded, words dropped/added, PAF thoroughfare, spelling), as a per-street convention. Lookup per USRN is
    non-portable.
  * Locality choice: patterns also conditioned on whether PAF has a dependent locality; "other" place text
    excludes building, sub-unit and organisation names written after the street (the repeated building name
    bug) and keeps up to three texts per street.
  * PAF rendering: how often a council writes the dwelling as PAF (Royal Mail) has it where PAF and NGD differ.
  * Floor wording by floor level, with bracket share.
  * Realisation hints for subtypes whose name hides what the string shows (PN3:number_replaced = number written
    as a name).

Inputs as v1. Cornwall and Derby are never read.
Generalised copy (study_general/): councils and paths from councils.py via fit_profile_v1; see GENERALISATION.md.
Usage: python fit_profile_v2.py --study <study folder> --output <new empty dir>     (duckdb, PyYAML, numpy, rapidfuzz)
"""
import argparse, csv, gzip, json, math, re, sys
from collections import Counter, defaultdict
from pathlib import Path
import duckdb, numpy as np
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).parent))
import fit_profile as v0
import fit_profile_v1 as v1
import flags_v2 as F

COUNCILS = v1.COUNCILS
v1.FLAGS = F.FLAGS          # v1's attach_context / learn_requirements / satisfies use the module global
FLAGS = F.FLAGS
BG_TEXT_SLOTS = {'street', 'loc', 'town', 'dstreet'}
COMP_COLS = ['uprn', 'subname', 'name', 'number', 'number_type', 'streetname', 'locality', 'townname', 'parentuprn',
             'n_children', 'organisationname', 'name_is_generic', 'rm_dependentthoroughfare', 'usrn', 'rm_udprn',
             'rm_subbuildingname', 'rm_buildingname', 'rm_buildingnumber', 'rm_thoroughfare', 'rm_dependentlocality',
             'rm_posttown', 'rm_organisationname']
FLOOR_LEVEL = [(r'^(LOWER GROUND|BASEMENT|BSMT|LOWER)', '-1'), (r'^(UPPER GROUND|GROUND|GRD|GND)', '0'), (r'^(FIRST|1ST)', '1'),
               (r'^(SECOND|2ND)', '2'), (r'^(THIRD|3RD)', '3'), (r'^(FOURTH|4TH)', '4'), (r'^(FIFTH|5TH)', '5'),
               (r'^(TOP|UPPER|ATTIC)', 'top')]


def toks(s):
    return v1.norm_tokens(s)


# ---------------------------------------------------------------- context with v2 flags

def load_context(con, study):
    parts = [f"select '{c}' council, * from read_csv('{study / v1.REF[c]}/components.csv.gz', all_varchar=true)" for c in COUNCILS]
    con.execute('create table comp as ' + ' union all by name '.join(parts))
    v0.build_context(con)
    q = 'select c.council, x.dwelling_type, ' + ', '.join('c.' + k for k in COMP_COLS) + \
        ' from comp c join ctx x on x.council=c.council and x.uprn=c.uprn'
    cols = [d[0] for d in con.execute(q + ' limit 0').description]
    flag_rows, meta = [], {}
    for t in con.execute(q).fetchall():
        r = dict(zip(cols, t))
        fl = F.flags_of(r)
        flag_rows.append((r['council'], r['uprn']) + tuple(fl[f] for f in FLAGS))
        dw = toks(r['subname']) + toks(r['name']) + toks(r['number'])
        rmw = toks(r['rm_subbuildingname']) + toks(r['rm_buildingname']) + toks(r['rm_buildingnumber'])
        meta[(r['council'], r['uprn'])] = dict(
            usrn=r['usrn'], street=r['streetname'], loc=r['locality'], town=r['townname'], dloc=r['rm_dependentlocality'],
            ptown=r['rm_posttown'], rm_street=r['rm_thoroughfare'],
            rm_differs=bool(r['rm_udprn']) and dw != rmw, has_rm=bool(r['rm_udprn']),
            names=[x for x in (toks(r['name']), toks(r['subname']), toks(r['organisationname']), toks(r['rm_buildingname']),
                               toks(r['rm_subbuildingname']), toks(r['rm_organisationname'])) if x])
    con.execute('create table flags (council varchar, uprn varchar, ' + ', '.join(f'{f} boolean' for f in FLAGS) + ')')
    import pandas as pd
    con.register('flags_df', pd.DataFrame(flag_rows, columns=['council', 'uprn'] + FLAGS))
    con.execute('insert into flags select * from flags_df')
    return meta


def load_rows(study, style):
    """v1 rows, with street/locality/town text edits removed from background rows (moved to the string layers)."""
    rows = v1.load_rows(study, style)
    moved = Counter()
    for r in rows:
        if r['subset'] != 'background' or not r['bundle']:
            continue
        keep = []
        for s in r['bundle'].split('|'):
            m, _, st = s.partition(':')
            slot = st.rsplit('_', 1)[-1] if m in ('TX1', 'TX2', 'TX3') else None
            if m == 'ST2' or slot in BG_TEXT_SLOTS:
                moved[s] += r['w']
            else:
                keep.append(s)
        r['bundle'] = '|'.join(keep)
    return rows, moved


def requirements(train):
    learned = v1.learn_requirements(train)
    subs = {m for r in train if r['bundle'] for m in r['bundle'].split('|')}
    req, coverage = {}, {}
    for m in subs:
        # learn only on the v1 property flags; structural flags come from the rule (learning them picks up correlates)
        rq = {f: v for f, v in learned.get(m, {}).items() if f in F.BASE}
        ex = F.structural_requirement(m)
        rq.update(ex)
        req[m] = rq
        if ex:
            tot = ok = 0.0
            for r in train:
                if r['bundle'] and m in r['bundle'].split('|'):
                    tot += r['w']; ok += r['w'] * all(r['sig'][FLAGS.index(f)] == v for f, v in ex.items())
            coverage[m] = round(ok / tot, 3) if tot else None
    return req, coverage


# ---------------------------------------------------------------- model (v1 maths, vectorised)

class Model(v1.Model):
    def __init__(self, rows, councils, req, a, b):
        self.req = req
        rows = [r for r in rows if r['council'] in councils]
        cnt = Counter(r['bundle'] for r in rows if r['bundle'])
        self.vocab = {k for k, v in cnt.items() if v >= v1.BUNDLE_MIN_ROWS and v1.bundle_req(k, req) is not None}
        self.breq = {k: v1.bundle_req(k, req) for k in self.vocab}
        self.blist = sorted(self.vocab)
        R = np.full((len(self.blist), len(FLAGS)), -1, dtype=np.int8)
        for i, k in enumerate(self.blist):
            for f, v in self.breq[k].items():
                R[i, FLAGS.index(f)] = int(v)
        self.R = R
        mass = Counter(); bm = Counter(); tail = Counter(); comp = Counter(); size = Counter()
        self.unrealisable = Counter()
        for r in rows:
            mass[(r['council'], r['stratum'], r['sig'])] += r['w']
            if r['bundle'] in self.vocab:
                # rate among eligible records: a real row whose record fails the rule's precondition is not counted
                if v1.satisfies(r['sig'], self.breq[r['bundle']]):
                    bm[(r['council'], r['stratum'], r['bundle'])] += r['w']
                else:
                    self.unrealisable[r['bundle']] += r['w']
            elif r['bundle']:
                tail[(r['council'], r['stratum'])] += r['w']
                ms = r['bundle'].split('|'); size[len(ms)] += r['w']
                for m in ms: comp[m] += r['w']
        self.size = {k: v / sum(size.values()) for k, v in size.items()} if size else {1: 1.0}
        Z = sum(comp.values()) or 1
        self.comp = {m: v / Z for m, v in comp.items()}
        keys = list(mass)
        cs = sorted({(c, s) for c, s, _ in keys}); cs_i = {k: i for i, k in enumerate(cs)}
        strata = sorted({s for _, s in cs}); s_i = {s: i for i, s in enumerate(strata)}
        sig = np.array([k[2] for k in keys], dtype=np.int8)
        w = np.array([mass[k] for k in keys])
        ci = np.array([cs_i[(k[0], k[1])] for k in keys]); si = np.array([s_i[k[1]] for k in keys])
        # eligible mass per bundle: (B x cells) via requirement matching
        elig = np.zeros((len(self.blist), len(cs))); elig_s = np.zeros((len(self.blist), len(strata))); elig_g = np.zeros(len(self.blist))
        for i in range(len(self.blist)):
            req_i = R[i]; on = req_i >= 0
            ok = (sig[:, on] == req_i[on]).all(1) if on.any() else np.ones(len(keys), bool)
            ww = w * ok
            elig[i] = np.bincount(ci, ww, len(cs)); elig_s[i] = np.bincount(si, ww, len(strata)); elig_g[i] = ww.sum()
        bm_s = Counter(); bm_g = Counter()
        for (c, s, k), x in bm.items():
            bm_s[(s, k)] += x; bm_g[k] += x
        self.rg, self.rs, self.rcs = {}, defaultdict(dict), defaultdict(dict)
        for i, k in enumerate(self.blist):
            self.rg[k] = bm_g[k] / elig_g[i] if elig_g[i] else 0.0
            for s in strata:
                self.rs[s][k] = (bm_s[(s, k)] + b * self.rg[k]) / (elig_s[i, s_i[s]] + b)
            for (c, s) in cs:
                self.rcs[(c, s)][k] = (bm[(c, s, k)] + a * self.rs[s][k]) / (elig[i, cs_i[(c, s)]] + a)
        tot_cs = np.bincount(ci, w, len(cs)); tot_s = np.bincount(si, w, len(strata))
        tg = sum(tail.values()) / w.sum()
        tail_s = Counter()
        for (c, s), x in tail.items(): tail_s[s] += x
        self.tail_g = tg
        self.tail_s = {s: (tail_s[s] + b * tg) / (tot_s[s_i[s]] + b) for s in strata}
        self.tail_cs = {(c, s): (tail[(c, s)] + a * self.tail_s[s]) / (tot_cs[cs_i[(c, s)]] + a) for (c, s) in cs}
        self._cache = {}

    def rates(self, council, stratum, sig, use_council):
        key = (council if use_council else None, stratum, sig)
        if key not in self._cache:
            src = self.rcs.get((council, stratum)) if use_council and (council, stratum) in self.rcs else self.rs.get(stratum, self.rg)
            sv = np.array(sig, dtype=np.int8)
            ok = ((self.R < 0) | (self.R == sv)).all(1)
            d = {k: src[k] for k, o in zip(self.blist, ok) if o and k in src}
            t = (self.tail_cs.get((council, stratum)) if use_council and (council, stratum) in self.tail_cs else self.tail_s.get(stratum, self.tail_g))
            tot = sum(d.values()) + t
            if tot > 0.95:
                f = 0.95 / tot; d = {k: v * f for k, v in d.items()}; t *= f; tot = 0.95
            self._cache[key] = (d, t, 1 - tot)
        return self._cache[key]


# ---------------------------------------------------------------- string layers on every paired record

def classify_variant(v, s):
    if ''.join(v) == ''.join(s):
        return 'joined_or_split'
    if len(v) == len(s):
        if [F.ABBR.get(t, t) for t in s] == v or [F.ABBR.get(t, t) for t in v] == [F.ABBR.get(t, t) for t in s] and any(t in F.EXPAND for t in v):
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
    """Return (start, end, kind, text). kind: exact | rm_thoroughfare | <variant kind> | None (not found)."""
    i = v1.find_seq(tk, st)
    if i >= 0:
        return i, i + len(st), 'exact', None
    if rm_st and rm_st != st:
        i = v1.find_seq(tk, rm_st)
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
            sc = fuzz.ratio(' '.join(win), target)
            if ''.join(win) == ''.join(st):
                sc = 100
            if sc > best[0]:
                best = (sc, (j, j + L))
    if best[0] >= 85:
        j, k = best[1]
        return j, k, classify_variant(tk[j:k], st), ' '.join(tk[j:k])
    return None, None, None, None


def string_layers(con, study, meta, split_of, stratum_of, out_dir):
    patt = defaultdict(lambda: defaultdict(Counter)); patt3 = defaultdict(lambda: defaultdict(Counter))
    other_by_usrn = defaultdict(Counter); moved_names = Counter(); n = Counter(); nf = Counter()
    street_kind = defaultdict(Counter); street_var = defaultdict(Counter); street_n = defaultdict(Counter)
    rm_cnt = defaultdict(Counter)
    names_by_usrn = defaultdict(set)
    for (c, u), m in meta.items():
        for nm in m['names']:
            names_by_usrn[(c, m['usrn'])].add(tuple(nm))
    for c in COUNCILS:
        for rid, uprn, addr, nearest in con.execute(
                f"select record_id, label_uprn, recorded_address, nearest_canonical from read_csv('{study / v1.PAIRS[c]}', all_varchar=true)").fetchall():
            m = meta.get((c, uprn))
            if m is None or split_of.get((c, uprn)) != 'train':
                continue
            n[c] += 1
            stratum = stratum_of[(c, uprn)]
            # PAF rendering
            if m['has_rm']:
                rm_cnt[(c, stratum, 'differs' if m['rm_differs'] else 'same')]['rm' if nearest == 'rm' else 'ngd'] += 1
            tk = toks(addr); st = toks(m['street'])
            if not st:
                continue
            own = [list(x) for x in names_by_usrn.get((c, m['usrn']), ())]
            s0, s1, kind, text = find_street(tk, st, toks(m['rm_street']), own)
            street_kind[c][kind or 'not_found'] += 1
            street_n[(c, m['usrn'])]['__n__'] += 1
            if kind not in (None, 'exact'):
                street_var[(c, m['usrn'])][(text, kind)] += 1
            if s0 is None:
                nf[c] += 1
                continue
            tail = tk[s1:]
            cands = []
            for lab, val in (('ngd_locality', m['loc']), ('paf_dep_locality', m['dloc']), ('ngd_town', m['town']), ('paf_post_town', m['ptown'])):
                vv = toks(val)
                if vv and all(vv != x[1] for x in cands):
                    cands.append((lab, vv))
            labels = [None] * len(tail)
            for lab, vv in sorted(cands, key=lambda x: -len(x[1])):
                j = v1.find_seq(tail, vv)
                if j >= 0 and all(labels[k] is None for k in range(j, j + len(vv))):
                    for k in range(j, j + len(vv)): labels[k] = lab
            # building / sub-unit / organisation names on this street written after it: word order, not locality
            for nm in sorted(names_by_usrn.get((c, m['usrn']), ()), key=len, reverse=True):
                j = v1.find_seq(tail, list(nm))
                if j >= 0 and all(labels[k] is None for k in range(j, j + len(nm))):
                    for k in range(j, j + len(nm)): labels[k] = 'moved_component'
                    moved_names[c] += 1
            for k, t in enumerate(tail):
                if labels[k] is None and (v1.COUNTY.match(t)):
                    labels[k] = 'county'
                elif labels[k] is None and re.search(r'\d', t):
                    labels[k] = 'moved_component'
            seq, other = [], []
            for k, lab in enumerate(labels):
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
            patt[c][f'ngd_locality={has_loc}|town_equals_post_town={teq}'][pk] += 1
            patt3[c][f'ngd_locality={has_loc}|town_equals_post_town={teq}|paf_dep_locality={dl}'][pk] += 1
            if other and m['usrn']:
                other_by_usrn[(c, m['usrn'])][' '.join(other)] += 1

    def pat(d):
        out = {}
        for cond, cnt in d.items():
            tot = sum(cnt.values())
            out[cond] = {'n': tot, 'p': {k: round(v / tot, 4) for k, v in cnt.most_common(15)},
                         'p_rest': round(1 - sum(v for _, v in cnt.most_common(15)) / tot, 4)}
        return out
    loc = {c: {'records_train': n[c], 'street_not_found_share': round(nf[c] / max(n[c], 1), 4),
               'names_after_street_excluded': moved_names[c], 'patterns': pat(patt[c]), 'patterns_v2': pat(patt3[c])} for c in COUNCILS}
    kept_loc = 0
    with gzip.open(out_dir / 'locality_other_by_usrn.csv.gz', 'wt', newline='') as fh:
        w = csv.writer(fh); w.writerow(['council', 'usrn', 'other_text', 'n', 'share'])
        for (c, usrn), cnt in other_by_usrn.items():
            tot = sum(cnt.values()); wrote = False
            for txt, k in cnt.most_common(3):
                if k >= 2:
                    w.writerow([c, usrn, txt, k, round(k / tot, 3)]); wrote = True
            kept_loc += wrote

    # street variants: per council shares, street-level convention, and the per-street lookup
    street = {}
    for c in COUNCILS:
        tot = sum(street_kind[c].values())
        streets = [(k, v) for k, v in street_n.items() if k[0] == c and v['__n__'] >= 3]
        var_streets = Counter(); within = []
        for (cc, usrn), v in streets:
            sv = street_var.get((cc, usrn))
            if not sv:
                continue
            (txt, kind), k = sv.most_common(1)[0]
            if k >= 2:
                var_streets[kind] += 1; within.append(k / v['__n__'])
        street[c] = {'records_with_street': tot,
                     'share_by_kind': {k: round(v / tot, 5) for k, v in street_kind[c].most_common()},
                     'streets_3plus_records': len(streets),
                     'share_of_streets_with_variant_convention': {k: round(v / max(len(streets), 1), 5) for k, v in var_streets.most_common()},
                     'within_street_share_given_convention': {'mean': round(float(np.mean(within)), 4) if within else None,
                                                              'median': round(float(np.median(within)), 4) if within else None}}
    kept_st = 0
    with gzip.open(out_dir / 'street_variant_by_usrn.csv.gz', 'wt', newline='') as fh:
        w = csv.writer(fh); w.writerow(['council', 'usrn', 'variant_text', 'kind', 'n', 'share_of_street_records'])
        for (c, usrn), cnt in street_var.items():
            tot = street_n[(c, usrn)]['__n__']; wrote = False
            for (txt, kind), k in cnt.most_common(2):
                if k >= 2 and kind != 'rm_thoroughfare':
                    w.writerow([c, usrn, txt, kind, k, round(k / tot, 3)]); wrote = True
            kept_st += wrote
    rm = {}
    for c in COUNCILS:
        d = {}
        for (cc, s, diff), v in rm_cnt.items():
            if cc != c:
                continue
            d.setdefault(diff, {})[s] = {'n': sum(v.values()), 'p_rm': round(v['rm'] / sum(v.values()), 4)}
        allv = Counter(); [allv.update(v) for (cc, s, diff), v in rm_cnt.items() if cc == c and diff == 'differs']
        rm[c] = {'p_rm_given_dwelling_differs': round(allv['rm'] / max(sum(allv.values()), 1), 4),
                 'n_dwelling_differs': sum(allv.values()), 'by_stratum': d}
    return loc, kept_loc, street, kept_st, rm


def floor_by_level(study):
    out = {}
    pat = re.compile(v1.FLOOR_RE.pattern, re.I)
    for c in COUNCILS:
        lev = defaultdict(Counter); br = n = 0
        with open(study / v1.CLEAN[c], newline='', encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                s = r['recorded_address_raw']
                for m in pat.finditer(s):
                    if not (m.group(2) or m.group(1).lower() in ('ground', 'grd', 'gnd', 'basement', 'bsmt')):
                        continue
                    form = re.sub(r'\s+', ' ', m.group(0).strip()).upper().rstrip('.')
                    L = next((lv for rx, lv in FLOOR_LEVEL if re.match(rx, form)), 'other')
                    lev[L][form] += 1; n += 1
                    br += s[:m.start()].rstrip().endswith('(')
        out[c] = {'n': n, 'bracketed_share': round(br / max(n, 1), 4),
                  'by_level': {L: {'n': sum(v.values()), 'forms': {k: round(x / sum(v.values()), 4) for k, x in v.most_common(8)}}
                               for L, v in sorted(lev.items())}}
    return out


def realisation_hints(study):
    sh = Counter()
    with gzip.open(study / v1.TAX / 'rates' / 'edit_v2_labels.csv.gz', 'rt', newline='') as fh:
        for e in csv.DictReader(fh):
            if e['v2_sub'] == 'PN3:number_replaced':
                parts = (e['signature'] or '').split('|')
                ins = parts[4] if len(parts) > 4 else ''
                sh['by_words' if re.search(r'[A-Z]{2,}|\bW\b', ins) else ('by_number' if re.search(r'\d|\bN\b', ins) else 'unknown')] += float(e['w'])
    t = sum(sh.values())
    return {'PN3:number_replaced': {'shares': {k: round(v / t, 3) for k, v in sh.items()},
                                    'note': 'Mostly the house number written as a name ("THE COTTAGE EXAMPLE ROAD" for "1A EXAMPLE ROAD"; a made-up illustration). '
                                            'Realise as: number dropped and a name added (real name if the record has one, else generic). '
                                            'The miner labels these PN4:number_dropped.'}}


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--study', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    a = ap.parse_args()
    if a.output.exists() and any(a.output.iterdir()):
        sys.exit('output directory is not empty')
    a.output.mkdir(parents=True, exist_ok=True)
    tax_version, tax_ids, STYLE, PER_BUILDING = v1.load_taxonomy(a.study)
    con = duckdb.connect()
    meta = load_context(con, a.study)
    print('context', len(meta), flush=True)
    raw_rows, moved = load_rows(a.study, STYLE)
    rows, missing = v1.attach_context(con, raw_rows)
    print('rows with context', len(rows), 'missing', missing, flush=True)
    train = [r for r in rows if r['split'] == 'train']
    req, coverage = requirements(train)

    grid = [10, 100, 1000, 10000, 100000]
    tuning = []
    for b in grid:
        for held in COUNCILS:
            m = Model(train, [c for c in COUNCILS if c != held], req, 1, b)
            tuning.append(dict(level='loco', held_out=held, a='', b=b, intensity=1.0, **v1.loglik(m, rows, held, None, False)))
        print('b', b, flush=True)
    for held in COUNCILS:
        flat = [dict(r, stratum='all') for r in train]
        m = Model(flat, [c for c in COUNCILS if c != held], req, 1, 1e9)
        tuning.append(dict(level='loco_baseline_no_strata', held_out=held, a='', b='inf', intensity=1.0,
                           **v1.loglik(m, [dict(r, stratum='all') for r in rows if r['council'] == held], held, None, False)))
    score = lambda lv, key, val: sum(t['ll_per_record'] for t in tuning if t['level'] == lv and t[key] == val)
    best_b = max(grid, key=lambda b: score('loco', 'b', b))
    for aa in grid:
        m = Model(train, COUNCILS, req, aa, best_b)
        for c in COUNCILS:
            k = v1.intensity_of(m, train, c, True)
            tuning.append(dict(level='in_distribution', held_out=c, a=aa, b=best_b, intensity=round(k, 3), **v1.loglik(m, rows, c, 'test', True, k)))
    best_a = max(grid, key=lambda aa: score('in_distribution', 'a', aa))
    with open(a.output / 'tuning_heldout_loglik.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(tuning[0].keys())); w.writeheader(); w.writerows(tuning)
    print('best a', best_a, 'best b', best_b, flush=True)

    M = Model(train, COUNCILS, req, best_a, best_b)
    intensity = {c: round(v1.intensity_of(M, train, c, False), 3) for c in COUNCILS}
    intensity_cl = {c: round(v1.intensity_of(M, train, c, True), 3) for c in COUNCILS}

    eff_b = defaultdict(Counter); eff_m = defaultdict(Counter); elig_m = defaultdict(Counter); cls_s = defaultdict(Counter)
    edits_dist = defaultdict(Counter); bg_m = Counter()
    for r in train:
        if not r['bundle']:
            continue
        eff_b[r['bundle']][r['effect']] += r['w']
        cls_s[r['stratum']]['variation' if r['effect'] == 'preserve' else 'error'] += r['w']
        edits_dist[r['council']][min(len(r['bundle'].split('|')), 5)] += r['w']
        for m in r['bundle'].split('|'):
            eff_m[m][r['effect']] += r['w']
            if r['subset'] == 'background': bg_m[m] += r['w']
            for rel in ('to_parent', 'to_child', 'to_sibling', 'to_neighbour', 'to_same_complex'):
                if r['elig_' + rel]: elig_m[m][rel] += r['w']
    dist = lambda cn: {k: round(v / sum(cn.values()), 4) for k, v in sorted(cn.items(), key=lambda x: -x[1])}
    bundles = {}
    for k in sorted(M.vocab, key=lambda k: -M.rg[k]):
        bundles[k] = {'mechanisms': k.split('|'), 'requires': M.breq[k], 'rate_per_eligible_global': round(M.rg[k], 7),
                      'building_convention': any(x.split(':')[0] in PER_BUILDING for x in k.split('|'))
                                             and not any(x.split(':')[0] in v1.NEVER_CONVENTION for x in k.split('|')),
                      'effect': {'n_weighted': round(sum(eff_b[k].values()), 1), 'p': dist(eff_b[k])}}
    mechs = {}
    for m in sorted(eff_m, key=lambda m: -sum(eff_m[m].values())):
        cond = {}
        for rel in ('to_parent', 'to_child', 'to_sibling', 'to_neighbour', 'to_same_complex'):
            if elig_m[m][rel]:
                cond[rel] = {'eligible_weighted': round(elig_m[m][rel], 1),
                             'p_exact_given_eligible': round(eff_m[m]['exact:' + rel] / elig_m[m][rel], 4),
                             'p_drift_given_eligible': round(eff_m[m]['drift:' + rel] / elig_m[m][rel], 4)}
        tw = sum(eff_m[m].values())
        mechs[m] = {'requires': req.get(m, {}), 'structural_requirement': F.structural_requirement(m),
                    'share_of_real_rows_meeting_structural_requirement': coverage.get(m),
                    'touched_weighted': round(tw, 1), 'background_share': round(bg_m[m] / tw, 3) if tw else None,
                    'effect_unconditional': dist(eff_m[m]), 'effect_given_eligible': cond,
                    'per_building': m.split(':')[0] in PER_BUILDING, 'never_convention': m.split(':')[0] in v1.NEVER_CONVENTION}

    style_rates = defaultdict(Counter); style_n = Counter()
    for r in train:
        style_n[r['council']] += r['w']
        for s in r['style']:
            if not s.startswith('LO'):
                style_rates[r['council']][s] += r['w']
    clus = v1.clustering(con, a.study, {r['record_id']: r for r in rows})
    split_of = {}; stratum_of = {}
    for c, u, dt, rural, sp in con.execute('select x.council, x.uprn, x.dwelling_type, x.rural, s.split from ctx x join splitmap s using (council, split_key)').fetchall():
        split_of[(c, u)] = sp; stratum_of[(c, u)] = f"{dt}|{'rural' if rural else 'urban'}"
    print('string layers', flush=True)
    loc_model, loc_kept, street_model, st_kept, rm_model = string_layers(con, a.study, meta, split_of, stratum_of, a.output)
    lb = {mid: {'name': tax_ids[mid]['name'], 'fit_status': tax_ids[mid].get('fit_status'),
                'rates': {c: (tax_ids[mid].get('rates') or {}).get(c) for c in COUNCILS}} for mid in ('LB1', 'LB2', 'LB3', 'LB4') if mid in tax_ids}
    exact_single = Counter()
    for r in train:
        if r['bundle'] and '|' not in r['bundle'] and r['bundle'].split(':')[0] in ('PN7', 'PN8', 'SU1', 'PN2') and r['effect'].startswith('exact:'):
            exact_single[r['effect'][6:]] += r['w']
    n_train = sum(r['w'] for r in train)

    profile = {
        'schema_version': '2.0', 'profile_id': 'uprn_corruption_profile_v2_20261012', 'status': 'not_frozen',
        'supersedes': 'uprn_corruption_profile_v1_20261012',
        'taxonomy_version': tax_version, 'house_style_ids': sorted(STYLE), 'per_building_ids': sorted(PER_BUILDING),
        'never_convention_ids': sorted(v1.NEVER_CONVENTION),
        'fitted_on': {'councils': COUNCILS, 'rows': f'{v1.TAX}/rates/rows_v2.csv.gz (discrepant rows weight 1, background sample weighted)',
                      'string_layers': 'every paired record of the training split (not weighted)',
                      'reference': v1.REF, 'pairs': v1.PAIRS, 'split': f'train (80% of building keys, salt {v0.SPLIT_SALT})',
                      'truth_verified': False, 'rows_without_context': missing,
                      'note': 'Rates are discrepancies under the council label, not verified error rates.'},
        'strata': {'definition': 'dwelling_type x rural, as v0', 'eligibility_flags': FLAGS,
                   'flag_definitions': 'code/flags_v2.py flags_of(row): the generator must import it (or copy it exactly)',
                   'requirement_rule': f'learned as v1 (>= {v1.REQ_SHARE:.0%} of weighted rows, base <= {v1.REQ_MAX_BASE:.0%}), '
                                       'then overlaid with the structural requirement of the generator rule (flags_v2.structural_requirement)'},
        'flag_vocabulary': {'abbreviations': F.ABBR, 'unit_words_regex': F.UNIT_RE.pattern, 'floor_regex': F.FLOOR_RE.pattern,
                            'slot_column': F.SLOT_COLUMN},
        'smoothing': {'council_to_stratum_a': best_a, 'stratum_to_global_b': best_b, 'bundle_min_rows': v1.BUNDLE_MIN_ROWS},
        'core': {
            'rate_unit': 'per eligible record: P(record gets bundle B | stratum, council) among records satisfying B.requires',
            'unrealisable_real_rows': {'rule': 'real rows whose canonical record fails the bundle requirement are left out of the rate '
                                                '(the generator rule cannot produce them there); per subtype share in mechanisms[].share_of_real_rows_meeting_structural_requirement',
                                       'weighted_total': round(sum(M.unrealisable.values()), 1),
                                       'top_bundles': {k: round(v, 1) for k, v in M.unrealisable.most_common(25)}},
            'background_text_edits_removed': {'rule': 'background rows: ST2 and TX1-TX3 on street/loc/town/dstreet go to the string layers',
                                              'weighted_by_subtype': {k: round(v, 1) for k, v in moved.most_common()}},
            'bundles': bundles,
            'rates_by_stratum': {s: {k: round(v, 7) for k, v in sorted(d.items(), key=lambda x: -x[1]) if v >= 1e-6} for s, d in sorted(M.rs.items())},
            'rates_by_council_stratum': {f'{c}|{s}': {k: round(v, 7) for k, v in sorted(d.items(), key=lambda x: -x[1]) if v >= 1e-5}
                                         for (c, s), d in sorted(M.rcs.items())},
            'tail': {'rate_global': round(M.tail_g, 6), 'rate_by_stratum': {s: round(v, 6) for s, v in sorted(M.tail_s.items())},
                     'size_distribution': {str(k): round(v, 4) for k, v in sorted(M.size.items())},
                     'mechanism_marginal': {k: round(v, 5) for k, v in sorted(M.comp.items(), key=lambda x: -x[1])}},
            'intensity_multiplier': 1.0, 'intensity_decision': 'Jo, 12 Oct 2026: pooled 1.0 for unseen councils; development range as sensitivity',
            'council_intensity_observed': intensity, 'council_intensity_with_council_rates': intensity_cl,
            'share_of_touched_by_class_by_stratum': {s: dist(v) for s, v in sorted(cls_s.items())},
            'variation_multiplier': 1.0, 'error_multiplier': 1.0,
            'edits_per_touched_record': {c: dist(v) for c, v in edits_dist.items()},
            'mechanisms': mechs,
            'realisation_hints': realisation_hints(a.study),
        },
        'clustering': clus,
        'label_drift': {'taxonomy': lb, 'observed_exact_single_slip_weighted_train': dict(exact_single),
                        'rate_per_record_by_relation': {k: round(v / n_train, 7) for k, v in exact_single.items()},
                        'share_attributed_to_label_drift_lambda': 0.5, 'lambda_status': 'prior; not identifiable without the verified subset',
                        'relation_to_mechanism': {'to_neighbour': 'LB1', 'to_parent': 'LB2', 'to_sibling': 'LB3', 'to_other': 'LB4'}},
        'house_style': {
            'from_strings': {c: v0.house_style(a.study, c) for c in COUNCILS},
            'style_edit_rates': {c: {k: round(v / style_n[c], 6) for k, v in sorted(style_rates[c].items(), key=lambda x: -x[1])} for c in COUNCILS},
            'locality_choice': loc_model,
            'locality_other_lookup': {'file': 'locality_other_by_usrn.csv.gz', 'streets': loc_kept, 'portable': False,
                                      'rows': 'up to 3 texts per street, each seen >= 2 times; share is among that street\'s "other" texts'},
            'street_variants': street_model,
            'street_variant_lookup': {'file': 'street_variant_by_usrn.csv.gz', 'streets': st_kept, 'portable': False,
                                      'use': 'per street: write variant_text instead of the NGD street on share_of_street_records of its records'},
            'paf_rendering': rm_model,
            'floor_vocabulary': v1.floor_vocabulary(a.study),
            'floor_by_level': floor_by_level(a.study),
            'postcode': v1.postcode_model(con, a.study),
        },
        'keying': {'status': 'measured as TX3 (core, per component); street/locality spelling in the string layers'},
        'disclosure': 'Mechanism IDs, rates, flags and generic vocabulary only. Place-name and street-variant lookups are separate, non-portable files.',
    }
    (a.output / 'profile.json').write_text(json.dumps(profile, indent=1))
    for t in tuning:
        if (t['level'] == 'loco' and t['b'] == best_b) or t['level'].startswith('loco_base') or (t['level'] == 'in_distribution' and t['a'] == best_a):
            print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()})
    print('intensity', intensity, intensity_cl)
    print('moved from background', moved.most_common(12))
    print('coverage', sorted(coverage.items(), key=lambda x: (x[1] or 0))[:25])


if __name__ == '__main__':
    main()
