"""House style: how a source writes an address down once the dwelling components are decided.

Locality tail (which of NGD locality, PAF dependent locality, NGD town, PAF post town, county and "other" place
text a source writes, in order), the per-street street-variant layer, ST3 and SU11 style edits, commas, case and
brackets. Then systemic settings: SY1 fixed-width truncation, applied last. Rates come from
profile.house_style[<source>]. Flattened from prototype_loop generator_v1.py / generator_v2.py (run 3b), with the
profile v3 changes from generator_v3.py: per-eligible style edits (SU13 unit word, SU4 floor, SU9 room, FM6 leading
zero, SU11 order, DQ4 brackets) and the v3 source of "other" locality text.
"""
import random
import re

from .vocab import ABBR, COUNTY_WORDS, FLOOR_RE, KEYS, UNIT_RE, norm, title_case

_COUNTY_TAIL = re.compile(r'\s+' + COUNTY_WORDS + '$')
_COUNTY_TAIL_SEP = re.compile(r'[\s,]+' + COUNTY_WORDS + '$')
_PARTIAL_POSTCODE = re.compile(r'[A-Z]{1,2}\d[A-Z\d]?( ?\d?[A-Z]{0,2})?')


def county(g, r):
    if g.county_word is not None:
        return g.county_word
    district = r['postcode'].split(' ')[0] if r['postcode'] else ''
    opts = {k: v for k, v in g.extras.get('county_by_postcode_district', {}).get(district, {}).items() if k != '__none__'}
    if not opts and g.county_words:
        opts = {k: v for k, v in g.county_words.items() if v > 0}
    return g.rng.choices(list(opts), list(opts.values()))[0] if opts else ''


def locality_tail(g, D, r):
    rng = g.rng
    dep = r['rm_dependentlocality']
    dep_yes = bool(dep) and dep != r['locality'] and dep != r['townname']
    k1 = f"ngd_locality={'yes' if D['locality'] else 'no'}|town_equals_post_town={'yes' if (r['rm_posttown'] or r['townname']) == r['townname'] else 'no'}"
    pat = g.loc_choice.get(f"{k1}|paf_dep_locality={'yes' if dep_yes else 'no'}") or g.loc_choice_v1.get(k1)
    if not pat:
        return [x for x in (D['locality'], D['town']) if x]
    ks, ws = zip(*pat['p'].items())
    choice = rng.choices(ks, ws)[0]
    tail = []
    avoid = {norm(D.get(f)) for f in ('sub', 'name', 'street', 'org', 'dep') if D.get(f)}
    for t in choice.split('>'):
        v = {'ngd_locality': D['locality'], 'paf_dep_locality': dep, 'ngd_town': D['town'],
             'paf_post_town': r['rm_posttown'] or D['town'], 'county': county(g, r), '(nothing)': ''}.get(t)
        if t == 'other' and g.v3:
            v = _COUNTY_TAIL_SEP.sub('', other_text_v3(g, r) or '')
        elif t == 'other':
            o = g.loc_other.get((g.src, r['usrn']))
            if o:
                v = rng.choices(list(o), list(o.values()))[0]
                v = _COUNTY_TAIL.sub('', v)
            else:
                sector = r['postcode'][:-2].strip() if r['postcode'] else ''
                opts = g.extras.get('locality_by_postcode_sector', {}).get(sector)
                v = rng.choices(list(opts), list(opts.values()))[0] if opts else ''
            v = _COUNTY_TAIL_SEP.sub('', v or '')
        if v and v not in tail and norm(v) not in avoid:
            tail.append(v)
    return tail


def other_text_v3(g, r):
    """v3: the per-street lookup, else another street's name at other_text_kind.another_street_name, else the
    per-sector lookup (locality_other_by_sector)."""
    rng = g.rng
    o = g.loc_other.get((g.src, r['usrn']))
    if o:
        return rng.choices(list(o), list(o.values()))[0]
    if rng.random() < g.other_kind.get('another_street_name', 0) * g.another_street_scale:
        return g.near_street(r) or ''
    sector = r['postcode'][:-2].strip() if r['postcode'] else ''
    if g.sector_from_extras:
        opts = g.extras.get('locality_by_postcode_sector', {}).get(sector)
    else:
        opts = g.loc_sector.get((g.src, sector))
    return rng.choices(list(opts), list(opts.values()))[0] if opts else ''


