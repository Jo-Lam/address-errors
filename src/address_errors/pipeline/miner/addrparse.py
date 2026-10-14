"""Vendored unchanged from mined_error_pairs/v3_basingstoke_20261012/code/addrparse.py.

Component parser and difference labeller for UK address strings.

Compares a recorded address string (council tax) with a canonical rendering
(OS NGD Built Address or Royal Mail PAF) and emits mechanism labels using the
IDs in CLAUDE.md (SU*, BN*, PN*, DQ*, ST*, LO*, FM*, KY*), with ':subtype'.
Labels new to CLAUDE.md v0 are marked in NEW_IDS.
"""
import re
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

NEW_IDS = {
    "PN6": "Extra primary number added (often the parent building's number)",
    "ST5": "Canonical street omitted; building/complex name stands in as thoroughfare",
    "FM6": "Leading zeros in numbers (e.g. 001)",
    "FM7": "Component duplicated in the string",
    "BN7": "Abbreviated words inside a building name (FM, SCH, HO)",
    "SU13": "Sub-unit identifier only (bare number/letter) vs typed sub-unit",
}

COUNTIES = {("LANCASHIRE",), ("LANCS",), ("CHESHIRE",), ("GREATER", "MANCHESTER"), ("MERSEYSIDE",),
            ("WEST", "YORKSHIRE"), ("W", "YORKS"), ("WEST", "YORKS"), ("YORKSHIRE",), ("NORTH", "YORKSHIRE"),
            ("N", "YORKS"), ("YORKS",), ("HANTS",), ("HAMPSHIRE",), ("BERKS",), ("BERKSHIRE",), ("SURREY",), ("WILTS",), ("WILTSHIRE",)}

STREET_ABBR = {
    "STREET": "ST", "SAINT": "ST", "ROAD": "RD", "AVENUE": "AVE", "AV": "AVE", "LANE": "LN", "DRIVE": "DR",
    "CLOSE": "CL", "CRESCENT": "CRES", "CRESC": "CRES", "CRES": "CRES", "GARDENS": "GDNS", "GDN": "GDNS",
    "GROVE": "GR", "GRO": "GR", "TERRACE": "TER", "TERR": "TER", "TCE": "TER", "PLACE": "PL", "COURT": "CT",
    "CRT": "CT", "SQUARE": "SQ", "MOUNT": "MT", "VIEW": "VW", "WALK": "WK", "PARADE": "PDE", "GREEN": "GRN",
    "BROW": "BRW", "HILL": "HL", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "UPPER": "UPR",
    "LOWER": "LWR", "GATE": "GT", "WAY": "WY", "FARM": "FM", "SCHOOL": "SCH", "HOUSE": "HO", "COTTAGE": "COTT",
    "COTTAGES": "COTTS", "COTTS": "COTTS", "COTT": "COTT", "BUNGALOW": "BUNG", "MOBILE": "MOB", "CHURCH": "CH",
    "APPROACH": "APPR", "BOULEVARD": "BLVD", "ESPLANADE": "ESP", "FOLD": "FLD", "MEWS": "MWS", "PARK": "PK",
    "RISE": "RI", "ROW": "RW", "VALE": "VL", "VILLAS": "VLS", "YARD": "YD", "WHARF": "WHF", "CHASE": "CHS",
}
STREET_TYPES = {"ST", "RD", "AVE", "LN", "DR", "CL", "CRES", "GDNS", "GR", "TER", "PL", "CT", "SQ", "MT", "VW",
                "WK", "PDE", "GRN", "BRW", "HL", "WY", "APPR", "BLVD", "FLD", "MWS", "RI", "RW", "VL", "CHS", "GT"}

UNIT_WORDS = {"FLAT": "FLAT", "FLT": "FLAT", "APARTMENT": "APT", "APT": "APT", "APPT": "APT",
              "APPARTMENT": "APT", "APARTMENTS": "APT", "UNIT": "UNIT", "STUDIO": "STUDIO", "MAISONETTE": "MAIS",
              "MAIS": "MAIS", "BEDSIT": "BEDSIT", "PENTHOUSE": "PENTHOUSE", "SUITE": "SUITE", "BLOCK": "BLOCK",
              "FL": "FLAT"}
