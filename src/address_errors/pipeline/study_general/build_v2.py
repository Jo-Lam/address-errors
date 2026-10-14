"""Render taxonomy v2: mechanisms.yaml, summary_by_mechanism.csv, rates_by_context.csv, examples_real.csv, README.md.
Usage: python build_v2.py <study_root> <v2_dir>. Development councils only; Cornwall and Derby are never read.
Generalised copy (study_general/): councils and paths from councils.py; see GENERALISATION.md."""
import sys, math, json, csv
import numpy as np, pandas as pd, yaml
ROOT, V2 = sys.argv[1:3]
sys.path.insert(0, f"{V2}/code")
from spec_v2 import M
import os
sys.path.insert(1, os.path.dirname(os.path.abspath(__file__)))
import councils as CFG   # generalised copy: council list and paths from the council config (GENERALISATION.md)
R = f"{V2}/rates"; CO = list(CFG.NAMES)
REFDIR = dict(CFG.REF)
PAIRS = {c: f"{ROOT}/{p}" for c, p in CFG.PAIRS.items()}
SY1_TAGGED = set()   # councils whose clean records carry systemic_truncation* tags (study: Basingstoke)
V1 = yaml.safe_load(open(f"{ROOT}/{CFG.TAXONOMY_V1}"))
V1M = {m["id"]: m for m in V1["mechanisms"]}
rates = pd.read_csv(f"{R}/rates_by_council.csv"); idn = pd.read_csv(f"{R}/identity_by_mechanism.csv")
subt = pd.read_csv(f"{R}/rates_by_subtype.csv"); cov = pd.read_csv(f"{R}/within_building_coverage.csv")
rows = pd.read_csv(f"{R}/rows_v2.csv.gz", dtype=str, keep_default_na=False)
rows["w"] = rows.w.astype(float); rows["ml"] = rows.mechs.str.split("|")

def wilson(k, n, z=1.96):
    p = k/n; d = 1+z*z/n; c = (p+z*z/(2*n))/d; h = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return max(0, c-h), min(1, c+h)

# ---- context rates (weighted numerators; denominators from all paired records)
ctx_rows = []
for c in CO:
    p = pd.read_csv(PAIRS[c], dtype=str, keep_default_na=False, usecols=["record_id", "label_uprn", "ngd_ftype"])
    p = p[p.ngd_ftype == "built"]
    if os.path.exists(f"{ROOT}/{CFG.CLEAN[c]}"):   # generic SY1 exclusion (no tags in Wigan, Bradford, Leeds)
        tg = pd.read_csv(f"{ROOT}/{CFG.CLEAN[c]}", dtype=str, keep_default_na=False, usecols=["record_id", "clean_tags"])
        trunc = set(tg.record_id[tg.clean_tags.str.contains("systemic_truncation")])
        if trunc: SY1_TAGGED.add(c)
        p = p[~p.record_id.isin(trunc)]
    comp = pd.read_csv(f"{ROOT}/{REFDIR[c]}/components.csv.gz", dtype=str, keep_default_na=False,
                       usecols=["uprn", "subname", "name", "number", "parentuprn", "number_type", "rm_subbuildingname"]).set_index("uprn")
    cm = comp.reindex(p.label_uprn).fillna("")
    hs = (cm.subname != "") | (cm.rm_subbuildingname != ""); hn = cm.name != ""; hu = cm.number != ""
    cdefs = {"all": np.ones(len(p), bool), "has_subunit": hs.values, "no_subunit": (~hs).values, "has_parent": (cm.parentuprn != "").values,
             "name_and_number": (hn & hu & ~hs).values, "name_no_number": (hn & ~hu & ~hs).values, "number_only": (~hn & hu & ~hs).values,
             "number_letter_suffix": (cm.number_type == "letter_suffix").values}
    ctxof = {k: dict(zip(p.record_id, v)) for k, v in cdefs.items()}
    rc = rows[rows.council == c]
    for k, v in cdefs.items():
        n = int(v.sum()); inctx = rc.record_id.map(ctxof[k]).fillna(False).astype(bool)
        for mid in sorted({x for L in rc.ml for x in L if x}):
            sel = rc[inctx & rc.ml.apply(lambda L: mid in L)]
            kk = sel.w.sum()
            if n: ctx_rows.append(dict(council=c, mechanism=mid, context=k, n_rows_weighted=round(kk, 1), n_context=n, rate=kk/n))
