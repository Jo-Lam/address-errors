"""Inline collision test (CLAUDE.md, "Identity effect").

After a record is corrupted, does its dwelling + street normalise-equal a *different* UPRN's canonical rendering
(NGD or Royal Mail) in the same area? The key ignores rendering-only differences: case, punctuation, unit words,
"THE", "AT", floor wording and street-word abbreviations. This mirrors the miner's rendering-insensitive key
(mined_error_pairs .../mine_pairs.py key2) closely but not exactly; the pipeline's verify step re-mines the output
with the miner itself, which is the reference check. Collision rates are an outcome to report, never a target.
"""
import re
from collections import defaultdict

from .vocab import ABBR

_DROP = {'FLAT', 'FLATS', 'APARTMENT', 'APT', 'UNIT', 'MAISONETTE', 'STUDIO', 'SUITE', 'THE', 'AT', 'FLOOR', 'FLR', 'FL'}
_FLOOR = {'BASEMENT': 'F-1', 'BSMT': 'F-1', 'LOWER': 'F-1', 'GROUND': 'F0', 'GRD': 'F0', 'GND': 'F0', 'FIRST': 'F1',
          '1ST': 'F1', 'SECOND': 'F2', '2ND': 'F2', 'THIRD': 'F3', '3RD': 'F3', 'FOURTH': 'F4', '4TH': 'F4',
          'FIFTH': 'F5', '5TH': 'F5', 'TOP': 'FTOP'}
_TOK = re.compile(r'[A-Z0-9]+')


def key(*parts):
    out = []
    for p in parts:
        for t in _TOK.findall((p or '').upper().replace("'", '')):
            if t in _DROP:
                continue
            t = _FLOOR.get(t, t)
            t = ABBR.get(t, t)          # abbreviate every known word: ROAD and RD both become RD
            out.append(t)
    return tuple(out)


REL_ORDER = ['to_parent', 'to_child', 'to_sibling', 'to_same_complex', 'to_neighbour', 'to_other']


class CollisionIndex:
    def __init__(self, rec, children):
        self.rec = rec
        self.idx = defaultdict(set)
        for u, r in rec.items():
            self.idx[key(r['subname'], r['name'], r['number'], r['streetname'])].add(u)
            if r.get('rm_thoroughfare') or r.get('rm_buildingname'):
                for st in {r['rm_thoroughfare'], r['rm_dependentthoroughfare']} - {''}:
                    self.idx[key(r['rm_subbuildingname'], r['rm_buildingname'], r['rm_buildingnumber'], st)].add(u)
                if r['rm_thoroughfare'] and r['rm_dependentthoroughfare']:
                    self.idx[key(r['rm_subbuildingname'], r['rm_buildingname'], r['rm_buildingnumber'],
                                 r['rm_dependentthoroughfare'], r['rm_thoroughfare'])].add(u)

    def same_area(self, a, b):
        ra, rb = self.rec.get(a), self.rec.get(b)
        if ra is None or rb is None:
            return False
        return bool(ra['usrn'] and ra['usrn'] == rb['usrn']) or (ra['townname'] == rb['townname'] and
                                                                 ra['postcode'].split(' ')[0] == rb['postcode'].split(' ')[0])

    def relation(self, L, O):
        rl, ro = self.rec.get(L), self.rec.get(O)
        if rl is None or ro is None:
            return 'to_other'
        if rl['parentuprn'] and O == rl['parentuprn']:
            return 'to_parent'
        if ro['parentuprn'] and ro['parentuprn'] == L:
            return 'to_child'
        if rl['parentuprn'] and rl['parentuprn'] == ro['parentuprn']:
            return 'to_sibling'
        if rl['rootuprn'] and rl['rootuprn'] == ro['rootuprn']:
            return 'to_same_complex'
        if rl['usrn'] and rl['usrn'] == ro['usrn']:
            return 'to_neighbour'
        return 'to_other'

    def check(self, D, label):
        """D: the realised dwelling dict; label: the UPRN the record carries. Returns (status, other_uprn, relation)."""
        if not D.get('street'):
            return 'not_tested', '', ''
        k = key(D['sub'], D['name'], D.get('name2'), D['number'], D.get('dep'), D['street'])
        hits = {h for h in self.idx.get(k, ()) if h == label or self.same_area(label, h)}
        if not hits:
            return 'no_match', '', ''
        if hits == {label}:
            return 'matches_label_only', '', ''
        others = sorted(hits - {label})
        rels = sorted({self.relation(label, o) for o in others}, key=REL_ORDER.index)
        return ('matches_label_and_other' if label in hits else 'matches_other_only'), others[0], rels[0]
