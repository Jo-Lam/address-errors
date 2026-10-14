"""Real-versus-synthetic discriminator on held-out buildings, and a ranked list of what gives synthetic records away.

Both sides are labelled by the same miner (mined_error_pairs/v2_20261012/code/mine_pairs.py), so every feature is
computed the same way for real and synthetic strings.

Two tasks, both on the 20% test split of buildings (profile split), development councils only:
  A  all records: each held-out real record vs the synthetic record generated for the same UPRN
  B  discrepancies only: real records with a dwelling-layer discrepancy vs synthetic records with one
Gradient boosting, 5-fold cross-validation grouped by building key, out-of-fold AUC. AUC 0.5 = indistinguishable.

Usage: python discriminate.py <run_dir>
"""
import json, math, os, re, sys
from collections import Counter, defaultdict
import numpy as np
import pandas as pd
import lightgbm as lgb
from rapidfuzz import fuzz
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from common import COUNCILS as COUNCILS_DEFAULT, load_components, add_context, load_split, load_pairs

UNIT = {'FLAT', 'FLT', 'APARTMENT', 'APT', 'APPT', 'UNIT', 'MAISONETTE', 'MAIS', 'STUDIO', 'SUITE', 'BLOCK', 'PENTHOUSE'}
FLOOR = {'FLOOR', 'FLR', 'FLOORS', 'GROUND', 'GRD', 'GND', 'FIRST', '1ST', 'SECOND', '2ND', 'THIRD', '3RD', 'BASEMENT',
         'TOP', 'LOWER', 'UPPER', 'ATTIC', 'GFF', 'FFF', 'GF', 'FF'}
POSITION = {'FRONT', 'REAR', 'BACK', 'LEFT', 'RIGHT', 'MIDDLE'}
ROOM = {'ROOM', 'ROOMS', 'RM', 'RMS', 'BEDSIT'}
ANNEX = {'ANNEX', 'ANNEXE'}
QUAL = {'ADJ', 'ADJACENT', 'REAR', 'LAND', 'OFF', 'OVER', 'ABOVE', 'AT', 'OF', 'PLOT', 'NEW', 'BUILD', 'DEVELOPMENT',
        'PROPOSED', 'FORMER', 'SITE', 'CARETAKERS', 'SHOP', 'PREMISES', 'TO', 'NEXT', 'PART'}
GENERIC = {'BUNGALOW', 'COTTAGE', 'LODGE', 'BARN', 'FARMHOUSE', 'COACH', 'VICARAGE', 'HOUSE', 'THE', 'FARM', 'COURT',
           'MILL', 'HALL', 'COTTAGES', 'VIEW', 'PARK', 'BUILDINGS', 'CHAMBERS', 'WORKS', 'MEWS'}
STREET = {'ROAD', 'RD', 'STREET', 'ST', 'AVENUE', 'AVE', 'LANE', 'LN', 'DRIVE', 'DR', 'CLOSE', 'CL', 'CRESCENT',
          'GROVE', 'TERRACE', 'PLACE', 'WAY', 'GARDENS', 'MOUNT', 'WALK', 'SQUARE', 'GREEN', 'HILL', 'ROW', 'FOLD'}
COUNTY = {'LANCASHIRE', 'LANCS', 'CHESHIRE', 'MERSEYSIDE', 'YORKSHIRE', 'YORKS', 'MANCHESTER', 'GREATER'}


def toks(s):
    return re.sub(r'[^A-Z0-9 ]', ' ', (s or '').upper()).split()


def tclass(t):
    if t in UNIT: return 'unit'
    if t in FLOOR: return 'floor'
    if t in POSITION: return 'position'
    if t in ROOM: return 'room'
    if t in ANNEX: return 'annex'
    if t in QUAL: return 'qualifier'
    if t in COUNTY: return 'county'
    if t in STREET: return 'streettype'
    if t in GENERIC: return 'namegeneric'
    if re.fullmatch(r'\d+', t): return 'number'
    if re.fullmatch(r'\d+[A-Z]+|[A-Z]+\d+', t): return 'alnum'
    if len(t) == 1: return 'letter'
    return 'word'


TCLASSES = ['unit', 'floor', 'position', 'room', 'annex', 'qualifier', 'county', 'streettype', 'namegeneric',
            'number', 'alnum', 'letter', 'word']


