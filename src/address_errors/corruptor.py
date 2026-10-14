"""The corruptor: clean canonical addresses with known UPRNs in, realistic recorded addresses out.

Plan, realise, verify (CLAUDE.md, "Corruption module design"):
  1. Plan: for each target record, decide whether its building follows a recording convention, then draw a bundle
     of mechanism edits among the bundles this record is eligible for (profile `requires` flags), at the
     profile's per-eligible-record rates for its source style and stratum.
  2. Realise: apply each edit with the component rules (rules.py); record which applied and which could not.
  3. Write: house style for the source (style.py), postcode layer, optional extra noise, then SY1 truncation.
  4. Label: with the pooled label-drift rates, a clean record may carry a confusable neighbour's string (LB).
  5. Audit: every output row carries source_uprn (what the string describes), assigned_uprn (the label), the
     requested and realised bundle, failed rules, touch route, and an inline collision check.

    from address_errors import Corruptor, Profile, load_components
    prof = Profile.load()                        # bundled portable profile, or Profile.load('<dir>')
    gen = Corruptor(prof, style='leeds', seed=1)
    gen.index(load_components('components.csv.gz'))
    rows = gen.generate(uprns)

This is the prototype_loop generator flattened into one class: generator.py, generator_v1.py and generator_v2.py
(run 3b) for a schema-2 profile, plus generator_v3.py for a schema-3 profile (v3: per-eligible style rates,
collision modifiers with a verify step, building-name abbreviations, per-sector locality text). With default Controls
and the same profile, lookups and seed it gives the same strings as the prototype.
"""
import random
import re
from collections import defaultdict

from . import rules, style as S
from .collision import CollisionIndex
from .controls import Controls
from .flags import collision_flags, flags_of
from .noise import add_noise
from .postcode import PostcodeLayer
from .vocab import FLOOR_NAMES

SLIPS = {'PN3', 'SU3', 'KY'}           # drawn per record, never shared within a building (profile DESIGN.md s5)
SUBUNIT_TEXT = re.compile(r'\b(FLOOR|FLR|FLAT|FLATS|APARTMENT|APT|UNIT|ROOM|ROOMS|GROUND|BASEMENT|MAISONETTE)\b')

OUTPUT_FIELDS = ['source_uprn', 'assigned_uprn', 'recorded_address', 'recorded_postcode', 'source_style', 'stratum',
                 'touch_route', 'requested_bundle', 'applied_rules', 'failed_rules', 'base_rendering',
                 'label_drift_relation', 'sy1_truncated', 'postcode_edit', 'noise_ops', 'collision', 'collision_uprn',
                 'collision_relation']