def style_edits_v3(g, D, r):
    """v3 style edits at rates per eligible record (house_style[<source>].style_rates_per_eligible)."""
    rng, pe = g.rng, g.per_elig
    sub = D['sub']
    if sub and not UNIT_RE.match(sub) and g.sdraw(r, 'SU13:unit_word_added', pe.get('SU13:unit_word_added', 0)):
        v = g.unit_vocab
        D['sub'] = g.brng(r, 'unit_word').choices(list(v), list(v.values()))[0] + ' ' + sub
    elif sub and not FLOOR_RE.search(sub) and g.sdraw(r, 'SU4:floor_descriptor_added', pe.get('SU4:floor_descriptor_added', 0)):
        try:
            lv = int((r['floorlevel'] or '').split(',')[0])
        except ValueError:
            lv = rng.choice([0, 1, 1, 2])
        f = g.floor_word(lv)
        D['sub'] = f'{sub} {f}' if g.brng(r, 'floor_order').random() < 0.5 else f'{f} {sub}'
    if g.sdraw(r, 'SU9:room_added', pe.get('SU9:room_added', 0)):
        D['sub'] = f'ROOM {rng.randint(1, 9)}' + (' ' + D['sub'] if D['sub'] else '')
    if D['sub'] and g.sdraw(r, 'FM6:leading_zero', pe.get('FM6:leading_zero', 0)):
        D['sub'] = re.sub(r'(?<!\d)(\d)(?!\d)', r'0\1', D['sub'], count=1)
    dep = r['rm_dependentthoroughfare']
    if dep and not D['dep'] and dep not in (D['name'], D['sub'], D['street']) \
            and g.sdraw(r, 'ST3:dependent_or_estate_name_added', pe.get('ST3:dependent_or_estate_name_added', 0)):
        D['dep'] = dep
    if D['street'] and g.sdraw(r, 'ST3:access_road_off_added', pe.get('ST3:access_road_off_added', 0)):
        s = g.near_street(r)
        if s:
            commas = g.shares.get('has_comma', 1) > 0.5 if g.controls.commas is None else g.controls.commas
            D['street'] = D['street'] + (', OFF ' if commas else ' OFF ') + s
    if D['sub'] and D['name'] and g.sdraw(r, 'SU11:component_order', pe.get('SU11:component_order', 0)):
        D['order'] = 'sub_after_name'
    elif D['sub'] and g.sdraw(r, 'SU11:subunit_after_street', pe.get('SU11:subunit_after_street', 0)):
        D['order'] = 'sub_after_street'


def variant_text(kind, r, srng):
    s = r['streetname']
    w = s.split()
    if kind == 'rm_thoroughfare':
        return r['rm_thoroughfare'] if r['rm_thoroughfare'] and r['rm_thoroughfare'] != s else None
    if kind == 'abbreviated':
        idx = [i for i, t in enumerate(w) if t in ABBR]
        if not idx:
            return None
        i = srng.choice(idx); w[i] = ABBR[w[i]]; return ' '.join(w)
    if kind == 'words_dropped':
        return ' '.join(w[:-1]) if len(w) > 1 else None
    if kind == 'joined_or_split':
        if "'" in s or '-' in s:
            return s.replace("'", ' ').replace('-', ' ')
        pairs = [i for i in range(len(w) - 1) if w[i].isalpha() and w[i + 1].isalpha()]
        long = [i for i, t in enumerate(w) if len(t) >= 8 and t.isalpha()]
        if pairs and (not long or srng.random() < .5):
            i = srng.choice(pairs); return ' '.join(w[:i] + [w[i] + w[i + 1]] + w[i + 2:])
        if long:
            i = srng.choice(long); k = srng.randrange(3, len(w[i]) - 2)
            return ' '.join(w[:i] + [w[i][:k], w[i][k:]] + w[i + 1:])
        return None
    if kind == 'spelling':
        idx = [i for i, t in enumerate(w) if len(t) >= 4 and t.isalpha()]
        if not idx:
            return None
        i = srng.choice(idx); t = w[i]; j = srng.randrange(1, len(t) - 1)
        op = srng.choice(['del', 'sub', 'ins', 'swap'])
        t = {'del': t[:j] + t[j + 1:], 'sub': t[:j] + srng.choice(KEYS) + t[j + 1:], 'ins': t[:j] + t[j] + t[j:],
             'swap': t[:j - 1] + t[j] + t[j - 1] + t[j + 1:]}[op]
        w[i] = t; return ' '.join(w)
    return None


