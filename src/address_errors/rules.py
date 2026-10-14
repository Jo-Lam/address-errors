"""Mechanism rules: apply one `MECHANISM:subtype` edit to a dwelling dict in place.

A dwelling dict D holds the components being written: pre (list of leading qualifiers), sub, name, name2, number,
dep (dependent street), street, locality, town, org, order, base. A rule either edits D or raises Unapplicable
(the requested edit cannot happen on this record); the corruptor records which.

These are the rules of the realism-checked prototype generator (prototype_loop/code/generator.py, generator_v1.py
and generator_v2.py, run 3b), flattened into one function per mechanism ID. Within each function the checks run in
the order the three prototype layers ran them, so the same random stream gives the same strings. Mechanism IDs and
subtypes are those of taxonomy v2 (CLAUDE.md, taxonomy/v2_20261012).

Each rule takes (g, st, D, r): g is the Corruptor (random stream, canonical index, vocabulary), st the subtype,
D the dwelling dict and r the canonical record.
"""
import re

from .vocab import (ABBR, DQ1_WORDS, DQ2_WORDS, DQ3_WORDS, EXPAND, FLOOR_NAMES, FLOOR_RE, FLOOR_RE_LEGACY, GENERIC,
                    KEYS, NAME_SUFFIX, POS_RE, SLOT_FIELD, UNIT_RE, DEFAULT_UNIT_WORDS, num_parts)


class Unapplicable(Exception):
    """The requested edit cannot be made on this record."""


def _level(g, r):
    try:
        return int((r['floorlevel'] or '').split(',')[0])
    except ValueError:
        return g.rng.choice([0, 1, 1, 2])


def _unit_word(g):
    uw = g.unit_words or DEFAULT_UNIT_WORDS
    return g.rng.choices(list(uw), list(uw.values()))[0]


def _bracket(g, f):
    return f'({f})' if g.rng.random() < g.floor_bracket else f


# ---------------------------------------------------------------------------------------------------- SU sub-unit

def su1(g, st, D, r):
    rng, sub, num = g.rng, D['sub'], D['number']
    n, s = num_parts(num)
    if st == 'suffix_added' and n is not None and not s:
        D['number'] = f'{n}{rng.choice("AAAB")}'; return
    if st == 'suffix_dropped' and n is not None and s:
        D['number'] = str(n); return
    if st == 'suffix_swapped' and n is not None and s:
        D['number'] = f'{n}{"B" if s == "A" else "A"}'; return
    if st == 'letter_id_added' and sub and re.search(r'\d$', sub):
        D['sub'] = sub + rng.choice('AB'); return
    if st == 'letter_id_dropped' and sub and re.search(r'\d[A-Z]$|\b[A-Z]$', sub):
        D['sub'] = sub[:-1].strip(); return
    if st == 'letter_id_swapped' and sub and re.search(r'[A-Z]$', sub) and re.search(r'\d', sub):
        D['sub'] = sub[:-1] + ('B' if sub[-1] == 'A' else 'A'); return
    raise Unapplicable


def su2(g, st, D, r):
    sub, num = D['sub'], D['number']
    mu = UNIT_RE.match(sub or '')
    n, s = num_parts(num)
    if st == 'suffix_as_flat_letter' and n is not None and s:
        D['sub'] = f'FLAT {s}'; D['number'] = str(n); return
    if st == 'flat_letter_as_suffix' and n is not None and not s and mu and re.fullmatch(r'[A-Z]', mu.group(2)):
        D['number'] = f'{n}{mu.group(2)}'; D['sub'] = ''; return
    if st == 'slash_form' and n is not None and mu and re.fullmatch(r'\d+', mu.group(2)):
        D['sub'] = ''; D['number'] = f'{mu.group(2)}/{n}'; return
    raise Unapplicable


def su3(g, st, D, r):
    sub = D['sub']
    if FLOOR_RE_LEGACY.search(sub or ''):
        cur = FLOOR_RE_LEGACY.search(sub).group(1)
        alt = [f for f in FLOOR_NAMES.values() if f != cur]
        D['sub'] = sub.replace(cur, g.rng.choice(alt[:4])); return
    raise Unapplicable


