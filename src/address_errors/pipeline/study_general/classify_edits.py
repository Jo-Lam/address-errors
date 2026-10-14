"""Taxonomy v2: give every aligned edit from the discovery run exactly one v2 mechanism ID, then compute
per-council rates (rows with >=1 edit of the mechanism), building-clustered bootstrap CIs, collision shares
(all rows and single-edit rows), within-building coverage, and edits per discrepant row.

Input: discovery/v1_20261012/{edit_ops_clustered,aligned_rows}.csv.gz (Wigan, Bradford, Leeds; background rows
weighted), mined_error_pairs/v2_20261012/pairs_<c>.csv.gz (denominators and clusters), reference components.
Cornwall and Derby are never read. Usage: python classify_edits.py <study_root> <out_dir>
Generalised copy (study_general/): councils, paths and weights from councils.py; see GENERALISATION.md.
"""
import sys, os, re, math
from collections import Counter, defaultdict
import numpy as np, pandas as pd
ROOT, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=False)
sys.path.insert(0, f"{ROOT}/discovery/code")
from families import FAMILIES
C2F = {c: f[:3] for f, cs in FAMILIES.items() for c in cs}
sys.path.insert(1, os.path.dirname(os.path.abspath(__file__)))
import councils as CFG   # generalised copy: council list and paths from the council config (GENERALISATION.md)
REFDIR = dict(CFG.REF)   # study: reference/<ngd dir>/<council>, joined below as f"{ROOT}/{REFDIR[c]}"
PAIRS = {c: f"{ROOT}/{p}" for c, p in CFG.PAIRS.items()}
LO_SLOTS = {"LOC", "TOWN", "TOWN>EOS", "STREET>TOWN", "STREET>LOC", "LOC>TOWN", "TOWN>TOWN", "LOC>LOC", "LOC>EOS"}
CO = list(CFG.NAMES)
D = f"{ROOT}/{CFG.DISCOVERY_DIR}"

UNIT = set("FLAT FLATS APARTMENT APARTMENTS APT APTS UNIT UNITS MAISONETTE ROOM ROOMS BEDSIT STUDIO SITE CARAVAN CHALET PITCH BERTH STUDIOS FLT FLTS".split())
FLOOR = set("GROUND GRD GND FIRST 1ST SECOND 2ND THIRD 3RD FOURTH 4TH FIFTH 5TH BASEMENT LOWER TOP FLOOR FLOORS FLR GF FF SF TF MEZZANINE ATTIC LG".split())
FLOOR_ORD = {"GROUND": 0, "GRD": 0, "GND": 0, "GF": 0, "FIRST": 1, "1ST": 1, "FF": 1, "SECOND": 2, "2ND": 2, "SF": 2,
             "THIRD": 3, "3RD": 3, "TF": 3, "FOURTH": 4, "4TH": 4, "FIFTH": 5, "5TH": 5, "BASEMENT": -1}
POSITION = set("FRONT REAR BACK LEFT RIGHT MIDDLE MID UPPER SIDE".split())
DQ1W = set("ADJ ADJACENT OPPOSITE OPP NEAR BEHIND".split())
DQ1P = ["REAR OF", "LAND AT", "LAND ADJ", "NEXT TO", "PART OF", "R/O"]
DQ2W = set("NEW PLOT PLOTS DEVELOPMENT PROPOSED BUILD CONSTRUCTION".split())
DQ3W = set("ABOVE OVER CARETAKER CARETAKERS CARETAKER'S WARDEN WARDENS MANAGER MANAGERS STAFF ACCOMMODATION LIVING CONVERSION STABLE STABLES SHOP".split())
ANNEX = set("ANNEX ANNEXE ANNEXES".split())
GENERIC = {"BUNGALOW", "COTTAGE", "LODGE", "COACH", "PRESBYTERY", "VICARAGE", "RECTORY", "FARMHOUSE", "BARN", "MANSE", "GATEHOUSE"}
CONNECT = {"AT", "&", "AND", "OF", "-", ","}

def toks(s): return [t for t in re.split(r"[\s,]+", s.upper()) if t]
def has_digit(s): return any(ch.isdigit() for ch in s)

