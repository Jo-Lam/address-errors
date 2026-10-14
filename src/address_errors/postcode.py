"""Postcode layer (PC1-PC5).

Fitted on sources that record postcodes (Wigan, and Basingstoke on non-truncated rows); profile
house_style.postcode. Bradford and Leeds released no postcode, so their styles write none.

New in the package: the prototype generator carried the clean postcode. This layer runs on its own random
stream, so it never changes the address strings; turn it off with Controls(postcode='clean').
Wrong postcodes are drawn from real postcodes in the canonical index where possible (a unit in the same sector,
a sector in the same district, a neighbouring district), so they look like keying slips, not invented codes.
"""
import random
import re
from collections import defaultdict

LABELS = {'PC:same_sector_diff_unit': 'PC3', 'PC:same_district_diff_sector': 'PC4', 'PC:different_district': 'PC5',
          'PC:format': 'PC2', 'PC:missing': 'PC1'}
_PC = re.compile(r'^([A-Z]{1,2})(\d[A-Z\d]?) (\d)([A-Z]{2})$')


class PostcodeLayer:
    def __init__(self, profile, style_of, style, seed, controls):
        # sources that recorded postcodes (a v3 profile writes null for one that did not)
        pcs = {k: v for k, v in profile.data['house_style'].get('postcode', {}).items() if v}
        mode = controls.postcode
        if mode is None:
            # a known source writes postcodes only if it recorded them; an unseen source gets the pooled layer
            known = style in profile.data['house_style']['from_strings']
            mode = 'with_errors' if (style in pcs or not known) else 'never'
        self.mode = mode
        if style in pcs:
            p = dict(pcs[style]['p'])
        else:   # pooled over the sources that record postcodes, weighted by records
            tot = sum(v['n'] for v in pcs.values()) or 1
            p = defaultdict(float)
            for v in pcs.values():
                for k, x in v['p'].items():
                    p[k] += x * v['n'] / tot
        m = controls.postcode_error_multiplier
        self.p = {k: v * m for k, v in p.items() if k != 'PC:same'}
        self.rng = random.Random(f'pc|{seed}|{style}')

    def index(self, rec):
        self.by_sector = defaultdict(set)
        self.by_district = defaultdict(set)
        for r in rec.values():
            pc = r['postcode']
            if _PC.match(pc or ''):
                d, sec = pc.split(' ')
                self.by_sector[(d, sec[0])].add(pc)
                self.by_district[d].add(pc)
        self.by_sector = {k: sorted(v) for k, v in self.by_sector.items()}
        self.by_district = {k: sorted(v) for k, v in self.by_district.items()}

    def write(self, r):
        """Returns (postcode as written, PC label or '')."""
        pc = r['postcode']
        if self.mode == 'never':
            return '', ''
        if self.mode == 'clean' or not pc:
            return pc, ''
        u = self.rng.random()
        acc = 0.0
        for k, v in self.p.items():
            acc += v
            if u < acc:
                new = self.edit(k, pc)
                return (new, LABELS[k]) if new is not None and new != pc else (pc, '')
        return pc, ''

    def edit(self, kind, pc):
        rng = self.rng
        m = _PC.match(pc)
        if kind == 'PC:missing':
            return ''
        if kind == 'PC:format':
            return rng.choice([pc.replace(' ', ''), pc.replace(' ', '  '), pc.title(),
                               pc.replace('0', 'O', 1) if '0' in pc else pc.replace(' ', '')])
        if not m:
            return None
        area, dnum, snum, unit = m.groups()
        d = area + dnum
        if kind == 'PC:same_sector_diff_unit':
            opts = [x for x in self.by_sector.get((d, snum), []) if x != pc]
            return rng.choice(opts) if opts else f'{d} {snum}{unit[0]}{rng.choice([c for c in "ABDEFGHJLNPQRSTUWXYZ" if c != unit[1]])}'
        if kind == 'PC:same_district_diff_sector':
            opts = [x for x in self.by_district.get(d, []) if x.split(' ')[1][0] != snum]
            return rng.choice(opts) if opts else f'{d} {(int(snum) + rng.choice([-1, 1])) % 10}{unit}'
        if kind == 'PC:different_district':
            dig = re.match(r'\d+', dnum).group(0)
            nd = f'{area}{max(1, int(dig) + rng.choice([-1, 1]))}{dnum[len(dig):]}'
            opts = self.by_district.get(nd)
            return rng.choice(opts) if opts else f'{nd} {snum}{unit}'
        return None