def su4(g, st, D, r):
    rng, sub = g.rng, D['sub']
    if st == 'floor_descriptor_dropped':
        if FLOOR_RE.search(sub or ''):
            nv = re.sub(r'\s+', ' ', FLOOR_RE.sub('', sub)).strip()
            if nv != sub:
                D['sub'] = nv; return
        raise Unapplicable
    if st == 'floor_descriptor_added':
        if not FLOOR_RE.search(sub or ''):
            f = _bracket(g, g.floor_word(_level(g, r)))
            D['sub'] = (f + ' FLAT') if not sub else rng.choice([f'{sub} {f}', f'{f} {sub}']); return
        if not FLOOR_RE_LEGACY.search(sub or ''):
            # sub-unit has an abbreviated floor ("1ST") the broad pattern sees but the legacy one does not
            f = g.floor_word(_level(g, r))
            D['sub'] = (f + ' FLAT') if not sub else rng.choice([f'{sub} {f}', f'{f} {sub}']); return
    raise Unapplicable


def su5(g, st, D, r):
    sub = D['sub']
    if FLOOR_RE.search(sub or ''):
        cur = FLOOR_RE.search(sub).group(0)
        new = _bracket(g, g.floor_word(_level(g, r)))
        if new != cur:
            D['sub'] = sub.replace(cur, new); return
    raise Unapplicable


def su6(g, st, D, r):
    sub = D['sub']
    if st == 'position_added' and sub and not POS_RE.search(sub):
        D['sub'] = sub + ' ' + g.rng.choice(['FRONT', 'REAR']); return
    if st == 'position_dropped' and POS_RE.search(sub or ''):
        D['sub'] = re.sub(r'\s+', ' ', POS_RE.sub('', sub)).strip(); return
    if st == 'position_swapped' and POS_RE.search(sub or ''):
        p0 = POS_RE.search(sub).group(1)
        D['sub'] = sub.replace(p0, 'REAR' if p0 != 'REAR' else 'FRONT'); return
    raise Unapplicable


def _subunit_number_dropped(D):
    sub = D['sub']
    mu = UNIT_RE.match(sub or '')
    if mu and mu.group(2):
        D['sub'] = mu.group(1); return
    if sub and re.fullmatch(r'[0-9]+[A-Z]?', sub):
        D['sub'] = ''; return
    raise Unapplicable


def su7(g, st, D, r):
    sub = D['sub']
    if st == 'numberless_subunit_dropped' and sub and not re.search(r'\d', sub):
        D['sub'] = ''; return
    if st in ('unit_span_dropped', 'whole_subunit_with_id_dropped') and sub:
        D['sub'] = ''; return
    if st in ('unit_id_dropped', 'unit_id_lost_in_rewrite'):
        return _subunit_number_dropped(D)
    raise Unapplicable


def su8(g, st, D, r):
    sub = D['sub']
    if st == 'annex_added':
        D['pre'].append('ANNEX AT'); return
    if st == 'annex_dropped' and re.search(r'ANNEXE?', sub or ''):
        D['sub'] = re.sub(r'\bANNEXE?\b', '', sub).strip(); return
    raise Unapplicable


def su9(g, st, D, r):
    sub = D['sub']
    if st == 'room_added':
        D['sub'] = (f'ROOM {g.rng.randint(1, 6)} ' + (sub or '')).strip(); return
    if st == 'room_dropped' and re.search(r'\bROOMS? \S+', sub or ''):
        D['sub'] = re.sub(r'\bROOMS? \S+\s*', '', sub).strip(); return
    raise Unapplicable


def su10(g, st, D, r):
    sub = D['sub']
    if st in ('subunit_text_replaced', 'unit_or_floor_word_swapped') and sub:
        D['sub'] = (g.floor_word(_level(g, r)) + ' FLAT') if not FLOOR_RE_LEGACY.search(sub) \
            else 'FLAT ' + (re.findall(r'\d+', sub) or ['1'])[0]
        return
    mu = UNIT_RE.match(sub or '')
    if mu:
        words = [w for w in (g.unit_words or DEFAULT_UNIT_WORDS) if w != mu.group(1)] or ['APARTMENT']
        D['sub'] = (g.rng.choice(words) + ' ' + mu.group(2)).strip(); return
    raise Unapplicable


