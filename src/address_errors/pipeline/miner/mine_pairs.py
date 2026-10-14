"""Vendored from mined_error_pairs/v3_basingstoke_20261012/code/mine_pairs.py (one edit: POSTCODE_SOURCES).

Mine council-vs-canonical address discrepancy pairs and label them.

Usage: python mine_pairs.py <duckdb path> <output dir> [council ...]
Reads tables ct (council staged records), ngd1 (NGD, one row per UPRN), rm (Royal Mail PAF),
altadd (NGD alternative/historic renderings). Writes one pairs CSV per council plus summaries.
"""
import csv, gzip, json, os, re, sys, collections
import duckdb
from rapidfuzz import fuzz
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from addrparse import (norm_text, canon_seq, canon_tok, find_phrase, find_phrase_fuzzy, parse_dwelling,
                       compare_dwelling, dwelling_tokens_from_components, num_parts, COUNTIES, UNIT_WORDS,
                       FLOOR_ABBR, ORDINAL, FLOOR_WORDS, ROOM_WORDS, ANNEX_WORDS, STREET_TYPES)

DB = os.environ.get("PAIRS_DB") or sys.argv[1]
# sources whose records carry a recorded postcode (package edit: was the literal ("wigan", "basingstoke"))
POSTCODE_SOURCES = set(filter(None, os.environ.get("ADDRESS_ERRORS_POSTCODE_SOURCES", "wigan,basingstoke").split(",")))
con = duckdb.connect(DB, read_only=True)

# ---------------- canonical data
print("loading NGD", flush=True)
NGD = {}
for r in con.execute("""select uprn, ftype, subname, name, number, streetname, locality, townname, postcode,
        fulladdress, classificationcode, parentuprn, rootuprn, hierarchylevel, usrn, organisationname from ngd1""").fetchall():
    NGD[r[0]] = r
CHILDREN = collections.defaultdict(list)
for u, r in NGD.items():
    if r[11]:
        CHILDREN[r[11]].append(u)
print("loading RM", flush=True)
RM = collections.defaultdict(list)
for r in con.execute("""select ltrim(uprn,'0'), subbuildingname, buildingname, buildingnumber, dependentthoroughfare,
        thoroughfare, doubledependentlocality, dependentlocality, posttown, postcode, organisationname
        from rm where uprn is not null and primaryuprnmatch='Yes'""").fetchall():
    RM[r[0]].append(r)
ALT = collections.defaultdict(set)
for u, a, b, c in con.execute("select ltrim(uprn,'0'), alternatesubname, alternatename, alternatenumber from altadd").fetchall():
    for x in (a, b):
        if x:
            ALT[u].add(" ".join(norm_text(x)[0]))

# locality vocabulary
LOCVOCAB = set(COUNTIES)
for r in NGD.values():
    for x in (r[6], r[7]):
        if x:
            LOCVOCAB.add(tuple(norm_text(x)[0]))
for rs in RM.values():
    for r in rs:
        for x in (r[6], r[7], r[8]):
            if x:
                LOCVOCAB.add(tuple(norm_text(x)[0]))
LOCVOCAB.discard(())
MAXLOC = max(len(p) for p in LOCVOCAB)


def key2(toks):
    """Rendering-insensitive key: drop unit words/THE, canonicalise floors and abbreviations."""
    out = []
    i = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        nxt = toks[i + 1] if i + 1 < n else ""
        if t in UNIT_WORDS or t == "THE":
            i += 1; continue
        if t in FLOOR_ABBR:
            out.append("F" + FLOOR_ABBR[t][0]); i += 2 if nxt in FLOOR_WORDS else 1; continue
        if t in ORDINAL and nxt in FLOOR_WORDS:
            out.append("F" + ORDINAL[t]); i += 2; continue
        out.append(canon_tok(t)); i += 1
    return tuple(out)


def ngd_dwelling(r):
    return dwelling_tokens_from_components(r[2], r[3], r[4])


def rm_dwelling(r):
    return dwelling_tokens_from_components(r[1], r[2], r[3])