# words that act as a sub-unit type only when a number/letter id follows
NUMBERED_UNIT = {"CARAVAN": "CARAVAN", "SITE": "PITCH", "PITCH": "PITCH", "BERTH": "BERTH", "MOORING": "BERTH",
                 "CHALET": "CHALET", "HOUSE": "HOUSE", "LODGE": "LODGE", "BUNGALOW": "BUNGALOW", "COTTAGE": "COTTAGE",
                 "BOAT": "BOAT", "HOME": "HOME", "VAN": "CARAVAN"}
ROOM_WORDS = {"ROOM", "ROOMS", "RM", "RMS", "ROOMZZZ", "BEDROOM", "BED", "BEDSPACE"}
ANNEX_WORDS = {"ANNEX", "ANNEXE", "ANNEXED", "ANNX", "ANX"}
POSITION_WORDS = {"FRONT": "FRONT", "REAR": "REAR", "BACK": "REAR", "LEFT": "LEFT", "RIGHT": "RIGHT",
                  "MIDDLE": "MIDDLE", "CENTRE": "MIDDLE", "LHS": "LEFT", "RHS": "RIGHT", "LH": "LEFT", "RH": "RIGHT"}
ORDINAL = {"FIRST": "1", "1ST": "1", "SECOND": "2", "2ND": "2", "THIRD": "3", "3RD": "3", "FOURTH": "4",
           "4TH": "4", "FIFTH": "5", "5TH": "5", "SIXTH": "6", "6TH": "6", "SEVENTH": "7", "7TH": "7",
           "EIGHTH": "8", "8TH": "8", "NINTH": "9", "9TH": "9", "TENTH": "10", "10TH": "10",
           "GROUND": "G", "GRD": "G", "GND": "G", "GRND": "G", "TOP": "TOP", "LOWER": "LOWER", "UPPER": "UPPER"}
FLOOR_WORDS = {"FLOOR", "FLR", "FL", "FLOORS", "FLRS"}
FLOOR_ABBR = {"GF": ("G", None), "GFF": ("G", "FLAT"), "FF": ("1", None), "FFF": ("1", "FLAT"),
              "SF": ("2", None), "SFF": ("2", "FLAT"), "TFF": ("3", "FLAT"), "BASEMENT": ("B", None),
              "BSMT": ("B", None), "BASEMNT": ("B", None), "ATTIC": ("ATTIC", None), "CELLAR": ("B", None),
              "LGF": ("LG", None), "MEZZANINE": ("MEZZ", None)}
DQ1_UNI = {"ADJACENT", "ADJ", "ADJOINING", "OPPOSITE", "OPP", "BEHIND", "OFF", "NR", "NEAR", "BESIDE"}
DQ1_BI = {("REAR", "OF"), ("LAND", "AT"), ("LAND", "ADJ"), ("NEXT", "TO"), ("PART", "OF"), ("SITE", "OF"),
          ("BACK", "OF"), ("SIDE", "OF"), ("LAND", "TO")}
DQ2_UNI = {"PLOT", "PROPOSED", "DEVELOPMENT", "NEWBUILD"}
DQ2_BI = {("NEW", "HOUSE"), ("NEW", "BUILD"), ("NEW", "DWELLING"), ("NEW", "BUNGALOW"), ("NEW", "PROPERTY")}
DQ3_UNI = {"ABOVE", "OVER", "CARETAKERS", "WARDENS", "GRANNY", "ACCOMMODATION", "PREMISES", "LIVING",
           "QUARTERS", "MANAGERS", "STAFF", "RESIDENTIAL", "DWELLING", "AT"}