def classify_ins(t, building_level, slot):
    """Return list of (mech, subtype) for one inserted text."""
    T = toks(t); out = []
    if "AT" in T:
        out.append(("FM8", "at_connective_added")); T = [x for x in T if x != "AT"]
    if not T: return out
    s = " ".join(T); S = set(T)
    if "OFF" in S: return out + [("ST3", "access_road_off_added")]
    if S & DQ2W: return out + [("DQ2", "added")]
    if S & ANNEX: return out + [("SU8", "annex_added")]
    if S & DQ3W: return out + [("DQ3", "use_descriptor_added")]
    if S & DQ1W or any(p in s for p in DQ1P): return out + [("DQ1", "added")]
    subish = bool(S & (UNIT | FLOOR | POSITION)) or (slot in ("BOS>SUB", "SUB>SUB", "SUB>NUM", "SUB>NAME") and has_digit(s) and len(T) <= 3)
    if subish:
        if building_level: return out + [("SU15", "subunit_added_on_building_uprn" + ("_span" if ("ROOMS" in S or "TO" in S or "-" in s) else ""))]
        if S & FLOOR: return out + [("SU4", "floor_descriptor_added")]
        if S & POSITION: return out + [("SU6", "position_added")]
        if S & UNIT and not has_digit(s): return out + [("SU13", "unit_word_added")]
        return out + [("PN6", "unit_id_added")]
    if S & GENERIC: return out + [("BN3", "generic_name_added")]
    if all(x in CONNECT for x in T): return out + [("FM8", "connective_added")]
    if has_digit(s) and len(T) == 1: return out + [("PN6", "number_added")]
    if slot in ("NAME>NAME",): return out + [("BN2", "name_elaborated")]
    if slot in ("NAME>STREET", "STREET>STREET", "DSTREET>STREET"): return out + [("ST3", "dependent_or_estate_name_added")]
    if slot.endswith(">ORG") or slot.startswith("ORG>"): return out + [("BN8", "organisation_added")]
    return out + [("BN1", "name_added")]

def classify_del(t, slot, full, has_parent):
    T = toks(t); S = set(T); s = " ".join(T)
    if slot == "SUB":
        if S <= {"AT"}: return [("FM8", "at_connective_dropped")]
        if full and not has_digit(s):
            if S & ANNEX: return [("SU8", "annex_dropped")]
            return [("SU7", "numberless_subunit_dropped")]
        if full: return [("SU7", "whole_subunit_with_id_dropped")]
        if has_digit(s): return [("SU7", "unit_span_dropped" if ("TO" in S or "-" in s or "ROOMS" in S) else "unit_id_dropped")]
        if S & FLOOR: return [("SU4", "floor_descriptor_dropped")]
        if S & POSITION: return [("SU6", "position_dropped")]
        if S - {"AT"} <= UNIT: return [("SU13", "unit_word_dropped")] + ([("FM8", "at_connective_dropped")] if "AT" in S else [])
        if S & DQ3W: return [("DQ3", "use_descriptor_dropped")]
        return [("SU13", "other_subunit_text_dropped")]
    if slot == "NAME":
        if has_digit(s) and len(T) <= 2: return [("PN4", "number_in_name_dropped")]
        if full: return [("BN3" if S & GENERIC else "BN1", "generic_name_dropped" if S & GENERIC else "name_dropped")]
        return [("BN2", "name_shortened")]
    if slot == "NUM": return [("PN4", "number_dropped")]
    if slot == "STREET": return [("ST5", "street_omitted")] if full else [("ST2", "street_words_dropped")]
    if slot == "ORG": return [("BN8", "organisation_dropped")]
    if slot in ("LOC", "TOWN", "DSTREET"): return [("LO", slot.lower() + "_dropped")] if slot != "DSTREET" else [("ST3", "dependent_street_dropped")]
    return [("UNRESOLVED", "del_" + slot)]