def su13(g, st, D, r):
    sub, name, num = D['sub'], D['name'], D['number']
    if st == 'other_subunit_text_dropped' and sub and len(sub.split()) > 2:
        D['sub'] = ' '.join(t for t in sub.split() if re.search(r'\d', t) or UNIT_RE.match(t)) or sub.split()[0]; return
    if st == 'unit_word_added':
        if sub and re.fullmatch(r'[0-9]+[A-Z]?|[A-Z]', sub):
            D['sub'] = f'{_unit_word(g)} {sub}'; return
        if not sub and num and name and r['parentuprn']:
            D['sub'] = f'{_unit_word(g)} {num}'; D['number'] = ''; return
        if not sub and r['dwelling_type'] in ('flat', 'room', 'floor_flat'):
            D['sub'] = _unit_word(g); return
        raise Unapplicable
    if st == 'unit_word_dropped':
        mu = UNIT_RE.match(sub or '')
        if mu and mu.group(2):
            D['sub'] = mu.group(2); return
        if sub and re.fullmatch(r'FLAT( AT| OVER| ABOVE)?', sub):
            D['sub'] = ''; return
    raise Unapplicable


def su14(g, st, D, r):
    rng, sub = g.rng, D['sub']
    ids = re.search(r'(\d+)([A-Z]?)$', sub or '')
    if not ids:
        raise Unapplicable
    n, s = ids.group(1), ids.group(2)
    head = sub[:ids.start()]
    new = {'num_leading_zero': f'{int(n):03d}{s}', 'id_letter_prefix_added': f'{rng.choice("ABC")}{n}{s}',
           'id_composite_contains_canonical': f'{n}.{rng.randint(1, 4)}' if rng.random() < .5 else f'{rng.choice("ABC")}{rng.randint(1, 3)}/{n}',
           'num_digit_added': f'{n}{rng.randint(0, 9)}{s}', 'id_letter_suffix_added': f'{n}{rng.choice("AB")}',
           'id_letter_moved_between_prefix_suffix': f'{s}{n}' if s else None,
           'letter_digit_same_rank': None}.get(st)
    if not new:
        raise Unapplicable
    D['sub'] = head + new


def su15(g, st, D, r):
    rng = g.rng
    if not D['sub']:
        D['sub'] = rng.choice([f'FLAT {rng.choice("AB")}', f'FLAT {rng.randint(1, 4)}', g.floor_word(_level(g, r)) + ' FLAT',
                               f'ROOMS 1-{rng.randint(3, 8)}' if 'span' in st else 'FLAT']); return
    raise Unapplicable


# ---------------------------------------------------------------------------------------------------- BN building name

def bn1(g, st, D, r):
    rng, name, num, sub = g.rng, D['name'], D['number'], D['sub']
    if st in ('name_added', 'second_name_added'):
        cand = []
        if r['rm_buildingname'] and r['rm_buildingname'] != name:
            cand.append(r['rm_buildingname'])
        par = g.rec.get(r['parentuprn'])
        if par and par['name'] and par['name'] != name:
            cand.append(par['name'])
        newname = cand[0] if cand and rng.random() < 0.7 else rng.choice(g.generic_names or GENERIC)
        if st == 'name_added' and not name:
            D['name'] = newname; return
        if st == 'second_name_added' and name:
            D['name2'] = newname; return
        if st == 'name_added' and name:
            D['name2'] = newname; return
        raise Unapplicable
    if st == 'name_dropped' and name and (num or sub):
        D['name'] = ''; return
    if st == 'second_name_dropped' and name and len(name.split()) > 2:
        D['name'] = ' '.join(name.split()[-2:]); return
    raise Unapplicable


def bn2(g, st, D, r):
    name = D['name']
    st = {'name_shortened': 'name_truncated'}.get(st, st)
    if name:
        w = name.split()
        if st == 'name_elaborated':
            D['name'] = name + ' ' + g.rng.choice([x for x in NAME_SUFFIX if x not in w]); return
        if st == 'name_truncated' and len(w) >= 2:
            D['name'] = ' '.join(w[:-1]); return
        if st == 'article_the':
            D['name'] = ' '.join(w[1:]) if w[0] == 'THE' and len(w) > 1 else 'THE ' + name; return
    raise Unapplicable