GENERIC_NAME = re.compile(
    r"^(THE )?(OLD |NEW |LITTLE |GARDEN |STABLE |FARM )?(BUNGALOW|BUNG|COTTAGE|COTT|LODGE|BARN|STABLES?|GRANARY|"
    r"COACH HOUSE|GATE ?HOUSE|FARM ?HOUSE|HOUSE|FLAT|ANNEXE?|MEWS|CHALET|CARAVAN|MOBILE HOME|MOB HOME|CABIN|"
    r"BOTHY|DAIRY|SMITHY|FORGE|BYRE|SHIPPON|LAITHE|SCHOOL HOUSE|CHAPEL|MANSE|VICARAGE|RECTORY|PRESBYTERY|"
    r"STATIC CARAVAN|HOUSEBOAT|BOAT|CROFT|MILL|WORKSHOP|STUDIO|ANNEX|OUTBUILDING|LOG CABIN|POD|SHOP|PUB|"
    r"POST OFFICE|SCHOOL|CHURCH|HALL|FARM|BARN CONVERSION|COTTAGES)S?$")

NUM_RE = re.compile(r"^(\d+)([A-Z]{0,2})$")
RANGE_RE = re.compile(r"^(\d+)([A-Z]?)-(\d+)([A-Z]?)$")
SLASH_RE = re.compile(r"^(\d+)/(\d+)$")


def norm_text(s):
    """Uppercase, unify punctuation; returns (tokens, raw_flags)."""
    flags = set()
    if s is None:
        return [], flags
    raw = s
    if "(" in raw or "[" in raw:
        flags.add("DQ4:brackets")
    if re.search(r",\s*,", raw):
        flags.add("FM3:empty_field")
    s = s.upper()
    s = s.replace("&", " AND ")
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"\b([RL])\s*[/-]\s*O\b", lambda m: "REAR OF" if m.group(1) == "R" else "LAND OF", s)
    s = re.sub(r"\bL\s*/\s*H\b", "LEFT", s)
    s = re.sub(r"\bR\s*/\s*H\b", "RIGHT", s)
    s = re.sub(r"\bG\s*/\s*F\b", "GF", s)
    s = re.sub(r"\bF\s*/\s*F\b", "FF", s)
    s = re.sub(r"\bS\s*/\s*F\b", "SF", s)
    s = re.sub(r"(\d[A-Z]?)\s+TO\s+(\d)", r"\1-\2", s)
    s = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", s)
    s = re.sub(r"(\d)\s*/\s*(\d)", r"\1/\2", s)
    s = re.sub(r"(?<=[A-Z])-(?=[A-Z])", " ", s)
    s = re.sub(r"[^A-Z0-9/\- ]", " ", s)
    s = re.sub(r"(?<![0-9])[-/]|[-/](?![0-9])", " ", s)
    toks = s.split()
    out = []
    for t in toks:
        m = re.match(r"^0+(\d+[A-Z]*)$", t)
        if m:
            flags.add("FM6:leading_zero")
            t = m.group(1)
        out.append(t)
    # join "193 B" -> "193B" when a single letter follows a bare number and is not a flat id ("FLAT A 30")
    j = []
    i = 0
    while i < len(out):
        t = out[i]
        if (j and re.fullmatch(r"\d+", j[-1]) and re.fullmatch(r"[A-H]", t)
                and not (len(j) >= 2 and j[-2] in UNIT_WORDS)
                and not (i + 1 < len(out) and re.fullmatch(r"\d+[A-Z]?", out[i + 1]))):
            j[-1] = j[-1] + t
        else:
            j.append(t)
        i += 1
    return j, flags


def canon_tok(t):
    return STREET_ABBR.get(t, t)


def canon_seq(toks):
    return tuple(canon_tok(t) for t in toks if t != "THE")


def find_phrase(toks, phrase, rightmost=True):
    """Find canonicalised phrase in token list; return (start,end) or None."""
    if not phrase:
        return None
    ct = [canon_tok(t) for t in toks]
    cp = [canon_tok(t) for t in phrase]
    n = len(cp)
    rng = range(len(ct) - n, -1, -1) if rightmost else range(0, len(ct) - n + 1)
    for i in rng:
        if ct[i:i + n] == cp:
            return (i, i + n)
    return None


def find_phrase_fuzzy(toks, phrase, threshold=85):
    if not phrase:
        return None
    target = " ".join(phrase)
    best = None
    n = len(phrase)
    for L in (n - 1, n, n + 1):
        if L < 1:
            continue
        for i in range(0, len(toks) - L + 1):
            cand = " ".join(toks[i:i + L])
            sc = fuzz.ratio(cand, target)
            if sc >= threshold and (best is None or sc > best[0] or (sc == best[0] and i > best[1])):
                best = (sc, i, i + L)
    return (best[1], best[2], best[0]) if best else None


