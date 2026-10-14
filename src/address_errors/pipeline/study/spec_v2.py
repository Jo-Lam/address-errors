"""Taxonomy v2 definitions. Each aligned edit gets exactly one ID (classify_edits.py), so rates are per edit/row
with no double labelling. change: kept | narrowed | widened | new | retired | unchanged_v1 (not re-measured here)."""
M = []
def m(id, name, layer, change, definition, example, detect, ctx="all", seed=None, notes="", replaces=""):
    M.append(dict(id=id, name=name, layer=layer, change=change, definition=definition, generic_example=example,
                  detection=detect, primary_context=ctx, seed=seed, notes=notes, replaces=replaces))

# SU
m("SU1", "Number suffix added, dropped or swapped", "pao_number", "narrowed",
  "The letter suffix of a house number is added, removed or replaced (12 <-> 12A, 12A <-> 12B). Unit-id letters inside a building recode are SU14.",
  "12A X Street <-> 12 X Street", "num_suffix_dropped/added/swapped on NUM or NAME.", ctx="number_letter_suffix", seed="Seed 1",
  notes="26% of v1 SU1 single-edit rows were really SU14 (building recode). A dropped suffix collides 79% of the time when alone; an added one 31%.")
m("SU3", "Floor level changed", "sao", "retired_to_seed",
  "A floor descriptor names a different floor.", "First Floor Flat <-> Ground Floor Flat",
  "Floor words on both sides map to different ordinals (TOP excluded).", ctx="has_subunit", seed="Seed 4",
  notes="Only 7 edits in four councils (all Leeds), and none of the 168 floor-word replacements is a real floor swap. Keep as a seed with a fixed small rate; do not fit.")
m("SU4", "Floor descriptor added or dropped", "sao", "kept", "Floor descriptor present on one side only, on a record that already has a sub-unit.",
  "Flat 2 <-> Flat 2 Ground Floor", "Inserted/deleted floor words where the canonical record is a child or has a sub-unit.", ctx="has_subunit")
m("SU5", "Floor vocabulary variant", "sao", "now_measured", "Same floor written with different words (FIRST <-> 1ST, GROUND <-> GRD, TOP <-> SECOND).",
  "1st Floor Flat <-> First Floor Flat", "Replaced floor words map to the same ordinal (TOP vs an ordinal is its own subtype).", ctx="has_subunit")
m("SU6", "Position qualifier added or dropped", "sao", "kept", "Front, rear, left, right, upper, middle on one side only.",
  "Ground Floor Front <-> Ground Floor", "Position words inserted or deleted.", ctx="has_subunit")
m("SU7", "Sub-unit, or its id or span, dropped", "sao", "widened",
  "The recorded string loses the sub-unit that identifies the dwelling: the whole numberless sub-unit (FLAT AT, FLAT), the unit id, a room span, or the whole sub-unit with its id. It reads as the building.",
  "Flat At, 191 X Road -> 191 X Road; Rooms 1-6, Y House -> Y House", "Deleted SUB text that is the whole component, or contains the id or span.",
  ctx="has_subunit", replaces="SU7 + SU9 dropped side + SU13 whole-numberless case + DQ3 dropped with collapse",
  notes="Collides with the parent 67-87% of the time when alone. This is the main to_parent route.")
m("SU8", "Annex attached or detached", "sao", "retired_to_seed", "Annex word on one side only.", "9 X Drive <-> Annexe, 9 X Drive",
  "Annex lexicon in inserted or deleted text.", seed="Seed 5", notes="21 rows in four councils, with no coherent edit pattern; 7 are in Basingstoke (3.2 per 10,000, about 15 times the urban councils). Fixed small rate, scaled by a rural/named-house context.")
m("SU9", "Room / HMO aggregation", "sao", "retired", "Merged: room span dropped is SU7 (span subtype); rooms added on a building UPRN is SU15.", "", "", replaces="-> SU7, SU15")
m("SU10", "Unit-type word swapped", "sao", "kept", "Flat <-> Apartment <-> Room <-> Site <-> Caravan for the same unit.", "Apartment 15 <-> Flat 15",
  "Replaced SUB words that are unit words.", ctx="has_subunit")