def features(df, vocab=None):
    F = defaultdict(list)
    added_lists = []
    for rec, ngd, rm in zip(df.recorded_address, df.ngd_address, df.rm_address):
        s = rec or ''
        F['s_len'].append(len(s)); T = toks(s); F['s_ntok'].append(len(T))
        F['s_ncomma'].append(s.count(',')); F['s_ndigit'].append(sum(ch.isdigit() for ch in s))
        F['s_bracket'].append('(' in s); F['s_slash'].append('/' in s); F['s_hyphen'].append('-' in s)
        F['s_dot'].append('.' in s); F['s_amp'].append('&' in s); F['s_apos'].append("'" in s)
        F['s_dblspace'].append('  ' in s); F['s_space_comma'].append(' ,' in s); F['s_comma_nospace'].append(bool(re.search(r',\S', s)))
        F['s_empty_field'].append(bool(re.search(r',\s*,', s)))
        letters = [ch for ch in s if ch.isalpha()]
        F['s_upper_share'].append(sum(ch.isupper() for ch in letters) / max(1, len(letters)))
        F['s_lower_after_digit'].append(bool(re.search(r'\d[a-z]', s)))
        F['s_upper_after_digit'].append(bool(re.search(r'\d[A-Z]', s)))
        F['s_starts_digit'].append(s[:1].isdigit())
        F['s_first_comma_pos'].append(s.find(',') if ',' in s else -1)
        F['s_max_tok'].append(max([len(t) for t in T] or [0]))
        F['s_n_numtok'].append(sum(t.isdigit() for t in T))
        F['s_trailing_punct'].append(bool(re.search(r'[.,;]\s*$', s)))
        N, R = toks(ngd), toks(rm)
        rn, nn, rr = ' '.join(T), ' '.join(N), ' '.join(R)
        F['d_ratio_ngd'].append(fuzz.ratio(rn, nn)); F['d_tset_ngd'].append(fuzz.token_set_ratio(rn, nn))
        F['d_ratio_rm'].append(fuzz.ratio(rn, rr) if rr else -1)
        F['d_len_diff'].append(len(rn) - len(nn))
        cn, cr, ct = Counter(N), Counter(R), Counter(T)
        add = ct - cn - cr if R else ct - cn
        drop = cn - ct
        F['d_n_added'].append(sum(add.values())); F['d_n_dropped'].append(sum(drop.values()))
        ca = Counter(tclass(t) for t in add.elements()); cd = Counter(tclass(t) for t in drop.elements())
        for k in TCLASSES:
            F['add_' + k].append(ca[k]); F['drop_' + k].append(cd[k])
        # order: first position where recorded and canonical token sequences differ (relative)
        i = 0
        while i < min(len(T), len(N)) and T[i] == N[i]:
            i += 1
        F['d_first_diff_rel'].append(i / max(1, len(N)))
        added_lists.append(set(add))
    X = pd.DataFrame(F)
    if vocab is not None:
        V = np.zeros((len(df), len(vocab)), dtype=np.int8)
        idx = {w: j for j, w in enumerate(vocab)}
        for i, a in enumerate(added_lists):
            for w in a:
                if w in idx:
                    V[i, idx[w]] = 1
        X = pd.concat([X, pd.DataFrame(V, columns=['vocab_' + w for w in vocab])], axis=1)
    return X, added_lists


def label_features(df, label_vocab, lo_vocab, fm_vocab):
    F = {}
    dl = [set(x for x in l.split('|') if x and not x.startswith('LC')) for l in df.labels_nearest]
    lv = [set(x for x in l.split('|') if x) for l in df.labels_vs_ngd]
    ff = [set(x for x in l.split('|') if x) for l in df.format_flags]
    for L in label_vocab:
        F['lab_' + L] = [L in s for s in dl]
    for m in sorted({L.split(':')[0] for L in label_vocab}):
        F['mech_' + m] = [any(x.split(':')[0] == m for x in s) for s in dl]
    for L in lo_vocab:
        F['style_' + L] = [L in s for s in lv]
    for L in fm_vocab:
        F['fmt_' + L] = [L in s for s in ff]
    F['lab_n_dwelling'] = [len(s) for s in dl]
    F['coll_other_only'] = (df.collision == 'matches_other_only').values
    F['coll_label_and_other'] = (df.collision == 'matches_label_and_other').values
    F['coll_no_match'] = (df.collision == 'no_match').values
    F['coll_not_tested'] = (df.collision == 'not_tested').values
    for rel in ['to_parent', 'to_child', 'to_sibling', 'to_neighbour', 'to_same_complex']:
        F['drift_' + rel] = (df.drift_relation == rel).values
        F['collrel_' + rel] = (df.collision_relation == rel).values
    F['nearest_rm'] = (df.nearest_canonical == 'rm').values
    F['street_not_found'] = (df.street_status_ngd == 'not_found').values
    return pd.DataFrame(F)