def parse_dwelling(toks):
    """Parse dwelling-layer tokens into a feature dict."""
    f = {"unit": [], "floor": [], "pos": [], "room": False, "annex": False, "dq1": [], "dq2": [], "dq3": [],
         "nums": [], "letters": [], "words": [], "generic": None, "order": []}
    i = 0
    n = len(toks)
    used = [False] * n
    # bigram qualifiers
    for i in range(n - 1):
        bg = (toks[i], toks[i + 1])
        if bg in DQ1_BI:
            f["dq1"].append(" ".join(bg)); used[i] = used[i + 1] = True
        elif bg in DQ2_BI:
            f["dq2"].append(" ".join(bg)); used[i] = used[i + 1] = True
    # floor phrases
    for i in range(n):
        if used[i]:
            continue
        t = toks[i]
        nxt = toks[i + 1] if i + 1 < n else ""
        prv = toks[i - 1] if i > 0 else ""
        if t in FLOOR_ABBR:
            lvl, u = FLOOR_ABBR[t]
            f["floor"].append(lvl); used[i] = True
            if u:
                f["unit"].append(u)
            if nxt in FLOOR_WORDS:
                used[i + 1] = True
        elif t in ORDINAL and (nxt in FLOOR_WORDS or nxt in UNIT_WORDS or (nxt == "AND" and i + 2 < n and toks[i + 2] in ORDINAL) or nxt in ("FLOOR", "MAISONETTE")
                               or prv in UNIT_WORDS or (t in ("TOP", "UPPER", "LOWER") and nxt in ("FLAT", "GROUND", "MAISONETTE", "FLOOR"))):
            lvl = ORDINAL[t]
            if t == "LOWER" and nxt == "GROUND":
                lvl = "LG"; used[i + 1] = True
            f["floor"].append(lvl); used[i] = True
            if i + 1 < n and toks[i + 1] in FLOOR_WORDS:
                used[i + 1] = True
    for i in range(n):
        if used[i]:
            continue
        t = toks[i]
        nxt = toks[i + 1] if i + 1 < n else ""
        nb = set(toks[max(0, i - 1):i]) | set(toks[i + 1:i + 2])
        if t in UNIT_WORDS:
            f["unit"].append(UNIT_WORDS[t]); used[i] = True
        elif t in NUMBERED_UNIT and re.fullmatch(r"\d+[A-Z]?|[A-Z]", nxt or "-"):
            f["unit"].append(NUMBERED_UNIT[t]); used[i] = True
        elif t in ROOM_WORDS:
            f["room"] = True; used[i] = True
        elif t in ANNEX_WORDS:
            f["annex"] = True; used[i] = True
        elif t in POSITION_WORDS and (nb & (set(UNIT_WORDS) | FLOOR_WORDS | set(ORDINAL) | set(FLOOR_ABBR) | ROOM_WORDS)):
            f["pos"].append(POSITION_WORDS[t]); used[i] = True
        elif t in DQ1_UNI:
            f["dq1"].append(t); used[i] = True
        elif t in DQ2_UNI:
            f["dq2"].append(t); used[i] = True
        elif t in DQ3_UNI and (t != "AT" or f["unit"] or f["annex"] or f["room"] or f["floor"]):
            f["dq3"].append(t); used[i] = True
    for i in range(n):
        if used[i]:
            continue
        t = toks[i]
        if NUM_RE.match(t) or RANGE_RE.match(t) or SLASH_RE.match(t):
            f["nums"].append(t); f["order"].append("N")
        elif re.fullmatch(r"[A-Z]", t) or re.fullmatch(r"[A-Z]\d+[A-Z]?", t):
            f["letters"].append(t); f["order"].append("L")
        else:
            f["words"].append(t); f["order"].append("W")
    name = " ".join(w for w in f["words"])
    if name and GENERIC_NAME.match(name):
        f["generic"] = name
    return f


