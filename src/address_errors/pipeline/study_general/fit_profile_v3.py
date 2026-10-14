"""Fit the corruption profile v3, the candidate for freezing: v2 plus the fixes from realism check run 3b.

Design: ../DESIGN.md section 15. Freeze note: ../FROZEN.md. Changes from v2 (code/fit_profile_v2.py, reused):
  * House style is fitted per council by code/fit_house_style.py, the same entry point used to refit house style for
    an external-test council. profile.house_style is now keyed by council: house_style[<council>] = block.
  * House style adds: locality "other" text kept per street even when seen once, a postcode-sector fallback lookup,
    the share of "other" text that is another street's name, per-eligible style rates from the miner's labels
    (SU11 component order, unit word and floor descriptor added, brackets), unit-word vocabulary, county words
    (with Cornwall and Derbyshire), and per-street variant shares shrunk towards zero (k / (n + 5)).
  * Collision modifiers: for subtypes that can land on another UPRN (sub-unit, name, number or suffix dropped), the
    real relative rate at which they fall on records where the drop collides, per council (flags_v2.collision_flags).
  * Building-name word abbreviations ("PRESBYTERY" -> "PSBTRY"): a generic word vocabulary and per-council rates.

Inputs as v2. Cornwall and Derby are never read.
Generalised copy (study_general/): councils and paths from councils.py via fit_profile_v1; see GENERALISATION.md.
Usage: python fit_profile_v3.py --study <study folder> --output <new empty dir>     (duckdb, PyYAML, numpy, rapidfuzz, pandas)
"""
import argparse, csv, gzip, json, math, re, sys
from collections import Counter, defaultdict
from pathlib import Path
import duckdb

sys.path.insert(0, str(Path(__file__).parent))
import fit_profile as v0
import fit_profile_v1 as v1
import fit_profile_v2 as v2
import flags_v2 as F
import fit_house_style as HS

COUNCILS = v1.COUNCILS
FLAGS = F.FLAGS
CLEAN = v1.CLEAN     # study: 'council_data/clean_v1_20261012/{c}/clean_records.csv'
MOD_PRIOR = 20          # rows: council collision share shrunk to the pooled share
MOD_RANGE = (0.05, 20.0)


def collision_modifiers(con, train, req):
    flags = {}
    for c in COUNCILS:
        rows = con.execute(f"select uprn, subname, name, number, streetname from comp where council='{c}'").fetchall()
        for u, f in F.collision_flags(dict(uprn=r[0], subname=r[1], name=r[2], number=r[3], streetname=r[4]) for r in rows).items():
            flags[(c, u)] = f
    out = {}
    for m, fl in F.COLLISION_FLAG_OF.items():
        rq = req.get(m)
        if rq is None:
            continue
        hit = defaultdict(lambda: [0.0, 0.0]); pop = defaultdict(lambda: [0.0, 0.0]); ex = defaultdict(lambda: [0.0, 0.0])
        for r in train:
            if not v1.satisfies(r['sig'], rq):
                continue
            h = flags.get((r['council'], r['uprn']), {}).get(fl, False)
            pop[r['council']][0] += r['w'] * h; pop[r['council']][1] += r['w']
            if r['bundle'] and m in r['bundle'].split('|'):
                hit[r['council']][0] += r['w'] * h; hit[r['council']][1] += r['w']
                if h:
                    ex[r['council']][0] += r['w'] * r['effect'].startswith('exact:'); ex[r['council']][1] += r['w']
        H = [sum(hit[c][i] for c in COUNCILS) for i in (0, 1)]; P = [sum(pop[c][i] for c in COUNCILS) for i in (0, 1)]
        if H[1] < 10 or not P[1]:
            continue
        p1g = H[0] / H[1]; p0g = P[0] / P[1]
        def mods(p1, p0):
            if p0 <= 0 or p0 >= 1:
                return {'true': 1.0, 'false': 1.0}
            clamp = lambda x: round(min(max(x, MOD_RANGE[0]), MOD_RANGE[1]), 4)
            return {'true': clamp(p1 / p0), 'false': clamp((1 - p1) / (1 - p0))}
        E = [sum(ex[c][i] for c in COUNCILS) for i in (0, 1)]
        d = {'flag': fl, 'pooled': {**mods(p1g, p0g), 'share_hit_real': round(p1g, 4), 'share_hit_eligible': round(p0g, 5), 'rows': round(H[1], 1),
                                    'p_exact_given_hit_real': round(E[0] / E[1], 4) if E[1] else None}}
        for c in COUNCILS:
            if pop[c][1]:
                p1 = (hit[c][0] + MOD_PRIOR * p1g) / (hit[c][1] + MOD_PRIOR); p0 = pop[c][0] / pop[c][1]
                d[c] = {**mods(p1, p0), 'share_hit_real': round(p1, 4), 'share_hit_eligible': round(p0, 5), 'rows': round(hit[c][1], 1),
                        'p_exact_given_hit_real': round(ex[c][0] / ex[c][1], 4) if ex[c][1] else None}
        out[m] = d
    return out


