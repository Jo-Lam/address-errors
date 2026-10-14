"""Fit the corruption profile v1 on taxonomy v2 (one mechanism per edit), with Basingstoke in development.

Design: ../DESIGN.md (section 13 lists what changed from v0). Evaluation plan: ../EVALUATION_PLAN.md.

Changes from v0 (code/fit_profile.py, kept unchanged):
  * Mechanism IDs come from taxonomy/v2_20261012 (one ID per aligned edit). A record's bundle is the set of its
    core v2 subtypes; house-style IDs (LO, SU11, ST3, FM1, FM2) go to the house-style layer.
  * Street and text edits (ST2, ST4, ST5, TX1-TX3) are core, not style.
  * Bundles are rated per ELIGIBLE record: each mechanism subtype learns which recipient flags it requires
    (has sub-unit, suffix, range, name, number, parent, children, organisation, locality), and a bundle's rate is
    its count divided by the records that satisfy all its members' requirements. The generator then draws among
    applicable bundles at these rates, so no redraw is needed and rare-property bundles keep their real frequency.
  * House style gains a locality-choice model, floor-word vocabulary, and SU11 word-order rates.
  * Postcode errors are fitted on non-truncated rows only (Wigan, Basingstoke). SY1 stays a source setting.
  * Four development councils: Wigan, Bradford, Leeds, Basingstoke. Leave-one-council-out has four folds.

Inputs (read only): taxonomy/v2_20261012/{mechanisms.yaml, rates/rows_v2.csv.gz, rates/edit_v2_labels.csv.gz};
mined_error_pairs/v2_20261012/pairs_*.csv.gz and v3_basingstoke_20261012/pairs_basingstoke.csv.gz;
reference/ngd_20261001/{wigan,bradford,leeds} and reference/ngd_20261001_v2_new_councils/basingstoke (only);
council_data/clean_v1_20261012/<council>/clean_records.csv. Cornwall and Derby are never read.

Usage: python fit_profile_v1.py --study <study folder> --output <new empty dir>     (duckdb, PyYAML)
Generalised copy (study_general/): councils and paths from councils.py; see GENERALISATION.md.
"""
import argparse, csv, gzip, json, math, re, sys
from collections import Counter, defaultdict
from pathlib import Path
import duckdb, yaml

sys.path.insert(0, str(Path(__file__).parent))
import fit_profile as v0   # reuse: split_bucket, build_context, house_style, constants

import councils as CFG     # generalised copy: council list and paths from the council config (GENERALISATION.md)

COUNCILS = list(CFG.NAMES)      # study: ['wigan', 'bradford', 'leeds', 'basingstoke']
FORBIDDEN = CFG.FORBIDDEN
REF = dict(CFG.REF)             # study-relative paths, same strings as the study's REF / PAIRS for the default config
PAIRS = dict(CFG.PAIRS)
CLEAN = dict(CFG.CLEAN)
POSTCODE_COUNCILS = list(CFG.POSTCODE)   # study: ('wigan', 'basingstoke')
TAX = 'taxonomy/v2_20261012'
FLAGS = ['has_sao', 'has_suffix', 'has_range', 'has_name', 'has_number', 'has_parent', 'has_children', 'has_org', 'has_locality']
REQ_SHARE = 0.97      # a flag value present in >= 97% of a subtype's weighted rows becomes a requirement
REQ_MIN_ROWS = 10
REQ_MAX_BASE = 0.90   # ...and only if that value is not already near-universal in the population (else it restricts nothing)
BUNDLE_MIN_ROWS = 3
NEVER_CONVENTION = {'PN3', 'PN7', 'PN8', 'SU3', 'TX3'}   # per-record slips (v0 clustering + taxonomy)
COUNTY = re.compile(r'^(LANCASHIRE|LANCS|CHESHIRE|MERSEYSIDE|YORKSHIRE|YORKS|WEST|HANTS|HAMPSHIRE|BERKS|BERKSHIRE|GREATER|MANCHESTER|WILTS|WILTSHIRE|SURREY)$')
FLOOR_RE = re.compile(r'\b(lower ground|upper ground|ground|grd|gnd|basement|bsmt|first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|top|upper|lower|attic)'
                      r'(\s*(?:floor|flr|fl)\b\.?)?', re.I)


# ---------------------------------------------------------------- loading