def bn3(g, st, D, r):
    name = D['name']
    if st == 'generic_name_added' and not name:
        D['name'] = g.rng.choice(GENERIC); return
    if st == 'generic_name_dropped' and name and r['name_is_generic'] == 'true':
        D['name'] = ''; return
    if st == 'generic_name_swapped' and name:
        D['name'] = g.rng.choice([x for x in GENERIC if x != name]); return
    raise Unapplicable


def bn4(g, st, D, r):
    rng, name = g.rng, D['name']
    if g.v3 and st == 'name_replaced' and name and rng.random() < g.bn4_partial:
        # profile v3: partly changed names are mostly one word abbreviated (core.name_word_abbreviations) or dropped
        w = name.split()
        idx = [i for i, t in enumerate(w) if t in g.name_abbr]
        if idx:
            i = rng.choice(idx); forms = g.name_abbr[w[i]]
            w[i] = rng.choices(list(forms), list(forms.values()))[0]
            D['name'] = ' '.join(w); return
        if len(w) >= 2:
            del w[rng.randrange(1, len(w)) if len(w) >= 3 else len(w) - 1]
            D['name'] = ' '.join(w); return
    if st == 'name_replaced' and name and len(name.split()) >= 2 and rng.random() < g.bn4_partial:
        # real BN4 rows are mostly "partly changed" (253 vs 32 fully replaced, run 2): one word swapped or dropped
        w = name.split()
        if len(w) >= 3 and rng.random() < .5:
            del w[rng.randrange(1, len(w))]
        else:
            i = rng.randrange(len(w)); w[i] = rng.choice([x for x in NAME_SUFFIX if x != w[i]])
        D['name'] = ' '.join(w); return
    if st == 'name_replaced' and name:
        # a different name that shares no word with the canonical one (shared words read as "partly changed")
        words = set(name.split())
        opts = []
        if r['rm_buildingname'] and r['rm_buildingname'] != name:
            opts.append(r['rm_buildingname'])
        par = g.rec.get(r['parentuprn']) if r['parentuprn'] else None
        if par and par['name']:
            opts.append(par['name'])
        if r['parentuprn']:
            opts += [g.rec[x]['name'] for x in g.children.get(r['parentuprn'], [])[:30] if g.rec[x]['name']]
        opts = [o for o in opts if o != name and not (set(o.split()) & words) and not re.search(r'\d', o)]
        if not opts:
            opts = [x for x in g.generic_names[:2000] if not (set(x.split()) & words)][:200]
        if not opts:
            raise Unapplicable
        D['name'] = rng.choice(opts); return
    raise Unapplicable


def bn8(g, st, D, r):
    if st == 'organisation_dropped' and D['org']:
        D['org'] = ''; return
    if st == 'organisation_replaced' and D['org']:
        D['org'] = ' '.join(D['org'].split()[:2]); return
    if st == 'organisation_added':
        D['org'] = g.rng.choice(['UNIVERSITY OF ' + (r['townname'] or 'LEEDS'), 'CARE HOME', 'THE SHOP']); return
    raise Unapplicable


# ---------------------------------------------------------------------------------------------------- PN primary number

def pn2(g, st, D, r):
    num = D['number']
    rm_ = re.match(r'^(\d+)[A-Z]?-(\d+)[A-Z]?$', num or '')
    n, s = num_parts(num)
    if st.startswith('range_collapsed') and rm_:
        D['number'] = rm_.group(1); return
    if st.startswith('range_vs_other_single') and rm_:
        a, b = int(rm_.group(1)), int(rm_.group(2))
        D['number'] = str(b if b != a else a + 2); return
    if st.startswith('range_extended') and n is not None:
        D['number'] = f'{n}-{n + 2}'; return
    raise Unapplicable


PN3_LEGACY = {'number_replaced': 'neighbour_pm2', 'one_digit_changed': 'digit_substituted', 'digit_dropped': 'digit_dropped',
              'digits_transposed': 'other', 'int_and_suffix_changed': 'neighbour_pm2', 'number_other': 'other'}