def num_parts(t):
    m = NUM_RE.match(t)
    if m:
        return int(m.group(1)), m.group(2), None
    m = RANGE_RE.match(t)
    if m:
        return int(m.group(1)), m.group(2), (int(m.group(1)), int(m.group(3)))
    m = SLASH_RE.match(t)
    if m:
        return int(m.group(2)), "/" + m.group(1), None
    return None, None, None


def num_relation(a, b):
    """Relation between recorded number a and canonical number b."""
    ba, sa, ra = num_parts(a)
    bb, sb, rb = num_parts(b)
    if ba is None or bb is None:
        return "PN3:other"
    if ra or rb:
        lo_hi = ra or rb
        single = ba if rb else bb
        if ra and rb:
            return "PN2:range_changed"
        if lo_hi[0] <= single <= lo_hi[1]:
            return "PN2:range_to_single" if rb else "PN2:single_to_range"
        return "PN3:other"
    if (sa or "").startswith("/") or (sb or "").startswith("/"):
        return "SU2:slash_form"
    if ba == bb:
        if sa and sb:
            return "SU1:suffix_swapped"
        return "SU1:suffix_dropped" if sb else "SU1:suffix_added"
    da, db = str(ba), str(bb)
    if len(da) == len(db) and sorted(da) == sorted(db):
        return "PN3:transposition"
    if abs(ba - bb) <= 2:
        return "PN3:neighbour_pm2"
    if Levenshtein.distance(da, db) == 1:
        if len(da) < len(db):
            return "PN3:digit_dropped"
        if len(da) > len(db):
            return "PN3:digit_added"
        return "PN3:digit_substituted"
    return "PN3:other"


REL_PRIORITY = ["SU1", "SU2", "PN2", "PN3:transposition", "PN3:neighbour_pm2", "PN3:digit"]


