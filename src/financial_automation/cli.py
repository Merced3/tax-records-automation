"""Command-line interface. Core logic remains reusable by future front-ends."""

import argparse
from pathlib import Path
import sys
import yaml

from .annotation_workflow import generate, lint, load, load_states, need_human, suggest
from .auditing import audit
from .outputs import write_year
from .pipeline import run_year, transactions


def config(root):
    return yaml.safe_load((root / "config" / "app.yaml").read_text(encoding="utf-8"))


def parser():
    p = argparse.ArgumentParser(description="Financial statement automation")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("audit", "annotate", "annotate-dry", "build", "final", "rules-lint"):
        cmd = sub.add_parser(name)
        cmd.add_argument("year", type=int, nargs="?" if name in ("build",) else None)
    need = sub.add_parser("need-you")
    need.add_argument("year", type=int)
    need.add_argument("--order", choices=["largest", "smallest", "oldest", "newest", "merchant"], default="largest")
    need.add_argument("--limit", type=int, default=20)
    need.add_argument("--all", action="store_true", help="include income, not only expenses")
    verify = sub.add_parser("verify")
    verify.add_argument("year", type=int)
    verify.add_argument("path", help="path relative to the year's Bank Statements folder")
    return p


def main(argv=None, repo_root=None):
    # Installed console scripts operate on the current project directory;
    # run.py passes its own root explicitly.
    root = Path(repo_root or Path.cwd()).resolve()
    if not (root / "config" / "app.yaml").exists():
        raise RuntimeError("run from the project root (config/app.yaml not found)")
    args = parser().parse_args(argv)
    cfg = config(root)
    years = cfg["years"] if args.command == "build" and args.year is None else [args.year]
    for year in years:
        _execute(root, cfg, args, year)


def _load(root, cfg, year):
    pipeline_report = run_year(root / cfg["records_root"], year,
                               ignored_sources=cfg.get("ignored_sources"))
    rows = transactions(pipeline_report, cfg.get("include", "all"))
    return pipeline_report, rows


def _rules(root, cfg):
    return load(root / cfg.get("rules_path", "config/rules.yaml"))


def _print_audit(audit_report, pipeline_report):
    print(f"audit {audit_report.year}")
    for check in audit_report.checks:
        print(f"  {'PASS' if check.passed else 'FAIL'}  {check.name}: {check.detail}")
    for item in pipeline_report.ignored_files:
        print(f"  IGNORE {item['path']}: {item['reason']}")
    print("  => " + ("ALL CHECKS PASSED" if audit_report.passed else "CHECK FAILURES"))


def _execute(root, cfg, args, year):
    pipeline_report, rows = _load(root, cfg, year)
    audit_report = audit(year, pipeline_report)
    annotation_path = root / "annotations" / f"{year}.csv"

    if args.command == "audit":
        _print_audit(audit_report, pipeline_report)
        if not audit_report.passed:
            raise SystemExit(1)
        return

    if args.command == "annotate":
        if not audit_report.passed:
            _print_audit(audit_report, pipeline_report)
            raise RuntimeError("annotation rewrite refused because audit failed")
        result = generate(rows, annotation_path, _rules(root, cfg), root)
        print(f"{year}: annotations safely rewritten (backup + atomic replace)")
        print(f"  rows={result['rows']} human={result['human']} "
              f"suggested={result['suggested']} need-you={result['needs_review']} "
              f"legacy-migrated={result['legacy_migrated']} "
              f"deleted-restored={result['deleted_rows_restored']}")
        return

    if args.command == "annotate-dry":
        states = load_states(annotation_path)
        rules = _rules(root, cfg)
        previews = []
        for txn in rows:
            state = states.get(txn.transaction_id)
            if state and state.human_reviewed:
                continue
            proposal = suggest(txn, rules)
            if proposal.present:
                previews.append((txn, proposal))
        print(f"{year}: DRY RUN; nothing written; {len(previews)} suggestion(s)")
        for txn, proposal in previews[:40]:
            print(f"  {txn.date:%m/%d/%Y} {txn.amount:>10} {txn.merchant[:34]:34} -> "
                  f"{proposal.category} [{proposal.rule_id} v{proposal.rule_version}]")
        return

    if args.command == "rules-lint":
        states = load_states(annotation_path)
        report = lint(rows, _rules(root, cfg), states)
        print(f"{year}: rules lint")
        if report.conflicts:
            print(f"  CONFLICTS: {len(report.conflicts)} row(s) matched by rules with different suggestions")
            pairs = {}
            for txn, matches in report.conflicts:
                key = tuple(r['id'] for r in matches)
                pairs[key] = pairs.get(key, 0) + 1
            for key, count in sorted(pairs.items(), key=lambda kv: -kv[1]):
                print(f"    {count:>5}  {' > '.join(key)}")
        if report.shadowed:
            print(f"  SHADOWED: {len(report.shadowed)} rule(s) matched rows but never won")
            for rule_id, count in sorted(report.shadowed.items(), key=lambda kv: -kv[1]):
                print(f"    {count:>5}  {rule_id}")
        if report.mixed_sign:
            print(f"  MIXED SIGN: {len(report.mixed_sign)} rule(s) won both income and expense rows")
            for rule_id, (pos, neg) in report.mixed_sign.items():
                print(f"    {rule_id}: +{pos} / -{neg} (consider applies.amount_sign)")
        if report.unmatched:
            print(f"  UNMATCHED: {len(report.unmatched)} row(s) with no rule and no human fields")
            for txn in report.unmatched[:20]:
                print(f"    {txn.date:%m/%d/%Y} {txn.amount:>10} {txn.merchant[:44]}")
        if report.clean:
            print("  clean: every row is decided by exactly one policy or a human")
        else:
            raise SystemExit(1)
        return

    if args.command == "need-you":
        states = load_states(annotation_path)
        queue = need_human(rows, states, args.order, not args.all, args.limit)
        print(f"{year}: {len(queue)} row(s) that need you ({args.order} first)")
        for txn, state in queue:
            proposed = ""
            if state and state.has_suggestion:
                proposed = f" -> suggested: {state.suggested_category}"
            print(f"  {txn.date:%m/%d/%Y} {txn.amount:>10} {txn.merchant[:38]:38}{proposed}")
        return

    if args.command in ("build", "final"):
        _print_audit(audit_report, pipeline_report)
        if not audit_report.passed:
            raise RuntimeError("output refused because audit failed")
        states = load_states(annotation_path)
        paths = write_year(root, year, rows, states, audit_report, cfg,
                           pipeline_report, final=args.command == "final")
        print(f"{year}: wrote")
        for path in paths:
            print(f"  {path.relative_to(root)}")
        return

    if args.command == "verify":
        requested = root / cfg["records_root"] / str(year) / "Bank Statements" / args.path
        statement = next((s for s in pipeline_report.statements
                          if Path(s.path).resolve() == requested.resolve()), None)
        if statement is None:
            raise RuntimeError(f"statement not parsed: {requested}")
        print(f"{statement.parser_name}: {len(statement.transactions)} transaction(s)")
        for txn in statement.transactions:
            print(f"  {txn.date:%m/%d/%Y} {txn.amount:>10} {txn.merchant} | {txn.raw_description}")
