"""Corruption profiles: load, inspect, and export a portable copy.

A profile directory holds:
  profile.json                      rates, bundles, flags, clustering, label drift, house style (no address strings)
  locality_other_by_usrn.csv.gz     optional, NOT portable: "other" place text per street (USRN)
  street_variant_by_usrn.csv.gz     optional, NOT portable: per-street spelling conventions
  locality_other_by_sector.csv.gz   optional (v3), NOT portable: "other" place text per postcode sector
  style_extras.json                 optional: per-source vocabulary (unit words; county by postcode district;
                                    place names by postcode sector, which is not portable)
  PORTABLE.json                     written by export_portable(): what was removed and why

Profile.load() with no argument loads the portable profile bundled with the package. Inside the study folder,
Profile.load('<study>/profile/fitted_v2_20261012', extras='<run>/style_extras.json') loads the full profile.

Two layouts are read. Schema 2 keys house_style by section, then source (house_style.from_strings.leeds). Schema 3
(profile v3) keys it by source, then section (house_style.leeds.from_strings), and adds per-eligible style rates,
collision modifiers and building-name abbreviations. Profile.data always has the section-first layout the corruptor
reads; Profile.raw is the file as written, and export_portable() writes that layout back.
"""
import csv
import gzip
import io
import json
import re
from importlib import resources
from pathlib import Path

# House-style facts the prototype generator hard-coded per source. A profile may override them under
# profile.json "style_settings".
STYLE_SETTINGS = {
    'basingstoke': {'county_word': 'HANTS', 'sy1_cap': 70},
    'bradford': {'fused_name_sub': True},
}
BUNDLED = 'profile_v3_all6_portable'          # default: fitted on all six councils (Jo, 14 Oct 2026)
# bundled portable profiles by short name: Profile.load('v2'), or --profile v2 on the command line.
# v3 = the frozen profile (profile/frozen_20261013); 'v3-candidate' is kept as an alias for older scripts.
BUNDLED_PROFILES = {'all6': 'profile_v3_all6_portable', 'frozen': 'profile_v3_frozen_portable',
                    'v3': 'profile_v3_frozen_portable', 'v3-candidate': 'profile_v3_frozen_portable',
                    'v2': 'profile_v2_portable'}
# Councils whose re-use terms are unconfirmed: council-level entries are left out of portable exports by default.
UNCONFIRMED_LICENCE = ('basingstoke',)
FORBIDDEN = ('cornwall', 'derby')     # external test councils: refused unless the profile declares an all-council fit


SECTION_RENAME = {'style_edit_rates_taxonomy': 'style_edit_rates'}
# v3: per-street "other locality" rows seen fewer times than this are not used (prototype generator_v3.MIN_LOOKUP_N)
MIN_LOOKUP_N = 2


def council_keyed(data):
    return 'from_strings' not in data['house_style']


def sectioned(data):
    """A schema-3 profile (house_style[source][section]) in the section-first layout (house_style[section][source]),
    as prototype_loop generator_v3.sectioned() does for one source."""
    P = json.loads(json.dumps(data))
    hs = {}
    for src, block in data['house_style'].items():
        for k, v in block.items():
            hs.setdefault(SECTION_RENAME.get(k, k), {})[src] = v
        hs.setdefault('style_edit_rates', {}).setdefault(src, {})
    P['house_style'] = hs
    return P