m("SU11", "Component order changed", "sao", "kept", "Same components in another order (Bradford 'Building, Flat n'; sub-unit after street).",
  "Z Court, Flat 51 <-> Flat 51, Z Court", "MOVE edits. Mostly Bradford house style: fit as a per-council style setting.", ctx="has_subunit")
m("SU12", "Sub-unit number in the house-number slot", "sao", "retired", "Not separable from SU13 at string level; needs the identity test (is the number also a real house number on the street?).",
  "", "", replaces="-> SU13 until an identity-based rule exists")
m("SU13", "Unit word added or dropped next to a kept id", "sao", "narrowed", "Only the unit word changes; the unit id stays.",
  "Flat 3, X House <-> 3 X House", "Inserted/deleted unit words where the canonical record already has a sub-unit or a parent.", ctx="has_subunit",
  notes="Identity-preserving: 0% collide when alone (v1 SU13 collided 7% because it included the whole-sub-unit drops now in SU7).")
m("SU14", "Unit ids re-encoded to a building scheme", "sao", "new",
  "Every unit in a building is written in the building's own block/floor/room code (3 -> C2/3.1, 301 -> S301, 14 -> 14.1). A building-level recode, mostly HMOs and student halls.",
  "Flat 3, Y Hall <-> Flat C2/3.1, Y Hall", "Discovery family F23 (id_composite_contains_canonical, id_letter_prefix_added, letter_digit_same_rank ...).",
  ctx="has_subunit", notes="Apply per building to all units; in Leeds the top 10 buildings hold 79% of rows. Absent in Wigan and Basingstoke (4 and 1 rows). Identity preserved (<1% collide).")
m("SU15", "Sub-unit added on a building-level UPRN", "sao", "new",
  "The council adds a whole sub-unit (Flat 1st Floor, Flat A, Rooms 1-6) to a UPRN that NGD records as a building with no sub-unit. The reverse of SU7.",
  "9 X Street <-> Flat A, 9 X Street", "Inserted sub-unit text where the labelled UPRN has no sub-unit and no parent.", ctx="no_subunit",
  notes="Collides only 1% because NGD usually has no child for it: the council is disaggregating below the gazetteer. Link to LB2.")
# BN
m("BN1", "Building name added or dropped", "pao_name", "kept", "A whole building name is present on one side only.", "Greystone Cottage, 205 X Road <-> 205 X Road",
  "Whole NAME deleted, or name text inserted before the number or street.")
m("BN2", "Building name partly shortened or elaborated", "pao_name", "widened", "Some words of the name are dropped or added (THE, FARM, HOUSE, COLLEGE).",
  "The Old Cottage <-> Old Cottage Rooms", "Partial NAME deletion, or insertion inside the name.", replaces="BN2 + BN4 'partly changed'")
m("BN3", "Generic dwelling name", "pao_name", "kept", "A generic dwelling name (The Bungalow, Coach House, Presbytery) is added or dropped.",
  "The Bungalow, Z House <-> 54 Z House", "Generic-name lexicon in inserted or deleted name text.", seed="Seed 6")
m("BN4", "Building name replaced", "pao_name", "narrowed", "The name is a different name (renamed business, sibling block).", "Weavers House <-> East Mill",
  "REPL on NAME. Check NGD alternative names (BN5) first.", notes="Collides 9% when alone, mostly to the same complex.")
m("BN5", "Alternative or historic name", "pao_name", "unchanged_v1", "Recorded name equals an NGD alternative/historical rendering.", "",
  "Exact match to _altadd. Not re-measured by alignment; v1 rates stand.")
m("BN6", "Name spelling or spacing variant", "pao_name", "retired", "", "", "", replaces="-> TX2 (spacing), TX3 (typo)")
m("BN7", "Abbreviated word inside a name", "pao_name", "retired", "", "", "", replaces="-> TX1")
m("BN8", "Organisation name dropped, added or replaced", "organisation", "new",
  "The organisation line (UNIVERSITY OF LEEDS, a care home, a shop) is dropped, added or changed.", "University of X, Flat 3 Y House <-> Flat 3 Y House",
  "Edits on the ORG slot.", notes="Collides 19% overall, but this is Wigan-driven (41% of Wigan's whole-org drops collide; Leeds and Bradford 5-9%). Fit the collision share per council.")
