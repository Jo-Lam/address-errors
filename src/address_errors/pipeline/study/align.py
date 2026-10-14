"""Step 1 of bottom-up discovery: align each council string with its nearest
canonical rendering (NGD or Royal Mail PAF), token by token, and write every
non-identity edit as one row.

No mechanism labels are read here. Canonical tokens carry a slot tag taken
from the reference components (SUB, NAME, NUM, STREET, ...), so each edit is
located component by component.

Usage: python align.py <study_root> <out_dir> [n_background_per_council]
"""
import re
import sys
import json
import random
from pathlib import Path

import pandas as pd
from rapidfuzz.distance import Levenshtein
from rapidfuzz import fuzz

COUNCILS = ["wigan", "bradford", "leeds"]
EXTERNAL_TEST = {"cornwall", "derby"}  # never read


def find_pairs(root, council):
    """Newest mined pairs file for this council (v2 first, then any later run)."""
    hits = sorted((root / "mined_error_pairs").rglob(f"pairs_{council}.csv.gz"), key=lambda p: p.stat().st_mtime)
    if not hits:
        raise FileNotFoundError(f"no mined pairs for {council}")
    return hits[-1]


def find_components(root, council):
    for d in ("ngd_20261001", "ngd_20261001_v2_new_councils"):
        p = root / "reference" / d / council / "components.csv.gz"
        if p.exists():
            return p
    raise FileNotFoundError(f"no reference components for {council}")

NGD_SLOTS = [("organisationname", "ORG"), ("subname", "SUB"), ("name", "NAME"),
             ("number", "NUM"), ("streetname", "STREET"), ("locality", "LOC"),
             ("townname", "TOWN")]
RM_SLOTS = [("rm_organisationname", "ORG"), ("rm_subbuildingname", "SUB"),
            ("rm_buildingname", "NAME"), ("rm_buildingnumber", "NUM"),
            ("rm_dependentthoroughfare", "DSTREET"), ("rm_thoroughfare", "STREET"),
            ("rm_dependentlocality", "LOC"), ("rm_posttown", "TOWN")]

_DROP = re.compile(r"(?<!\d)\.|\.(?!\d)|['\u2019`]")  # keep 3.41-style unit ids
_SPACE = re.compile(r"[,;:()\[\]\"]+|\s+")


def tokens(s):
    if not isinstance(s, str) or not s.strip():
        return []
    s = _DROP.sub("", s.upper())
    return [t for t in _SPACE.split(s) if t and t != "-"]


def canon_tokens(row, slots):
    out = []
    for col, tag in slots:
        for t in tokens(row.get(col)):
            out.append((t, tag))
    return out


def alnum(t):
    return re.sub(r"[^A-Z0-9]", "", t)


def has_digit(t):
    return any(ch.isdigit() for ch in t)


def is_subseq(short, long_):
    it = iter(long_)
    return all(ch in it for ch in short)


def sim(c, r):
    if c == r:
        return 3.0
    ca, ra = alnum(c), alnum(r)
    if ca and ca == ra:
        return 2.5
    dc, dr = has_digit(c), has_digit(r)
    if dc != dr:
        return -3.0
    if dc and dr:
        return 0.5
    if len(ra) < len(ca) and ra and ra[0] == ca[0] and is_subseq(ra, ca):
        return 1.5
    if len(ca) < len(ra) and ca and ca[0] == ra[0] and is_subseq(ca, ra):
        return 1.5
    f = fuzz.ratio(ca, ra)
    if f >= 80:
        return 1.5
    if f >= 60:
        return 0.3
    return -2.5


GAP = -1.0


def nw(c, r):
    """Global alignment of canonical tokens c and council tokens r.
    Returns a list of (ci or None, ri or None)."""
    n, m = len(c), len(r)
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    B = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        S[i][0], B[i][0] = i * GAP, 1
    for j in range(1, m + 1):
        S[0][j], B[0][j] = j * GAP, 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d = S[i - 1][j - 1] + sim(c[i - 1], r[j - 1])
            u = S[i - 1][j] + GAP
            lft = S[i][j - 1] + GAP
            if d >= u and d >= lft:
                S[i][j], B[i][j] = d, 0
            elif u >= lft:
                S[i][j], B[i][j] = u, 1
            else:
                S[i][j], B[i][j] = lft, 2
    i, j, path = n, m, []
    while i > 0 or j > 0:
        b = B[i][j]
        if i > 0 and j > 0 and b == 0:
            path.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i > 0 and (j == 0 or b == 1):
            path.append((i - 1, None)); i -= 1
        else:
            path.append((None, j - 1)); j -= 1
    return path[::-1]