def load_context(con, study):
    parts = [f"select '{c}' council, * from read_csv('{study / REF[c]}/components.csv.gz', all_varchar=true)" for c in COUNCILS]
    con.execute('create table comp as ' + ' union all by name '.join(parts))
    v0.build_context(con)
    con.execute("""create table flags as select council, uprn,
        coalesce(subname,'')<>'' has_sao, number_type='letter_suffix' has_suffix, number_type='range' has_range,
        coalesce(name,'')<>'' has_name, coalesce(number,'')<>'' has_number,
        coalesce(parentuprn,'')<>'' has_parent, coalesce(try_cast(n_children as int),0)>0 has_children,
        coalesce(organisationname,'')<>'' has_org, coalesce(locality,'')<>'' has_locality,
        locality, townname, streetname, usrn, rm_dependentlocality, rm_posttown from comp""")


def load_taxonomy(study):
    tax = yaml.safe_load((study / TAX / 'mechanisms.yaml').read_text())
    ids = {m['id']: m for m in tax['mechanisms']}
    style = {i for i, m in ids.items() if 'house style' in str(m.get('fit_status', '')).lower()} | {'FM1', 'FM2'}
    per_building = {i for i, m in ids.items() if m.get('sample_per_building')}
    return tax['version'], ids, style, per_building


def load_rows(study, style):
    """One dict per v2 row: council, record, weight, core subtypes (bundle), style subtypes, effect."""
    edits = defaultdict(list)
    with gzip.open(study / TAX / 'rates' / 'edit_v2_labels.csv.gz', 'rt', newline='') as fh:
        for e in csv.DictReader(fh):
            for sub in e['v2_sub'].split('|'):
                edits[e['record_id']].append(sub)
    rows = []
    with gzip.open(study / TAX / 'rates' / 'rows_v2.csv.gz', 'rt', newline='') as fh:
        for r in csv.DictReader(fh):
            assert r['council'] not in FORBIDDEN
            subs = edits.get(r['record_id'], [])
            core = sorted({s for s in subs if s.split(':')[0] not in style and not s.startswith('LB')})
            sty = sorted({s for s in subs if s.split(':')[0] in style})
            if r['collision'] == 'matches_other_only':
                eff = 'exact:' + (r['collision_relation'] or 'to_other')
            elif r['drift_relation']:
                eff = 'drift:' + r['drift_relation']
            else:
                eff = 'preserve'
            lb = any(s.startswith('LB') for s in subs)
            rows.append(dict(council=r['council'], record_id=r['record_id'], uprn=r['label_uprn'], w=float(r['w']),
                             subset=r['subset'], bundle='|'.join(core), style=sty, effect=eff, lb=lb,
                             n_edits=int(r['n_dwelling_edits'] or 0)))
    return rows


def attach_context(con, rows):
    q = """select x.council, x.uprn, x.dwelling_type, x.rural, x.elig_to_parent, x.elig_to_child, x.elig_to_sibling,
                  x.elig_to_neighbour, x.elig_to_same_complex, x.split_key, s.split, """ + ', '.join('f.' + f for f in FLAGS) + """
           from ctx x join splitmap s using (council, split_key) join flags f using (council, uprn)"""
    cols = [d[0] for d in con.execute(q + ' limit 0').description]
    want = {(r['council'], r['uprn']) for r in rows}
    ctx = {}
    for t in con.execute(q).fetchall():
        d = dict(zip(cols, t))
        if (d['council'], d['uprn']) in want:
            ctx[(d['council'], d['uprn'])] = d
    out, missing = [], Counter()
    for r in rows:
        c = ctx.get((r['council'], r['uprn']))
        if c is None:
            missing[r['council']] += 1
            continue
        r.update({k: v for k, v in c.items() if k not in ('council', 'uprn')})
        r['stratum'] = f"{c['dwelling_type']}|{'rural' if c['rural'] else 'urban'}"
        r['sig'] = tuple(bool(c[f]) for f in FLAGS)
        out.append(r)
    return out, dict(missing)


# ---------------------------------------------------------------- eligibility