def ctx_features(df):
    F = {}
    for d in ['numbered', 'named_number', 'named_only', 'flat', 'floor_flat', 'room', 'annex', 'other']:
        F['ctx_' + d] = (df.dwelling_type == d).values
    F['ctx_rural'] = df.rural.astype(bool).values
    F['ctx_has_parent'] = (df.has_parent == 'True').values
    F['ctx_n_children'] = pd.to_numeric(df.n_children, errors='coerce').fillna(0).values
    for c in COUNCILS:
        F['council_' + c] = (df.council == c).values
    return pd.DataFrame(F)


def group_of(col):
    for p, g in [('ctx_', 'context (who gets touched)'), ('council_', 'council'), ('s_', 'surface format'),
                 ('d_', 'distance to canonical'), ('add_', 'added-token classes'), ('drop_', 'dropped-token classes'),
                 ('vocab_', 'added words'), ('lab_', 'mechanism labels'), ('mech_', 'mechanism labels'),
                 ('style_', 'town/locality style'), ('fmt_', 'format flags'), ('coll', 'collision / drift'),
                 ('drift_', 'collision / drift'), ('nearest_', 'collision / drift'), ('street_', 'parse status')]:
        if col.startswith(p):
            return g
    return 'other'


PARAMS = dict(objective='binary', learning_rate=0.05, num_leaves=31, min_child_samples=30, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=1)


def cv_oof(X, y, groups, rounds=300):
    oof = np.zeros(len(y))
    gain = np.zeros(X.shape[1])
    for tr, te in StratifiedGroupKFold(5, shuffle=True, random_state=1).split(X, y, groups):
        m = lgb.train(PARAMS, lgb.Dataset(X.iloc[tr], y[tr]), rounds)
        oof[te] = m.predict(X.iloc[te])
        gain += m.feature_importance('gain')
    return oof, gain / gain.sum()


def load_side(run, c, kind, comp, split):
    if kind == 'real':
        p = load_pairs(c)
    else:
        p = pd.read_csv(os.path.join(run, f'pairs_synth_{c}.csv.gz'), dtype=str, keep_default_na=False)
        s = pd.read_csv(os.path.join(run, f'synthetic_{c}.csv.gz'), dtype=str, keep_default_na=False)
        p = p.merge(s[['record_id', 'requested_bundle', 'applied_rules', 'failed_rules', 'touch_route',
                       'label_drift_relation', 'source_uprn']], on='record_id', how='left')
    test = split[(split.council == c) & (split.split == 'test')].set_index('uprn').split_key
    p = p[(p.ngd_ftype == 'built') & p.label_uprn.isin(test.index)].copy()
    p['split_key'] = p.label_uprn.map(test)
    ctx = comp.set_index('uprn').loc[p.label_uprn, ['dwelling_type', 'rural', 'stratum']]
    p['dwelling_type'] = ctx.dwelling_type.values; p['rural'] = ctx.rural.values; p['stratum'] = ctx.stratum.values
    p['y'] = int(kind == 'synth')
    return p


COUNCILS = list(COUNCILS_DEFAULT)