def compare_dwelling(rec, can, can_sub_nums, parent_nums, alt_names):
    """Return labels for dwelling-layer differences. rec/can are parse_dwelling dicts."""
    L = []
    # ---- numbers
    rn = list(rec["nums"])
    cn = list(can["nums"])
    common = []
    for x in list(rn):
        if x in cn:
            rn.remove(x); cn.remove(x); common.append(x)
    # SU2: canonical "12B" vs recorded "12" + letter B (Flat B, 12) or reverse
    for x in list(cn):
        b, s, r = num_parts(x)
        if b is not None and s and not s.startswith("/") and str(b) in rn and s in rec["letters"]:
            L.append("SU2:suffix_as_flat_letter"); cn.remove(x); rn.remove(str(b)); rec["letters"].remove(s)
    for x in list(rn):
        b, s, r = num_parts(x)
        if b is not None and s and not s.startswith("/") and str(b) in cn and s in can["letters"]:
            L.append("SU2:flat_letter_as_suffix"); rn.remove(x); cn.remove(str(b)); can["letters"].remove(s)
    # pair leftovers greedily by relation priority
    pairs = []
    while rn and cn:
        best = None
        for a in rn:
            for b in cn:
                rel = num_relation(a, b)
                pr = next((k for k, p in enumerate(REL_PRIORITY) if rel.startswith(p)), len(REL_PRIORITY))
                if best is None or pr < best[0]:
                    best = (pr, a, b, rel)
        pr, a, b, rel = best
        if pr == len(REL_PRIORITY) and (len(rn) > 1 or len(cn) > 1):
            # unrelated: only pair if one each
            pass
        pairs.append((a, b, rel)); rn.remove(a); cn.remove(b)
    for a, b, rel in pairs:
        L.append(rel)
    for a in rn:
        if a in parent_nums:
            L.append("PN6:parent_number_added")
        else:
            L.append("PN6:number_added")
    for b in cn:
        if b in can_sub_nums:
            L.append("SU7:subunit_number_dropped")
        else:
            L.append("PN4:number_dropped")
    # letters (flat ids like FLAT A)
    rl, cl = list(rec["letters"]), list(can["letters"])
    for x in list(rl):
        if x in cl:
            rl.remove(x); cl.remove(x)
    if rl and cl:
        L.append("SU1:letter_id_swapped")
    elif rl:
        L.append("SU1:letter_id_added")
    elif cl:
        L.append("SU1:letter_id_dropped")
    # ---- sub-unit typing
    ru, cu = set(rec["unit"]), set(can["unit"])
    if ru != cu:
        if ru and cu:
            L.append("SU10:unit_word_swapped")
        elif ru:
            L.append("SU13:unit_word_added")
        else:
            L.append("SU13:unit_word_dropped")
    rf, cf = set(rec["floor"]), set(can["floor"])
    if rf != cf:
        if rf and cf:
            L.append("SU3:floor_changed")
        elif rf:
            L.append("SU4:floor_descriptor_added")
        else:
            L.append("SU4:floor_descriptor_dropped")
    rp, cp = set(rec["pos"]), set(can["pos"])
    if rp != cp:
        L.append("SU6:position_swapped" if rp and cp else ("SU6:position_added" if rp else "SU6:position_dropped"))
    if rec["annex"] != can["annex"]:
        L.append("SU8:annex_added" if rec["annex"] else "SU8:annex_dropped")
    if rec["room"] != can["room"]:
        L.append("SU9:room_added" if rec["room"] else "SU9:room_dropped")
    for key, mid in (("dq1", "DQ1"), ("dq2", "DQ2"), ("dq3", "DQ3")):
        a, b = set(rec[key]), set(can[key])
        if a - b:
            L.append(f"{mid}:added")
        if b - a:
            L.append(f"{mid}:dropped")
    # ---- names
    rw = " ".join(rec["words"])
    cw = " ".join(can["words"])
    if rw != cw:
        rcs, ccs = canon_seq(rec["words"]), canon_seq(can["words"])
        if rcs == ccs:
            if [t for t in rec["words"] if t != "THE"] == [t for t in can["words"] if t != "THE"]:
                L.append("BN2:article_the")
            else:
                L.append("BN7:abbreviated_name_word")
        elif rw.replace(" ", "") == cw.replace(" ", ""):
            L.append("BN6:spacing")
        elif not rw:
            L.append("BN3:generic_name_dropped" if can["generic"] else "BN1:name_dropped")
        elif not cw:
            L.append("BN3:generic_name_added" if rec["generic"] else "BN1:name_added")
        elif sorted(rcs) == sorted(ccs):
            L.append("SU11:word_order")
        else:
            rs, cs = set(rcs), set(ccs)
            if rec["generic"] and not can["generic"] or can["generic"] and not rec["generic"]:
                L.append("BN3:generic_name_swapped")
            elif rs < cs:
                L.append("BN1:second_name_dropped" if _separate_block(can, rcs) else "BN2:name_truncated")
            elif cs < rs:
                L.append("BN1:second_name_added" if _separate_block(rec, ccs) else "BN2:name_elaborated")
            elif rw in alt_names:
                L.append("BN5:alternative_or_historic_name")
            else:
                sc = fuzz.ratio(" ".join(rcs), " ".join(ccs))
                if sc >= 85:
                    L.append("BN6:spelling")
                elif rs & cs:
                    L.append("BN4:name_partly_changed")
                else:
                    L.append("BN4:name_replaced")
    elif rec["order"] != can["order"] and rec["nums"] and rec["words"] and set(rec["nums"]) == set(can["nums"]):
        L.append("SU11:component_order")
    return L


def _separate_block(f, shared):
    """True when the words of f not in `shared` sit in a separate word block (split by a number/letter)."""
    blocks, cur = [], []
    wi = 0
    for o in f["order"]:
        if o == "W":
            if wi < len(f["words"]):
                cur.append(canon_tok(f["words"][wi]))
            wi += 1
        elif cur:
            blocks.append(cur); cur = []
    if cur:
        blocks.append(cur)
    sh = set(shared)
    return len(blocks) >= 2 and any(all(t in sh or t == "THE" for t in b) for b in blocks) and \
        any(all(t not in sh for t in b) for b in blocks)


def dwelling_tokens_from_components(sub, name, number):
    toks = []
    for part in (sub, name, number):
        if part:
            t, _ = norm_text(part)
            toks += t
    return toks