NUMRE = re.compile(r"^(\d+)([A-Z]?)$")


def relation(c, r):
    """Data-level relation between a canonical token and the council token
    aligned to it. Purely string arithmetic, no lexicon."""
    ca, ra = alnum(c), alnum(r)
    if ca == ra:
        return "punct_only"
    if has_digit(c) and has_digit(r):
        rng = re.compile(r"^(\d+[A-Z]?)[-/](\d+[A-Z]?)$")
        if rng.match(r) and not rng.match(c):
            return "num_range_extended" if rng.match(r).group(1) == c else "num_range_vs_single_other"
        if rng.match(c) and not rng.match(r):
            return "num_range_collapsed" if rng.match(c).group(1) == r else "num_range_vs_single_other"
        mc, mr = NUMRE.match(ca), NUMRE.match(ra)
        if mc and mr:
            ic, sc = int(mc.group(1)), mc.group(2)
            ir, sr = int(mr.group(1)), mr.group(2)
            if ic == ir:
                if mc.group(1) != mr.group(1):
                    return "num_leading_zero"
                if sc and not sr:
                    return "num_suffix_dropped"
                if sr and not sc:
                    return "num_suffix_added"
                return "num_suffix_swapped"
            dd = ir - ic
            if sc != sr:
                return "num_int_and_suffix_changed"
            if abs(dd) <= 2:
                return f"num_delta_{'+' if dd > 0 else '-'}{abs(dd)}"
            a, b = mc.group(1), mr.group(1)
            if len(a) == len(b) and sorted(a) == sorted(b):
                return "num_digits_transposed"
            if len(a) == len(b) and Levenshtein.distance(a, b) == 1:
                return "num_one_digit_changed"
            if abs(len(a) - len(b)) == 1 and (is_subseq(b, a) or is_subseq(a, b)):
                return "num_digit_dropped" if len(b) < len(a) else "num_digit_added"
            return "num_other"
        dc_, dr_ = re.sub(r"\D", "", ca), re.sub(r"\D", "", ra)
        lc_, lr_ = re.sub(r"\d", "", ca), re.sub(r"\d", "", ra)
        if re.fullmatch(r"\d+(ST|ND|RD|TH)", ra) and not re.fullmatch(r"\d+(ST|ND|RD|TH)", ca):
            return "id_became_ordinal_same_n" if dc_ == dr_ else "id_became_ordinal_other_n"
        if dc_ == dr_:
            pre_c, pre_r = ca[0].isalpha(), ra[0].isalpha()
            if not lc_:
                return "id_letter_prefix_added" if pre_r else "id_letter_suffix_added"
            if not lr_:
                return "id_letter_prefix_dropped" if pre_c else "id_letter_suffix_dropped"
            if pre_c != pre_r:
                return "id_letter_moved_between_prefix_suffix"
            return "id_letter_changed"
        if dc_ and dc_ in dr_ and len(ra) > len(ca):
            return "id_composite_contains_canonical"
        if dr_ and dr_ in dc_ and len(ca) > len(ra):
            return "id_canonical_composite_contains_council"
        return "id_other"
    if len(ra) < len(ca) and ra[:1] == ca[:1] and is_subseq(ra, ca):
        return "council_shorter_subsequence"  # abbreviation-like
    if len(ca) < len(ra) and ca[:1] == ra[:1] and is_subseq(ca, ra):
        return "council_longer_supersequence"  # expansion-like
    d = Levenshtein.distance(ca, ra)
    if d == 1:
        return "edit1"
    if d == 2 and min(len(ca), len(ra)) >= 4:
        return "edit2"
    if sorted(ca) == sorted(ra):
        return "letters_transposed"
    return "word_replaced"