# PN
m("PN1", "Suffix + name change (Seed 2)", "pao_number", "bundle", "SU1 with BN1/BN2/BN4 on one record. Sample as a bundle.", "The Old Cottage, 115 <-> The Old Cottage Rooms, 115A", "Co-occurrence.", seed="Seed 2")
m("PN2", "Range collapsed, extended or changed", "pao_number", "narrowed", "A real range change: 92-94 -> 92 (collapse), 25 -> 25-27 (extension), or another single number from the range.",
  "111-113 X Road <-> 111 X Road", "num_range_* relations. Separator-only differences (60/62 vs 60-62) are FM9.", notes="Collapse collides 15%, extension 3%.")
m("PN3", "House number keyed wrong", "pao_number", "narrowed", "Digit changed, dropped or transposed, or a different number with the street unchanged.",
  "143 X Road <-> 134 X Road", "num_one_digit_changed / digit_dropped / digits_transposed / number_other on NUM.",
  notes="Transpositions and dropped digits never collide; one changed digit collides about 70% when alone.")
m("PN4", "House number dropped", "pao_number", "kept", "Canonical number missing in the recorded string.", "Rose Villa, X Lane <-> Rose Villa, 12 X Lane", "Whole NUM deleted.", ctx="name_and_number")
m("PN5", "Renumbering over time", "pao_number", "lifecycle", "", "", "LC tag; not fitted as error.")
m("PN6", "Extra number or unit id added", "pao_number", "kept", "A number the canonical lacks is added (often the block's number, or a unit id on a child record).",
  "Flat 3, 12 X Court <-> Flat 3, X Court", "Inserted digits.")
m("PN7", "House number slip to a neighbour (+-1, +-2)", "pao_number", "new", "House number off by one or two.",
  "12 X Road <-> 14 X Road", "num_delta on NUM.", notes="Collides 83% when alone (to_neighbour). Discovery: the low +-1 collision rate comes from Leeds only, so use partial pooling.")
m("PN8", "Unit number slip to a sibling", "sao", "new", "Flat/unit number off by one or two, or one digit changed.",
  "Flat 6 <-> Flat 7, same building", "num_delta or one digit changed on SUB.", ctx="has_subunit", notes="Collides 70-100% when alone, to_sibling.")
# DQ
m("DQ1", "Relative-location qualifier", "qualifier", "narrowed", "Adj, Rear of, Land at, Next to, Opposite on one side only.",
  "Cottage Adj X Farm <-> X Farm Cottage", "Qualifier lexicon. 'Off <road>' is ST3.")
m("DQ2", "Development-stage descriptor", "qualifier", "kept", "New, Plot, Development, Proposed on one side only.", "New House Adjacent, 81 X Street <-> 81 X Street", "Lexicon.", seed="Seed 3")
m("DQ3", "Use or occupancy descriptor", "qualifier", "narrowed", "A real use descriptor (above shop, caretaker's, warden's, stable conversion) added or dropped.",
  "Flat Above Shop, 1A Market Street <-> 1A Market Street", "Lexicon. The 'AT' connective is FM8; a dropped whole sub-unit is SU7.")
m("DQ4", "Bracketed note", "whole_string", "unchanged_v1", "", "", "Format flag; v1 counts stand.")
# ST/LO
m("ST1", "Street-type abbreviation", "street", "retired", "", "", "", replaces="-> TX1 (street slot)")
m("ST2", "Street words differ", "street", "narrowed", "Some street words dropped (LANE, ROAD). Spelling and spacing are TX2/TX3.", "X Lane <-> X", "Partial STREET deletion.")
m("ST3", "Dependent, access or estate street added or dropped", "street", "widened", "'Off <road>' (Bradford convention), a dependent street or an estate name inserted next to the street.",
  "10 X Close, Off Y Lane <-> 10 X Close", "Inserted text with OFF, or inserted between name and street.", replaces="ST3 + DQ1 'Off' rows")