# collision index over all canonical renderings: key2(dwelling + street) -> uprns
print("building collision index", flush=True)
IDX = collections.defaultdict(set)
STREETIDX = collections.defaultdict(set)  # (canon street, base number) -> uprns
for u, r in NGD.items():
    d = ngd_dwelling(r)
    st = norm_text(r[5])[0]
    IDX[key2(d + st)].add(u)
    for t in d:
        b, s, rg = num_parts(t)
        if b is not None:
            STREETIDX[(canon_seq(st), b)].add(u)
for u, rs in RM.items():
    for r in rs:
        d = rm_dwelling(r)
        for st in (r[5], r[4]):
            if st:
                IDX[key2(d + norm_text(st)[0])].add(u)
        if r[4] and r[5]:
            IDX[key2(d + norm_text(r[4])[0] + norm_text(r[5])[0])].add(u)


def relation(L, O):
    rl, ro = NGD.get(L), NGD.get(O)
    if rl is None or ro is None:
        return "to_other"
    if rl[11] and O == rl[11]:
        return "to_parent"
    if ro[11] and ro[11] == L:
        return "to_child"
    if rl[11] and rl[11] == ro[11]:
        return "to_sibling"
    if rl[12] and rl[12] == ro[12]:
        return "to_same_complex"
    if rl[14] and rl[14] == ro[14]:
        return "to_neighbour"
    return "to_other"


def district(pc):
    return pc.split()[0] if pc and " " in pc else (pc[:-3] if pc else "")


def same_area(a, b):
    ra, rb = NGD.get(a), NGD.get(b)
    if ra is None or rb is None:
        return False
    return (ra[14] and ra[14] == rb[14]) or (ra[7] == rb[7] and district(ra[8]) == district(rb[8]))


REL_ORDER = ["to_parent", "to_child", "to_sibling", "to_same_complex", "to_neighbour", "to_other"]


def split_recorded(toks, streets):
    """streets: list of (tokens, kind). Return dict with dwelling, street span tokens, tail, status labels."""
    res = {"labels": [], "street_tokens": [], "street_status": "not_found"}
    found = []
    for st, kind in streets:
        if not st:
            continue
        sp = find_phrase(toks, st, rightmost=True)
        if sp:
            raw_eq = toks[sp[0]:sp[1]] == list(st)
            found.append((sp, kind, raw_eq))
    if found:
        s0 = min(f[0][0] for f in found)
        e1 = max(f[0][1] for f in found)
        main = [f for f in found if f[1] == "main"]
        kinds = {f[1] for f in found}
        if main:
            res["street_status"] = "exact" if main[0][2] else "abbrev"
            if not main[0][2]:
                res["labels"].append("ST1:street_type_abbrev")
        else:
            res["street_status"] = "alt_street"
            res["labels"].append("ST3:recorded_dependent_or_postal_street")
        if "main" in kinds and "dep" in kinds:
            pass
        elif "dep" in [k for _, k in streets] and "dep" not in kinds and "main" in kinds:
            res["labels"].append("ST3:dependent_street_dropped")
        dwelling = toks[:s0]
        res["street_tokens"] = toks[s0:e1]
        tail = toks[e1:]
    else:
        # strip locality phrases from the end
        end = len(toks)
        while end > 0:
            hit = False
            for L in range(min(MAXLOC, end), 0, -1):
                if tuple(toks[end - L:end]) in LOCVOCAB:
                    end -= L; hit = True; break
            if not hit:
                break
        head, tail = toks[:end], toks[end:]
        main = [st for st, k in streets if k == "main"]
        fz = find_phrase_fuzzy(head, main[0]) if main and main[0] else None
        if fz:
            res["street_status"] = "fuzzy"
            res["labels"].append("ST2:street_spelling")
            dwelling = head[:fz[0]]
            res["street_tokens"] = head[fz[0]:fz[1]]
            tail = head[fz[1]:] + tail
        else:
            dwelling = head
            res["street_status"] = "not_found"
    # sub-unit / number tokens recorded after the street
    moved = []
    while tail and (tail[0] in UNIT_WORDS or tail[0] in FLOOR_ABBR or tail[0] in ROOM_WORDS or tail[0] in ANNEX_WORDS
                    or re.fullmatch(r"\d+[A-Z]?", tail[0]) or tail[0] in FLOOR_WORDS or (tail[0] in ORDINAL and len(tail) > 1 and tail[1] in FLOOR_WORDS)):
        moved.append(tail.pop(0))
    if moved:
        res["labels"].append("SU11:subunit_after_street")
        dwelling = dwelling + moved
    res["dwelling"] = dwelling
    res["tail"] = tail
    return res


