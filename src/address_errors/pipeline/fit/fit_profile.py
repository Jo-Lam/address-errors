"""Fit a first-pass corruption profile (v0) from the mined error pairs.

Design: ../DESIGN.md. Evaluation plan: ../EVALUATION_PLAN.md.

Inputs (read only):
  mined_error_pairs/v2_20261012/pairs_<council>.csv.gz      council string vs canonical, labelled
  reference/ngd_20261001/<council>/components.csv.gz        NGD components and hierarchy
  council_data/clean_v1_20261012/<council>/clean_records.csv recorded strings (house style, SY1)
Development councils only: Wigan, Bradford, Leeds (pairs) and Basingstoke (strings only, no NGD order yet).
Cornwall and Derby are never read.

Usage: python fit_profile.py --study <study folder> --output <new empty dir>
Needs duckdb. UPRNs are kept as text throughout.
"""
import argparse, csv, hashlib, json, math, re, sys
from collections import Counter, defaultdict
from pathlib import Path
import duckdb, yaml

PAIR_COUNCILS = ['wigan', 'bradford', 'leeds']
STYLE_COUNCILS = ['wigan', 'bradford', 'leeds', 'basingstoke']
FORBIDDEN = {'cornwall', 'derby'}
TEST_PERCENT = 20          # in-distribution holdout share, by building key
SPLIT_SALT = 'uprn-profile-split-v1'
RURAL_MAX_POSTCODE_SIZE = 5  # matches the comparability note's rural proxy
BUNDLE_MIN_COUNT = 3       # pooled training count for a bundle to be kept explicitly
RELATIONS = ['to_parent', 'to_child', 'to_sibling', 'to_neighbour', 'to_same_complex', 'to_other']
TAXONOMY = 'taxonomy/mechanisms.yaml'
HOUSE_STYLE_IDS = set()  # filled from the taxonomy: mechanisms fitted as per-council house style, kept out of core bundles
COUNTY = r'\b(LANCASHIRE|LANCS|CHESHIRE|MERSEYSIDE|YORKSHIRE|YORKS|HANTS|HAMPSHIRE|BERKS|BERKSHIRE|GREATER MANCHESTER)\b'
PC_RE = re.compile(r'^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$')


def split_bucket(council, key):
    h = hashlib.sha256(f'{SPLIT_SALT}|{council}|{key}'.encode()).hexdigest()
    return int(h[:8], 16) % 100


def load(con, study):
    ref = study / 'reference' / 'ngd_20261001'
    pairs = study / 'mined_error_pairs' / 'v2_20261012'
    con.execute(f"""create table comp as select split_part(split_part(filename, 'ngd_20261001/', 2), '/', 1) council, *
        from read_csv('{ref}/*/components.csv.gz', all_varchar=true, filename=true)""")
    con.execute(f"""create table pairs as select * from read_csv('{pairs}/pairs_*.csv.gz', all_varchar=true)""")
    bad = con.execute("select distinct council from pairs").fetchall()
    assert not FORBIDDEN & {b[0] for b in bad}, 'external test councils found in pairs'