def extract_ops(c_toks, r_toks, other_canon, parent_canon):
    c = [t for t, _ in c_toks]
    tags = [g for _, g in c_toks]
    path = nw(c, r_toks)
    ops = []
    k = 0
    while k < len(path):
        ci, ri = path[k]
        if ci is not None and ri is not None:
            if c[ci] != r_toks[ri]:
                ops.append({"op": "SUB", "slot": tags[ci], "del": [c[ci]], "ins": [r_toks[ri]],
                            "rel": relation(c[ci], r_toks[ri]), "pos": k})
            k += 1
            continue
        kind = "DEL" if ri is None else "INS"
        run = []
        while k < len(path) and (path[k][1] is None if kind == "DEL" else path[k][0] is None):
            run.append(path[k]); k += 1
        if kind == "DEL":
            # split deletions at slot boundaries
            cur = []
            for ci2, _ in run:
                if cur and tags[cur[-1]] != tags[ci2]:
                    ops.append({"op": "DEL", "slot": tags[cur[0]], "del": [c[x] for x in cur], "ins": [], "rel": "", "pos": k})
                    cur = []
                cur.append(ci2)
            ops.append({"op": "DEL", "slot": tags[cur[0]], "del": [c[x] for x in cur], "ins": [], "rel": "", "pos": k})
        else:
            prev_ci = next((path[q][0] for q in range(k - len(run) - 1, -1, -1) if path[q][0] is not None), None)
            next_ci = next((path[q][0] for q in range(k, len(path)) if path[q][0] is not None), None)
            ctx = f"{tags[prev_ci] if prev_ci is not None else 'BOS'}>{tags[next_ci] if next_ci is not None else 'EOS'}"
            ops.append({"op": "INS", "slot": ctx, "del": [], "ins": [r_toks[x] for _, x in run], "rel": "", "pos": k})
    # adjacent deletion + insertion inside one dwelling/street component = replacement
    i = 0
    while i < len(ops) - 1:
        a, b = ops[i], ops[i + 1]
        if {a["op"], b["op"]} == {"DEL", "INS"}:
            d, n = (a, b) if a["op"] == "DEL" else (b, a)
            adjacent = (n["pos"] - len(n["ins"]) == d["pos"]) if a is d else (d["pos"] - len(d["del"]) == n["pos"])
            touches = d["slot"] in n["slot"].split(">")
            if adjacent and touches and d["slot"] in ("SUB", "NAME", "NUM", "ORG", "STREET", "DSTREET") \
                    and len(d["del"]) <= 3 and len(n["ins"]) <= 3:
                rel = "replaced"
                if len(d["del"]) == 1 and len(n["ins"]) == 1:
                    x, y = alnum(d["del"][0]), alnum(n["ins"][0])
                    if (x.isalpha() and len(x) == 1 and y.isdigit() and int(y) == ord(x) - 64) or \
                       (y.isalpha() and len(y) == 1 and x.isdigit() and int(x) == ord(y) - 64):
                        rel = "letter_digit_same_rank"
                    elif (len(x) == 1 and x.isalpha() and y.isdigit()) or (len(y) == 1 and y.isalpha() and x.isdigit()):
                        rel = "letter_digit_other"
                ops[i] = {"op": "REPL", "slot": d["slot"], "del": d["del"], "ins": n["ins"], "rel": rel, "pos": n["pos"]}
                del ops[i + 1]
        i += 1
    # token join / split: SUB next to DEL/INS whose concatenation matches
    for i in range(len(ops) - 1):
        a, b = ops[i], ops[i + 1]
        if {a["op"], b["op"]} == {"SUB", "DEL"}:
            s, d = (a, b) if a["op"] == "SUB" else (b, a)
            joined = "".join(a["del"] + b["del"])
            if alnum(joined) == alnum(s["ins"][0]):
                s["rel"] = "tokens_joined"; s["del"] = a["del"] + b["del"]; d["op"] = "MERGED"
        if {a["op"], b["op"]} == {"SUB", "INS"}:
            s = a if a["op"] == "SUB" else b
            joined = "".join(a["ins"] + b["ins"])
            if alnum(joined) == alnum(s["del"][0]):
                s["rel"] = "token_split"; s["ins"] = a["ins"] + b["ins"]
                (b if a is s else a)["op"] = "MERGED"
    ops = [o for o in ops if o["op"] != "MERGED"]
    # moves: a deleted run reappears as an inserted run
    dels = [o for o in ops if o["op"] == "DEL"]
    for o in ops:
        if o["op"] != "INS":
            continue
        for d in dels:
            if d["op"] == "DEL" and [alnum(x) for x in d["del"]] == [alnum(x) for x in o["ins"]]:
                d["op"] = "MOVED_FROM"
                o["op"] = "MOVE"; o["rel"] = f"moved_{d['slot']}"; o["del"] = d["del"]
                o["slot"] = d["slot"] + "@" + o["slot"]
                break
    ops = [o for o in ops if o["op"] != "MOVED_FROM"]
    slot_len = {g: tags.count(g) for g in set(tags)}
    for o in ops:
        o["full_slot"] = o["op"] in ("DEL", "MOVE") and len(o["del"]) == slot_len.get(o["slot"].split("@")[0], -1)
    # provenance flags for inserted tokens (data-level only)
    cset = {alnum(t) for t in c}
    for o in ops:
        ins = [alnum(t) for t in o["ins"]]
        o["ins_dup_in_canon"] = bool(ins) and o["op"] == "INS" and all(t in cset for t in ins)
        o["ins_in_other_canon"] = bool(ins) and all(t in other_canon for t in ins)
        o["ins_in_parent"] = bool(ins) and bool(parent_canon) and all(t in parent_canon for t in ins)
        o["del_in_other_canon"] = bool(o["del"]) and all(alnum(t) in other_canon for t in o["del"])
    return ops


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    nbg = int(sys.argv[3]) if len(sys.argv) > 3 else 4000
    councils = sys.argv[4].split(",") if len(sys.argv) > 4 else COUNCILS
    assert not EXTERNAL_TEST & set(councils), "external test councils are never used"
    out.mkdir(parents=True, exist_ok=True)
    random.seed(20261012)
    all_ops, rows_meta, audit = [], [], {}
    for council in councils:
        pp = find_pairs(root, council)
        print(council, "pairs from", pp.relative_to(root), flush=True)
        pairs = pd.read_csv(pp, dtype=str, keep_default_na=False)
        comp = pd.read_csv(find_components(root, council), dtype=str, keep_default_na=False)
        comp = comp.set_index("uprn")
        pairs = pairs[pairs.label_uprn.isin(comp.index)]
        # SY1 systemic truncation is a known source-level process; its rows are
        # left out so the cut tail does not masquerade as record-level edits
        clean = root / f"council_data/clean_v1_20261012/{council}/clean_records.csv"
        n_trunc = 0
        if clean.exists():
            tags = pd.read_csv(clean, dtype=str, keep_default_na=False, usecols=["record_id", "clean_tags"])
            trunc = set(tags.record_id[tags.clean_tags.str.contains("systemic_truncation")])
            n_trunc = int(pairs.record_id.isin(trunc).sum())
            pairs = pairs[~pairs.record_id.isin(trunc)]
        pairs = pairs[pairs.ngd_ftype == "built"]  # LC rows (historic/prebuild/NAO) excluded, as in the taxonomy
        diff = pairs[pairs.dwelling_diff == "True"]
        rest = pairs[pairs.dwelling_diff != "True"]
        bg = rest.sample(min(nbg, len(rest)), random_state=20261012)
        audit[council] = {"paired_built": len(pairs), "dwelling_diff": len(diff), "background_sampled": len(bg),
                          "background_pool": len(rest), "background_weight": len(rest) / max(len(bg), 1),
                          "excluded_sy1_truncated": n_trunc}
        for subset, df in (("dwelling_diff", diff), ("background", bg)):
            for r in df.itertuples(index=False):
                cr = comp.loc[r.label_uprn]
                ngd_t = canon_tokens(cr, NGD_SLOTS)
                rm_t = canon_tokens(cr, RM_SLOTS)
                use_rm = r.nearest_canonical == "rm" and rm_t
                c_toks = rm_t if use_rm else ngd_t
                other = {alnum(t) for t, _ in (ngd_t if use_rm else rm_t)}
                parent = set()
                pu = cr["parentuprn"]
                if pu and pu in comp.index:
                    parent = {alnum(t) for t, _ in canon_tokens(comp.loc[pu], NGD_SLOTS)}
                r_toks = tokens(r.recorded_address)
                ops = extract_ops(c_toks, r_toks, other, parent)
                rows_meta.append({"record_id": r.record_id, "council": council, "subset": subset,
                                  "label_uprn": r.label_uprn, "canon": "rm" if use_rm else "ngd",
                                  "n_ops": len(ops), "collision": r.collision,
                                  "collision_relation": r.collision_relation, "drift_relation": r.drift_relation,
                                  "has_parent": r.has_parent, "n_children": r.n_children,
                                  "labels_nearest": r.labels_nearest,
                                  "labels_used": r.labels_vs_rm if use_rm else r.labels_vs_ngd,
                                  "recorded_address": r.recorded_address,
                                  "canon_address": " ".join(t for t, _ in c_toks)})
                for o in ops:
                    o.update(record_id=r.record_id, council=council, subset=subset)
                    o["del"] = " ".join(o["del"]); o["ins"] = " ".join(o["ins"])
                    all_ops.append(o)
        print(council, audit[council], flush=True)
    pd.DataFrame(all_ops).to_csv(out / "edit_ops.csv.gz", index=False)
    pd.DataFrame(rows_meta).to_csv(out / "aligned_rows.csv.gz", index=False)
    (out / "align_audit.json").write_text(json.dumps(audit, indent=1))


if __name__ == "__main__":
    main()
