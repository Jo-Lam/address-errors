"""Tuning controls (CLAUDE.md, "Corruption module design").

The baseline (every field at its default) reproduces the learned profile. An experiment changes one control and
keeps the rest at baseline. Every default is a no-op: with Controls() the corruptor gives exactly the output of
the realism-checked prototype generator for the same profile and seed.
"""
from dataclasses import dataclass, field, asdict


@dataclass
class Noise:
    """Extra noise beyond the learned profile (outside what real councils showed; for stress tests).

    rate: share of records that get extra noise. ops: relative weight of each operation. max_ops: up to this many
    operations per noised record. Applied to the written string after house style and before SY1 truncation, with
    its own random stream, so turning it on does not change which profile errors a record receives.
    """
    rate: float = 0.0
    ops: dict = field(default_factory=lambda: {'typo': 4, 'abbreviate': 2, 'expand': 1, 'token_dropped': 1,
                                               'tokens_swapped': 1, 'tokens_joined': 1, 'case_flip': 0})
    max_ops: int = 1


@dataclass
class Controls:
    # Prevalence: multiplies every touch probability (records and building conventions). 1.0 = learned rate.
    prevalence: float = 1.0
    # Council intensity. None = the profile's value for the source style (1.0 for an unseen/pooled source).
    # The development range is reported in the profile (core.council_intensity_observed) as the sensitivity band.
    intensity: float = None
    # Composition: multiplier per mechanism, by family ("SU"), ID ("SU7") or subtype ("SU7:unit_id_dropped").
    # The most specific key wins. A bundle's rate is multiplied by the product over its members.
    composition: dict = field(default_factory=dict)
    # Severity, by identity effect: a bundle's rate is split into its identity-preserving share (variation) and its
    # identity-shifting share (error: drift or exact collision), and each part is multiplied.
    variation_multiplier: float = 1.0
    error_multiplier: float = 1.0
    # Dependencies: building conventions (one recording convention per building, applied to every unit).
    building_conventions: bool = True
    # Profile v3 only: collision modifiers (a drop lands on a record whose drop would equal another UPRN at the real
    # relative rate) and the verify step that keeps such collisions at the real share. False = v2 behaviour.
    collision_modifiers: bool = True
    # Label drift (LB1-LB4): multiplier on the pooled label-drift rates, and lambda override (share of exact
    # collisions attributed to label drift rather than string drift).
    label_drift: float = 1.0
    lb_lambda: float = None
    # Source style overrides (None = the style's learned setting).
    case: str = None                  # 'upper' or 'title'
    commas: bool = None
    sy1_cap: int = None               # fixed field length, e.g. 70 for a Basingstoke-like source; 0 = no cap
    postcode: str = None              # 'never', 'clean' or 'with_errors'; None = the style's own setting
    postcode_error_multiplier: float = 1.0
    street_variant_scale: float = 1.0  # multiplier on the share of streets with a variant convention
    # Extra noise beyond the profile.
    noise: Noise = field(default_factory=Noise)

    def as_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        if isinstance(d.get('noise'), dict):
            d['noise'] = Noise(**d['noise'])
        return cls(**d)

    def composition_multiplier(self, mech):
        if not self.composition:
            return 1.0
        m = mech.split(':')[0]
        fam = ''.join(ch for ch in m if ch.isalpha())
        for k in (mech, m, fam):
            if k in self.composition:
                return float(self.composition[k])
        return 1.0
