"""address_errors: a tunable generator of realistic UK address recording errors, with a labelled truth table.

    from address_errors import Profile, Corruptor, Controls, load_components
    gen = Corruptor(Profile.load(), style='leeds', seed=1)
    gen.index(load_components('components.csv.gz'))
    rows = gen.generate(['900000000001', ...])   # your record IDs

See README.md for the controls, the truth table and the pipeline for fitting a profile on your own data.
"""
from .context import load_components, add_context
from .controls import Controls, Noise
from .corruptor import Corruptor, OUTPUT_FIELDS
from .profile import Profile


def example_path():
    """Path of the bundled example gazetteer: an invented town of 261 addresses (no real addresses or UPRNs)."""
    from pathlib import Path
    return str(Path(__file__).parent / 'data' / 'example' / 'components.csv')


__version__ = '0.1.1'
__all__ = ['Profile', 'Corruptor', 'Controls', 'Noise', 'load_components', 'add_context', 'OUTPUT_FIELDS', 'example_path']