def pn3(g, st, D, r):
    rng = g.rng
    if st == 'number_replaced':
        # profile realisation hint: mostly the house number written as a name
        if not D['number']:
            raise Unapplicable
        D['number'] = ''
        if not D['name']:
            alt = r['rm_buildingname'] if r['rm_buildingname'] and not re.search(r'\d', r['rm_buildingname']) else ''
            D['name'] = alt or rng.choice(GENERIC)
        return
    st = PN3_LEGACY.get(st, 'other')
    sub, num = D['sub'], D['number']
    mu = UNIT_RE.match(sub or '')
    target = num if num and re.match(r'^\d', num) else (mu.group(2) if mu and re.match(r'^\d', mu.group(2)) else None)
    if not target:
        raise Unapplicable
    n, s = num_parts(target)
    if n is None:
        raise Unapplicable
    if st == 'neighbour_pm2':
        # aim at a real neighbour on the same street when one exists
        opts = [n + d for d in (-2, 2, -1, 1) if n + d > 0]
        real = [x for x in opts if x in g.by_street.get(r['usrn'], {})]
        new = str(rng.choice(real or opts)) + (s or '')
    elif st == 'digit_substituted':
        t = list(str(n)); i = rng.randrange(len(t)); t[i] = rng.choice([d for d in '0123456789' if d != t[i]])
        new = ''.join(t).lstrip('0') or '1'
    elif st == 'digit_dropped' and n >= 10:
        t = str(n); i = rng.randrange(len(t)); new = (t[:i] + t[i + 1:]).lstrip('0') or '1'
    elif st == 'other':
        new = str(n)[::-1].lstrip('0') if n >= 10 and str(n)[::-1] != str(n) else str(n + rng.choice([-10, 10, 3]))
    else:
        raise Unapplicable
    if num and target == num:
        D['number'] = new
    else:
        D['sub'] = f'{mu.group(1)} {new}'


def pn4(g, st, D, r):
    name, num, sub = D['name'], D['number'], D['sub']
    if st == 'number_in_name_dropped' and name and re.search(r'\d', name):
        D['name'] = re.sub(r'\s*\d+[A-Z]?\s*', ' ', name).strip(); return
    if num and (name or sub):
        D['number'] = ''; return
    raise Unapplicable


def pn6(g, st, D, r):
    rng, sub, name, num = g.rng, D['sub'], D['name'], D['number']
    if st in ('unit_id_added', 'unit_id_added_in_rewrite'):
        mu = UNIT_RE.match(sub or '')
        if mu and not mu.group(2):
            D['sub'] = f'{mu.group(1)} {rng.randint(1, 12)}'; return
        if not sub and r['parentuprn']:
            D['sub'] = str(rng.randint(1, 12)); return
        raise Unapplicable
    if num:
        raise Unapplicable
    par = g.rec.get(r['parentuprn'])
    if par and par['number']:
        D['number'] = par['number']; return
    if st == 'number_added' and (sub or name):
        D['number'] = str(rng.randint(1, 120)); return
    raise Unapplicable


def pn7(g, st, D, r):
    num = D['number']
    if num:
        n, s = num_parts(num)
        d = int(st.split('_')[-1]) if st.startswith('delta') else g.rng.choice([-1, 1])
        if n is None or n + d <= 0:
            raise Unapplicable
        D['number'] = f'{n + d}{s}'; return
    raise Unapplicable


def pn8(g, st, D, r):
    rng, sub = g.rng, D['sub']
    ids = re.search(r'(\d+)([A-Z]?)$', sub or '')
    if not ids:
        raise Unapplicable
    n = int(ids.group(1))
    if st.startswith('delta'):
        new = n + int(st.split('_')[-1])
    else:
        t = list(str(n)); i = rng.randrange(len(t)); t[i] = rng.choice([x for x in '0123456789' if x != t[i]]); new = int(''.join(t))
    if new <= 0:
        raise Unapplicable
    D['sub'] = sub[:ids.start()] + str(new) + ids.group(2)


# ---------------------------------------------------------------------------------------------------- DQ qualifiers

def dq1(g, st, D, r):
    if st == 'added':
        D['pre'].append(g.rng.choice(DQ1_WORDS)); return
    if st == 'dropped':
        for f in ('sub', 'name'):
            v = D[f]
            nv = re.sub(r'^(LAND AT|REAR OF|ADJACENT TO|ADJ|FORMER SITE OF|SITE OF|PART OF)\s+|\s+(REAR OF|ADJ)$', '', v or '')
            if nv != v:
                D[f] = nv; return
    raise Unapplicable