def classify_sub(op, slot, rel, d, i, row_has_street_change):
    if rel in ("council_shorter_subsequence",): return [("TX1", "abbreviated_" + slot.lower())]
    if rel in ("council_longer_supersequence",): return [("TX1", "expanded_" + slot.lower())]
    if rel in ("tokens_joined", "token_split"): return [("TX2", rel + "_" + slot.lower())]
    if rel in ("edit1", "edit2"): return [("TX3", rel + "_" + slot.lower())]
    if rel == "punct_only": return [("FM9", "punctuation_" + slot.lower())]
    if rel == "num_leading_zero": return [("FM6", "leading_zero")]
    if rel.startswith("num_suffix"): return [("SU1", rel.replace("num_", ""))]
    if rel == "num_range_collapsed": return [("PN2", "range_collapsed" + ("_unit" if slot == "SUB" else ""))]
    if rel == "num_range_extended": return [("PN2", "range_extended" + ("_unit" if slot == "SUB" else ""))]
    if rel == "num_range_vs_single_other": return [("PN2", "range_vs_other_single" + ("_unit" if slot == "SUB" else ""))]
    if rel.startswith("num_delta_"):
        return [("PN7" if slot in ("NUM", "NAME") else "PN8", rel.replace("num_", ""))]
    if rel == "num_one_digit_changed": return [("PN3" if slot in ("NUM", "NAME") else "PN8", "one_digit_changed")]
    if rel in ("num_digit_dropped", "num_digits_transposed", "num_digit_added", "num_int_and_suffix_changed"):
        return [("PN3", rel.replace("num_", ""))]
    if rel == "num_other":
        if row_has_street_change: return [("LB4", "number_and_street_changed")]
        return [("PN3", "number_other")]
    if rel.startswith("id_") or rel.startswith("letter_digit"): return [("SU14", rel)]
    if rel in ("replaced", "word_replaced"):
        D_, I_ = set(toks(d)), set(toks(i))
        if slot == "SUB":
            if (D_ | I_) <= (FLOOR | UNIT | POSITION | {"AT"}):
                od = {FLOOR_ORD[x] for x in D_ if x in FLOOR_ORD}; oi = {FLOOR_ORD[x] for x in I_ if x in FLOOR_ORD}
                if od and oi: return [("SU5", "floor_vocabulary")] if od == oi else [("SU3", "floor_changed")]
                if (D_ | I_) & UNIT and not ((D_ | I_) & FLOOR): return [("SU10", "unit_word_swapped")]
                if "TOP" in D_ | I_: return [("SU5", "top_vs_ordinal")]
                return [("SU10", "unit_or_floor_word_swapped")]
            if has_digit(d) and has_digit(i): return [("SU14", "unit_id_rewritten")]
            if has_digit(d) and not has_digit(i): return [("SU7", "unit_id_lost_in_rewrite")]
            if has_digit(i) and not has_digit(d): return [("PN6", "unit_id_added_in_rewrite")]
            return [("SU10", "subunit_text_replaced")]
        if slot == "NAME": return [("BN4", "name_replaced")]
        if slot == "STREET": return [("LB4" if row_has_num_change.get(cur_row, False) else "ST4", "street_replaced")]
        if slot == "NUM": return [("LB4", "number_and_street_changed")] if row_has_street_change else [("PN3", "number_replaced")]
        if slot == "ORG": return [("BN8", "organisation_replaced")]
        if slot in ("LOC", "TOWN"): return [("LO", "locality_replaced")]
        if slot == "DSTREET": return [("ST3", "dependent_street_replaced")]
    return [("UNRESOLVED", f"{op}_{slot}_{rel}")]

# discovery-run councils (study: Wigan, Bradford, Leeds): clustered edits with fixed background weights
if CFG.DISCOVERY:
    E = pd.read_csv(f"{D}/edit_ops_clustered.csv.gz", dtype=str, keep_default_na=False)
    A = pd.read_csv(f"{D}/aligned_rows.csv.gz", dtype=str, keep_default_na=False)
    E = E[E.council.isin(CFG.DISCOVERY)].reset_index(drop=True)   # no-op for the default config
    A = A[A.council.isin(CFG.DISCOVERY)].reset_index(drop=True)
    E_COLS = list(E.columns)
else:
    E = A = None
    E_COLS = None
# separately aligned councils (study: Basingstoke): same discovery code (align.py, SY1-truncated rows excluded), no clusters
import json as _json
BG_W = dict(CFG.FIXED_BG_W)
for _c in CFG.SEPARATE:
    BD = CFG.align_dir(os.path.dirname(OUT.rstrip("/")), _c)
    bw = _json.load(open(f"{BD}/align_audit.json"))[_c]["background_weight"]
    EB = pd.read_csv(f"{BD}/edit_ops.csv.gz", dtype=str, keep_default_na=False)
    EB["w"] = np.where(EB.subset == "background", str(bw), "1.0"); EB["cluster"] = ""; EB["signature"] = ""
    AB = pd.read_csv(f"{BD}/aligned_rows.csv.gz", dtype=str, keep_default_na=False)
    if E is None:   # no discovery councils: discovery column order (w, cluster, signature appended)
        E_COLS = [c for c in EB.columns if c not in ("w", "cluster", "signature")] + ["w", "signature", "cluster"]
        E, A = EB[E_COLS], AB
    else:
        E = pd.concat([E, EB[E_COLS]], ignore_index=True)
        A = pd.concat([A, AB], ignore_index=True)
    BG_W[_c] = bw