def parse_tail(tail):
    phrases, unknown = [], []
    i = 0
    while i < len(tail):
        hit = None
        for L in range(min(MAXLOC, len(tail) - i), 0, -1):
            if tuple(tail[i:i + L]) in LOCVOCAB:
                hit = L; break
        if hit:
            phrases.append(tuple(tail[i:i + hit])); i += hit
        else:
            unknown.append(tail[i]); i += 1
    return phrases, unknown


def locality_labels(tail, ngd_loc, ngd_town, rm_locs, rm_town):
    L = []
    phrases, unknown = parse_tail(tail)
    pset = set(phrases)
    ngd_loc_t = tuple(norm_text(ngd_loc)[0]) if ngd_loc else None
    ngd_town_t = tuple(norm_text(ngd_town)[0]) if ngd_town else None
    rm_locs_t = {tuple(norm_text(x)[0]) for x in rm_locs if x}
    rm_town_t = tuple(norm_text(rm_town)[0]) if rm_town else None
    for p in phrases:
        if p in COUNTIES:
            L.append("LO2:county_added")
        elif p == ngd_loc_t or p == ngd_town_t:
            continue
        elif rm_town_t and p == rm_town_t:
            L.append("LO3:postal_town_used")
        elif p in rm_locs_t:
            L.append("LO1:postal_locality_used")
        else:
            L.append("LO1:other_locality_added")
    if ngd_loc_t and ngd_loc_t not in pset:
        L.append("LO1:ngd_locality_dropped")
    if ngd_town_t and ngd_town_t not in pset and not (rm_town_t and rm_town_t in pset):
        L.append("LO3:town_dropped")
    if unknown:
        if "OFF" in unknown:
            L.append("DQ1:off_street_reference")
        else:
            L.append("LO1:unrecognised_tail_text")
    return sorted(set(L))


def compare(rec_toks, can_d, can_streets, can_sub, parent_nums, alt_names):
    sp = split_recorded(rec_toks, can_streets)
    labels = list(sp["labels"])
    dw = sp["dwelling"]
    can_toks = can_d
    rp = parse_dwelling(dw)
    cp = parse_dwelling(can_toks)
    # street not found: decide ST4 / ST5
    if sp["street_status"] == "not_found":
        extra = [w for w in rp["words"] if w not in cp["words"]]
        if extra and canon_tok(extra[-1]) in STREET_TYPES:
            labels.append("ST4:different_street")
            # strip the extra street-like words from the dwelling words for name comparison
            k = len(rp["words"]) - 1
            while k >= 0 and rp["words"][k] in extra:
                k -= 1
            rp["words"] = rp["words"][:k + 1]
            rp["order"] = rp["order"][:len(rp["order"])]
        else:
            labels.append("ST5:street_omitted")
    can_sub_nums = set(norm_text(can_sub)[0]) if can_sub else set()
    labels += compare_dwelling(rp, cp, can_sub_nums, parent_nums, alt_names)
    return labels, sp


DWELL_PREFIX = ("SU", "BN", "PN", "DQ")


def dwelling_labels(ls):
    return [l for l in ls if l.startswith(DWELL_PREFIX) and l != "DQ1:off_street_reference"]


