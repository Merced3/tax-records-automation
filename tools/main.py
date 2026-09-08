"""Entry point for the statement pipeline.

Usage (from the repo root, with the venv active):

  Invoke as:  python tools/main.py <command> ...
  (NOT:  tools/main.py ...  — Windows can't run the .py as a bare command
   and will silently do nothing.)

    python tools/main.py verify 2023 "Everyday Spend Bank Account/Apr-10.pdf"
        Read ONE statement, print what we extracted + the report.
        Writes nothing. Use this to eyeball a parser before trusting it.

    python tools/main.py verify-year 2023
        Parse a whole year, print stats + a sample. Writes nothing.

    python tools/main.py run
        Parse every configured year and write CSVs to output/.

    python tools/main.py audit 2024
        Prove the extraction for one year: reconcile parsed transactions
        against the balances the statements themselves print.

    python tools/main.py annotate 2024
        Generate annotations/<year>.csv for you to fill in (Category, Note).
        Preserves rows you've already annotated. Re-runnable.

    python tools/main.py annotate-dry 2024
        Show what rules WOULD auto-fill for still-blank rows. Writes nothing.
        Use this to tune tools/rules.yaml before running annotate for real.

    python tools/main.py need-you 2024 [--order largest] [--limit 20] [--all]
        Show the rows that still need you, ranked by importance. Default:
        largest expenses first (what a tax pro itemizes). --all includes
        income; --order picks the ranking (largest/smallest/oldest/newest/
        merchant).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml

from pipeline import filters
from pipeline.engine import run_year
from writers.csv_writer import write_year_csv
from parsers import PLUGINS
from audit import reconcile
from annotations import store

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    with open(os.path.join(REPO_ROOT, "tools", "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_report(report):
    print(f"\n--- report ---")
    print(f"statements parsed:    {report.parsed_files}")
    print(f"duplicates removed:   {report.duplicates_removed}")
    print(f"unclaimed PDFs:       {len(report.unclaimed_files)}")
    for p in report.unclaimed_files:
        print(f"    (no parser claimed) {os.path.relpath(p, REPO_ROOT)}")
    print(f"errors:               {len(report.errored_files)}")
    for p, err in report.errored_files:
        print(f"    {os.path.relpath(p, REPO_ROOT)}: {err}")


def print_sample(transactions, n=8):
    print(f"\n--- sample (first {n}) ---")
    for t in transactions[:n]:
        print(f"  {t.date}  {t.amount:>10.2f}  {t.merchant[:40]:<40}  [{t.source_account}]")


def cmd_verify(year, rel_pdf):
    path = os.path.join(REPO_ROOT, "records", str(year), "Bank Statements", rel_pdf)
    if not os.path.isfile(path):
        sys.exit(f"No such file: {path}")

    import pdfplumber
    with pdfplumber.open(path) as pdf:
        first_text = pdf.pages[0].extract_text() or ""

    plugin = next((p for p in PLUGINS if p.can_parse(first_text, path)), None)
    if plugin is None:
        sys.exit(f"No parser claimed this file. Known plugins: "
                 f"{[p.name for p in PLUGINS]}")

    print(f"parser: {plugin.name}")
    account = os.path.basename(os.path.dirname(path))
    txns = plugin.parse(path, account, year)
    print(f"extracted {len(txns)} transactions from {os.path.basename(path)}\n")
    for t in txns:
        print(f"  {t.date}  {t.amount:>10.2f}  {t.merchant[:35]:<35}  | {t.description[:60]}")


def cmd_verify_year(year, config):
    txns, report = run_year(os.path.join(REPO_ROOT, config["records_root"]), year)
    txns = filters.apply(txns, config["include"])
    print(f"year {year}: {len(txns)} transactions")
    if txns:
        total_in = sum(t.amount for t in txns if t.amount > 0)
        total_out = sum(t.amount for t in txns if t.amount < 0)
        print(f"  money in:  {total_in:>12.2f}")
        print(f"  money out: {total_out:>12.2f}")
        print(f"  date range: {txns[0].date} -> {txns[-1].date}")
    print_sample(txns)
    print_report(report)


def cmd_audit(year, config):
    records = os.path.join(REPO_ROOT, config["records_root"])
    txns, report = run_year(records, year)

    chase_paths, cashapp_paths = [], []
    chase_txns, cashapp_txns = [], []
    for t in txns:
        (cashapp_txns if "Cash App" in t.source_file or "CashApp" in t.source_file
         else chase_txns).append(t)
    for dirpath, _d, files in os.walk(os.path.join(records, str(year), "Bank Statements")):
        for f in files:
            if not f.lower().endswith(".pdf"):
                continue
            p = os.path.join(dirpath, f)
            (cashapp_paths if "CashApp" in dirpath else chase_paths).append(p)

    # Map each Chase PDF to the transactions parsed from it, for the
    # per-statement dollar reconciliation.
    chase_txns_by_file = {}
    for t in chase_txns:
        chase_txns_by_file.setdefault(t.source_file, []).append(t)

    results = []
    if chase_paths:
        results.append(reconcile.audit_chase(chase_paths, chase_txns_by_file))
    if cashapp_paths:
        results.append(reconcile.audit_cashapp(cashapp_paths, cashapp_txns))

    print(f"audit {year}")
    all_ok = True
    for r in results:
        print(f"  [{r.label}]")
        for ok, msg in r.checks:
            print(f"    {'PASS' if ok else 'FAIL'}  {msg}")
            all_ok = all_ok and ok
    print(f"  => {'ALL CHECKS PASSED' if all_ok else 'CHECK FAILURES ABOVE'}")
    if not all_ok:
        sys.exit(1)


def _rules_suggester():
    from annotations import rules
    rule_list = rules.load_rules(os.path.join(REPO_ROOT, "tools", "rules.yaml"))
    return (lambda t: rules.suggest(t, rule_list)) if rule_list else None


def cmd_annotate_dry(year, config):
    """Show what rules WOULD fill for still-blank rows. Writes nothing."""
    records = os.path.join(REPO_ROOT, config["records_root"])
    txns, report = run_year(records, year)
    txns = filters.apply(txns, config["include"])
    suggester = _rules_suggester()
    path = os.path.join(REPO_ROOT, "annotations", f"{year}.csv")
    rows = store.preview(txns, path, suggester)

    print(f"{year}: DRY RUN — nothing written")
    if not suggester:
        print("  no rules found (tools/rules.yaml empty or missing)")
        return
    print(f"  {len(rows)} still-blank rows would be auto-filled:\n")
    for t, sugg in rows[:40]:
        note = f"  | {sugg.note}" if sugg.note else ""
        print(f"    {t.date} {t.amount:>10.2f} {t.merchant[:34]:<34} -> "
              f"{sugg.category}{note}")
    if len(rows) > 40:
        print(f"    ... and {len(rows) - 40} more")


def cmd_annotate(year, config):
    records = os.path.join(REPO_ROOT, config["records_root"])
    txns, report = run_year(records, year)
    txns = filters.apply(txns, config["include"])

    suggester = _rules_suggester()

    out_dir = os.path.join(REPO_ROOT, "annotations")
    path = os.path.join(out_dir, f"{year}.csv")
    total, annotated, carried, suggested = store.generate(txns, path, suggester)

    print(f"{year}: wrote {os.path.relpath(path, REPO_ROOT)}")
    print(f"  transactions:        {total}")
    print(f"  auto-filled by rules:{suggested:5d}  (edit tools/rules.yaml to tune)")
    print(f"  annotated by you:    {carried:5d}  (carried over, never overwritten)")
    print(f"  still to annotate:   {total - annotated:5d}")
    print(f"\nFill in the Category and Note columns, then re-run anytime.")


def cmd_need_you(year, config, order="largest", limit=20, expenses_only=True):
    """Show the rows that still need you, ranked by importance.

    The ranking logic lives in annotations/report.py (pure, reusable); this
    is just the CLI renderer. Defaults to largest expenses first because
    that's what a tax pro itemizes — flip with --order or --all.
    """
    from annotations import report as rep
    records = os.path.join(REPO_ROOT, config["records_root"])
    txns, _ = run_year(records, year)
    txns = filters.apply(txns, config["include"])
    existing = store.load_existing(os.path.join(REPO_ROOT, "annotations", f"{year}.csv"))

    rows = rep.unannotated(txns, existing, order=order, limit=limit,
                           expenses_only=expenses_only)
    scope = "expenses" if expenses_only else "all transactions"
    print(f"{year}: {len(rows)} un-annotated {scope} shown ({order} first)")
    print(f"    (orders: largest, smallest, oldest, newest, merchant)\n")
    for r in rows:
        print(f"  {r['date']} {r['amount']:>10.2f}  {r['merchant'][:38]:<38}  [{r['source_account'][:20]}]")


def cmd_run(config):
    for year in config["years"]:
        txns, report = run_year(os.path.join(REPO_ROOT, config["records_root"]), year)
        txns = filters.apply(txns, config["include"])
        path = write_year_csv(txns, config["columns"],
                              os.path.join(REPO_ROOT, config["output_dir"]), year)
        print(f"{year}: {len(txns)} transactions -> {os.path.relpath(path, REPO_ROOT)}")
        print_report(report)


def _flag_value(argv, name, default):
    """Read '--name value' from argv; default if absent."""
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    config = load_config()
    cmd = sys.argv[1]

    if cmd == "verify" and len(sys.argv) == 4:
        cmd_verify(sys.argv[2], sys.argv[3])
    elif cmd == "verify-year" and len(sys.argv) == 3:
        cmd_verify_year(int(sys.argv[2]), config)
    elif cmd == "audit" and len(sys.argv) == 3:
        cmd_audit(int(sys.argv[2]), config)
    elif cmd == "annotate" and len(sys.argv) == 3:
        cmd_annotate(int(sys.argv[2]), config)
    elif cmd == "annotate-dry" and len(sys.argv) == 3:
        cmd_annotate_dry(int(sys.argv[2]), config)
    elif cmd == "need-you" and len(sys.argv) >= 3:
        # need-you <year> [--order largest|smallest|oldest|newest|merchant]
        #                 [--limit N] [--all]
        year = int(sys.argv[2])
        order = _flag_value(sys.argv, "--order", "largest")
        limit = int(_flag_value(sys.argv, "--limit", "20"))
        expenses_only = "--all" not in sys.argv
        cmd_need_you(year, config, order=order, limit=limit, expenses_only=expenses_only)
    elif cmd == "run":
        cmd_run(config)
    else:
        sys.exit(__doc__)