BG_W = {c: BG_W[c] for c in CO}
E = E.rename(columns={"del": "deltxt"}); E["fam"] = E.cluster.map(C2F)
# canonical context from reference components
ctx = {}
for c in CO:
    comp = pd.read_csv(f"{ROOT}/{REFDIR[c]}/components.csv.gz", dtype=str, keep_default_na=False,
                       usecols=["uprn", "subname", "rm_subbuildingname", "parentuprn", "rootuprn", "usrn", "hierarchylevel"])
    ctx[c] = comp.set_index("uprn")
lab = dict(zip(A.record_id, A.label_uprn))
def building_level(c, u):
    try: r = ctx[c].loc[u]
    except KeyError: return False
    return r.subname == "" and r.rm_subbuildingname == "" and r.parentuprn == ""
street_change = set(E[(E.slot == "STREET") & E.op.isin(["REPL", "SUB"]) & E.rel.isin(["replaced", "word_replaced"])].record_id)
num_change = set(E[(E.slot.isin(["NUM"])) & (E.rel.isin(["num_other", "replaced"]))].record_id)
row_has_num_change = {r: True for r in num_change}

mech, sub = [], []
for r in E.itertuples():
    cur_row = r.record_id
    if r.slot in LO_SLOTS and r.op in ("INS", "DEL") and "OFF" not in toks(r.ins): res = [("LO", "locality_town_county_style")]
    elif r.fam == "F23" and r.op in ("SUB", "REPL"): res = [("SU14", r.rel or "recode")]
    elif r.op == "MOVE": res = [("SU11", r.rel)]
    elif r.op == "INS": res = classify_ins(r.ins, building_level(r.council, lab[r.record_id]), r.slot)
    elif r.op == "DEL": res = classify_del(r.deltxt, r.slot, r.full_slot == "True", None)
    else: res = classify_sub(r.op, r.slot, r.rel, r.deltxt, r.ins, r.record_id in street_change)
    if r.fam == "F23" and r.op in ("INS", "DEL"):  # recode buildings: inserted/deleted id fragments belong to the recode
        res = [("SU14", "recode_" + r.op.lower()) if m not in ("FM8",) else (m, s) for m, s in res]
    mech.append("|".join(m for m, s in res)); sub.append("|".join(f"{m}:{s}" for m, s in res))
E["v2"] = mech; E["v2_sub"] = sub
E.drop(columns=["deltxt", "ins"]).to_csv(f"{OUT}/edit_v2_labels.csv.gz", index=False)  # no address text
EX = E.explode("v2_sub")
EX = E.assign(v2_sub=E.v2_sub.str.split("|")).explode("v2_sub")
EX["v2"] = EX.v2_sub.str.split(":").str[0]
print("unresolved edits", (EX.v2 == "UNRESOLVED").sum(), "of", len(EX))
print(EX[EX.v2 == "UNRESOLVED"].v2_sub.value_counts().head(10).to_dict())

# ---- rows: weights, clusters, collision
w = dict(zip(E.record_id, E.w.astype(float)))
A["w"] = A.subset.map({"dwelling_diff": 1.0}).fillna(0.0)
aw = E.drop_duplicates("record_id").set_index("record_id").w.astype(float)
A["w"] = A.record_id.map(aw).fillna(A.apply(lambda r: BG_W[r.council] if r.subset == "background" else 1.0, axis=1))
nonlo = EX[EX.v2 != "LO"].groupby("record_id").size()
A["n_dwelling_edits"] = A.record_id.map(nonlo).fillna(0).astype(int)
rowmech = EX[EX.v2 != "LO"].groupby("record_id").v2.apply(lambda s: sorted(set(s)))
rowsub = EX.groupby("record_id").v2_sub.apply(lambda s: sorted(set(s)))
A["mechs"] = A.record_id.map(rowmech).apply(lambda x: x if isinstance(x, list) else [])
A["subs"] = A.record_id.map(rowsub).apply(lambda x: x if isinstance(x, list) else [])
A["has_LO"] = A.record_id.isin(set(EX[EX.v2 == "LO"].record_id))