m("ST4", "Different street", "street", "kept", "Street replaced by another street, number unchanged.", "9 X Close <-> 9 X Drive", "REPL on STREET with no number change.")
m("ST5", "Street omitted", "street", "kept", "The street is missing (complex or building name used as the thoroughfare).", "4 Mill Court <-> 4 Mill Court, Mill Lane", "Whole STREET deleted.")
m("LO", "Locality, town and county (LO1-LO3)", "locality_town_county", "kept", "House style: locality, post town, county.", "", "Aligned LOC/TOWN edits; per-council setting.")
# TX
m("TX1", "Word abbreviated or expanded (any component)", "any", "new", "A word is abbreviated or expanded in any slot: RESIDENCES -> RESS, HOUSE -> HSE, ROAD -> RD, FIRST -> 1ST.",
  "Hall Fm <-> Hall Farm; X Rd <-> X Road", "council_shorter_subsequence / council_longer_supersequence, any slot. Report per slot.",
  replaces="BN7, ST1, abbreviation part of BN4/BN6/SU5")
m("TX2", "Word spacing or hyphenation (any component)", "any", "new", "Words joined or split (CLAY PIT <-> CLAYPIT, BURLEY IN WHARFEDALE <-> BURLEY-IN-WHARFEDALE).",
  "Lakeview House <-> Lake View House", "tokens_joined / token_split, any slot.", replaces="BN6 spacing, ST2 spacing")
m("TX3", "1-2 character typo (any component)", "any", "new", "Insert, delete, substitute or transpose 1-2 characters in a word.",
  "Wigna <-> Wigan", "edit1 / edit2, any slot.", replaces="KY, BN6 spelling, ST2 spelling")
# FM
m("FM8", "Connective token (AT, &)", "whole_string", "new", "'AT' or '&' inserted or dropped (Flat At, 1st Floor At).",
  "Flat At, 349 X Road <-> Flat, 349 X Road", "Inserted/deleted AT or connective-only text.",
  notes="Was 853 of 1,124 DQ3-added rows. Adding it never collides; dropping it collides only where the whole sub-unit goes too.")
m("FM9", "Punctuation or separator variant", "whole_string", "new", "Same text, different punctuation: 60/62 vs 60-62, VM1 vs VM-1.",
  "60/62 X Road <-> 60-62 X Road", "punct_only, any slot.", replaces="PN2 separator rows (47% of v1 PN2)", notes="Never collides. Mainly Leeds and Wigan; Bradford's rows sit in a few sites (VM1 vs VM-1).")
for x, n in (("FM1", "Case convention"), ("FM2", "Separator convention"), ("FM3", "Empty-field artefact"), ("FM5", "Postcode in address text"),
             ("FM6", "Leading zeros"), ("FM7", "Duplicated component"), ("SY1", "Fixed-width truncation")):
    m(x, n, "whole_string", "unchanged_v1", "", "", "See v1.")
for x, n in (("PC1", "Postcode missing"), ("PC2", "Postcode format"), ("PC3", "Unit within sector"), ("PC4", "Sector"), ("PC5", "District")):
    m(x, n, "postcode", "unchanged_v1", "", "", "See v1 (Wigan and Basingstoke only).")
m("LB1", "Neighbour's UPRN on a clean address", "label", "unchanged_v1", "", "", "Conflict groups; single-row form = PN7/SU1 with exact collision.")
m("LB2", "Parts under the whole's UPRN", "label", "unchanged_v1", "", "", "Conflict groups; single-row form = SU15 (and SU7 with collision).")
m("LB3", "Sibling's UPRN", "label", "unchanged_v1", "", "", "Conflict groups; single-row form = PN8.")
m("LB4", "Unrelated property's UPRN", "label", "widened", "The record points at another address: number and street both changed, or (conflicts) a different property.",
  "36 X Way <-> 36 Y Avenue", "Conflict groups, plus single rows where number and street are both replaced.", replaces="LB4 + PN3 'number completely different with street change'")
