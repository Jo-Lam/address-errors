"""Shim: the vendored fit scripts import flags_v2; the package's flags.py is the same file (profile/code/flags_v2.py)."""
import address_errors.flags as _f

globals().update({k: v for k, v in vars(_f).items() if not k.startswith('__')})