def build_context(con):
    """One row per UPRN per council: dwelling type, rural flag, eligibility for each drift relation, split key."""
    con.execute(f"""create table pcsize as select council, postcode, count(*) n from comp
        where feature_type='builtaddress' and postcode is not null group by all""")
    con.execute("""create table nb as
        select a.council, a.uprn,
               count(*) filter (where b.number_int is not null and b.number_int <> a.number_int) n_neigh,
               count(*) filter (where b.number_int = a.number_int and coalesce(b.number_suffix,'') <> coalesce(a.number_suffix,'')
                                 and coalesce(b.subname,'') = '') n_suffix_sib
        from comp a join comp b on a.council=b.council and a.usrn=b.usrn and a.uprn<>b.uprn
             and abs(try_cast(a.number_int as int) - try_cast(b.number_int as int)) <= 4
        where a.number_int is not null group by all""")
    con.execute("""create table rootsize as select council, rootuprn, count(*) n_root from comp where rootuprn is not null group by all""")
    con.execute(f"""create table ctx as select c.council, c.uprn,
        case when c.sao_type in ('room','bedsit') then 'room'
             when c.sao_type in ('floor_descriptor','position') then 'floor_flat'
             when c.sao_type = 'annex' then 'annex'
             when coalesce(c.subname,'')<>'' or coalesce(c.parentuprn,'')<>'' then 'flat'
             when coalesce(c.name,'')<>'' and coalesce(c.number,'')<>'' then 'named_number'
             when coalesce(c.name,'')<>'' then 'named_only'
             when coalesce(c.number,'')<>'' then 'numbered'
             else 'other' end dwelling_type,
        coalesce(p.n, 99) <= {RURAL_MAX_POSTCODE_SIZE} rural,
        c.number_type, c.name_is_generic='true' generic_name,
        coalesce(c.parentuprn,'')<>'' and c.parent_in_extract='true' elig_to_parent,
        coalesce(try_cast(c.n_children as int),0) > 0 elig_to_child,
        coalesce(try_cast(c.n_siblings as int),0) > 0 elig_to_sibling,
        coalesce(nb.n_neigh,0) + coalesce(nb.n_suffix_sib,0) > 0 elig_to_neighbour,
        coalesce(r.n_root,1) > coalesce(try_cast(c.n_siblings as int),0) + 2 elig_to_same_complex,
        case when coalesce(c.parentuprn,'')<>'' or coalesce(try_cast(c.n_children as int),0)>0 then 'root:'||c.rootuprn
             when coalesce(c.usrn,'')<>'' then 'usrn:'||c.usrn else 'uprn:'||c.uprn end split_key
        from comp c left join pcsize p on c.council=p.council and c.postcode=p.postcode
        left join nb on c.council=nb.council and c.uprn=nb.uprn
        left join rootsize r on c.council=r.council and c.rootuprn=r.rootuprn""")
    keys = con.execute("select distinct council, split_key from ctx").fetchall()
    con.execute("create table splitmap(council varchar, split_key varchar, split varchar)")
    con.executemany("insert into splitmap values (?,?,?)",
                    [(c, k, 'test' if split_bucket(c, k) < TEST_PERCENT else 'train') for c, k in keys])


def records(con):
    q = """select p.council, p.label_uprn, p.ngd_ftype, p.street_status_ngd, p.dwelling_diff, p.labels_nearest,
               p.collision, p.collision_relation, p.drift_relation, p.labels_vs_ngd, p.format_flags, p.postcode_label,
               x.dwelling_type, x.rural, x.number_type, x.generic_name,
               x.elig_to_parent, x.elig_to_child, x.elig_to_sibling, x.elig_to_neighbour, x.elig_to_same_complex, x.split_key, s.split
        from pairs p join ctx x on p.council=x.council and p.label_uprn=x.uprn
        join splitmap s on x.council=s.council and x.split_key=s.split_key"""
    cols = [d[0] for d in con.execute(q + ' limit 0').description]
    for row in con.execute(q).fetchall():
        yield dict(zip(cols, row))


def load_taxonomy(study):
    tax = yaml.safe_load((study / TAXONOMY).read_text())
    ids = {m['id']: m for m in tax['mechanisms']}
    for mid, m in ids.items():
        txt = f"{m.get('fit_status', '')} {m.get('detection', '')}".lower()
        if 'house style' in txt or 'council style parameter' in txt:
            HOUSE_STYLE_IDS.add(mid)
    return tax['version'], ids


def classify(r):
    """Returns (status, bundle, effect) for one paired record. House-style IDs are removed from core bundles."""
    if r['ngd_ftype'] != 'built':
        return 'lifecycle', None, None
    if r['street_status_ngd'] == 'not_found':
        return 'unparsed', None, None
    labels = sorted(l for l in (r['labels_nearest'] or '').split('|')
                    if l and not l.startswith('LC:') and l.split(':')[0] not in HOUSE_STYLE_IDS)
    if r['collision'] == 'matches_other_only':
        effect = 'exact:' + (r['collision_relation'] or 'to_other')
    elif r['drift_relation']:
        effect = 'drift:' + r['drift_relation']
    else:
        effect = 'preserve'
    if not labels and effect == 'preserve':
        return 'clean', None, None
    return 'touched', '|'.join(labels) if labels else 'UNLABELLED_STREET_OR_OTHER', effect