def pc_label(rec, can):
    if not rec:
        return "PC:missing"
    a, b = rec.replace(" ", "").upper(), (can or "").replace(" ", "").upper()
    if not b:
        return "PC:canonical_missing"
    if a == b:
        return "PC:same" if rec.upper() == can.upper() else "PC:format"
    if a[:-2] == b[:-2]:
        return "PC:same_sector_diff_unit"
    if a[:-3] == b[:-3]:
        return "PC:same_district_diff_sector"
    return "PC:different_district"


FIELDS = ["record_id", "council", "epoch", "label_uprn", "ngd_ftype", "ngd_class", "hierarchylevel", "has_parent",
          "n_children", "recorded_address", "ngd_address", "rm_address", "street_status_ngd", "labels_vs_ngd",
          "labels_vs_rm", "nearest_canonical", "labels_nearest", "dwelling_diff", "postcode_label", "format_flags",
          "collision", "collision_relation", "collision_uprns", "drift_relation", "drift_uprn", "drift_margin"]

def main():
  OUT = sys.argv[2]
  COUNCILS = sys.argv[3:] or ["wigan", "bradford", "leeds"]
  os.makedirs(OUT, exist_ok=False)
  summary = collections.Counter()
  for council in COUNCILS:
      print("council", council, flush=True)
      rows = con.execute(f"""select record_id, ons_epoch, label_uprn, recorded_address_raw, recorded_address, recorded_postcode
          from ct where council='{council}' and label_uprn is not null and label_uprn<>''""").fetchall()
      if os.environ.get("LIMIT"):
          import random; random.seed(1); rows = random.sample(rows, int(os.environ["LIMIT"]))
      fout = gzip.open(os.path.join(OUT, f"pairs_{council}.csv.gz"), "wt", newline="", encoding="utf-8")
      w = csv.DictWriter(fout, FIELDS)
      w.writeheader()
      for k, (rid, epoch, L, raw, recaddr, recpc) in enumerate(rows):
          if k % 50000 == 0:
              print(" ", council, k, flush=True)
          n = NGD.get(L)
          summary[(council, "records")] += 1
          if n is None:
              summary[(council, "no_ngd")] += 1
              continue
          rec_toks, fflags = norm_text(recaddr)
          # format flags
          letters = re.sub(r"[^A-Za-z]", "", recaddr or "")
          fflags.add("FM1:upper" if letters.isupper() else ("FM1:title_or_mixed"))
          if "," not in (recaddr or ""):
              fflags.add("FM2:no_commas")
          # duplication
          for i in range(len(rec_toks) - 3):
              if rec_toks[i:i + 2] == rec_toks[i + 2:i + 4] and not re.fullmatch(r"\d+", rec_toks[i]):
                  fflags.add("FM7:duplicated_component"); break
          parent = NGD.get(n[11]) if n[11] else None
          parent_nums = set(t for t in ngd_dwelling(parent) if num_parts(t)[0] is not None) if parent else set()
          alt = ALT.get(L, set())
          ngd_d = ngd_dwelling(n)
          lab_n, sp_n = compare(rec_toks, ngd_d, [(norm_text(n[5])[0], "main")], n[2], parent_nums, alt)
          rms = RM.get(L, [])
          rm_town, rm_locs = None, []
          lab_r, rm_addr = None, ""
          if rms:
              r = rms[0]
              rm_town, rm_locs = r[8], [r[6], r[7]]
              streets = [(norm_text(r[5])[0], "main")] + ([(norm_text(r[4])[0], "dep")] if r[4] else [])
              lab_r, sp_r = compare(rec_toks, rm_dwelling(r), streets, r[1], parent_nums, alt)
              rm_addr = ", ".join(x for x in (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]) if x)
          loc = locality_labels(sp_n["tail"], n[6], n[7], rm_locs, rm_town)
          lab_n = sorted(set(lab_n)) + loc
          if lab_r is not None:
              lab_r = sorted(set(lab_r))
          dn = dwelling_labels(lab_n)
          dr = dwelling_labels(lab_r) if lab_r is not None else None
          if dr is not None and len(dr) < len(dn):
              nearest, lab_near = "rm", dr
          else:
              nearest, lab_near = "ngd", dn
          if not dn:
              nearest = "ngd"
          # lifecycle
          if n[1] != "built":
              lab_near = lab_near + [f"LC:label_is_{n[1]}"]
          # collision test on rendering-insensitive key
          coll, crel, cu = "not_tested", "", ""
          if sp_n["street_status"] != "not_found":
              key = key2(sp_n["dwelling"] + sp_n["street_tokens"])
              hits = {h for h in IDX.get(key, set()) if h == L or same_area(L, h)}
              if not hits:
                  coll = "no_match"
              elif hits == {L}:
                  coll = "matches_label_only"
              else:
                  others = sorted(hits - {L})
                  coll = "matches_label_and_other" if L in hits else "matches_other_only"
                  rels = sorted({relation(L, o) for o in others}, key=REL_ORDER.index)
                  crel = rels[0]
                  cu = ";".join(others[:5])
          # drift candidate: a confusable neighbour scores clearly better than the label
          drel, du, dm = "", "", ""
          if lab_near and any(not l.startswith(("LC",)) for l in lab_near) and sp_n["street_status"] != "not_found":
              rk = " ".join(key2(sp_n["dwelling"]))
              cands = set()
              if n[11]:
                  cands.add(n[11]); cands.update(CHILDREN.get(n[11], [])[:400])
              cands.update(CHILDREN.get(L, [])[:400])
              st = canon_seq(norm_text(n[5])[0])
              for t in ngd_d + sp_n["dwelling"]:
                  b, s, rg = num_parts(t)
                  if b is not None:
                      for bb in (b - 2, b - 1, b, b + 1, b + 2):
                          cands.update(STREETIDX.get((st, bb), ()))
              cands.discard(L)
              if cands:
                  own = max([fuzz.token_sort_ratio(rk, " ".join(key2(ngd_d)))] +
                            [fuzz.token_sort_ratio(rk, " ".join(key2(rm_dwelling(x)))) for x in rms])
                  best = None
                  for c in cands:
                      cr = NGD.get(c)
                      if cr is None or not same_area(L, c):
                          continue
                      sc = fuzz.token_sort_ratio(rk, " ".join(key2(ngd_dwelling(cr))))
                      for x in RM.get(c, []):
                          sc = max(sc, fuzz.token_sort_ratio(rk, " ".join(key2(rm_dwelling(x)))))
                      if best is None or sc > best[0]:
                          best = (sc, c)
                  if best and best[0] >= own + 10 and best[0] >= 80:
                      drel, du, dm = relation(L, best[1]), best[1], f"{best[0] - own:.0f}"
          pcl = pc_label(recpc, n[8]) if council in POSTCODE_SOURCES else ""
          w.writerow({"record_id": rid, "council": council, "epoch": epoch, "label_uprn": L, "ngd_ftype": n[1],
                      "ngd_class": n[10], "hierarchylevel": n[13], "has_parent": bool(n[11]),
                      "n_children": len(CHILDREN.get(L, [])), "recorded_address": recaddr,
                      "ngd_address": ", ".join(x for x in (n[2], n[3], n[4], n[5], n[6], n[7]) if x),
                      "rm_address": rm_addr, "street_status_ngd": sp_n["street_status"],
                      "labels_vs_ngd": "|".join(lab_n), "labels_vs_rm": "|".join(lab_r) if lab_r is not None else "",
                      "nearest_canonical": nearest, "labels_nearest": "|".join(lab_near),
                      "dwelling_diff": bool([l for l in lab_near if not l.startswith("LC")]),
                      "postcode_label": pcl, "format_flags": "|".join(sorted(fflags)),
                      "collision": coll, "collision_relation": crel, "collision_uprns": cu,
                      "drift_relation": drel, "drift_uprn": du, "drift_margin": dm})
      fout.close()
  json.dump({f"{a}|{b}": v for (a, b), v in summary.items()}, open(os.path.join(OUT, "run_counts.json"), "w"), indent=1)
  print("done", flush=True)


if __name__ == "__main__":
    main()