rate_rows, ident_rows, cov_rows, sub_rows = [], [], [], []
B = 400; rng = np.random.default_rng(20261012)
def wilson(k, n, z=1.96):
    if n <= 0: return (np.nan, np.nan)
    p = min(max(k/n, 0), 1); d = 1+z*z/n; c = (p+z*z/(2*n))/d; h = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return max(0, c-h), min(1, c+h)
for c in CO:
    p = pd.read_csv(PAIRS[c], dtype=str, keep_default_na=False, usecols=["record_id", "label_uprn", "ngd_ftype"])
    p = p[p.ngd_ftype == "built"]
    # SY1-truncated rows out of the denominator, for every council with systemic_truncation* tags (study: Basingstoke
    # only; Wigan, Bradford and Leeds have no such tags, so this is the same result)
    if os.path.exists(f"{ROOT}/{CFG.CLEAN[c]}"):
        tg = pd.read_csv(f"{ROOT}/{CFG.CLEAN[c]}", dtype=str, keep_default_na=False, usecols=["record_id", "clean_tags"])
        p = p[~p.record_id.isin(set(tg.record_id[tg.clean_tags.str.contains("systemic_truncation")]))]
    p = p.reset_index(drop=True)
    cm = ctx[c].reindex(p.label_uprn)
    inh = (cm.parentuprn.fillna("").values != "") | cm.hierarchylevel.isin(["2", "3"]).values
    cl = np.where(inh, "b:" + cm.rootuprn.fillna("").values, np.where(cm.usrn.fillna("").values != "", "s:" + cm.usrn.fillna("").values, "r:" + p.label_uprn.values))
    codes, cidx = np.unique(cl, return_inverse=True); Cn = len(codes)
    rid2cl = dict(zip(p.record_id, cidx)); rid2root = dict(zip(p.record_id, cl))
    N = len(p); M = np.bincount(cidx, minlength=Cn).astype(float)
    a = A[(A.council == c) & A.record_id.isin(rid2cl)].copy()
    a["cl"] = a.record_id.map(rid2cl)
    keys = sorted({m for L in a.mechs for m in L}) + ["LO", "ANY_DWELLING_EDIT"]
    subkeys = sorted({s for L in a.subs for s in L})
    K = np.zeros((Cn, len(keys)))
    for j, k in enumerate(keys):
        if k == "ANY_DWELLING_EDIT": sel = a[a.n_dwelling_edits > 0]
        elif k == "LO": sel = a[a.has_LO]
        else: sel = a[a.mechs.apply(lambda L: k in L)]
        np.add.at(K[:, j], sel.cl.values, sel.w.values)
    W = rng.multinomial(Cn, np.full(Cn, 1/Cn), size=B).astype(float)
    boot = (W @ K) / (W @ M)[:, None]
    lo, hi = np.percentile(boot, [2.5, 97.5], axis=0)
    for j, k in enumerate(keys):
        kk = K[:, j].sum(); r = kk/N
        vb = boot[:, j].var(); vbin = r*(1-r)/N if 0 < r < 1 else np.nan
        sel_rows = a[a.mechs.apply(lambda L: k in L)] if k not in ("LO", "ANY_DWELLING_EDIT") else a[a.has_LO] if k == "LO" else a[a.n_dwelling_edits > 0]
        rate_rows.append(dict(council=c, mechanism=k, n_rows_weighted=round(kk, 1), n_rows_observed=len(sel_rows),
                              n_from_background_sample=int((sel_rows.subset == "background").sum()), n_records=N, rate=r,
                              cluster_boot_lo=lo[j], cluster_boot_hi=hi[j], design_effect=vb/vbin if vbin else np.nan,
                              n_clusters_with_event=int((K[:, j] > 0).sum()), n_clusters=Cn))
    for s in subkeys:
        sel = a[a.subs.apply(lambda L: s in L)]
        sub_rows.append(dict(council=c, mechanism=s.split(":")[0], subtype=s, n_rows_weighted=round(sel.w.sum(), 1), n_rows_observed=len(sel), rate=sel.w.sum()/N))
    # within-building coverage: among buildings (b: clusters) with >=1 row of mechanism, share of the building's records with it
    a["root"] = a.record_id.map(rid2root)
    bsize = pd.Series(cl).value_counts()
    for k in keys[:-2]:
        sel = a[a.mechs.apply(lambda L: k in L) & a.root.str.startswith("b:") & (a.subset == "dwelling_diff")]
        if len(sel) == 0: continue
        g = sel.groupby("root").w.sum()
        sizes = bsize.reindex(g.index)
        multi = sizes[sizes >= 4]
        cov = (g.reindex(multi.index) / multi)
        cov_rows.append(dict(council=c, mechanism=k, buildings_with_event=len(g), buildings_ge4_units=len(multi),
                             median_share_of_units_affected=round(float(cov.median()), 3) if len(cov) else np.nan,
                             share_buildings_ge50pct=round(float((cov >= 0.5).mean()), 3) if len(cov) else np.nan,
                             rows_in_top10_buildings_share=round(float(g.sort_values(ascending=False).head(10).sum()/g.sum()), 3)))
    print(c, "records", N, "aligned", len(a))