def learn_requirements(rows):
    """For each core subtype, the flag values it (almost) always occurs with. Learned on training rows only."""
    tot = Counter(); n = Counter(); on = defaultdict(Counter)
    pop_w = sum(r['w'] for r in rows)
    pop_on = {f: sum(r['w'] * r['sig'][i] for r in rows) / pop_w for i, f in enumerate(FLAGS)}
    def informative(f, share):
        if share >= REQ_SHARE:
            return pop_on[f] <= REQ_MAX_BASE
        if share <= 1 - REQ_SHARE:
            return 1 - pop_on[f] <= REQ_MAX_BASE
        return False
    for r in rows:
        if not r['bundle']:
            continue
        for m in r['bundle'].split('|'):
            tot[m] += r['w']; n[m] += 1
            for f, v in zip(FLAGS, r['sig']):
                on[m][f] += r['w'] * v
    req = {}
    for m in tot:
        if n[m] < REQ_MIN_ROWS:
            # too few rows: borrow the requirements of the mechanism ID (all its subtypes pooled)
            continue
        req[m] = {f: (on[m][f] / tot[m] >= REQ_SHARE) for f in FLAGS if informative(f, on[m][f] / tot[m])}
    by_id = defaultdict(lambda: [Counter(), 0.0])
    for m in tot:
        mid = m.split(':')[0]
        by_id[mid][1] += tot[m]
        for f in FLAGS:
            by_id[mid][0][f] += on[m][f]
    for m in tot:
        if m not in req:
            on_id, t = by_id[m.split(':')[0]]
            req[m] = {f: on_id[f] / t >= REQ_SHARE for f in FLAGS if informative(f, on_id[f] / t)}
    return req


def bundle_req(bundle, req):
    out = {}
    for m in bundle.split('|'):
        for f, v in req.get(m, {}).items():
            if f in out and out[f] != v:
                return None      # contradictory: never applicable
            out[f] = v
    return out


def satisfies(sig, rq):
    return rq is not None and all(sig[FLAGS.index(f)] == v for f, v in rq.items())


# ---------------------------------------------------------------- model

class Model:
    """Bundle rates per eligible record, shrunk council x stratum -> stratum -> global, plus a tail rate."""

    def __init__(self, rows, councils, req, a, b):
        self.req = req
        rows = [r for r in rows if r['council'] in councils]
        cnt = Counter(r['bundle'] for r in rows if r['bundle'])
        self.vocab = {k for k, v in cnt.items() if v >= BUNDLE_MIN_ROWS and bundle_req(k, req) is not None}
        self.breq = {k: bundle_req(k, req) for k in self.vocab}
        # weighted record mass per (council, stratum, sig) and bundle mass per (council, stratum, bundle)
        mass = Counter(); bm = Counter(); tail = Counter(); comp = Counter(); size = Counter()
        for r in rows:
            mass[(r['council'], r['stratum'], r['sig'])] += r['w']
            if r['bundle'] in self.vocab:
                bm[(r['council'], r['stratum'], r['bundle'])] += r['w']
            elif r['bundle']:
                tail[(r['council'], r['stratum'])] += r['w']
                ms = r['bundle'].split('|'); size[len(ms)] += r['w']
                for m in ms: comp[m] += r['w']
        self.size = {k: v / sum(size.values()) for k, v in size.items()} if size else {1: 1.0}
        Z = sum(comp.values()) or 1
        self.comp = {m: v / Z for m, v in comp.items()}
        sigs_cs = defaultdict(Counter)
        for (c, s, g), w in mass.items():
            sigs_cs[(c, s)][g] += w
        def elig_mass(cells, rq):
            return sum(w for g, w in cells.items() if satisfies(g, rq))
        strata = {s for (_, s) in sigs_cs}
        sig_s = defaultdict(Counter); sig_g = Counter()
        for (c, s), cells in sigs_cs.items():
            sig_s[s].update(cells); sig_g.update(cells)
        # global and stratum rates per eligible record
        self.rg, self.rs, self.rcs = {}, defaultdict(dict), defaultdict(dict)
        bm_s = Counter(); bm_g = Counter()
        for (c, s, k), w in bm.items():
            bm_s[(s, k)] += w; bm_g[k] += w
        for k in self.vocab:
            rq = self.breq[k]
            eg = elig_mass(sig_g, rq)
            self.rg[k] = bm_g[k] / eg if eg else 0.0
            for s in strata:
                es = elig_mass(sig_s[s], rq)
                self.rs[s][k] = (bm_s[(s, k)] + b * self.rg[k]) / (es + b)
            for (c, s), cells in sigs_cs.items():
                ec = elig_mass(cells, rq)
                self.rcs[(c, s)][k] = (bm[(c, s, k)] + a * self.rs[s][k]) / (ec + a)
        tg = sum(tail.values()) / sum(sig_g.values())
        tail_s = Counter(); m_s = Counter()
        for (c, s), w in tail.items(): tail_s[s] += w
        for s in strata: m_s[s] = sum(sig_s[s].values())
        self.tail_g = tg
        self.tail_s = {s: (tail_s[s] + b * tg) / (m_s[s] + b) for s in strata}
        self.tail_cs = {(c, s): (tail[(c, s)] + a * self.tail_s[s]) / (sum(cells.values()) + a) for (c, s), cells in sigs_cs.items()}
        self._cache = {}

    def rates(self, council, stratum, sig, use_council):
        key = (council if use_council else None, stratum, sig)
        if key not in self._cache:
            src = self.rcs.get((council, stratum)) if use_council and (council, stratum) in self.rcs else self.rs.get(stratum, self.rg)
            d = {k: v for k, v in src.items() if satisfies(sig, self.breq[k])}
            t = (self.tail_cs.get((council, stratum)) if use_council and (council, stratum) in self.tail_cs else self.tail_s.get(stratum, self.tail_g))
            tot = sum(d.values()) + t
            if tot > 0.95:                       # keep a valid distribution
                f = 0.95 / tot; d = {k: v * f for k, v in d.items()}; t *= f; tot = 0.95
            self._cache[key] = (d, t, 1 - tot)
        return self._cache[key]

    def tail_prob(self, bundle):
        ms = bundle.split('|')
        p = self.size.get(len(ms), 0.001) * math.factorial(len(ms))
        for m in ms:
            p *= self.comp.get(m, 1e-5)
        return min(p, 1.0)