CTX = pd.DataFrame(ctx_rows); CTX.to_csv(f"{R}/rates_by_context.csv", index=False, float_format="%.6g")

def fit_status(mid, cells):
    if not cells: return None
    e = [v["n_clusters_with_event"] for v in cells.values()]
    if sum(e) < 30: return "too rare: pooled fixed rate only; not evaluable per fold"
    if min(e) >= 30 and len(e) == len(CO): return "fit per council"   # study: len(e) == 4 (all four councils)
    if max(e) >= 30: return "partial pooling (shrink sparse councils to pooled)"
    return "pooled across councils"

out, summ = [], []
for s in M:
    mid = s["id"]; d = dict(s)
    g = rates[rates.mechanism == mid]
    cells = {}
    for r in g.itertuples():
        cells[r.council] = dict(n_rows_observed=int(r.n_rows_observed), n_rows_weighted=float(r.n_rows_weighted), n_from_background_sample=int(r.n_from_background_sample),
                                n_records=int(r.n_records), rate=float(r.rate), ci_lo=float(r.cluster_boot_lo), ci_hi=float(r.cluster_boot_hi),
                                design_effect=None if r.design_effect != r.design_effect else round(float(r.design_effect), 1),
                                n_clusters_with_event=int(r.n_clusters_with_event))
    if s["change"] in ("unchanged_v1",) and mid in V1M:
        d["rates_v1"] = V1M[mid].get("rates"); d["fit_status"] = V1M[mid].get("fit_status")
    elif s["change"] in ("retired", "lifecycle", "bundle") and not cells:
        d["fit_status"] = {"retired": "retired", "lifecycle": "lifecycle layer (LC), not fitted", "bundle": "bundle: sample with co-occurrence"}[s["change"]]
    else:
        d["rates"] = cells
        fs = fit_status(mid, cells)
        if s["change"] == "retired_to_seed": fs = "seed only: fixed small rate, not fitted"
        if mid in ("SU11", "LO", "ST3"): fs = "per-council house style" + (" (Bradford 'Off' convention)" if mid == "ST3" else "")
        d["fit_status"] = fs
    deffs = [v["design_effect"] for v in cells.values() if v["design_effect"]]
    d["sample_per_building"] = bool(sum(x >= 20 for x in deffs) >= 2)
    cv = cov[cov.mechanism == mid]
    if len(cv): d["within_building"] = {r.council: dict(buildings=int(r.buildings_with_event), median_share_of_units=None if r.median_share_of_units_affected != r.median_share_of_units_affected else float(r.median_share_of_units_affected),
                                                        rows_in_top10_buildings=float(r.rows_in_top10_buildings_share)) for r in cv.itertuples()}
    for scope in ("all_rows", "single_edit_rows"):
        x = idn[(idn.mechanism == mid) & (idn.scope == scope)]
        if len(x):
            x = x.iloc[0]
            d.setdefault("observed_identity", {})[scope] = dict(n=int(x.n), n_tested=int(x.n_tested), collides_other_only=None if x.collides_other_only != x.collides_other_only else float(x.collides_other_only),
                                                                 collides_by_relation=x.collides_by_relation if isinstance(x.collides_by_relation, str) else "", drift_share=float(x.drift_share))
    st = subt[subt.mechanism == mid].groupby("subtype").n_rows_observed.sum().sort_values(ascending=False)
    if len(st): d["subtypes_rows_observed"] = {k.split(":", 1)[1]: int(v) for k, v in st.items()}
    if s["primary_context"] != "all":
        x = CTX[(CTX.mechanism == mid) & (CTX.context == s["primary_context"])]
        if len(x): d["rates_in_primary_context"] = {r.council: dict(n_rows_weighted=r.n_rows_weighted, n_context=int(r.n_context), rate=round(r.rate, 6)) for r in x.itertuples()}
    out.append(d)
    srow = dict(id=mid, name=s["name"], change=s["change"], replaces=s["replaces"], fit_status=d.get("fit_status"), sample_per_building=d["sample_per_building"])
    for c in CO:
        v = cells.get(c)
        srow[f"{c}_rows"] = v["n_rows_observed"] if v else ""; srow[f"{c}_per10k"] = round(v["rate"]*1e4, 3) if v else ""
        srow[f"{c}_ci"] = f"{v['ci_lo']*1e4:.2f}-{v['ci_hi']*1e4:.2f}" if v else ""; srow[f"{c}_buildings_or_streets"] = v["n_clusters_with_event"] if v else ""
    oi = d.get("observed_identity", {})
    srow["collides_all"] = oi.get("all_rows", {}).get("collides_other_only", ""); srow["collides_alone"] = oi.get("single_edit_rows", {}).get("collides_other_only", "")
    srow["n_alone"] = oi.get("single_edit_rows", {}).get("n", "")
    summ.append(srow)