class Counts:
    def __init__(self):
        self.n = Counter()          # (council, stratum) -> records
        self.t = Counter()          # (council, stratum) -> touched
        self.b = defaultdict(Counter)  # (council, stratum) -> bundle counts
        self.eff_b = defaultdict(Counter)  # bundle -> effect counts (pooled)
        self.eff_m = defaultdict(Counter)  # mechanism:subtype -> effect counts
        self.elig_m = defaultdict(Counter)  # mechanism:subtype -> relation -> eligible touched rows
        self.status = defaultdict(Counter)  # council -> status counts
        self.ambig = Counter()       # council -> matches_label_and_other rows among clean
        self.eclass = defaultdict(Counter)  # stratum -> variation (preserve) / error (exact or drift) among touched


def tally(rows, split):
    C = Counts()
    for r in rows:
        if r['split'] != split:
            continue
        status, bundle, effect = classify(r)
        C.status[r['council']][status] += 1
        if status in ('lifecycle', 'unparsed'):
            continue
        s = stratum(r)
        C.n[(r['council'], s)] += 1
        if r['collision'] == 'matches_label_and_other':
            C.ambig[r['council']] += 1
        if status != 'touched':
            continue
        C.t[(r['council'], s)] += 1
        C.eclass[s]['variation' if effect == 'preserve' else 'error'] += 1
        C.b[(r['council'], s)][bundle] += 1
        C.eff_b[bundle][effect] += 1
        for m in bundle.split('|'):
            C.eff_m[m][effect] += 1
            for rel in RELATIONS[:-1]:
                if r['elig_' + rel]:
                    C.elig_m[m][rel] += 1
    return C


def stratum(r):
    return f"{r['dwelling_type']}|{'rural' if r['rural'] else 'urban'}"


# ---------- hierarchical smoothing ----------

def pooled(counter_by_cs, councils):
    out = defaultdict(Counter)
    for (c, s), v in counter_by_cs.items():
        if c in councils:
            out[s].update(v if isinstance(v, Counter) else Counter({'_': v}))
    return out


def touch_model(C, councils, a, b):
    """P(touched | council, stratum) with Beta shrinkage council->stratum->global."""
    n_s, t_s = Counter(), Counter()
    for (c, s), n in C.n.items():
        if c in councils:
            n_s[s] += n; t_s[s] += C.t[(c, s)]
    N, T = sum(n_s.values()), sum(t_s.values())
    pg = T / N
    ps = {s: (t_s[s] + b * pg) / (n_s[s] + b) for s in n_s}
    pcs = {(c, s): (C.t[(c, s)] + a * ps[s]) / (C.n[(c, s)] + a) for (c, s) in C.n if c in councils and s in ps}
    return pg, ps, pcs


def bundle_model(C, councils, a, b, esc=1.0):
    """P(bundle | touched, council, stratum): Dirichlet shrinkage with an escape mass for unseen bundles."""
    b_s = defaultdict(Counter); b_g = Counter()
    for (c, s), v in C.b.items():
        if c in councils:
            b_s[s].update(v); b_g.update(v)
    G = sum(b_g.values())
    vocab = {k for k, v in b_g.items() if v >= BUNDLE_MIN_COUNT}
    # mechanism marginal and size distribution for the composition (tail) model
    mech, size = Counter(), Counter()
    for k, v in b_g.items():
        ms = k.split('|'); size[len(ms)] += v
        for m in ms: mech[m] += v
    M = sum(mech.values()); S = sum(size.values())
    def comp_prob(k):
        ms = k.split('|')
        p = size.get(len(ms), 0.5) / (S + 1) * math.factorial(len(ms))
        for m in ms:
            p *= (mech.get(m, 0) + 0.5) / (M + 0.5 * (len(mech) + 1))
        return p
    tail_g = sum(v for k, v in b_g.items() if k not in vocab)
    pg = {k: b_g[k] / (G + esc) for k in vocab}
    pg['__tail__'] = (tail_g + esc) / (G + esc)
    def level(counts, prior, conc):
        n = sum(counts.values())
        out = {k: (counts.get(k, 0) + conc * prior[k]) / (n + conc) for k in vocab}
        out['__tail__'] = (sum(v for k, v in counts.items() if k not in vocab) + conc * prior['__tail__']) / (n + conc)
        return out
    ps = {s: level(b_s[s], pg, b) for s in b_s}
    pcs = {(c, s): level(C.b[(c, s)], ps[s], a) for (c, s) in C.b if c in councils}
    return vocab, pg, ps, pcs, comp_prob