def intensity_of(model, rows, council, use_council):
    """Observed touched mass / expected touched mass on these rows: the council's recording intensity."""
    obs = exp = 0.0
    for r in rows:
        if r['council'] != council: continue
        d, t, p0 = model.rates(council, r['stratum'], r['sig'], use_council)
        exp += r['w'] * (1 - p0); obs += r['w'] * bool(r['bundle'])
    return obs / exp if exp else 1.0


def loglik(model, rows, council, split, use_council, mult=1.0):
    ll = n = 0.0; ll_b = nt = 0.0; pred = obs = 0.0; unseen = 0.0
    for r in rows:
        if r['council'] != council or (split and r['split'] != split):
            continue
        d, t, p0 = model.rates(council, r['stratum'], r['sig'], use_council)
        if mult != 1.0:
            f = min(mult, 0.95 / max(1 - p0, 1e-9))
            d = {k: v * f for k, v in d.items()}; t *= f; p0 = 1 - (1 - p0) * f
        w = r['w']; n += w; pred += w * (1 - p0); obs += w * bool(r['bundle'])
        if not r['bundle']:
            ll += w * math.log(p0)
            continue
        pt = 1 - p0
        pb = d.get(r['bundle'])
        if pb is None:
            pb = t * model.tail_prob(r['bundle']); unseen += w * (r['bundle'] not in model.vocab)
        pb = max(pb, 1e-9)
        ll += w * math.log(pb); ll_b += w * math.log(pb / pt); nt += w
    return dict(n_weighted=round(n), touched_weighted=round(nt), ll_per_record=ll / n, ll_bundle_given_touched=ll_b / max(nt, 1),
                predicted_touch_rate=pred / n, observed_touch_rate=obs / n, share_touched_outside_vocab=unseen / max(nt, 1))


# ---------------------------------------------------------------- clustering on full pairs

def clustering(con, study, rows_by_record):
    """Within-building concordance on every paired record of the training split (not the weighted sample):
    non-discrepant records count as untouched in the dwelling layer."""
    units = defaultdict(list)
    for c in COUNCILS:
        con.execute(f"create or replace temp table pp as select record_id, label_uprn uprn from read_csv('{study / PAIRS[c]}', all_varchar=true)")
        for rid, uprn, key, split in con.execute(f"""select pp.record_id, pp.uprn, x.split_key, s.split from pp
                join ctx x on x.council='{c}' and x.uprn=pp.uprn join splitmap s on s.council='{c}' and s.split_key=x.split_key""").fetchall():
            if split != 'train' or not key.startswith('root:'):
                continue
            r = rows_by_record.get(rid)
            b = r['bundle'] if r and r['subset'] == 'dwelling_diff' else ''
            units[(c, key)].append(b)
    units = {k: v for k, v in units.items() if len(v) >= 2}
    def conc(has):
        num = den = k_all = n_all = 0
        for v in units.values():
            k = sum(has(u) for u in v); n = len(v)
            num += k * (k - 1); den += k * (n - 1); k_all += k; n_all += n
        m = k_all / n_all; c = num / den if den else None
        return {'marginal': round(m, 5), 'given_other_unit_has_it': round(c, 4) if c is not None else None, 'units_with_it': k_all}
    out = {'buildings': len(units), 'units': sum(len(v) for v in units.values()), 'any_touch': conc(lambda u: bool(u))}
    num = den = 0
    for v in units.values():
        cc = Counter(u for u in v if u); n = len(v)
        num += sum(k * (k - 1) for k in cc.values()); den += sum(cc.values()) * (n - 1)
    out['same_bundle_given_other_unit_touched'] = round(num / den, 4) if den else None
    ids = Counter(m.split(':')[0] for v in units.values() for u in v if u for m in u.split('|'))
    out['by_mechanism'] = {m: conc(lambda u, m=m: bool(u) and any(x.split(':')[0] == m for x in u.split('|')))
                           for m, k in ids.most_common() if k >= 20}
    return out