def street_variant(g, D, r):
    """Per-street layer: the street lookup if one is loaded, else a per-street convention drawn by kind."""
    if not D['street'] or D['street'] != r['streetname'] or not r['usrn']:
        return
    rng = g.rng
    lk = g.sv_lookup.get((g.src, r['usrn']))
    if lk:
        text, share = lk
        if rng.random() < share:
            D['street'] = text
        return
    if r['usrn'] not in g._sv_conv:
        srng = random.Random(f'sv|{g.source_id}|{r["usrn"]}')
        conv = None
        for kind, p in g.sv.get('share_of_streets_with_variant_convention', {}).items():
            if srng.random() < p * g.controls.street_variant_scale:
                conv = kind
                break
        g._sv_conv[r['usrn']] = variant_text(conv, r, srng) if conv else None
    text = g._sv_conv[r['usrn']]
    if text and rng.random() < g.sv.get('within_street_share_given_convention', {}).get('mean', 0.5):
        D['street'] = text


def serialise(g, D, r):
    if g.v3:
        street_variant(g, D, r)   # before the style edits, which may append "OFF <street>" (runs again below)
        style_edits_v3(g, D, r)
        s = _serialise(g, D, r)
        if D['sub'] and g.sdraw(r, 'DQ4:brackets', g.per_elig.get('DQ4:brackets', 0)):
            i = s.upper().find(D['sub'].upper())
            if i >= 0:
                s = s[:i] + '(' + s[i:i + len(D['sub'])] + ')' + s[i + len(D['sub']):]
        return s
    return _serialise(g, D, r)


def _serialise(g, D, r):
    street_variant(g, D, r)
    rng = g.rng
    c = g.controls
    tail = locality_tail(g, D, r)
    sr = g.style_rates
    el = g.elig_share
    if rng.random() < sr.get('ST3:access_road_off_added', 0) / el['street'] and D['street']:
        s = g.near_street(r)
        if s:
            tail.insert(0, 'OFF ' + s)
    if rng.random() < sr.get('ST3:dependent_or_estate_name_added', 0) / el['dep'] and r['rm_dependentthoroughfare'] and not D['dep'] \
            and r['rm_dependentthoroughfare'] not in (D['name'], D['sub'], D['street']):
        D['dep'] = r['rm_dependentthoroughfare']
    order = D['order']
    if D['sub'] and D['name'] and rng.random() < sr.get('SU11:moved_NAME', 0) / el['sub_name']:
        order = 'sub_after_name'
    elif D['sub'] and rng.random() < sr.get('SU11:moved_SUB', 0) / el['sub']:
        order = 'sub_after_street'
    num_street = [x for x in (D['number'], D['dep'], D['street']) if x]
    org = [D['org']] if D.get('org') else []
    sub = D['sub']
    if order == 'std':
        parts = org + D['pre'] + [sub, D['name'], D['name2']] + num_street
    elif order == 'sub_after_name':
        parts = org + D['pre'] + [D['name'] + (',' if g.fused_name_sub else ', ') + sub if sub else D['name'], D['name2']] + num_street
    else:
        parts = org + D['pre'] + [D['name'], D['name2']] + num_street + [sub]
    parts = [x for x in parts + tail if x]
    sh = g.shares
    commas = sh.get('has_comma', 1) > 0.5 if c.commas is None else c.commas
    if commas:
        s = ', '.join(parts)
        s = re.sub(r'^(\d+[A-Z]?(?:-\d+[A-Z]?)?), ', lambda mm: mm.group(1) + (', ' if rng.random() < sh.get('comma_after_leading_number', 1) else ' '), s)
        s = re.sub(r'(, )(\d+[A-Z]?), (?=[A-Z])', lambda mm: mm.group(1) + mm.group(2) + (', ' if rng.random() < sh.get('comma_after_leading_number', 1) else ' '), s)
        if rng.random() < sh.get('double_comma_or_empty_field', 0):
            s = s.replace(', ', ', , ', 1)
    else:
        s = ' '.join(parts)
    if rng.random() < sh.get('brackets', 0) and sub:
        s = s.replace(sub, f'({sub})', 1)
    upper = sh.get('upper', 0) > 0.5 if c.case is None else c.case == 'upper'
    return s.upper() if upper else title_case(s)


def truncate_sy1(s_out, pc, cap):
    """SY1: the source stores address and postcode in one field of `cap` characters and cuts the rest.
    Returns (address, postcode, truncated). A partial postcode left at the end stays in the postcode slot."""
    full = s_out + (', ' + pc if pc else '')
    if len(full) <= cap:
        return s_out, pc, False
    full = full[:cap]
    head, _, last = full.rpartition(', ')
    if pc and _PARTIAL_POSTCODE.fullmatch(last.strip()):
        return head, last.strip(), True
    return full, '', True


def paf_differs(r):
    if not (r['rm_thoroughfare'] or r['rm_buildingname']):
        return False
    return norm(r['subname'], r['name'], r['number']) != norm(r['rm_subbuildingname'], r['rm_buildingname'], r['rm_buildingnumber'])