def name_abbreviations(con, study, split_of):
    """Building-name words written shortened: same first letter, letters a subsequence, shorter (PRESBYTERY -> PSBTRY)."""
    def subseq(a, b):
        it = iter(b); return all(x in it for x in a)
    vocab = defaultdict(Counter); recs = Counter(); named = Counter(); dropped = Counter()
    for c in COUNCILS:
        q = f"""select pp.label_uprn, pp.recorded_address, f.name from read_csv('{study / v1.PAIRS[c]}', all_varchar=true) pp
                join comp f on f.council='{c}' and f.uprn=pp.label_uprn where coalesce(f.name,'')<>''"""
        for u, addr, name in con.execute(q).fetchall():
            if split_of.get((c, u)) != 'train':
                continue
            named[c] += 1
            raw = [t.strip('.,') for t in re.split(r'[\s,]+', (addr or '').upper()) if t.strip('.,')]
            alnum = {re.sub(r'[^A-Z0-9]', '', t) for t in raw}
            ntok = re.findall(r'[A-Z0-9]+', name.upper())
            hit = False
            for t in ntok:
                if len(t) < 4 or not t.isalpha() or t in alnum:
                    continue
                best = None
                for r in raw:
                    ra = re.sub(r'[^A-Z]', '', r)
                    if 2 <= len(ra) < len(t) and ra[0] == t[0] and ra not in ntok and subseq(ra, t) and (best is None or len(ra) > len(re.sub(r'[^A-Z]', '', best))):
                        best = r
                if best:
                    vocab[t][best] += 1; hit = True
                else:
                    dropped[c] += 1
            recs[c] += hit
    keep = {t: {a: k for a, k in cnt.most_common(4) if k >= 3} for t, cnt in vocab.items()}
    keep = {t: {a: round(k / sum(v.values()), 3) for a, k in v.items()} for t, v in keep.items() if v}
    return {'rule': 'name word written as a shorter form: same first letter, letters in order, seen >= 3 times',
            'vocabulary': dict(sorted(keep.items())),
            'rate_per_named_record': {c: round(recs[c] / max(named[c], 1), 5) for c in COUNCILS},
            'name_words_missing_without_abbreviation_per_named_record': {c: round(dropped[c] / max(named[c], 1), 5) for c in COUNCILS},
            'note': 'Realise BN4:name_replaced / partly changed edits mostly as these abbreviations or word drops; whole-name replacement is rare.'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--study', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--lookup-fix', action='store_true', help='next-version locality lookups (fit_house_style.fit_council); off reproduces v3e')
    a = ap.parse_args()
    if a.output.exists() and any(a.output.iterdir()):
        sys.exit('output directory is not empty')
    a.output.mkdir(parents=True, exist_ok=True)
    tax_version, tax_ids, STYLE, PER_BUILDING = v1.load_taxonomy(a.study)
    con = duckdb.connect()
    v2.load_context(con, a.study)
    raw_rows, moved = v2.load_rows(a.study, STYLE)
    rows, missing = v1.attach_context(con, raw_rows)
    print('rows with context', len(rows), 'missing', missing, flush=True)
    train = [r for r in rows if r['split'] == 'train']
    req, coverage = v2.requirements(train)

    grid = [10, 100, 1000, 10000, 100000]
    tuning = []
    for b in grid:
        for held in COUNCILS:
            m = v2.Model(train, [c for c in COUNCILS if c != held], req, 1, b)
            tuning.append(dict(level='loco', held_out=held, a='', b=b, intensity=1.0, **v1.loglik(m, rows, held, None, False)))
        print('b', b, flush=True)
    for held in COUNCILS:
        flat = [dict(r, stratum='all') for r in train]
        m = v2.Model(flat, [c for c in COUNCILS if c != held], req, 1, 1e9)
        tuning.append(dict(level='loco_baseline_no_strata', held_out=held, a='', b='inf', intensity=1.0,
                           **v1.loglik(m, [dict(r, stratum='all') for r in rows if r['council'] == held], held, None, False)))
    score = lambda lv, key, val: sum(t['ll_per_record'] for t in tuning if t['level'] == lv and t[key] == val)
    best_b = max(grid, key=lambda b: score('loco', 'b', b))
    for aa in grid:
        m = v2.Model(train, COUNCILS, req, aa, best_b)
        for c in COUNCILS:
            k = v1.intensity_of(m, train, c, True)
            tuning.append(dict(level='in_distribution', held_out=c, a=aa, b=best_b, intensity=round(k, 3), **v1.loglik(m, rows, c, 'test', True, k)))
    best_a = max(grid, key=lambda aa: score('in_distribution', 'a', aa))
    with open(a.output / 'tuning_heldout_loglik.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(tuning[0].keys())); w.writeheader()
        w.writerows([{k: (float(v) if hasattr(v, 'dtype') else v) for k, v in t.items()} for t in tuning])
    print('best a', best_a, 'best b', best_b, flush=True)

    M = v2.Model(train, COUNCILS, req, best_a, best_b)
    intensity = {c: round(float(v1.intensity_of(M, train, c, False)), 3) for c in COUNCILS}
    intensity_cl = {c: round(float(v1.intensity_of(M, train, c, True)), 3) for c in COUNCILS}

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
    clus = v1.clustering(con, a.study, {r['record_id']: r for r in rows})

    # split file (UPRN-level: stays in the study folder) and per-council house style through the standalone entry point
    split_of = {}
    with gzip.open(a.output / 'split_assignments.csv.gz', 'wt', newline='') as fh:
        w = csv.writer(fh); w.writerow(['council', 'uprn', 'split'])
        for c, u, sp in con.execute('select x.council, x.uprn, s.split from ctx x join splitmap s using (council, split_key)').fetchall():
            split_of[(c, u)] = sp; w.writerow([c, u, sp])
    print('collision modifiers', flush=True)
    modifiers = collision_modifiers(con, train, req)
    print('name abbreviations', flush=True)
    name_abbr = name_abbreviations(con, a.study, split_of)
    house = {}
    for i, c in enumerate(COUNCILS):
        print('house style', c, flush=True)
        train_u = {u for (cc, u), sp in split_of.items() if cc == c and sp == 'train'}
        block, lookups = HS.fit_council(c, a.study / v1.REF[c] / 'components.csv.gz', a.study / v1.PAIRS[c], a.study / CLEAN[c], train_u,
                                       lookup_fix=a.lookup_fix)
        house[c] = json.loads(json.dumps(block))
        house[c]['style_edit_rates_taxonomy'] = None
        HS.write_lookups(a.output, lookups, append=i > 0)
    style_rates = defaultdict(Counter); style_n = Counter()
    for r in train:
        style_n[r['council']] += r['w']
        for s in r['style']:
            if not s.startswith('LO'):
                style_rates[r['council']][s] += r['w']
    for c in COUNCILS:
        house[c]['style_edit_rates_taxonomy'] = {k: round(v / style_n[c], 6) for k, v in sorted(style_rates[c].items(), key=lambda x: -x[1])}
    lb = {mid: {'name': tax_ids[mid]['name'], 'fit_status': tax_ids[mid].get('fit_status'),
                'rates': {c: (tax_ids[mid].get('rates') or {}).get(c) for c in COUNCILS}} for mid in ('LB1', 'LB2', 'LB3', 'LB4') if mid in tax_ids}
    exact_single = Counter()
    for r in train:
        if r['bundle'] and '|' not in r['bundle'] and r['bundle'].split(':')[0] in ('PN7', 'PN8', 'SU1', 'PN2') and r['effect'].startswith('exact:'):
            exact_single[r['effect'][6:]] += r['w']
    n_train = sum(r['w'] for r in train)
    hints = v2.realisation_hints(a.study)
    hints['PN3:number_replaced']['note'] = ('Mostly the house number written as a name (for example "THE COTTAGE, EXAMPLE ROAD" for '
                                            '"12, EXAMPLE ROAD"; a made-up illustration). Realise as: number dropped and a name added (the '
                                            'record\'s own name if it has one, else generic). The miner labels these PN4:number_dropped.')
    hints['BN4:name_replaced'] = {'note': 'Use core.name_word_abbreviations: real "partly changed" names are mostly one word abbreviated '
                                          '(PRESBYTERY to PSBTRY) or dropped, rarely a whole new name.'}

    profile = {
        'schema_version': '3.0', 'profile_id': 'uprn_corruption_profile_v3_20261013', 'status': 'candidate_for_freeze',
        'supersedes': 'uprn_corruption_profile_v2_20261012',
        'taxonomy_version': tax_version, 'house_style_ids': sorted(STYLE), 'per_building_ids': sorted(PER_BUILDING),
        'never_convention_ids': sorted(v1.NEVER_CONVENTION),
        'fitted_on': {'councils': COUNCILS, 'rows': f'{v1.TAX}/rates/rows_v2.csv.gz (discrepant rows weight 1, background sample weighted)',
                      'house_style': 'code/fit_house_style.py per council, every paired record of the training split (not weighted)',
                      'reference': v1.REF, 'pairs': v1.PAIRS, 'split': f'train (80% of building keys, salt {v0.SPLIT_SALT}); split_assignments.csv.gz',
                      'truth_verified': False, 'rows_without_context': missing,
                      'note': 'Rates are discrepancies under the council label, not verified error rates.'},
        'strata': {'definition': 'dwelling_type x rural, as v0', 'eligibility_flags': FLAGS,
                   'flag_definitions': 'code/flags_v2.py flags_of(row); collision flags: flags_v2.collision_flags(rows)',
                   'requirement_rule': 'learned on the v1 property flags, overlaid with the generator rule requirement (flags_v2.structural_requirement)'},
        'flag_vocabulary': {'abbreviations': F.ABBR, 'unit_words_regex': F.UNIT_RE.pattern, 'floor_regex': F.FLOOR_RE.pattern,
                            'slot_column': F.SLOT_COLUMN, 'county_words': HS.COUNTY_WORDS},
        'smoothing': {'council_to_stratum_a': best_a, 'stratum_to_global_b': best_b, 'bundle_min_rows': v1.BUNDLE_MIN_ROWS},
        'core': {
            'rate_unit': 'per eligible record: P(record gets bundle B | stratum, council) among records satisfying B.requires',
            'unrealisable_real_rows': {'weighted_total': round(sum(M.unrealisable.values()), 1),
                                       'top_bundles': {k: round(v, 1) for k, v in M.unrealisable.most_common(25)}},
            'background_text_edits_removed': {'rule': 'background rows: ST2 and TX1-TX3 on street/loc/town/dstreet go to house style',
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
            'collision_modifiers': {'use': 'multiply a bundle\'s rate by modifier[council or pooled][true|false] for each member listed here, '
                                           'using the record\'s collision flag (flags_v2.collision_flags). Unseen council: pooled. '
                                           'p_exact_given_hit_real is how often a real record whose drop could collide actually equals the other '
                                           'UPRN\'s string: the rest differ elsewhere (locality, punctuation, other edits). Use it as the verify '
                                           'target: when a realised record collides more often than this, keep the collision with probability '
                                           'p_exact_given_hit_real / synthetic share, else add a house-style difference or redraw.',
                                    'by_subtype': modifiers},
            'name_word_abbreviations': name_abbr,
            'realisation_hints': hints,
        },
        'clustering': clus,
        'label_drift': {'taxonomy': lb, 'observed_exact_single_slip_weighted_train': dict(exact_single),
                        'rate_per_record_by_relation': {k: round(v / n_train, 7) for k, v in exact_single.items()},
                        'share_attributed_to_label_drift_lambda': 0.5, 'lambda_status': 'prior; not identifiable without the verified subset',
                        'relation_to_mechanism': {'to_neighbour': 'LB1', 'to_parent': 'LB2', 'to_sibling': 'LB3', 'to_other': 'LB4'}},
        'house_style': house,
        'house_style_note': 'Keyed by council. Refit for a new council with code/fit_house_style.py; the core is never refitted.',
        'keying': {'status': 'measured as TX3 (core, per component); street/locality spelling in house style'},
        'disclosure': 'Mechanism IDs, rates, flags and generic single-word vocabulary only. Place-name, street-variant and split files are separate and not portable.',
    }
    (a.output / 'profile.json').write_text(json.dumps(profile, indent=1, default=float))
    for t in tuning:
        if (t['level'] == 'loco' and t['b'] == best_b) or t['level'].startswith('loco_base') or (t['level'] == 'in_distribution' and t['a'] == best_a):
            print({k: (round(float(v), 4) if isinstance(v, float) or hasattr(v, 'dtype') else v) for k, v in t.items()})
    print('intensity', intensity, intensity_cl)
    print('modifiers', {m: (d['pooled'], d.get('leeds')) for m, d in modifiers.items()})


if __name__ == '__main__':
    main()