def main():
    global COUNCILS
    run = sys.argv[1]
    out = os.path.join(run, 'discriminator'); os.makedirs(out, exist_ok=True)
    if os.path.exists(os.path.join(run, 'test_split.csv.gz')):
        split = pd.read_csv(os.path.join(run, 'test_split.csv.gz'), dtype=str, keep_default_na=False)
        COUNCILS = [c for c in ['wigan', 'bradford', 'leeds', 'basingstoke'] if os.path.exists(os.path.join(run, f'synthetic_{c}.csv.gz'))]
    else:
        split = load_split()
    sides = []
    for c in COUNCILS:
        comp = add_context(load_components(c))[['uprn', 'dwelling_type', 'rural', 'stratum']]
        real, syn = (load_side(run, c, k, comp, split) for k in ('real', 'synth'))
        real = real[real.label_uprn.isin(set(syn.label_uprn))]   # same recipients on both sides
        sides += [real, syn]
        print('loaded', c, flush=True)
    D = pd.concat(sides, ignore_index=True).fillna('')
    D['dwelling_diff_b'] = D.dwelling_diff == 'True'
    D['group'] = D.council + '|' + D.split_key
    lab_counts = Counter(x for l in D.labels_nearest for x in l.split('|') if x and not x.startswith('LC'))
    label_vocab = sorted(k for k, v in lab_counts.items() if v >= 20)
    lo_counts = Counter(x for l in D.labels_vs_ngd for x in l.split('|') if x and x.split(':')[0] in ('LO1', 'LO2', 'LO3', 'ST1', 'ST2', 'ST3', 'ST4', 'ST5', 'SU11', 'DQ1'))
    lo_vocab = sorted(k for k, v in lo_counts.items() if v >= 20)
    fm_counts = Counter(x for l in D.format_flags for x in l.split('|') if x)
    fm_vocab = sorted(k for k, v in fm_counts.items() if v >= 20)
    Xs, added = features(D)
    add_counts = Counter(w for a in added for w in a)
    vocab = [w for w, n in add_counts.most_common(300) if n >= 30]
    V = np.zeros((len(D), len(vocab)), dtype=np.int8)
    vidx = {w: j for j, w in enumerate(vocab)}
    for i, a in enumerate(added):
        for w in a:
            if w in vidx:
                V[i, vidx[w]] = 1
    Xv = pd.concat([Xs, pd.DataFrame(V, columns=['vocab_' + w for w in vocab])], axis=1)
    X = pd.concat([Xv, label_features(D, label_vocab, lo_vocab, fm_vocab), ctx_features(D)], axis=1).astype(float)
    X.columns = [re.sub(r'[^A-Za-z0-9_]', '_', c) for c in X.columns]
    y = D.y.values
    results = {'n': {}, 'auc': {}, 'ablation': {}}
    tasks = {'A_all_records': np.ones(len(D), bool), 'B_discrepancies_only': D.dwelling_diff_b.values}
    oofs = {}
    for tname, mask in tasks.items():
        Xt, yt, gt = X[mask].reset_index(drop=True), y[mask], D.group.values[mask]
        if tname.startswith('A'):
            Xt = Xt[[c for c in Xt.columns if not c.startswith('ctx_')]]   # paired: same recipients on both sides
        oof, gain = cv_oof(Xt, yt, gt)
        oofs[tname] = (mask, oof)
        sub = D[mask]
        results['n'][tname] = {c: {'real': int(((sub.council == c) & (sub.y == 0)).sum()),
                                   'synthetic': int(((sub.council == c) & (sub.y == 1)).sum())} for c in COUNCILS}
        results['auc'][tname] = {'pooled': round(roc_auc_score(yt, oof), 4)}
        for c in COUNCILS:
            cm = (sub.council == c).values
            if len(set(yt[cm])) == 2:
                results['auc'][tname][c] = round(roc_auc_score(yt[cm], oof[cm]), 4)
        gi = pd.DataFrame({'feature': Xt.columns, 'gain_share': gain, 'group': [group_of(c) for c in Xt.columns]})
        gi.sort_values('gain_share', ascending=False).to_csv(os.path.join(out, f'feature_gain_{tname}.csv'), index=False)
        # ablation: drop each feature group, re-run CV, AUC drop
        abl = {}
        for g in sorted(set(gi.group)):
            keep = [c for c in Xt.columns if group_of(c) != g]
            o2, _ = cv_oof(Xt[keep], yt, gt, rounds=200)
            abl[g] = round(results['auc'][tname]['pooled'] - roc_auc_score(yt, o2), 4)
            print(tname, 'ablate', g, abl[g], flush=True)
        results['ablation'][tname] = dict(sorted(abl.items(), key=lambda kv: -kv[1]))
        # only-group models: how far does each group alone get?
        only = {}
        for g in sorted(set(gi.group)):
            keep = [c for c in Xt.columns if group_of(c) == g]
            o2, _ = cv_oof(Xt[keep], yt, gt, rounds=200)
            only[g] = round(roc_auc_score(yt, o2), 4)
        results.setdefault('group_alone_auc', {})[tname] = dict(sorted(only.items(), key=lambda kv: -kv[1]))
        print(tname, results['auc'][tname], flush=True)
    json.dump(results, open(os.path.join(out, 'discriminator_results.json'), 'w'), indent=1)
    # ------------------------------------------------------------ per-mechanism giveaway ranking
    maskB, oofB = oofs['B_discrepancies_only']
    DB = D[maskB].reset_index(drop=True); DB['p_synth'] = oofB
    maskA, oofA = oofs['A_all_records']
    DA = D[maskA].reset_index(drop=True); DA['p_synth'] = oofA
    rows = []
    def lab_sets(series, kind):
        if kind == 'dwelling':
            return [set(x for x in l.split('|') if x and not x.startswith('LC')) for l in series]
        return [set(x for x in l.split('|') if x) for l in series]
    for kind, col, frame in [('dwelling', 'labels_nearest', DB), ('style', 'labels_vs_ngd', DA), ('format', 'format_flags', DA)]:
        sets = lab_sets(frame[col], kind)
        allL = Counter(x for s in sets for x in s)
        for L, n in allL.items():
            if kind == 'style' and L.split(':')[0] not in ('LO1', 'LO2', 'LO3', 'ST1', 'ST2', 'ST3', 'ST4', 'ST5', 'SU11'):
                continue
            has = np.array([L in s for s in sets])
            if has.mean() > 0.5:      # near-universal labels (case, commas) only restate the overall AUC
                continue
            yr = frame.y.values[has]
            nr, ns = int((yr == 0).sum()), int((yr == 1).sum())
            auc = roc_auc_score(yr, frame.p_synth.values[has]) if nr >= 5 and ns >= 5 else np.nan
            rows.append(dict(layer=kind, label=L, mechanism=L.split(':')[0], n_real=nr, n_synth=ns,
                             ratio_synth_to_real=round((ns + 0.5) / (nr + 0.5), 3),
                             within_label_auc=round(auc, 3) if not np.isnan(auc) else '',
                             giveaway_records=round(abs(ns - nr) + (nr + ns) * 2 * max(0, (auc if not np.isnan(auc) else 0.5) - 0.5), 1)))
    G = pd.DataFrame(rows).sort_values('giveaway_records', ascending=False)
    G.to_csv(os.path.join(out, 'giveaway_by_label.csv'), index=False)
    # by council for dwelling labels
    rows = []
    for c in COUNCILS:
        for frame, kind, col in [(DB, 'dwelling', 'labels_nearest'), (DA, 'style', 'labels_vs_ngd')]:
            f = frame[frame.council == c]
            sets = lab_sets(f[col], 'dwelling' if kind == 'dwelling' else 'x')
            for L, n in Counter(x for s in sets for x in s).items():
                has = np.array([L in s for s in sets]); yr = f.y.values[has]
                rows.append(dict(council=c, layer=kind, label=L, n_real=int((yr == 0).sum()), n_synth=int((yr == 1).sum())))
    pd.DataFrame(rows).to_csv(os.path.join(out, 'label_counts_by_council.csv'), index=False)
    # requested vs realised (verification)
    S = D[D.y == 1]
    req, hit = Counter(), Counter()
    for a, l in zip(S.applied_rules, S.labels_nearest):
        A = set(x for x in a.split('|') if x); L = set(l.split('|'))
        for x in A:
            req[x] += 1; hit[x] += x in L
    fails = Counter(x for f in S.failed_rules for x in f.split('|') if x)
    reqd = Counter(x for f in S.requested_bundle for x in f.split('|') if x)
    V = pd.DataFrame([dict(mechanism=k, requested=reqd[k], applied=req[k], failed_unapplicable=fails[k],
                           detected_by_miner=hit[k], detected_share_of_applied=round(hit[k] / req[k], 3) if req[k] else '')
                      for k in sorted(set(reqd) | set(req))]).sort_values('requested', ascending=False)
    V.to_csv(os.path.join(out, 'requested_vs_realised.csv'), index=False)
    # collisions and drift, real vs synthetic, all test records
    C = D.groupby(['council', 'y']).agg(records=('record_id', 'size'),
                                         dwelling_diff=('dwelling_diff_b', 'mean'),
                                         exact_other_only=('collision', lambda s: (s == 'matches_other_only').mean()),
                                         label_and_other=('collision', lambda s: (s == 'matches_label_and_other').mean()),
                                         drift_candidate=('drift_relation', lambda s: (s != '').mean()),
                                         street_not_found=('street_status_ngd', lambda s: (s == 'not_found').mean()))
    C.reset_index().replace({'y': {0: 'real', 1: 'synthetic'}}).to_csv(os.path.join(out, 'collision_and_touch_rates.csv'), index=False)
    # the most obviously synthetic and most "real-looking" records, task B (address-level: stays in this folder)
    ex = DB.assign(kind=DB.y.map({0: 'real', 1: 'synthetic'}))
    cols = ['council', 'kind', 'p_synth', 'recorded_address', 'ngd_address', 'labels_nearest', 'applied_rules']
    pd.concat([ex[ex.y == 1].nlargest(60, 'p_synth')[cols], ex[ex.y == 0].nsmallest(60, 'p_synth')[cols],
               ex[ex.y == 1].nsmallest(30, 'p_synth')[cols]]).to_csv(os.path.join(out, 'examples_extreme.csv'), index=False)
    print(json.dumps(results, indent=1))


if __name__ == '__main__':
    main()