def prob_bundle(dist, vocab, comp_prob, k):
    if k in vocab:
        return dist[k]
    return dist['__tail__'] * comp_prob(k)


def heldout_loglik(rows, train_C, councils_fit, eval_council, split, a, b, use_council_level):
    pg, ps, pcs = touch_model(train_C, councils_fit, a, b)
    vocab, bg, bs, bcs, comp = bundle_model(train_C, councils_fit, a, b)
    ll_t = ll_b = 0.0; n = nt = 0; pred_t = obs_t = 0.0
    for r in rows:
        if r['council'] != eval_council or (split and r['split'] != split):
            continue
        status, bundle, _ = classify(r)
        if status in ('lifecycle', 'unparsed'):
            continue
        s = stratum(r); key = (eval_council, s)
        p = pcs.get(key) if use_council_level and key in pcs else ps.get(s, pg)
        touched = status == 'touched'
        ll_t += math.log(p if touched else 1 - p); n += 1; pred_t += p; obs_t += touched
        if touched:
            d = bcs.get(key) if use_council_level and key in bcs else bs.get(s, bg)
            ll_b += math.log(max(prob_bundle(d, vocab, comp, bundle), 1e-12)); nt += 1
    return dict(n=n, n_touched=nt, ll_touch_per_record=ll_t / n, ll_bundle_per_touched=ll_b / max(nt, 1),
                predicted_touch_rate=pred_t / n, observed_touch_rate=obs_t / n)


# ---------- building-level clustering (recording conventions) ----------

def clustering(rows, split, min_units=2):
    """Pairwise within-building concordance. For buildings (NGD root) with >= min_units paired records:
    P(unit j has X | another unit i in the same building has X) = sum k(k-1) / sum k(n-1),
    compared with the marginal P(X). X = any touch, the identical bundle, or each mechanism ID.
    Also the beta-binomial intra-building correlation for 'any touch' (method of moments)."""
    bld = defaultdict(list)
    for r in rows:
        if r['split'] != split or not r['split_key'].startswith('root:'):
            continue
        status, bundle, _ = classify(r)
        if status in ('lifecycle', 'unparsed'):
            continue
        bld[(r['council'], r['split_key'])].append(bundle if status == 'touched' else None)
    bld = {k: v for k, v in bld.items() if len(v) >= min_units}
    def conc(has):
        num = den = 0; tot_k = tot_n = 0
        for units in bld.values():
            k = sum(has(u) for u in units); n = len(units)
            num += k * (k - 1); den += k * (n - 1); tot_k += k; tot_n += n
        marg = tot_k / tot_n if tot_n else 0
        cond = num / den if den else None
        return {'marginal': round(marg, 5), 'given_other_unit_has_it': round(cond, 4) if cond is not None else None,
                'lift': round(cond / marg, 1) if cond and marg else None, 'units_with_it': tot_k}
    out = {'buildings': len(bld), 'units': sum(len(v) for v in bld.values()),
           'any_touch': conc(lambda u: u is not None)}
    # same bundle: P(j has the identical bundle | i touched with bundle B)
    num = den = 0
    for units in bld.values():
        c = Counter(u for u in units if u is not None); n = len(units)
        num += sum(k * (k - 1) for k in c.values()); den += sum(c.values()) * (n - 1)
    out['same_bundle_given_other_unit_touched'] = round(num / den, 4) if den else None
    ids = Counter(m.split(':')[0] for v in bld.values() for u in v if u for m in u.split('|'))
    out['by_mechanism'] = {m: conc(lambda u, m=m: u is not None and any(x.split(':')[0] == m for x in u.split('|')))
                           for m, _ in ids.most_common() if _ >= 20}
    # ICC for any touch (Fleiss / beta-binomial moments, unequal cluster sizes approximated by mean size)
    ks = [(sum(u is not None for u in v), len(v)) for v in bld.values()]
    N = sum(n for _, n in ks); p = sum(k for k, _ in ks) / N
    nbar = N / len(ks)
    msb = sum(n * (k / n - p) ** 2 for k, n in ks) / (len(ks) - 1)
    msw = sum(k - k * k / n for k, n in ks) / (N - len(ks))
    out['any_touch_icc'] = round((msb - msw) / (msb + (nbar - 1) * msw), 4)
    return out