def dq2(g, st, D, r):
    rng, name = g.rng, D['name']
    if st == 'added':
        w = rng.choice(DQ2_WORDS)
        if w == 'DEVELOPMENT' and name:
            D['name'] = name + ' DEVELOPMENT'
        elif w == 'PLOT':
            D['pre'].append(f'PLOT {rng.randint(1, 60)}')
        else:
            D['pre'].append(w)
        return
    if st == 'dropped':
        for f in ('sub', 'name'):
            nv = re.sub(r'\b(PLOT \d+|NEW BUILD|DEVELOPMENT|PROPOSED)\b', '', D[f] or '').strip()
            if nv != (D[f] or ''):
                D[f] = nv; return
    raise Unapplicable


def dq3(g, st, D, r):
    rng, sub = g.rng, D['sub']
    if 'added' in st:
        if not sub or re.fullmatch(r'FLAT', sub or ''):
            D['sub'] = rng.choice(DQ3_WORDS); return
        D['pre'].append(rng.choice(['FLAT AT', 'FLAT OVER'])); return
    nv = re.sub(r'\b(FLAT )?(OVER|ABOVE|AT)\b|\bCARETAKERS\b|\bSHOP\b', '', sub or '').strip()
    if nv != (sub or ''):
        D['sub'] = nv; return
    raise Unapplicable


# ---------------------------------------------------------------------------------------------------- ST street

def st2(g, st, D, r):
    if D['street'] and len(D['street'].split()) > 1:
        D['street'] = ' '.join(D['street'].split()[:-1]); return
    raise Unapplicable


def st4(g, st, D, r):
    if D['street']:
        s = g.near_street(r) or (sorted(g.streets_by_town.get(r['townname'], [])) or [None])[0]
        if s and s != D['street']:
            D['street'] = s; return
    raise Unapplicable


def st5(g, st, D, r):
    if D['street'] and (D['name'] or D['sub']):
        D['street'] = ''; return
    raise Unapplicable


# ---------------------------------------------------------------------------------------------------- TX text edits

def _slot_edit(D, slot, fn):
    f = SLOT_FIELD.get(slot)
    if not f or not D.get(f):
        raise Unapplicable
    new = fn(D[f])
    if new is None or new == D[f]:
        raise Unapplicable
    D[f] = new


def _with_dstreet(rule):
    """TX edits on the dependent street: NGD has none, so take PAF's dependent thoroughfare (profile v2 note)."""
    def wrapped(g, st, D, r):
        if st.endswith('_dstreet') and not D['dep'] and r['rm_dependentthoroughfare']:
            D['dep'] = r['rm_dependentthoroughfare']
            try:
                return rule(g, st, D, r)
            except Unapplicable:
                D['dep'] = ''
                raise
        return rule(g, st, D, r)
    wrapped.__name__ = rule.__name__
    return wrapped


@_with_dstreet
def tx1(g, st, D, r):
    rng = g.rng
    kind, _, slot = st.partition('_')

    def ab(v):
        w = v.split()
        idx = [i for i, t in enumerate(w) if (t in ABBR if kind == 'abbreviated' else t in EXPAND)]
        if not idx:
            return None
        i = rng.choice(idx); w[i] = ABBR[w[i]] if kind == 'abbreviated' else EXPAND[w[i]]
        return ' '.join(w)
    return _slot_edit(D, slot, ab)


@_with_dstreet
def tx2(g, st, D, r):
    rng = g.rng
    kind, _, slot = st.rpartition('_')

    def sp(v):
        w = v.split()
        if kind.startswith('tokens_joined') and len(w) >= 2:
            i = rng.randrange(len(w) - 1)
            if w[i].isdigit() or w[i + 1].isdigit():
                return None
            return ' '.join(w[:i] + [w[i] + w[i + 1]] + w[i + 2:])
        if kind.startswith('token_split'):
            if '-' in v:
                return v.replace('-', ' ', 1)
            long = [i for i, t in enumerate(w) if len(t) >= 8 and t.isalpha()]
            if long:
                i = rng.choice(long); k = rng.randrange(3, len(w[i]) - 2)
                return ' '.join(w[:i] + [w[i][:k], w[i][k:]] + w[i + 1:])
        return None
    return _slot_edit(D, slot, sp)


