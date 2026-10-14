"""Recorded side (pipeline step 2): stage and clean a source's address records that carry UPRN labels.

Address text is never edited: case, spacing, abbreviations and truncation are the recording behaviour being
measured. Staging only splits off an embedded trailing postcode (kept raw as well) and normalises the UPRN label as
text. Cleaning removes rows that cannot serve as labelled examples, by the study's rules (council_data/
clean_councils.py), first rule wins:
  R1 missing_or_malformed_uprn   label empty or not 1-12 digits after stripping padding zeros
  R2 empty_address
  R4 exact_duplicate             same label and same normalised address+postcode as an earlier row
  R5 uprn_conflict               one label on rows with different normalised addresses (all its rows removed;
                                 written to uprn_conflicts.csv as candidate label-drift evidence)
(R3, Derby's band U, is council-specific: pass extra exclusions with `exclude`.)
Tags: systemic_truncation_<L> for a fixed-width cut detected from a length spike (SY1), and
address_shared_by_multiple_uprns.

    address-errors stage-records --input my.csv --source mysource --address-col ADDRESS --uprn-col UPRN \\
        [--postcode-col POSTCODE] [--epoch 2025] --output work/records/mysource

A source that stores the address in several fields: give --address-col once per field, in order. The fields are
joined with ", " (empty fields skipped), and that joined string is the recorded address everywhere downstream,
recorded_address_raw included, so the house-style refit (which reads recorded_address_raw) sees the same commas a
matcher will. The untouched fields are kept in source_fields_raw, separated by " | ".
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

PC_TAIL = re.compile(r'[,\s]+([A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2})\s*$')
norm = lambda s: re.sub(r'[^A-Z0-9]+', ' ', (s or '').upper()).strip()


def clean_uprn(u):
    """UPRN as text without padding zeros (as join_reference.py does); '' if malformed. Never cast to a number."""
    u = (u or '').strip()
    if u.endswith('.0') and u[:-2].isdigit():
        u = u[:-2]        # spreadsheet export artefact; the digits are kept as text
    u = u.lstrip('0')
    return u if re.fullmatch(r'[1-9]\d{0,11}', u) else ''


def detect_truncation(lengths, min_share=0.005, ratio=2.0):
    """SY1 detection: the longest string length is a hard cap if many rows sit exactly at it (nothing is longer)
    and it holds far more rows than the lengths just below. Returns the cap or None."""
    c = Counter(lengths)
    if not c:
        return None
    n = sum(c.values())
    L = max(c)
    base = sum(c.get(L - d, 0) for d in range(2, 7)) / 5
    if (c[L] + c.get(L - 1, 0)) / n >= min_share and c[L] >= ratio * max(base, 1):
        return L
    return None


def stage(rows, source, address_col, uprn_col, postcode_col=None, epoch='', id_col=None):
    out = []
    cols = [address_col] if isinstance(address_col, str) else list(address_col)
    for i, r in enumerate(rows, 1):
        parts = [(r.get(c) or '').strip() for c in cols]
        raw = (r.get(cols[0]) or '') if len(cols) == 1 else ', '.join(x for x in parts if x)
        addr, pc = raw.strip(), (r.get(postcode_col) or '').strip() if postcode_col else ''
        flags = []
        if not postcode_col:
            m = PC_TAIL.search(addr)
            if m:
                pc, addr = m.group(1), addr[:m.start()]
        if not pc:
            flags.append('missing_postcode')
        lab = clean_uprn(r.get(uprn_col))
        if (r.get(uprn_col) or '').strip() and not lab:
            flags.append('malformed_uprn')
        rid = f"{source}:{(r.get(id_col) or '').strip() if id_col else ''}:{i}"
        out.append({'record_id': rid, 'source_council': source, 'source_row': str(i), 'label_uprn': lab,
                    'publisher_uprn_raw': r.get(uprn_col) or '', 'truth_verified': 'false',
                    'recorded_address_raw': raw, 'recorded_address': addr, 'recorded_postcode': pc.upper(),
                    'ons_epoch': epoch, 'review_flags': ';'.join(flags),
                    'source_fields_raw': ' | '.join(parts) if len(cols) > 1 else ''})
    return out


def clean(staged, exclude=None):
    """Returns kept, removed, conflicts (lists of dicts) and stats. exclude: optional predicate(row) -> reason."""
    reason = {}
    seen = set()
    for r in staged:
        rid = r['record_id']
        if not r['label_uprn']:
            reason[rid] = 'R1_missing_or_malformed_uprn'
        elif not r['recorded_address'].strip():
            reason[rid] = 'R2_empty_address'
        elif exclude and exclude(r):
            reason[rid] = 'R3_' + exclude(r)
        else:
            k = (r['label_uprn'], norm(r['recorded_address']) + '|' + r['recorded_postcode'].replace(' ', '').upper())
            if k in seen:
                reason[rid] = 'R4_exact_duplicate'
            seen.add(k)
    keys = {}
    for r in staged:
        if r['record_id'] not in reason:
            keys.setdefault(r['label_uprn'], set()).add(norm(r['recorded_address']) + '|' + r['recorded_postcode'].replace(' ', ''))
    conflict = {u for u, ks in keys.items() if len(ks) > 1}
    for r in staged:
        if r['record_id'] not in reason and r['label_uprn'] in conflict:
            reason[r['record_id']] = 'R5_uprn_conflict'
    kept = [dict(r) for r in staged if r['record_id'] not in reason]
    cap = detect_truncation([len(r['recorded_address_raw'].rstrip()) for r in kept])
    multi = Counter()
    by_key = {}
    for r in kept:
        by_key.setdefault(norm(r['recorded_address']) + '|' + r['recorded_postcode'].replace(' ', ''), set()).add(r['label_uprn'])
    for r in kept:
        t = [x for x in r['review_flags'].split(';') if x]
        if cap and len(r['recorded_address_raw'].rstrip()) >= cap - 1:
            t.append(f'systemic_truncation_{cap}')
        if len(by_key[norm(r['recorded_address']) + '|' + r['recorded_postcode'].replace(' ', '')]) > 1:
            t.append('address_shared_by_multiple_uprns')
        r['clean_tags'] = ';'.join(t)
        multi.update(t)
    removed = [dict(r, removed_reason=reason[r['record_id']]) for r in staged if r['record_id'] in reason]
    conflicts = [r for r in removed if r['removed_reason'] == 'R5_uprn_conflict']
    stats = {'input_rows': len(staged), 'kept_rows': len(kept), 'removed_rows': len(removed),
             'removed_by_rule': dict(sorted(Counter(r['removed_reason'] for r in removed).items())),
             'uprn_conflict_uprns': len({r['label_uprn'] for r in conflicts}), 'sy1_cap_detected': cap,
             'kept_tags': dict(multi)}
    assert len({r['label_uprn'] for r in kept}) == len(kept), 'kept set must have one row per UPRN'
    return kept, removed, conflicts, stats


def _write(path, rows):
    import csv
    if not rows:
        Path(path).write_text('')
        return
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    import csv
    p = argparse.ArgumentParser(prog='address-errors stage-records', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--input', required=True)
    p.add_argument('--source', required=True, help='short source name, e.g. mycouncil')
    p.add_argument('--address-col', required=True, action='append',
                   help='address column; repeat for a source with several address fields (joined with ", ")')
    p.add_argument('--uprn-col', required=True)
    p.add_argument('--postcode-col')
    p.add_argument('--id-col')
    p.add_argument('--epoch', default='')
    p.add_argument('--output', required=True, help='new directory')
    a = p.parse_args(argv)
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=False)
    with open(a.input, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    staged = stage(rows, a.source, a.address_col, a.uprn_col, a.postcode_col, a.epoch, a.id_col)
    kept, removed, conflicts, stats = clean(staged)
    _write(out / 'staged_records.csv', staged)
    _write(out / 'clean_records.csv', kept)
    _write(out / 'removed_records.csv', removed)
    _write(out / 'uprn_conflicts.csv', conflicts)
    (out / 'clean_summary.json').write_text(json.dumps(dict(source=a.source, **stats), indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == '__main__':
    main()