class Corruptor:
    def __init__(self, profile, style=None, seed=0, controls=None, rates='council', source_id=None):
        """profile: a Profile (profile.py).
        style: the house style to write in, one of profile.styles(); None or an unknown name = the profile's
          default style with pooled rates (an unseen source).
        rates: 'council' = the style council's own rates and intensity; 'pooled' = pooled stratum rates at
          intensity 1.0, the setting decided for unseen councils (profile.intensity_band() is the sensitivity range).
        controls: Controls(); the defaults reproduce the profile.
        source_id: names one synthetic source. Source-level conventions (which records a source renders from PAF,
          each street's spelling convention) are fixed per source_id, as a real source is consistent. Default: the
          style name. Give each independent synthetic source of the same style its own id."""
        self.profile = profile
        self.p = p = profile.data
        self.controls = c = controls or Controls()
        self.src = style
        self.source_id = source_id or style
        self.seed = seed
        self.rng = random.Random(seed)
        core = p['core']
        hs = p['house_style']
        known = style in hs['from_strings']
        sty = style if known else profile.default_style
        self.style_of = sty
        self.rates_key = style if (known and rates == 'council') else 'pooled'
        if not known:
            style = self.src = 'pooled'
            self.source_id = source_id or 'pooled'
        base_int = core['council_intensity_with_council_rates'].get(self.rates_key, core.get('intensity_multiplier', 1.0)) \
            if c.intensity is None else c.intensity
        self.intensity = base_int * c.prevalence if c.prevalence != 1.0 else base_int
        self.lb_lambda = c.lb_lambda if c.lb_lambda is not None else p['label_drift']['share_attributed_to_label_drift_lambda']
        self.sy1_cap = (profile.sy1_cap(sty) if c.sy1_cap is None else c.sy1_cap) or None
        cl = p['clustering']
        self.rho = cl['any_touch']['given_other_unit_has_it']
        self.same_bundle = cl['same_bundle_given_other_unit_touched'] / self.rho
        self.loc_other = profile.locality_other if known else {}
        self.sv_lookup = profile.street_variants if known else {}
        self.extras = profile.extras.get(sty) or {}
        self.unit_words = self.extras.get('unit_words')
        self.stats = defaultdict(int)
        self._cand = {}
        self._flags = {}
        self._sv_conv = {}
        self.shares = hs['from_strings'][sty]['shares']
        self.floor_forms = hs['floor_vocabulary'].get(sty, {}).get('forms', {'First Floor': 1})
        self.style_rates = hs['style_edit_rates'].get(sty, {})
        self.loc_choice = hs['locality_choice'][sty]['patterns_v2']
        self.loc_choice_v1 = hs['locality_choice'][sty]['patterns']
        fl = hs['floor_by_level'].get(sty, {})
        self.floor_levels = fl.get('by_level', {})
        self.floor_bracket = fl.get('bracketed_share', 0)
        self.sv = hs['street_variants'].get(sty, {})
        pr = hs['paf_rendering'].get(sty, {})
        self.paf = pr.get('by_stratum', {}).get('differs', {})
        self.paf_default = pr.get('p_rm_given_dwelling_differs', 0)
        self.bn4_partial = 253 / (253 + 32)   # real share of BN4 labelled partly changed by the miner (run 2)
        self.county_word = profile.style_setting(sty, 'county_word')
        # a refitted style has no county-by-district extras: draw from its own county words (from_strings.county_words)
        self.county_words = None if 'county_by_postcode_district' in self.extras else \
            hs['from_strings'][sty].get('county_words') or None
        self.fused_name_sub = profile.style_setting(sty, 'fused_name_sub', False)
        self.postcode_layer = PostcodeLayer(profile, sty, style, seed, c)
        self.coll = None
        self._collflags = {}
        self.v3 = profile.v3
        if self.v3:
            self._init_v3(profile, sty, known)

    def _init_v3(self, profile, sty, known):
        """Profile v3 (generator_v3.py): style rates per eligible record, collision modifiers, name abbreviations."""
        p, c = self.p, self.controls
        block = profile.raw['house_style'][sty]
        # SU11 now comes from the per-eligible rates; the per-record SU11 path is switched off (ST3 kept)
        self.style_rates = {k: v for k, v in self.style_rates.items() if k.startswith('ST3')}
        self.per_elig = {k: v['rate'] for k, v in (block.get('style_rates_per_eligible') or {}).items()}
        if any(k.startswith('ST3') for k in self.per_elig):
            self.style_rates = {}          # v3e: ST3 per eligible record, applied with the other style edits
        if c.composition:
            self.per_elig = {k: v * c.composition_multiplier(k) for k, v in self.per_elig.items()}
        self.shares = dict(self.shares, brackets=0.0)          # DQ4 brackets drawn per eligible record instead
        self.unit_vocab = block.get('unit_word_added_vocabulary') or {'FLAT': 1.0}
        self.other_kind = (block.get('locality_choice') or {}).get('other_text_kind', {})
        self.loc_sector = profile.locality_sector if known else {}
        # sub-unit text (floors, flats) written after the street is not a place name: keep it out of the lookups
        self.loc_other = {k: {t: w for t, w in v.items() if not SUBUNIT_TEXT.search(t)} for k, v in self.loc_other.items()}
        self.loc_other = {k: v for k, v in self.loc_other.items() if v}
        self.loc_sector = {k: {t: w for t, w in v.items() if not SUBUNIT_TEXT.search(t)} for k, v in self.loc_sector.items()}
        # locality "other" defaults from realism run 5: no "another street" route; the sector fallback comes from the
        # miner-recognised localities in the style extras, not the profile's sector lookup
        self.another_street_scale = 0.0
        self.sector_from_extras = True
        cm = p['core'].get('collision_modifiers', {}).get('by_subtype', {}) if c.collision_modifiers else {}
        self.cmod = {st: (d.get(self.rates_key) or d['pooled'], d['flag']) for st, d in cm.items()}
        self.cmod_pooled = {st: d['pooled'] for st, d in cm.items()}
        self.name_abbr = p['core'].get('name_word_abbreviations', {}).get('vocabulary', {})
        # building-shared house style (prototype run 6): a unit's per-eligible style decision is the building's shared
        # decision with probability s = (kappa - p) / (1 - p), so that P(another unit has it | one has) ~ kappa
        # (profile clustering.by_mechanism, else any_touch) while the per-record rate stays p
        cl = p.get('clustering', {})
        self.kappa = {m: d['given_other_unit_has_it'] for m, d in cl.get('by_mechanism', {}).items()}
        self.kappa_any = cl.get('any_touch', {}).get('given_other_unit_has_it', 0.0)
        self.shared_style = c.building_conventions
        # building-shared non-convention bundles: a unit's per-record draw is the building's shared draw with the same
        # formula, k = the rate-weighted concordance of the non-convention, non-slip bundles
        num = den = 0.0
        for st_rates in p['core']['rates_by_stratum'].values():
            for b, rate in st_rates.items():
                meta = p['core']['bundles'][b]
                if meta['building_convention']:
                    continue
                ms = [m.split(':')[0] for m in meta['mechanisms']]
                if any(m in SLIPS for m in ms):
                    continue
                num += rate * min(self.kappa.get(m, self.kappa_any) for m in ms); den += rate
        self.kappa_nonconv = num / den if den else 0.0
        self.shared_core = c.building_conventions
        # building adoption: the profile's any_touch and same-bundle share are measured on core bundles; real units of a
        # touched building are touched together more often (prototype run 6, picked on the development rehearsal)
        self.rho = 0.92
        self.same_bundle = 1.0

    # ------------------------------------------------------------------ canonical index
    def index(self, records):
        """records: list of canonical record dicts with context (context.load_components / add_context)."""
        self.rec = {r['uprn']: r for r in records}
        self.children = defaultdict(list)
        self.by_street = defaultdict(dict)   # usrn -> number_int -> [uprn]
        for u, r in self.rec.items():
            if r['parentuprn']:
                self.children[r['parentuprn']].append(u)
            if r['usrn'] and r['number_int'] and not r['subname']:
                self.by_street[r['usrn']].setdefault(int(r['number_int']), []).append(u)
        # house names to borrow: residential built records only (no 'STREET RECORD', churches, retail parks)
        self.generic_names = [r['name'] for r in self.rec.values()
                              if r['feature_type'] == 'builtaddress' and r['classificationcode'].startswith('RD')
                              and r['dwelling_type'] == 'named_only' and r['name'] and not re.search(r'\d', r['name'])]
        self.streets_by_town = defaultdict(set)
        self.grid = defaultdict(list)
        for u, r in self.rec.items():
            if r['streetname'] and r['feature_type'] == 'builtaddress':
                self.streets_by_town[r['townname']].add(r['streetname'])
                try:
                    e, n = float(r['easting']), float(r['northing'])
                    self.grid[(int(e // 250), int(n // 250))].append((r['usrn'], r['streetname']))
                except ValueError:
                    pass
        self.coll = CollisionIndex(self.rec, self.children)
        self.postcode_layer.index(self.rec)
        if self.v3:
            self._collflags = collision_flags(
                {'uprn': u, 'subname': r['subname'], 'name': r['name'], 'number': r['number'],
                 'streetname': r['streetname']} for u, r in self.rec.items())
        return self

    def canonical(self, r):
        if r['uprn'] in self._paf:
            return dict(pre=[], sub=r['rm_subbuildingname'], name=r['rm_buildingname'], name2='',
                        number=r['rm_buildingnumber'], dep=r['rm_dependentthoroughfare'], street=r['rm_thoroughfare'],
                        locality=r['rm_dependentlocality'], town=r['rm_posttown'], order='std', base='rm',
                        org=r['organisationname'])
        return dict(pre=[], sub=r['subname'], name=r['name'], name2='', number=r['number'], dep='',
                    street=r['streetname'], locality=r['locality'], town=r['townname'], order='std', base='ngd',
                    org=r['organisationname'])

    def near_street(self, r):
        try:
            gx, gy = int(float(r['easting']) // 250), int(float(r['northing']) // 250)
        except ValueError:
            return None
        opts = {s for dx in (-1, 0, 1) for dy in (-1, 0, 1) for (us, s) in self.grid.get((gx + dx, gy + dy), [])
                if us != r['usrn'] and s != r['streetname']}
        return self.rng.choice(sorted(opts)) if opts else None

    def floor_word(self, level=None):
        lv = self.floor_levels.get(str(level)) if level is not None else None
        if lv:
            forms = lv['forms']
            return self.rng.choices(list(forms), list(forms.values()))[0].upper()
        forms = self.floor_forms
        if level is not None:
            want = {-1: ('BASEMENT', 'BSMT', 'LOWER'), 0: ('GROUND', 'GRD', 'GND'), 1: ('FIRST', '1ST'), 2: ('SECOND', '2ND'),
                    3: ('THIRD', '3RD')}.get(level)
            if want:
                f2 = {k: v for k, v in forms.items() if k.upper().split()[0] in want}
                if f2:
                    forms = f2
        return self.rng.choices(list(forms), list(forms.values()))[0].upper()

    # ------------------------------------------------------------------ plan: composition by eligibility
    def flags(self, r):
        u = r['uprn']
        if u not in self._flags:
            f = flags_of(r)
            if self._collflags:
                f = dict(f)
                f.update(self._collflags.get(u, {}))
            self._flags[u] = f
        return self._flags[u]

    def _bundle_weight(self, meta):
        c = self.controls
        w = 1.0
        if c.composition:
            for m in meta['mechanisms']:
                w *= c.composition_multiplier(m)
        if c.variation_multiplier != 1.0 or c.error_multiplier != 1.0:
            pres = meta.get('effect', {}).get('p', {}).get('preserve', 1.0)
            w *= pres * c.variation_multiplier + (1 - pres) * c.error_multiplier
        return w

    def _tail_weight(self, stratum):
        c = self.controls
        if c.variation_multiplier == 1.0 and c.error_multiplier == 1.0:
            return 1.0
        sh = self.p['core']['share_of_touched_by_class_by_stratum'].get(stratum, {})
        err = sh.get('error', 0.0)
        return (1 - err) * c.variation_multiplier + err * c.error_multiplier

    def candidates(self, stratum, fl, convention=None):
        key = (stratum, tuple(sorted(fl.items())), convention)
        if key in self._cand:
            return self._cand[key]
        core = self.p['core']
        rates = core['rates_by_council_stratum'].get(f'{self.rates_key}|{stratum}') or core['rates_by_stratum'].get(stratum, {})
        out = []
        for b, rate in rates.items():
            meta = core['bundles'][b]
            if convention is not None and meta['building_convention'] != convention:
                continue
            if all(fl.get(k) == v for k, v in meta['requires'].items()):
                w = rate * self.intensity
                bw = self._bundle_weight(meta)
                out.append((b, w * bw if bw != 1.0 else w))
        tail = core['tail']['rate_by_stratum'].get(stratum, core['tail']['rate_global']) * self.intensity
        tw = self._tail_weight(stratum)
        if tw != 1.0:
            tail *= tw
        if convention is not True:
            out.append(('__tail__', tail))
        if self.v3 and self.cmod:
            # v3 collision modifiers: within the eligible records, a drop lands on a record whose drop would equal
            # another UPRN at the real relative rate
            mods = []
            for b, w in out:
                if b == '__tail__':
                    mods.append((b, w)); continue
                m = 1.0
                for st in core['bundles'][b]['mechanisms']:
                    if st in self.cmod:
                        d, flag = self.cmod[st]
                        m *= d['true' if fl.get(flag) else 'false']
                mods.append((b, w * m))
            out = mods
        self._cand[key] = out
        return out

    def building_of(self, r):
        root = r['rootuprn']
        return root if root and (r['parentuprn'] or self.children.get(r['uprn'])) else None

    def brng(self, r, key):
        """The building's own stream for a style choice (unit word, floor word order), so its units share the wording."""
        root = self.building_of(r) if self.shared_style else None
        return random.Random(f'{self.seed}|{root}|{key}') if root else self.rng

    def sdraw(self, r, key, p):
        """v3 per-eligible style decision at rate p, shared within a building (see _init_v3)."""
        if p <= 0:
            return False
        root = self.building_of(r) if self.shared_style else None
        if root:
            k = self.kappa.get(key.split(':')[0], self.kappa_any)
            s = max(0.0, (k - p) / (1 - p)) if p < 1 else 1.0
            if self.rng.random() < s:
                return random.Random(f'{self.seed}|{root}|{key}').random() < p
        return self.rng.random() < p

    def draw(self, r, convention=None, force=False):
        """A bundle (list of subtypes) or [] for untouched. force: draw given touched."""
        root = self.building_of(r) if (self.v3 and self.shared_core and convention is False and not force) else None
        if root:
            # v3: a unit's per-record draw is its building's shared draw with probability s; slips stay per record
            p = self.touch_prob(r, convention=False)
            s = max(0.0, (self.kappa_nonconv - p) / (1 - p)) if p < 1 else 1.0
            if self.rng.random() < s:
                keep = self.rng
                self.rng = random.Random(f'{self.seed}|{root}|nonconv|{r["stratum"]}')
                try:
                    b = self._draw(r, convention, force)
                finally:
                    self.rng = keep
                if not any(m.split(':')[0] in SLIPS for m in b):
                    return b
                return self._draw(r, convention, force)
        return self._draw(r, convention, force)

    def _draw(self, r, convention=None, force=False):
        cand = self.candidates(r['stratum'], self.flags(r), convention)
        if not cand:
            return []
        tot = sum(w for _, w in cand)
        if tot > 1:
            self.stats['overfull'] += 1
        if not force and self.rng.random() >= min(1.0, tot):
            return []
        b = self.rng.choices([k for k, _ in cand], [w for _, w in cand])[0]
        if b == '__tail__':
            tm = self.p['core']['tail']
            size = int(self.rng.choices(list(tm['size_distribution']), list(tm['size_distribution'].values()))[0])
            mk, mw = zip(*tm['mechanism_marginal'].items())
            if self.controls.composition:
                mw = [w * self.controls.composition_multiplier(m) for m, w in zip(mk, mw)]
            ms = set()
            for _ in range(50):
                if len(ms) >= size:
                    break
                ms.add(self.rng.choices(mk, mw)[0])
            return sorted(m for m in ms if not m.startswith(('LB', 'LO', 'ST3', 'SU11')))
        return list(self.p['core']['bundles'][b]['mechanisms'])

    def touch_prob(self, r, convention=None):
        return min(1.0, sum(w for _, w in self.candidates(r['stratum'], self.flags(r), convention)))

    # ------------------------------------------------------------------ realise
    def realise_bundle(self, r, bundle):
        order = sorted(bundle, key=lambda b: 0 if b.split(':')[0] in rules.FIRST else 1)
        D = self.canonical(r)
        realised, failed = [], []
        for mech in order:
            try:
                rules.apply(self, mech, D, r)
                realised.append(mech)
            except rules.Unapplicable:
                failed.append(mech)
        if self.v3 and self.cmod:
            # verify: a drop that would equal another UPRN keeps the collision at the real share; otherwise the
            # record gets a second small difference in the street, as real non-colliding drops do
            for st in realised:
                if st in self.cmod:
                    d, flag = self.cmod[st]
                    pe = d.get('p_exact_given_hit_real')
                    if pe is None:    # the council had no hits: use the pooled target, else keep the collision
                        pe = self.cmod_pooled.get(st, {}).get('p_exact_given_hit_real')
                    if self._collflags.get(r['uprn'], {}).get(flag) and self.rng.random() >= (1.0 if pe is None else pe):
                        if rules.second_difference(self, D):
                            realised = realised + ['verify:second_difference']
                            self.stats['verify_second_difference'] += 1
                    break
        return D, realised, failed

    def confusable(self, r, rel):
        rng = self.rng
        if rel == 'to_parent':
            return r['parentuprn'] if r['parentuprn'] in self.rec else None
        if rel == 'to_sibling' and r['parentuprn']:
            sib = [x for x in self.children.get(r['parentuprn'], []) if x != r['uprn']]
            return rng.choice(sib) if sib else None
        if rel == 'to_neighbour' and r['usrn'] and r['number_int']:
            n = int(r['number_int'])
            near = [u for d in (-2, -1, 1, 2) for u in self.by_street.get(r['usrn'], {}).get(n + d, [])]
            return rng.choice(near) if near else None
        return None

    # ------------------------------------------------------------------ generate
    def generate(self, uprns):
        """uprns: target UPRNs (each must be in the index; others are skipped). Returns a list of output dicts."""
        c = self.controls
        rng = self.rng
        uprns = [u for u in uprns if u in self.rec]
        # PAF-rendered records skip the core; decided first with a separate stream so the rest is unchanged
        prng = random.Random(f'paf|{self.source_id}')
        self._paf = set()
        for u in uprns:
            r = self.rec[u]
            if S.paf_differs(r):
                p = self.paf.get(r['stratum'], {}).get('p_rm', self.paf_default)
                if prng.random() < p:
                    self._paf.add(u)
        self.stats['paf_rendered'] = len(self._paf)
        # style-edit rates in the profile are per record; apply them per eligible record
        R = [self.rec[u] for u in uprns]
        n = max(1, len(R))
        self.elig_share = {'street': max(1e-3, sum(bool(r['streetname']) for r in R) / n),
                           'dep': max(1e-3, sum(bool(r['rm_dependentthoroughfare']) for r in R) / n),
                           'sub_name': max(1e-3, sum(bool(r['subname'] and r['name']) for r in R) / n),
                           'sub': max(1e-3, sum(bool(r['subname']) for r in R) / n)}
        # building conventions: roots with >= 2 target units
        by_root = defaultdict(list)
        if c.building_conventions:
            for u in uprns:
                r = self.rec[u]
                if (r['parentuprn'] or self.children.get(u)) and r['rootuprn']:
                    by_root[r['rootuprn']].append(u)
        conv = {}
        for root, us in by_root.items():
            if len(us) < 2:
                continue
            r0 = self.rec[rng.choice(us)]
            q = min(1.0, self.touch_prob(r0, convention=True) / self.rho)
            if rng.random() < q:
                b = self.draw(r0, convention=True, force=True)
                if b:
                    conv[root] = b
        out = []
        lb = self.p['label_drift']['rate_per_record_by_relation']
        lb_scale = c.label_drift
        nrng = random.Random(f'noise|{self.seed}|{self.src}')
        for u in uprns:
            r = self.rec[u]
            root = r['rootuprn']
            in_building = root in by_root and len(by_root[root]) >= 2
            bundle, how = [], ''
            if u in self._paf:
                how = 'paf_rendering'
            elif in_building and root in conv and rng.random() < self.rho:
                if rng.random() < self.same_bundle:
                    bundle, how = conv[root], 'building_convention'
                else:
                    bundle, how = self.draw(r, force=True), 'building_other'
            elif in_building:
                bundle = self.draw(r, convention=False)
                how = 'record_in_building' if bundle else ''
            else:
                bundle = self.draw(r)
                how = 'record' if bundle else ''
            source_uprn, lb_rel = u, ''
            if bundle:
                if how == 'building_convention':
                    # one convention per building: the same edits (same random choices) for every unit
                    keep = self.rng; self.rng = random.Random(f'{root}|{bundle}')
                    D, realised, failed = self.realise_bundle(r, bundle)
                    self.rng = keep
                else:
                    D, realised, failed = self.realise_bundle(r, bundle)
            else:
                realised, failed = [], []
                x = None
                for rel, rate in lb.items():
                    if rng.random() < (rate * self.lb_lambda * lb_scale if lb_scale != 1.0 else rate * self.lb_lambda):
                        x = self.confusable(r, rel)
                        if x:
                            lb_rel = rel
                            break
                if x:
                    source_uprn = x
                D = self.canonical(self.rec[source_uprn])
            src_rec = self.rec[source_uprn]
            s_out = S.serialise(self, D, src_rec)
            pc, pc_edit = self.postcode_layer.write(src_rec)
            noise_ops = ''
            if c.noise.rate > 0:
                s_out, noise_ops = add_noise(s_out, c.noise, nrng)
            truncated = False
            if self.sy1_cap:
                s_out, pc, truncated = S.truncate_sy1(s_out, pc, self.sy1_cap)
            coll, coll_u, coll_rel = self.coll.check(D, u)
            self.stats['records'] += 1
            self.stats['touched'] += bool(bundle)
            self.stats['partial'] += bool(failed)
            self.stats['failed_rules'] += len(failed)
            self.stats['applied_rules'] += len(realised)
            out.append(dict(source_uprn=source_uprn, assigned_uprn=u, recorded_address=s_out, recorded_postcode=pc,
                            source_style=self.src, stratum=r['stratum'], touch_route=how,
                            requested_bundle='|'.join(bundle), applied_rules='|'.join(realised),
                            failed_rules='|'.join(failed), base_rendering=D.get('base', 'ngd'), label_drift_relation=lb_rel,
                            sy1_truncated=truncated, postcode_edit=pc_edit, noise_ops=noise_ops, collision=coll,
                            collision_uprn=coll_u, collision_relation=coll_rel))
        return out