# ---------- house style from recorded strings ----------

def house_style(study, council):
    path = study / 'council_data' / 'clean_v1_20261012' / council / 'clean_records.csv'
    n = 0; f = Counter(); lengths = Counter(); trunc_tag = 0; pc_n = pc_bad = 0
    with open(path, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            s = r['recorded_address_raw']; n += 1; lengths[len(s)] += 1
            letters = [ch for ch in s if ch.isalpha()]
            f['upper'] += bool(letters) and all(ch.isupper() for ch in letters)
            f['has_comma'] += ',' in s
            f['comma_after_leading_number'] += bool(re.match(r'^\s*\d+[A-Za-z]?,', s)) or bool(re.search(r',\s*\d+[A-Za-z]?,', s))
            f['double_comma_or_empty_field'] += bool(re.search(r',\s*,', s))
            f['county_word'] += bool(re.search(COUNTY, s.upper()))
            f['brackets'] += '(' in s
            f['leading_zero_unit'] += bool(re.search(r'\b0\d+\b', s))
            if 'systemic_truncation' in (r.get('clean_tags') or ''):
                trunc_tag += 1
            pc = (r.get('recorded_postcode') or '').strip()
            if pc:
                pc_n += 1; pc_bad += not PC_RE.match(pc.upper())
    # SY1: a hard field cap shows as a pile-up at the maximum length (more strings at max than at max-1,
    # and a non-trivial share of all records). Natural length tails thin out instead.
    mx = max(lengths)
    spike = lengths[mx] / max(1, lengths.get(mx - 1, 0))
    cap = mx if spike >= 1.5 and lengths[mx] / n >= 0.005 else None
    return dict(records=n, shares={k: round(v / n, 5) for k, v in sorted(f.items())},
                length={'mean': round(sum(k * v for k, v in lengths.items()) / n, 1), 'max': mx, 'count_at_max_over_max_minus_1': round(spike, 2), 'share_at_max': round(lengths[mx] / n, 5)},
                systemic={'SY1': {'max_field_length': cap, 'applies_to': 'single_concatenated_field' if cap else None,
                                  'records_tagged': trunc_tag, 'share_tagged': round(trunc_tag / n, 5)}},
                postcode_recorded_share=round(pc_n / n, 5),
                postcode_format_nonstandard_share=round(pc_bad / pc_n, 5) if pc_n else None)


def town_layer(rows, split):
    """Per-council rates of LO/ST/FM/DQ4 labels (house style, fitted per council, never transferred)."""
    n = Counter(); lab = defaultdict(Counter); fm = defaultdict(Counter); pc = defaultdict(Counter)
    for r in rows:
        if r['split'] != split or r['ngd_ftype'] != 'built' or r['street_status_ngd'] == 'not_found':
            continue
        c = r['council']; n[c] += 1
        for l in set((r['labels_vs_ngd'] or '').split('|')):
            if l[:2] in ('LO', 'ST'):
                lab[c][l] += 1
        for l in set((r['labels_nearest'] or '').split('|')):
            if l and l.split(':')[0] in HOUSE_STYLE_IDS:
                lab[c]['dwelling_layer:' + l] += 1
        for l in (r['format_flags'] or '').split('|'):
            if l: fm[c][l] += 1
        if r['postcode_label']:
            pc[c][r['postcode_label']] += 1
    out = {}
    for c in n:
        out[c] = {'records': n[c],
                  'street_town_rates': {k: round(v / n[c], 5) for k, v in sorted(lab[c].items())},
                  'format_flag_rates': {k: round(v / n[c], 5) for k, v in sorted(fm[c].items())},
                  'postcode': {k: round(v / sum(pc[c].values()), 6) for k, v in sorted(pc[c].items())} if pc[c] and set(pc[c]) != {'PC:not_available'} else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--study', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    a = ap.parse_args()
    if a.output.exists() and any(a.output.iterdir()):
        sys.exit('output directory is not empty')
    a.output.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    tax_version, tax_ids = load_taxonomy(a.study)
    print('taxonomy', tax_version, 'house-style IDs:', sorted(HOUSE_STYLE_IDS))
    load(con, a.study); build_context(con)
    rows = list(records(con))
    print('paired rows with context:', len(rows))

    # split summary (counts only)
    split_counts = Counter((r['council'], r['split']) for r in rows)
    con.execute(f"copy (select x.council, x.uprn, x.split_key, s.split from ctx x join splitmap s using (council, split_key) where x.council in ('wigan','bradford','leeds')) to '{a.output}/split_assignments.csv.gz' (header, compression gzip)")

    C_train = tally(rows, 'train')

    # ---- tuning: concentration of stratum->global (b) by leave-one-council-out; council->stratum (a) by in-distribution test
    grid = [1, 10, 100, 1000, 10000]
    tuning = []
    for b in grid:
        for held in PAIR_COUNCILS:
            others = [c for c in PAIR_COUNCILS if c != held]
            # fitted on the other councils' train split; the held-out council is scored on all its rows
            res = heldout_loglik(rows, C_train, others, held, None, 1, b, False)
            tuning.append(dict(level='loco', held_out=held, a=None, b=b, **res))
    # no-strata pooled baseline for LOCO: one stratum for everyone
    for held in PAIR_COUNCILS:
        others = [c for c in PAIR_COUNCILS if c != held]
        res = heldout_loglik(rows, C_train, others, held, None, 1, 1e12, False)
        tuning.append(dict(level='loco_baseline_global_only', held_out=held, a=None, b='inf', **res))
    best_b = max(grid, key=lambda b: sum(t['ll_touch_per_record'] + t['ll_bundle_per_touched'] * t['n_touched'] / t['n']
                                          for t in tuning if t['level'] == 'loco' and t['b'] == b))
    for aa in grid:
        for c in PAIR_COUNCILS:
            res = heldout_loglik(rows, C_train, PAIR_COUNCILS, c, 'test', aa, best_b, True)
            tuning.append(dict(level='in_distribution', held_out=c, a=aa, b=best_b, **res))
    best_a = max(grid, key=lambda aa: sum(t['ll_touch_per_record'] + t['ll_bundle_per_touched'] * t['n_touched'] / t['n']
                                           for t in tuning if t['level'] == 'in_distribution' and t['a'] == aa))
    with open(a.output / 'tuning_heldout_loglik.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(tuning[0].keys())); w.writeheader(); w.writerows(tuning)

    # ---- final fit on the train split of all pair councils
    pg, ps, pcs = touch_model(C_train, PAIR_COUNCILS, best_a, best_b)
    vocab, bg, bs, bcs, _ = bundle_model(C_train, PAIR_COUNCILS, best_a, best_b)
    mech_marg, size = Counter(), Counter()
    for (c, s), v in C_train.b.items():
        for k, n in v.items():
            size[len(k.split('|'))] += n
            for m in k.split('|'): mech_marg[m] += n

    def effect_table(cnt):
        tot = sum(cnt.values())
        return {'n': tot, 'p': {k: round(v / tot, 4) for k, v in sorted(cnt.items(), key=lambda x: -x[1])}}

    # council intensity: observed touched / expected from pooled stratum rates (indirect standardisation).
    # Strata explain the dwelling mix; what is left is how carefully each council records.
    intensity = {}
    for c in PAIR_COUNCILS:
        obs = sum(C_train.t[(cc, s)] for (cc, s) in C_train.n if cc == c)
        exp = sum(n * ps[s] for (cc, s), n in C_train.n.items() if cc == c)
        intensity[c] = round(obs / exp, 3)

    mechanisms = {}
    for m, n in sorted(mech_marg.items(), key=lambda x: -x[1]):
        eff = C_train.eff_m[m]; el = C_train.elig_m[m]
        cond = {}
        for rel in RELATIONS[:-1]:
            k_ex, k_dr = eff.get('exact:' + rel, 0), eff.get('drift:' + rel, 0)
            if el[rel]:
                cond[rel] = {'eligible_rows': el[rel], 'p_exact_given_eligible': round(k_ex / el[rel], 4),
                             'p_drift_given_eligible': round(k_dr / el[rel], 4)}
        mechanisms[m] = {'touched_rows_train': n, 'effect_unconditional': effect_table(eff)['p'], 'effect_given_eligible': cond}

    bundles = {}
    for k in sorted(vocab, key=lambda k: -bg[k]):
        bundles[k] = {'mechanisms': k.split('|'), 'p_global': round(bg[k], 6), 'effect': effect_table(C_train.eff_b[k])}

    label_drift_rows = Counter()
    for k, cnt in C_train.eff_b.items():
        if len(k.split('|')) == 1 and k.split(':')[0] in ('PN3', 'SU1', 'PN2'):
            for e, v in cnt.items():
                if e.startswith('exact:'):
                    label_drift_rows[e[6:]] += v
    n_train = sum(C_train.n.values())

    lb = {}
    for mid in ('LB1', 'LB2', 'LB3', 'LB4'):
        m = tax_ids.get(mid)
        if m:
            ev = sum((m['rates'].get(c) or {}).get('n_events', 0) for c in PAIR_COUNCILS)
            nr = sum((m['rates'].get(c) or {}).get('n_records', 0) for c in PAIR_COUNCILS)
            lb[mid] = {'name': m['name'], 'expected_identity': m['expected_identity'],
                       'conflict_lower_bound_rate_pooled': round(ev / nr, 7) if nr else None, 'conflict_events': ev}
    unknown = sorted({m.split(':')[0] for m in mech_marg} - set(tax_ids))

    profile = {
        'schema_version': '0.1',
        'taxonomy_version': tax_version,
        'house_style_ids_from_taxonomy': sorted(HOUSE_STYLE_IDS),
        'mechanism_ids_not_in_taxonomy': unknown,
        'profile_id': 'uprn_corruption_profile_v0_20261012',
        'status': 'first_pass_not_frozen',
        'fitted_on': {'pairs': 'mined_error_pairs/v2_20261012', 'reference': 'reference/ngd_20261001',
                      'clean_records': 'council_data/clean_v1_20261012', 'councils_core': PAIR_COUNCILS,
                      'councils_style_only': ['basingstoke'], 'split': f'train ({100 - TEST_PERCENT}%, by building key, salt {SPLIT_SALT})',
                      'epochs': {'leeds': '2024-10', 'wigan': '2025-11', 'bradford': '2025-12', 'os_ngd': '2026-10-01'},
                      'truth_verified': False,
                      'note': 'Rates are discrepancies under the council label, not verified error rates.'},
        'strata': {'definition': 'dwelling_type x rural; dwelling_type from NGD subname/name/number/parent; rural = NGD postcode with <= '
                                 f'{RURAL_MAX_POSTCODE_SIZE} built UPRNs',
                   'dwelling_types': ['numbered', 'named_number', 'named_only', 'flat', 'floor_flat', 'room', 'annex', 'other'],
                   'train_records': {s: sum(n for (c, ss), n in C_train.n.items() if ss == s) for s in sorted(ps)}},
        'smoothing': {'council_to_stratum_a': best_a, 'stratum_to_global_b': best_b, 'bundle_min_count': BUNDLE_MIN_COUNT,
                      'tuned_by': 'held-out log-likelihood; b by leave-one-council-out, a by in-distribution building split'},
        'core': {
            'touch_rate': {'global': round(pg, 6), 'by_stratum': {s: round(v, 6) for s, v in sorted(ps.items())},
                           'by_council_stratum': {f'{c}|{s}': round(v, 6) for (c, s), v in sorted(pcs.items())},
                           'intensity_multiplier': 1.0,
                           'share_of_touched_by_class_by_stratum': {
                               s: {k: round(v / sum(C_train.eclass[s].values()), 4) for k, v in sorted(C_train.eclass[s].items())}
                               for s in sorted(C_train.eclass)},
                           'variation_multiplier': 1.0,
                           'error_multiplier': 1.0,
                           'class_note': 'variation = touched with identity preserved (legitimate rendering); error = exact collision or drift. '
                                         'The two multipliers scale them separately (CLAUDE.md: keep valid variation separate from error).',
                           'council_intensity_observed': intensity,
                           'intensity_note': 'Multiply stratum touch rates by this for a target source. 1.0 = pooled development average; '
                                             'use the development range as the sensitivity band for an unseen council.'},
            'bundles': {'explicit': bundles,
                        'by_stratum': {s: {k: round(v, 6) for k, v in sorted(d.items(), key=lambda x: -x[1]) if v >= 1e-4}
                                       for s, d in sorted(bs.items())},
                        'tail_model': {'size_distribution': {str(k): round(v / sum(size.values()), 4) for k, v in sorted(size.items())},
                                       'mechanism_marginal': {m: round(v / sum(mech_marg.values()), 5) for m, v in mech_marg.most_common()}}},
            'mechanisms': mechanisms,
        },
        'clustering': clustering(rows, 'train'),
        'label_drift': {
            'description': 'Clean string, wrong UPRN label: the string is a correct rendering of a confusable UPRN X, and the label is the record\'s UPRN.',
            'observed_exact_single_number_mechanism_rows_train': dict(label_drift_rows),
            'observed_rate_per_record': round(sum(label_drift_rows.values()) / n_train, 6),
            'share_attributed_to_label_drift_lambda': 0.5,
            'lambda_status': 'prior, not identifiable without the verified subset; about half the UPRN-conflict variants were label mix-ups (v2 README)',
            'taxonomy_mechanisms': lb,
            'relation_to_mechanism': {'to_neighbour': 'LB1', 'to_parent': 'LB2', 'to_sibling': 'LB3', 'to_other': 'LB4'},
            'rate_per_record_by_relation': {rel: round(v / n_train, 7) for rel, v in sorted(label_drift_rows.items())}},
        'house_style': {'from_pairs': town_layer(rows, 'train'),
                        'from_strings': {c: house_style(a.study, c) for c in STYLE_COUNCILS}},
        'keying': {'status': 'not_fitted_v0', 'note': 'KY character ops to be fitted with council_data/pipeline_support learner on residual component diffs'},
        'coverage': {c: dict(C_train.status[c]) for c in PAIR_COUNCILS},
        'reference_ambiguity': {c: round(C_train.ambig[c] / sum(n for (cc, s), n in C_train.n.items() if cc == c), 5) for c in PAIR_COUNCILS},
        'split_counts': {f'{c}|{s}': n for (c, s), n in sorted(split_counts.items())},
        'disclosure': 'Contains mechanism IDs, rates and generic county/vocabulary patterns only. No donor address strings.',
    }
    (a.output / 'profile.json').write_text(json.dumps(profile, indent=1))
    print('best a', best_a, 'best b', best_b)
    for t in tuning:
        if (t['level'] == 'loco' and t['b'] == best_b) or t['level'] == 'loco_baseline_global_only' or (t['level'] == 'in_distribution' and t['a'] == best_a):
            print(t)


if __name__ == '__main__':
    main()