def _read_csv(path):
    with io.TextIOWrapper(gzip.open(path, 'rb'), encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


class Profile:
    def __init__(self, data, locality_other=None, street_variants=None, extras=None, source=None, locality_sector=None,
                 allow=()):
        self.raw = data
        self.v3 = council_keyed(data)
        self.data = sectioned(data) if self.v3 else data
        self.locality_other = locality_other or {}
        self.street_variants = street_variants or {}
        self.locality_sector = locality_sector or {}
        self.extras = extras or {}
        self.source = source
        self.external_test_styles = tuple(allow)
        # A profile fitted on all six councils (Jo's decision of 14 Oct 2026, after the one-off external test) declares
        # it in fitted_on; any other profile holding Cornwall or Derby is refused.
        self.all_councils = bool((self.raw.get('fitted_on') or {}).get('external_test_included'))
        if self.all_councils:
            allow = tuple(allow) + FORBIDDEN
        bad = set(FORBIDDEN) & set(self.data['house_style']['from_strings']) - set(allow)
        if bad:
            raise ValueError(f'profile contains external-test councils {sorted(bad)}')

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, path=None, extras=None, lookups=True):
        """path: a profile directory or profile.json; None = the default bundled portable profile; a name in
        BUNDLED_PROFILES = that bundled profile.
        extras: style_extras.json path (default: <dir>/style_extras.json if present). lookups: load the
        per-street lookups if present (they are never present in a portable profile)."""
        if path is None or path in BUNDLED_PROFILES:
            name = BUNDLED_PROFILES.get(path, BUNDLED)
            base = resources.files('address_errors') / 'data' / name
            data = json.loads((base / 'profile.json').read_text())
            ex = json.loads((base / 'style_extras.json').read_text())
            return cls(data, extras=ex, source=f'bundled:{name}')
        p = Path(path)
        d = p if p.is_dir() else p.parent
        data = json.loads((d / 'profile.json' if p.is_dir() else p).read_text())
        lo, sv, ls = {}, {}, {}
        v3 = council_keyed(data)
        if lookups and (d / 'locality_other_by_usrn.csv.gz').exists():
            for r in _read_csv(d / 'locality_other_by_usrn.csv.gz'):
                if v3 and int(r.get('n') or 0) < MIN_LOOKUP_N:
                    continue
                lo.setdefault((r['council'], r['usrn']), {})[r['other_text']] = float(r['share'])
        if lookups and (d / 'street_variant_by_usrn.csv.gz').exists():
            for r in _read_csv(d / 'street_variant_by_usrn.csv.gz'):
                sv[(r['council'], r['usrn'])] = (r['variant_text'], float(r['share_of_street_records']))
        if lookups and (d / 'locality_other_by_sector.csv.gz').exists():
            for r in _read_csv(d / 'locality_other_by_sector.csv.gz'):
                ls.setdefault((r['council'], r['sector']), {})[r['other_text']] = float(r['share'])
        ex_path = Path(extras) if extras else d / 'style_extras.json'
        ex = {}
        if ex_path.exists():
            ex = {k: v for k, v in json.loads(ex_path.read_text()).items() if isinstance(v, dict)}
        return cls(data, lo, sv, ex, source=str(d), locality_sector=ls)

    # ------------------------------------------------------------------ inspection
    @property
    def profile_id(self):
        return self.data.get('profile_id')

    def styles(self):
        return list(self.data['house_style']['from_strings'])

    @property
    def default_style(self):
        """House style used for an unseen ('pooled') source when no style is named."""
        return self.data.get('default_style') or self.styles()[0]

    def style_setting(self, style, key, default=None):
        s = dict(STYLE_SETTINGS.get(style, {}))
        s.update(self.data.get('style_settings', {}).get(style, {}))
        return s.get(key, default)

    def sy1_cap(self, style):
        cap = self.style_setting(style, 'sy1_cap')
        if cap is None:   # a refitted style carries the cap its strings showed (from_strings.systemic.SY1)
            sy = self.data['house_style']['from_strings'].get(style, {}).get('systemic', {}).get('SY1') or {}
            cap = sy.get('max_field_length')
        return cap

    def with_style(self, name, fit_dir, allow_external_test=False):
        """A copy of this (schema-3) profile with one more house style, refitted from a source's own strings by
        `address-errors fit-house-style` (or profile/code/fit_house_style.py): <fit_dir>/house_style.json plus its
        lookups. The core is unchanged. Generate with Corruptor(prof, style=name, rates='pooled'): pooled rates at
        intensity 1.0, the setting for a council the profile has never seen.
        allow_external_test: the external-test councils (Cornwall, Derby) are refused unless this is set, which is
        only for the frozen-profile external test inside the study folder. Such a profile can never be exported."""
        if not self.v3:
            raise ValueError('with_style needs a schema-3 (v3) profile: house style keyed by source')
        if name in FORBIDDEN and not allow_external_test:
            raise ValueError(f'{name} is an external-test council; pass allow_external_test=True only for the external test')
        d = Path(fit_dir)
        fit = json.loads((d / 'house_style.json').read_text())
        raw = json.loads(json.dumps(self.raw))
        raw['house_style'][name] = fit['house_style']
        lo, sv, ls = dict(self.locality_other), dict(self.street_variants), dict(self.locality_sector)
        src = fit.get('council', name)
        if (d / 'locality_other_by_usrn.csv.gz').exists():
            for r in _read_csv(d / 'locality_other_by_usrn.csv.gz'):
                if r['council'] == src and int(r.get('n') or 0) >= MIN_LOOKUP_N:
                    lo.setdefault((name, r['usrn']), {})[r['other_text']] = float(r['share'])
        if (d / 'street_variant_by_usrn.csv.gz').exists():
            for r in _read_csv(d / 'street_variant_by_usrn.csv.gz'):
                if r['council'] == src:
                    sv[(name, r['usrn'])] = (r['variant_text'], float(r['share_of_street_records']))
        if (d / 'locality_other_by_sector.csv.gz').exists():
            for r in _read_csv(d / 'locality_other_by_sector.csv.gz'):
                if r['council'] == src:
                    ls.setdefault((name, r['sector']), {})[r['other_text']] = float(r['share'])
        p = Profile(raw, lo, sv, dict(self.extras), source=f'{self.source} + style {name} from {d}', locality_sector=ls,
                    allow=(name,) if allow_external_test else ())
        return p

    def intensity_band(self):
        if 'intensity_sensitivity_band' in self.data['core']:
            return tuple(self.data['core']['intensity_sensitivity_band'])
        v = self.data['core'].get('council_intensity_observed', {})
        return (min(v.values()), max(v.values())) if v else (1.0, 1.0)

    def mechanisms(self):
        """Mechanism subtypes the profile can generate, with their bundle count."""
        out = {}
        for b in self.data['core']['bundles'].values():
            for m in b['mechanisms']:
                out[m] = out.get(m, 0) + 1
        return dict(sorted(out.items()))

    def summary(self):
        lo, hi = self.intensity_band()
        return {'profile_id': self.profile_id, 'status': self.data.get('status'), 'source': self.source,
                'taxonomy': self.data.get('taxonomy_version'), 'styles': self.styles(),
                'bundles': len(self.data['core']['bundles']), 'mechanism_subtypes': len(self.mechanisms()),
                'schema': 3 if self.v3 else 2,
                'intensity_band': [lo, hi],
                'per_street_lookups': bool(self.locality_other or self.street_variants or self.locality_sector),
                'portable': self.data.get('portable', {}).get('portable', False)}

    # ------------------------------------------------------------------ disclosure
    @staticmethod
    def disclosure_scan(data):
        """Paths of strings that look like address text (a number followed by named street words, or a quoted
        upper-case phrase). Used before any export leaves the study folder."""
        hits = []
        street = r'(ROAD|STREET|AVENUE|LANE|DRIVE|CLOSE|WAY|COURT|PLACE|GROVE|TERRACE|HOUSE|GARDENS|CRESCENT|MEWS)'
        pat = re.compile(r'\b\d+[A-Z]?\b,? [A-Z][A-Za-z]+ ' + street + r'\b|"[A-Z0-9 ,\']{12,}"', re.I)

        def walk(x, path):
            if isinstance(x, dict):
                for k, v in x.items():
                    if pat.search(str(k)):
                        hits.append(path + '/' + str(k))
                    walk(v, f'{path}/{k}')
            elif isinstance(x, list):
                for i, v in enumerate(x):
                    walk(v, f'{path}[{i}]')
            elif isinstance(x, str) and pat.search(x):
                hits.append(path)
        walk(data, '')
        return hits

    def export_portable(self, out_dir, exclude_councils=UNCONFIRMED_LICENCE, county_min_records=10):
        """Write a portable copy: no per-street lookups, no place names by postcode sector, no address-like text,
        and no council-level entries for `exclude_councils`. Pooled and stratum rates still pool every development
        council's rows (the fit cannot be undone here); PORTABLE.json says so."""
        if set(FORBIDDEN) & set(self.data['house_style']['from_strings']) and not self.all_councils:
            raise ValueError('a profile holding an external-test council style is never exported')
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=False)
        d = json.loads(json.dumps(self.raw))
        removed = []
        # 1. address-like strings
        for path in self.disclosure_scan(d):
            parts = [x for x in path.split('/') if x]
            node = d
            for k in parts[:-1]:
                node = node[k]
            node[parts[-1]] = '[removed for disclosure: address-like text]'
            removed.append(f'text at {path}')
        # 2. council-level entries for excluded councils
        core, hs = d['core'], d['house_style']
        for c in exclude_councils:
            for k in [k for k in core['rates_by_council_stratum'] if k.split('|')[0] == c]:
                del core['rates_by_council_stratum'][k]
            for sect in ('council_intensity_observed', 'council_intensity_with_council_rates', 'edits_per_touched_record'):
                if c in core.get(sect, {}):
                    del core[sect][c]
            # any other entry keyed by the council, anywhere but the provenance record (fitted_on)
            def drop(x):
                if isinstance(x, dict):
                    x.pop(c, None)
                    for v in x.values():
                        drop(v)
                elif isinstance(x, list):
                    for v in x:
                        drop(v)
            for k, v in d.items():
                if k not in ('fitted_on', 'house_style'):
                    drop(v)
            if self.v3:
                hs.pop(c, None)
            else:
                for k, v in hs.items():
                    if isinstance(v, dict) and c in v:
                        del v[c]
            removed.append(f'council-level entries for {c} (re-use terms unconfirmed)')
        # 3. non-portable lookups
        stub = {'portable': False, 'shipped': False, 'note': 'lookup left out of the portable profile'}
        for blk in (hs.values() if self.v3 else [hs]):
            for k in ('locality_other_lookup', 'street_variant_lookup', 'locality_other_by_sector'):
                if k in blk:
                    blk[k] = dict(stub)
        removed.append('per-street and per-sector lookups (locality_other_by_usrn, street_variant_by_usrn, '
                       'locality_other_by_sector)')
        # the unseen-council sensitivity band is a decision input (Jo, D1): keep the development range as one pair
        core['intensity_sensitivity_band'] = list(self.intensity_band())
        styles = list(hs) if self.v3 else list(hs['from_strings'])
        if d.get('default_style') in exclude_councils or not d.get('default_style'):
            d['default_style'] = styles[0]
        left = self.disclosure_scan(d)
        assert not left, left
        # 4. extras: generic unit words; county words by postcode district (aggregated, >= county_min_records)
        ex = {}
        for c, v in self.extras.items():
            if c in exclude_councils:
                continue
            cbd = {dist: {w: n for w, n in ws.items() if n >= county_min_records}
                   for dist, ws in v.get('county_by_postcode_district', {}).items()}
            ex[c] = {'unit_words': v.get('unit_words', {}),
                     'county_by_postcode_district': {k: w for k, w in cbd.items() if w}}
        d['portable'] = {
            'portable': True, 'exported_from': self.source, 'profile_id': self.profile_id,
            'removed': removed,
            'kept_needs_review': ['style_extras.county_by_postcode_district: county words by postcode district, '
                                  f'aggregated, counts >= {county_min_records}',
                                  'core.intensity_sensitivity_band: development range of council intensity, '
                                  'all development councils included']
                                 + (['core.name_word_abbreviations: single building-name words and their short '
                                     'forms, each seen at least 3 times; some words are distinctive local names']
                                    if 'name_word_abbreviations' in core else []),
            'note': ('Pooled and stratum rates were fitted on all development councils, including '
                     + ', '.join(exclude_councils) + '. Check its re-use terms before publishing this file.')
                    if exclude_councils else ''}
        (out / 'profile.json').write_text(json.dumps(d, indent=None, separators=(',', ':')))
        (out / 'style_extras.json').write_text(json.dumps(ex, indent=1))
        (out / 'PORTABLE.json').write_text(json.dumps(d['portable'], indent=1))
        return out