# ---------------------------------------------------------------- house style additions

def norm_tokens(s):
    return re.findall(r'[A-Z0-9]+', (s or '').upper())


def find_seq(toks, seq, start=0):
    if not seq:
        return -1
    for i in range(len(toks) - len(seq), start - 1, -1):
        if toks[i:i + len(seq)] == seq:
            return i
    return -1


def locality_model(con, study, out_dir):
    """Which place names a council writes after the street, relative to the canonical candidates.
    Pattern = ordered labels among ngd_locality, paf_dep_locality, ngd_town, paf_post_town, county, other.
    Conditioned on what the canonical record offers (has NGD locality; NGD town equals PAF post town).
    'other' text is resolved per street (USRN) in a lookup that stays inside the study folder."""
    patt = defaultdict(lambda: defaultdict(Counter)); other_by_usrn = defaultdict(Counter); nf = Counter(); n = Counter()
    for c in COUNCILS:
        con.execute(f"create or replace temp table pp as select record_id, label_uprn uprn, recorded_address from read_csv('{study / PAIRS[c]}', all_varchar=true)")
        q = f"""select pp.recorded_address, f.streetname, f.locality, f.townname, f.rm_dependentlocality, f.rm_posttown, f.usrn, s.split
                from pp join flags f on f.council='{c}' and f.uprn=pp.uprn
                join ctx x on x.council='{c}' and x.uprn=pp.uprn join splitmap s on s.council='{c}' and s.split_key=x.split_key"""
        for addr, street, loc, town, dloc, ptown, usrn, split in con.execute(q).fetchall():
            if split != 'train':
                continue
            n[c] += 1
            toks = norm_tokens(addr); st = norm_tokens(street)
            i = find_seq(toks, st)
            if i < 0:
                nf[c] += 1
                continue
            tail = toks[i + len(st):]
            cands = []
            for lab, val in (('ngd_locality', loc), ('paf_dep_locality', dloc), ('ngd_town', town), ('paf_post_town', ptown)):
                v = norm_tokens(val)
                if v and all(v != x[1] for x in cands):
                    cands.append((lab, v))
            labels = [None] * len(tail)
            for lab, v in sorted(cands, key=lambda x: -len(x[1])):
                j = find_seq(tail, v)
                if j >= 0 and all(labels[k] is None for k in range(j, j + len(v))):
                    for k in range(j, j + len(v)): labels[k] = lab
            for k, t in enumerate(tail):
                if labels[k] is None and COUNTY.match(t):
                    labels[k] = 'county'
            seq, other = [], []
            for k, lab in enumerate(labels):
                lab = lab or 'other'
                if lab == 'other':
                    other.append(tail[k])
                if not seq or seq[-1] != lab:
                    seq.append(lab)
            cond = f"ngd_locality={'yes' if norm_tokens(loc) else 'no'}|town_equals_post_town={'yes' if norm_tokens(town) == norm_tokens(ptown) else 'no'}"
            patt[c][cond]['>'.join(seq) or '(nothing)'] += 1
            if other and usrn:
                other_by_usrn[(c, usrn)][' '.join(other)] += 1
    model = {}
    for c in patt:
        model[c] = {'records_train': n[c], 'street_not_found_share': round(nf[c] / n[c], 4), 'patterns': {}}
        for cond, cnt in patt[c].items():
            tot = sum(cnt.values())
            model[c]['patterns'][cond] = {'n': tot, 'p': {k: round(v / tot, 4) for k, v in cnt.most_common(12)},
                                          'p_rest': round(1 - sum(v for _, v in cnt.most_common(12)) / tot, 4)}
    with gzip.open(out_dir / 'locality_other_by_usrn.csv.gz', 'wt', newline='') as fh:
        w = csv.writer(fh); w.writerow(['council', 'usrn', 'other_text', 'n', 'share'])
        kept = 0
        for (c, usrn), cnt in other_by_usrn.items():
            txt, k = cnt.most_common(1)[0]; tot = sum(cnt.values())
            if k >= 3 and k / tot >= 0.6:
                w.writerow([c, usrn, txt, k, round(k / tot, 3)]); kept += 1
    return model, kept


