"""Extra noise beyond the learned profile (decision (c) in CLAUDE.md "Next stages": not yet decided by Jo).

Off by default. Use it to stress a matcher with more, or rougher, errors than real councils make. It acts on the
written string with its own random stream and is listed per record in `noise_ops`, so noised records can always
be told apart from profile errors. Rates here are user settings, not fitted.
"""
from .rules import typo
from .vocab import ABBR, EXPAND


def _tokens(s):
    return s.split(' ')


def _op(name, s, rng):
    w = _tokens(s)
    words = [i for i, t in enumerate(w) if t.strip(',').isalpha()]
    if name == 'typo':
        idx = [i for i in words if len(w[i].strip(',')) >= 4]
        if not idx:
            return None
        i = rng.choice(idx)
        core, comma = (w[i][:-1], ',') if w[i].endswith(',') else (w[i], '')
        w[i] = typo(rng, core) + comma
    elif name in ('abbreviate', 'expand'):
        table = ABBR if name == 'abbreviate' else EXPAND
        idx = [i for i in words if w[i].strip(',').upper() in table]
        if not idx:
            return None
        i = rng.choice(idx)
        core, comma = (w[i][:-1], ',') if w[i].endswith(',') else (w[i], '')
        new = table[core.upper()]
        w[i] = (new if core.isupper() else new.title()) + comma
    elif name == 'token_dropped':
        if len(w) < 3:
            return None
        del w[rng.randrange(len(w))]
    elif name == 'tokens_swapped':
        if len(w) < 2:
            return None
        i = rng.randrange(len(w) - 1)
        w[i], w[i + 1] = w[i + 1], w[i]
    elif name == 'tokens_joined':
        idx = [i for i in range(len(w) - 1) if not w[i].endswith(',') and w[i].isalpha() and w[i + 1].strip(',').isalpha()]
        if not idx:
            return None
        i = rng.choice(idx)
        w[i:i + 2] = [w[i] + w[i + 1]]
    elif name == 'case_flip':
        return s.swapcase()
    else:
        raise ValueError(f'unknown noise op {name!r}')
    return ' '.join(w)


def add_noise(s, spec, rng):
    """Returns (string, '|'-joined ops applied)."""
    if rng.random() >= spec.rate:
        return s, ''
    names = [k for k, v in spec.ops.items() if v > 0]
    if not names:
        return s, ''
    done = []
    for _ in range(rng.randint(1, max(1, spec.max_ops))):
        name = rng.choices(names, [spec.ops[k] for k in names])[0]
        new = _op(name, s, rng)
        if new is not None and new != s:
            s = new
            done.append(name)
    return s, '|'.join('NOISE:' + d for d in done)