R = pd.DataFrame(rate_rows); R.to_csv(f"{OUT}/rates_by_council.csv", index=False, float_format="%.6g")
pd.DataFrame(sub_rows).to_csv(f"{OUT}/rates_by_subtype.csv", index=False, float_format="%.6g")
pd.DataFrame(cov_rows).to_csv(f"{OUT}/within_building_coverage.csv", index=False)
# identity: discrepant rows only (unweighted), all rows and single-dwelling-edit rows
dd = A[A.subset == "dwelling_diff"]
for scope, sel in (("all_rows", dd), ("single_edit_rows", dd[dd.n_dwelling_edits == 1])):
    for k in sorted({m for L in sel.mechs for m in L}):
        s = sel[sel.mechs.apply(lambda L: k in L)]
        t = s[s.collision != "not_tested"]
        oo = t[t.collision == "matches_other_only"]
        ident_rows.append(dict(mechanism=k, scope=scope, n=len(s), n_tested=len(t),
                               collides_other_only=round(len(oo)/len(t), 4) if len(t) else np.nan,
                               collides_by_relation="; ".join(f"{x} {n}" for x, n in oo.collision_relation.value_counts().items()),
                               drift_share=round((s.drift_relation != "").mean(), 4),
                               drift_by_relation="; ".join(f"{x} {n}" for x, n in s[s.drift_relation != ""].drift_relation.value_counts().items())))
    # subtype identity on single-edit rows
pd.DataFrame(ident_rows).to_csv(f"{OUT}/identity_by_mechanism.csv", index=False)
si = []
for s_ in sorted({x for L in dd.subs for x in L}):
    s = dd[dd.subs.apply(lambda L: s_ in L) & (dd.n_dwelling_edits == 1)]
    t = s[s.collision != "not_tested"]
    if len(t): si.append(dict(subtype=s_, single_edit_rows=len(s), collides_other_only=round((t.collision == "matches_other_only").mean(), 4),
                             main_relation=t[t.collision == "matches_other_only"].collision_relation.value_counts().head(1).to_dict()))
pd.DataFrame(si).to_csv(f"{OUT}/identity_by_subtype_single_edit.csv", index=False)
# edits per discrepant row and labels per single-edit row
ep = dd.groupby("council").n_dwelling_edits.describe()
ep.to_csv(f"{OUT}/dwelling_edits_per_discrepant_row.csv")
dist = dd.groupby(["council", dd.n_dwelling_edits.clip(upper=5)]).size().unstack(fill_value=0)
dist.to_csv(f"{OUT}/dwelling_edits_per_discrepant_row_dist.csv")
print(dist)
# v1 label vs v2 mechanism crosswalk on single-edit rows
cw = Counter()
for r in dd[dd.n_dwelling_edits == 1].itertuples():
    v1 = sorted({x.split(":")[0] for x in r.labels_nearest.split("|") if x}) or ["(none)"]
    for m in r.mechs:
        for l in v1: cw[(l, m)] += 1
pd.DataFrame([dict(v1_label=a_, v2_mechanism=b_, single_edit_rows=n) for (a_, b_), n in cw.items()]).sort_values(["v1_label", "single_edit_rows"], ascending=[True, False]).to_csv(f"{OUT}/crosswalk_v1_to_v2_single_edit.csv", index=False)
A.assign(mechs=A.mechs.str.join("|"))[["record_id", "council", "subset", "label_uprn", "w", "n_dwelling_edits", "mechs", "collision", "collision_relation", "drift_relation"]].to_csv(f"{OUT}/rows_v2.csv.gz", index=False)
print("done")
