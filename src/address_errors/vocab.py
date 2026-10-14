"""Generic vocabulary and patterns used by the mechanism rules.

Nothing here is a donor address string: these are generic dwelling, unit, floor and abbreviation words.
Copied from prototype_loop/code/generator.py (v0 rules) and generator_v1.py, where the rules were tuned.

Two floor patterns exist on purpose. FLOOR_RE_LEGACY is the narrow v0 pattern that some older rules still test;
FLOOR_RE (from flags.py) is the broad one the profile v2 eligibility flags use. Keeping both reproduces the
realism-checked generator exactly.
"""
import re

from .flags import FLOOR_RE, POS_RE, UNIT_RE, ABBR, EXPAND  # noqa: F401  (re-exported)

FLOOR_NAMES = {-1: 'BASEMENT', 0: 'GROUND FLOOR', 1: 'FIRST FLOOR', 2: 'SECOND FLOOR', 3: 'THIRD FLOOR',
               4: 'FOURTH FLOOR', 5: 'FIFTH FLOOR'}
FLOOR_RE_LEGACY = re.compile(r'\b(BASEMENT|LOWER GROUND FLOOR|GROUND FLOOR|FIRST FLOOR|SECOND FLOOR|THIRD FLOOR|'
                             r'FOURTH FLOOR|FIFTH FLOOR|TOP FLOOR)\b')
GENERIC = ['THE BUNGALOW', 'THE COTTAGE', 'THE LODGE', 'COACH HOUSE', 'THE FLAT', 'THE BARN', 'FARMHOUSE',
           'THE COACH HOUSE', 'THE ANNEXE', 'THE VICARAGE']
NAME_SUFFIX = ['HOUSE', 'COURT', 'COTTAGE', 'FARM', 'LODGE', 'BUILDINGS', 'MILL']
DQ1_WORDS = ['ADJ', 'REAR OF', 'LAND AT', 'ADJACENT TO', 'OFF']
DQ2_WORDS = ['PLOT', 'NEW BUILD', 'DEVELOPMENT']
DQ3_WORDS = ['FLAT OVER', 'FLAT ABOVE', 'FLAT AT', 'CARETAKERS FLAT']
KEYS = 'QWERTYUIOPASDFGHJKLZXCVBNM'
# taxonomy slot -> field of the dwelling dict D
SLOT_FIELD = {'street': 'street', 'town': 'town', 'name': 'name', 'loc': 'locality', 'sub': 'sub', 'dstreet': 'dep',
              'org': 'org', 'num': 'number'}
COUNTY_WORDS = r'(HANTS|HAMPSHIRE|LANCASHIRE|LANCS|CHESHIRE|YORKSHIRE|YORKS)'
DEFAULT_UNIT_WORDS = {'FLAT': 1}


def num_parts(s):
    """'12A' -> (12, 'A'); anything else -> (None, None)."""
    m = re.match(r'^(\d+)([A-Z]?)$', s or '')
    return (int(m.group(1)), m.group(2)) if m else (None, None)


def norm(*xs):
    return ' '.join(' '.join((x or '').upper().split()) for x in xs)


def title_case(s):
    """Council-system title case: capitalise letter runs that start a word; letters after a digit or an
    apostrophe stay lower case (100a, St John's)."""
    out = []
    prev = ' '
    for ch in s.lower():
        if ch.isalpha() and not (prev.isalpha() or prev.isdigit() or prev == "'"):
            out.append(ch.upper())
        else:
            out.append(ch)
        prev = ch
    return ''.join(out)