def floor_vocabulary(study):
    out = {}
    for c in COUNCILS:
        cnt = Counter()
        with open(study / CLEAN[c], newline='', encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                for m in FLOOR_RE.finditer(r['recorded_address_raw']):
                    if m.group(2) or m.group(1).lower() in ('ground', 'grd', 'gnd', 'basement', 'bsmt'):
                        cnt[re.sub(r'\s+', ' ', m.group(0).strip())] += 1
        tot = sum(cnt.values())
        out[c] = {'n': tot, 'forms': {k: round(v / tot, 4) for k, v in cnt.most_common(25)}}
    return out


def postcode_model(con, study):
    """PC labels per council on non-truncated rows (SY1 rows excluded: their postcode loss is the cut, not keying)."""
    out = {}
    for c in POSTCODE_COUNCILS:
        tags = {}
        with open(study / CLEAN[c], newline='', encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                tags[r['record_id']] = 'systemic_truncation' in (r.get('clean_tags') or '')
        cnt = Counter(); excl = 0
        for rid, lab in con.execute(f"select record_id, postcode_label from read_csv('{study / PAIRS[c]}', all_varchar=true)").fetchall():
            if tags.get(rid):
                excl += 1; continue
            if lab: cnt[lab] += 1
        tot = sum(cnt.values())
        out[c] = {'n': tot, 'excluded_truncated': excl, 'p': {k: round(v / tot, 6) for k, v in cnt.most_common()}}
    return out


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--study', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    a = ap.parse_args()
    if a.output.exists() and any(a.output.iterdir()):
        sys.exit('output directory is not empty')
    a.output.mkdir(parents=True, exist_ok=True)
    tax_version, tax_ids, STYLE, PER_BUILDING = load_taxonomy(a.study)
    print('taxonomy', tax_version, 'style IDs', sorted(STYLE))
    con = duckdb.connect()
    load_context(con, a.study)
    rows, missing = attach_context(con, load_rows(a.study, STYLE))
    print('rows with context', len(rows), 'missing', missing)
    train = [r for r in rows if r['split'] == 'train']
    req = learn_requirements(train)

    # ---- tuning
    grid = [1, 10, 100, 1000, 10000, 100000]
    tuning = []
    for b in grid:
        for held in COUNCILS:
            m = Model([r for r in train], [c for c in COUNCILS if c != held], req, 1, b)
            tuning.append(dict(level='loco', held_out=held, a='', b=b, intensity=1.0, **loglik(m, rows, held, None, False)))
    for held in COUNCILS:   # baseline: one pooled stratum ('all') for everyone, eligibility kept
        flat = [dict(r, stratum='all') for r in train]
        m = Model(flat, [c for c in COUNCILS if c != held], req, 1, 1e9)
        tuning.append(dict(level='loco_baseline_no_strata', held_out=held, a='', b='inf', intensity=1.0,
                           **loglik(m, [dict(r, stratum='all') for r in rows if r['council'] == held], held, None, False)))
    def score(lv, key, val):
        return sum(t['ll_per_record'] for t in tuning if t['level'] == lv and t[key] == val)
    best_b = max(grid, key=lambda b: score('loco', 'b', b))
    for aa in grid:
        m = Model(train, COUNCILS, req, aa, best_b)
        for c in COUNCILS:
            # a development council is generated at its own observed intensity (measured on its training split)
            k = intensity_of(m, train, c, True)
            tuning.append(dict(level='in_distribution', held_out=c, a=aa, b=best_b, intensity=round(k, 3),
                               **loglik(m, rows, c, 'test', True, k)))
    best_a = max(grid, key=lambda aa: score('in_distribution', 'a', aa))
    with open(a.output / 'tuning_heldout_loglik.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(tuning[0].keys())); w.writeheader(); w.writerows(tuning)
    print('best a', best_a, 'best b', best_b)

    # ---- final fit
    M = Model(train, COUNCILS, req, best_a, best_b)
    intensity = {c: round(intensity_of(M, train, c, False), 3) for c in COUNCILS}
    intensity_council_level = {c: round(intensity_of(M, train, c, True), 3) for c in COUNCILS}

    eff_b = defaultdict(Counter); eff_m = defaultdict(Counter); elig_m = defaultdict(Counter); cls_s = defaultdict(Counter)
    edits_dist = defaultdict(Counter)
    for r in train:
        if not r['bundle']:
            continue
        eff_b[r['bundle']][r['effect']] += r['w']
        cls_s[r['stratum']]['variation' if r['effect'] == 'preserve' else 'error'] += r['w']
        edits_dist[r['council']][min(len(r['bundle'].split('|')), 5)] += r['w']
        for m in r['bundle'].split('|'):
            eff_m[m][r['effect']] += r['w']
            for rel in ('to_parent', 'to_child', 'to_sibling', 'to_neighbour', 'to_same_complex'):
                if r['elig_' + rel]: elig_m[m][rel] += r['w']
    def dist(cn):
        t = sum(cn.values()); return {k: round(v / t, 4) for k, v in sorted(cn.items(), key=lambda x: -x[1])}
    bundles = {}
    for k in sorted(M.vocab, key=lambda k: -M.rg[k]):
        bundles[k] = {'mechanisms': k.split('|'), 'requires': M.breq[k], 'rate_per_eligible_global': round(M.rg[k], 7),
                      'building_convention': any(x.split(':')[0] in PER_BUILDING for x in k.split('|'))
                                             and not any(x.split(':')[0] in NEVER_CONVENTION for x in k.split('|')),
                      'effect': {'n_weighted': round(sum(eff_b[k].values()), 1), 'p': dist(eff_b[k])}}
    mechs = {}
    for m in sorted(eff_m, key=lambda m: -sum(eff_m[m].values())):
        cond = {}
        for rel in ('to_parent', 'to_child', 'to_sibling', 'to_neighbour', 'to_same_complex'):
            if elig_m[m][rel]:
                cond[rel] = {'eligible_weighted': round(elig_m[m][rel], 1),
                             'p_exact_given_eligible': round(eff_m[m]['exact:' + rel] / elig_m[m][rel], 4),
                             'p_drift_given_eligible': round(eff_m[m]['drift:' + rel] / elig_m[m][rel], 4)}
        mechs[m] = {'requires': req.get(m, {}), 'touched_weighted': round(sum(eff_m[m].values()), 1),
                    'effect_unconditional': dist(eff_m[m]), 'effect_given_eligible': cond,
                    'per_building': m.split(':')[0] in PER_BUILDING, 'never_convention': m.split(':')[0] in NEVER_CONVENTION}

    style_rates = defaultdict(Counter); style_n = Counter()
    for r in train:
        style_n[r['council']] += r['w']
        for s in r['style']:
            if not s.startswith('LO'):
                style_rates[r['council']][s] += r['w']
    rows_by_record = {r['record_id']: r for r in rows}
    clus = clustering(con, a.study, rows_by_record)
    loc_model, loc_kept = locality_model(con, a.study, a.output)
    lb = {}
    for mid in ('LB1', 'LB2', 'LB3', 'LB4'):
        m = tax_ids.get(mid)
        if m:
            lb[mid] = {'name': m['name'], 'fit_status': m.get('fit_status'), 'rates': {c: (m.get('rates') or {}).get(c) for c in COUNCILS}}
    exact_single = Counter()
    for r in train:
        if r['bundle'] and '|' not in r['bundle'] and r['bundle'].split(':')[0] in ('PN7', 'PN8', 'SU1', 'PN2') and r['effect'].startswith('exact:'):
            exact_single[r['effect'][6:]] += r['w']
    n_train = sum(r['w'] for r in train)

    profile = {
        'schema_version': '1.0', 'profile_id': 'uprn_corruption_profile_v1_20261012', 'status': 'not_frozen',
        'taxonomy_version': tax_version, 'house_style_ids': sorted(STYLE), 'per_building_ids': sorted(PER_BUILDING),
        'never_convention_ids': sorted(NEVER_CONVENTION),
        'fitted_on': {'councils': COUNCILS, 'rows': f'{TAX}/rates/rows_v2.csv.gz (discrepant rows weight 1, background sample weighted)',
                      'reference': REF, 'pairs': PAIRS, 'split': f'train (80% of building keys, salt {v0.SPLIT_SALT})',
                      'epochs': {**{c: CFG.EPOCH[c] for c in COUNCILS}, 'os_ngd': '2026-10-01'},
                      'truth_verified': False, 'rows_without_context': missing,
                      'note': 'Rates are discrepancies under the council label, not verified error rates.'},
        'strata': {'definition': 'dwelling_type x rural, as v0', 'eligibility_flags': FLAGS,
                   'requirement_rule': f'a flag value seen in >= {REQ_SHARE:.0%} of a subtype\'s weighted rows (>= {REQ_MIN_ROWS} rows; else pooled over the mechanism ID), '
                                       f'and held by <= {REQ_MAX_BASE:.0%} of all records'},
        'smoothing': {'council_to_stratum_a': best_a, 'stratum_to_global_b': best_b, 'bundle_min_rows': BUNDLE_MIN_ROWS},
        'core': {
            'rate_unit': 'per eligible record: P(record gets bundle B | stratum, council) among records satisfying B.requires',
            'bundles': bundles,
            'rates_by_stratum': {s: {k: round(v, 7) for k, v in sorted(d.items(), key=lambda x: -x[1]) if v >= 1e-6} for s, d in sorted(M.rs.items())},
            'rates_by_council_stratum': {f'{c}|{s}': {k: round(v, 7) for k, v in sorted(d.items(), key=lambda x: -x[1]) if v >= 1e-5}
                                         for (c, s), d in sorted(M.rcs.items())},
            'tail': {'rate_global': round(M.tail_g, 6), 'rate_by_stratum': {s: round(v, 6) for s, v in sorted(M.tail_s.items())},
                     'size_distribution': {str(k): round(v, 4) for k, v in sorted(M.size.items())},
                     'mechanism_marginal': {k: round(v, 5) for k, v in sorted(M.comp.items(), key=lambda x: -x[1])}},
            'intensity_multiplier': 1.0, 'intensity_decision': 'Jo, 12 Oct 2026: pooled 1.0 for unseen councils; development range as sensitivity',
            'council_intensity_observed': intensity,
            'council_intensity_note': 'Relative to pooled stratum rates. For a development council generated with its own '
                                      'council-level rates, use council_intensity_with_council_rates instead.',
            'council_intensity_with_council_rates': intensity_council_level,
            'share_of_touched_by_class_by_stratum': {s: dist(v) for s, v in sorted(cls_s.items())},
            'variation_multiplier': 1.0, 'error_multiplier': 1.0,
            'edits_per_touched_record': {c: dist(v) for c, v in edits_dist.items()},
            'mechanisms': mechs,
        },
        'clustering': clus,
        'label_drift': {'taxonomy': lb, 'observed_exact_single_slip_weighted_train': dict(exact_single),
                        'rate_per_record_by_relation': {k: round(v / n_train, 7) for k, v in exact_single.items()},
                        'share_attributed_to_label_drift_lambda': 0.5,
                        'lambda_status': 'prior; not identifiable without the verified subset',
                        'relation_to_mechanism': {'to_neighbour': 'LB1', 'to_parent': 'LB2', 'to_sibling': 'LB3', 'to_other': 'LB4'}},
        'house_style': {
            'from_strings': {c: v0.house_style(a.study, c) for c in COUNCILS},
            'style_edit_rates': {c: {k: round(v / style_n[c], 6) for k, v in sorted(style_rates[c].items(), key=lambda x: -x[1])} for c in COUNCILS},
            'locality_choice': loc_model,
            'locality_other_lookup': {'file': 'locality_other_by_usrn.csv.gz', 'streets': loc_kept, 'portable': False},
            'floor_vocabulary': floor_vocabulary(a.study),
            'postcode': postcode_model(con, a.study),
        },
        'keying': {'status': 'measured as TX3 (core, per component)'},
        'disclosure': 'Mechanism IDs, rates, flags and generic floor/county vocabulary only. Place-name lookup is a separate, non-portable file.',
    }
    (a.output / 'profile.json').write_text(json.dumps(profile, indent=1))
    for t in tuning:
        if (t['level'] == 'loco' and t['b'] == best_b) or t['level'].startswith('loco_base') or (t['level'] == 'in_distribution' and t['a'] == best_a):
            print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()})
    print('intensity', intensity)


if __name__ == '__main__':
    main()
