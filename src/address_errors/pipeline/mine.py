"""Mine recorded-vs-canonical discrepancy pairs (pipeline step 3).

Builds the miner's DuckDB (tables ngd, ngd1, altadd, rm from the OS NGD orders; ct from cleaned records), then
runs the study's miner (miner/mine_pairs.py, vendored from mined_error_pairs/v3_basingstoke_20261012) to write
pairs_<source>.csv.gz: every record labelled against the nearer of the NGD and PAF renderings, with format flags,
locality labels, a collision test and drift candidates. The same miner re-labels synthetic output for the
realism check, so real and synthetic records are labelled identically.

    address-errors mine --work work/ --source wigan=OS_data/Wigan:records/wigan/clean_records.csv \\
        [--source ...] [--postcode-sources wigan]

Needs duckdb and rapidfuzz (pip install address-errors[pipeline]).
"""
import argparse
import os
import subprocess
import sys
import zipfile
from pathlib import Path

COLS = ("uprn,organisationname,subname,name,number,streetname,locality,townname,postcode,fulladdress,floorlevel,"
        "classificationcode,classificationdescription,buildstatus,addressstatus,parentuprn,rootuprn,hierarchylevel,usrn,"
        "effectivestartdate,effectiveenddate")
FEATURES = [('builtaddress', 'built'), ('prebuildaddress', 'prebuild'), ('historicaddress', 'historic'),
            ('nonaddressableobject', 'nao')]
CT_COLS = ['record_id', 'ons_epoch', 'label_uprn', 'recorded_address_raw', 'recorded_address', 'recorded_postcode']


def unzip_order(order, dest):
    dest.mkdir(parents=True, exist_ok=True)
    for z in sorted(Path(order).glob('*.zip')):
        with zipfile.ZipFile(z) as zf:
            for m in zf.namelist():
                if m.endswith('.csv') and not (dest / m).exists():
                    zf.extract(m, dest)


def build_db(work, orders, records=None):
    """orders: {source: OS order folder}; records: {source: clean_records.csv} (optional: empty ct table)."""
    import duckdb
    work = Path(work)
    for s, o in orders.items():
        unzip_order(o, work / 'os' / s)
    db = work / 'miner.db'
    con = duckdb.connect(str(db))
    parts = [f"select '{s}' as ord, '{lab}' as ftype, {COLS} from read_csv('{work}/os/{s}/add_gb_{t}.csv', all_varchar=true, header=true)"
             for s in orders for t, lab in FEATURES]
    con.execute("create or replace table ngd as " + " union all ".join(parts))
    parts = [f"select '{s}' as ord, * from read_csv('{work}/os/{s}/add_gb_{t}_altadd.csv', all_varchar=true, header=true)"
             for s in orders for t in ['builtaddress', 'historicaddress', 'prebuildaddress']]
    con.execute("create or replace table altadd as " + " union all by name ".join(parts))
    parts = [f"select '{s}' as ord, * from read_csv('{work}/os/{s}/add_gb_royalmailaddress.csv', all_varchar=true, header=true)"
             for s in orders]
    con.execute("create or replace table rm as " + " union all by name ".join(parts))
    # one row per UPRN across overlapping orders; prefer built > prebuild > historic > nao (study load.py rule)
    con.execute("""create or replace table ngd1 as select * exclude(rk) from (select *, row_number() over (partition by ltrim(uprn,'0')
        order by case ftype when 'built' then 1 when 'prebuild' then 2 when 'historic' then 3 else 4 end, ord) rk from ngd) where rk=1""")
    con.execute("update ngd1 set uprn=ltrim(uprn,'0'), parentuprn=ltrim(parentuprn,'0'), rootuprn=ltrim(rootuprn,'0')")
    con.execute(f"create or replace table ct(council varchar, {', '.join(c + ' varchar' for c in CT_COLS)})")
    for s, path in (records or {}).items():
        sel = ', '.join(f"coalesce(cast({c} as varchar), '')" if c != 'ons_epoch' else "coalesce(cast(ons_epoch as varchar), '')"
                        for c in CT_COLS)
        con.execute(f"insert into ct select '{s}', {sel} from read_csv('{path}', all_varchar=true, header=true)")
    counts = {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in ['ngd1', 'altadd', 'rm', 'ct']}
    con.close()
    return db, counts


def run_miner(db, out, sources, postcode_sources=()):
    env = dict(os.environ, ADDRESS_ERRORS_POSTCODE_SOURCES=','.join(postcode_sources))
    script = Path(__file__).parent / 'miner' / 'mine_pairs.py'
    subprocess.run([sys.executable, str(script), str(db), str(out)] + list(sources), check=True, env=env)
    return Path(out)


def main(argv=None):
    p = argparse.ArgumentParser(prog='address-errors mine', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--work', required=True, help='working directory (OS CSVs are extracted here)')
    p.add_argument('--source', action='append', required=True, help='name=OS_order_folder:clean_records.csv')
    p.add_argument('--postcode-sources', default='', help='comma list of sources whose records carry postcodes')
    p.add_argument('--output', help='new directory for pairs (default <work>/pairs)')
    a = p.parse_args(argv)
    orders, recs = {}, {}
    for s in a.source:
        name, _, rest = s.partition('=')
        order, _, rec = rest.partition(':')
        orders[name] = order
        if rec:
            recs[name] = rec
    db, counts = build_db(a.work, orders, recs)
    print(counts, flush=True)
    run_miner(db, a.output or Path(a.work) / 'pairs', list(recs), [x for x in a.postcode_sources.split(',') if x])


if __name__ == '__main__':
    main()