pd.DataFrame(summ).to_csv(f"{R}/summary_by_mechanism.csv", index=False)
def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items() if v is not None and v != "" and v != {}}
    if isinstance(o, list): return [clean(v) for v in o]
    if isinstance(o, float): return round(o, 7) if o == o else None
    if hasattr(o, "item"): return o.item()
    return o
Y = dict(version="taxonomy_v2_20261012", supersedes="taxonomy/mechanisms.yaml (v1)",
         basis="every aligned edit (discovery/v1_20261012) gets exactly one mechanism; rate = share of records with >=1 such edit; discrepancy rows complete, non-discrepant rows from a 4,000-row weighted sample per council",
         development_councils=[c + (" (SY1-truncated rows excluded from rates; SY1 is a final deterministic step)" if c in SY1_TAGGED else "") for c in CO],
         external_test_never_used=[c for c in CFG.EXTERNAL_TEST if c not in CO],
         mechanisms=clean(out))
yaml.safe_dump(Y, open(f"{V2}/mechanisms.yaml", "w"), sort_keys=False, allow_unicode=True, width=120)

# ---- examples (address-level, internal): single-edit discrepancy rows per subtype
# same row order as classify_edits.py (discovery councils, then each separately aligned council in config order)
_E = [pd.read_csv(f"{ROOT}/{CFG.DISCOVERY_DIR}/edit_ops_clustered.csv.gz", dtype=str, keep_default_na=False)] if CFG.DISCOVERY else []
_A = [pd.read_csv(f"{ROOT}/{CFG.DISCOVERY_DIR}/aligned_rows.csv.gz", dtype=str, keep_default_na=False)] if CFG.DISCOVERY else []
if CFG.DISCOVERY:
    _E[0] = _E[0][_E[0].council.isin(CFG.DISCOVERY)]; _A[0] = _A[0][_A[0].council.isin(CFG.DISCOVERY)]
for _c in CFG.SEPARATE:
    _E.append(pd.read_csv(f"{CFG.align_dir(V2, _c)}/edit_ops.csv.gz", dtype=str, keep_default_na=False))
    _A.append(pd.read_csv(f"{CFG.align_dir(V2, _c)}/aligned_rows.csv.gz", dtype=str, keep_default_na=False))
E = pd.concat(_E, ignore_index=True)
L2 = pd.read_csv(f"{R}/edit_v2_labels.csv.gz", dtype=str, keep_default_na=False)
E["v2_sub"] = L2.v2_sub.values
A = pd.concat(_A).set_index("record_id")
single = set(rows[(rows.subset == "dwelling_diff") & (rows.n_dwelling_edits == "1")].record_id)
ex = []
for st, g in E[E.record_id.isin(single) & ~E.v2_sub.str.startswith("LO")].groupby("v2_sub"):
    for r in g.sample(min(3, len(g)), random_state=1).itertuples():
        a = A.loc[r.record_id]
        ex.append(dict(mechanism=st.split(":")[0].split("|")[0], subtype=st, council=r.council, recorded_address=a.recorded_address, canonical=a.canon_address,
                       collision=a.collision, collision_relation=a.collision_relation, v1_labels=a.labels_nearest))
EXD = pd.DataFrame(ex); EXD.to_csv(f"{V2}/examples_real.csv", index=False)
json.dump({"n_mech": len(out)}, open(f"{V2}/code/_build_info.json", "w"))
print("mechanisms", len(out), "examples", len(EXD))