def typo(rng, t, n_edits=1):
    """1-2 keyboard-style character edits inside a word (delete, substitute, insert, swap)."""
    for _ in range(n_edits):
        j = rng.randrange(1, len(t) - 1)
        op = rng.choice(['del', 'sub', 'ins', 'swap'])
        if op == 'del':
            t = t[:j] + t[j + 1:]
        elif op == 'sub':
            t = t[:j] + rng.choice(KEYS) + t[j + 1:]
        elif op == 'ins':
            t = t[:j] + t[j] + t[j:]
        else:
            t = t[:j - 1] + t[j] + t[j - 1] + t[j + 1:]
    return t


@_with_dstreet
def tx3(g, st, D, r):
    rng = g.rng
    k, _, slot = st.partition('_')
    n_ed = 2 if k == 'edit2' else 1

    def ty(v):
        w = v.split()
        idx = [i for i, t in enumerate(w) if len(t) >= 4 and t.isalpha()]
        if not idx:
            return None
        i = rng.choice(idx)
        w[i] = typo(rng, w[i], n_ed)
        return ' '.join(w)
    return _slot_edit(D, slot, ty)


# ---------------------------------------------------------------------------------------------------- FM format

def fm8(g, st, D, r):
    sub = D['sub']
    if 'added' in st and sub and not re.search(r'\bAT$', sub):
        D['sub'] = sub + ' AT'; return
    if 'dropped' in st and re.search(r'\bAT$', sub or ''):
        D['sub'] = sub[:-3].strip(); return
    raise Unapplicable


def fm9(g, st, D, r):
    sub, name, num = D['sub'], D['name'], D['number']
    if st == 'punctuation_num' and re.search(r'\d-\d', num or ''):
        D['number'] = num.replace('-', '/'); return
    if st == 'punctuation_name' and name:
        D['name'] = name.replace(' ', '-', 1) if ' ' in name else name + '.'; return
    if st == 'punctuation_sub' and sub and re.search(r'\d[A-Z]$', sub):
        D['sub'] = sub[:-1] + '-' + sub[-1]; return
    raise Unapplicable


RULES = {
    'SU1': su1, 'SU2': su2, 'SU3': su3, 'SU4': su4, 'SU5': su5, 'SU6': su6, 'SU7': su7, 'SU8': su8, 'SU9': su9,
    'SU10': su10, 'SU13': su13, 'SU14': su14, 'SU15': su15,
    'BN1': bn1, 'BN2': bn2, 'BN3': bn3, 'BN4': bn4, 'BN8': bn8,
    'PN2': pn2, 'PN3': pn3, 'PN4': pn4, 'PN6': pn6, 'PN7': pn7, 'PN8': pn8,
    'DQ1': dq1, 'DQ2': dq2, 'DQ3': dq3,
    'ST2': st2, 'ST4': st4, 'ST5': st5,
    'TX1': tx1, 'TX2': tx2, 'TX3': tx3,
    'FM8': fm8, 'FM9': fm9,
}
# Mechanisms handled elsewhere: house style (FM1, FM2, LO, ST3, SU11), label drift (LB), systemic (SY1), postcode
# (PC). Retired or rule-less IDs (SU12, BN5, BN6, BN7, DQ4, KY) raise Unapplicable, as in the prototype.
# Rules that run before the others in a bundle, because SU13 or others rewrite the sub-unit or number they need.
FIRST = ('SU7', 'DQ3', 'PN3', 'PN4')


def second_difference(g, D):
    """Profile v3 verify step: one street word abbreviated, or a one-letter slip. False if the street has neither."""
    s = D['street']
    if not s:
        return False
    w = s.split()
    idx = [i for i, t in enumerate(w) if t in ABBR]
    if idx and g.rng.random() < .5:
        i = g.rng.choice(idx); w[i] = ABBR[w[i]]
    else:
        idx = [i for i, t in enumerate(w) if len(t) >= 4 and t.isalpha()]
        if not idx:
            return False
        i = g.rng.choice(idx); t = w[i]; j = g.rng.randrange(1, len(t) - 1)
        w[i] = t[:j] + t[j + 1:]
    D['street'] = ' '.join(w)
    return True


def apply(g, mech, D, r):
    m, _, st = mech.partition(':')
    rule = RULES.get(m)
    if rule is None:
        raise Unapplicable
    return rule(g, st, D, r)
