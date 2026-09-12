"""Command-line interface. Core logic remains reusable by future front-ends."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import yaml

from .annotation_workflow import (generate, lint, load, load_approvals,
                                  load_states, need_human, resolve_all,
                                  rule_approval_queue, suggest)
from .annotation_workflow.resolution import RULE, STALE, UNAPPROVED
from .auditing import audit, coverage
from .outputs import write_calendar_year, write_year
from .pipeline import run_year, transactions


def config(root):
    return yaml.safe_load((root / "config" / "app.yaml").read_text(encoding="utf-8"))


def parser():
    p = argparse.ArgumentParser(description="Financial statement automation")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("audit", "annotate", "annotate-dry", "build", "final",
                 "rules-lint", "coverage", "resolve", "approvals"):
        cmd = sub.add_parser(name)
        cmd.add_argument("year", type=int, nargs="?" if name in ("build",) else None)
    approve = sub.add_parser("approve-rule",
                             help="record owner approval of a rule at its current version")
    approve.add_argument("year", type=int)
    approve.add_argument("rule_id")
    approve.add_argument("--all-years", action="store_true",
                         help="approve for every year instead of just this one")
    cal = sub.add_parser("calendar-year",
                         help="derive a tax-year export by transaction date")
    cal.add_argument("year", type=int)
    cal.add_argument("--final", action="store_true",
                     help="require every included row to have Category and Note")
    need = sub.add_parser("need-you")
    need.add_argument("year", type=int)
    need.add_argument("--ignore-approvals", action="store_true",
                      help="treat approved rules as undecided (legacy view)")
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
    if args.command == "calendar-year":
        return _calendar_year(root, cfg, args)
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


def _approvals_path(root, cfg):
    return root / cfg.get("rule_approvals_path", "annotations/rule-approvals.yaml")


def _approvals(root, cfg):
    return load_approvals(_approvals_path(root, cfg))


def _print_audit(audit_report, pipeline_report):
    print(f"audit {audit_report.year}")
    for check in audit_report.checks:
        print(f"  {'PASS' if check.passed else 'FAIL'}  {check.name}: {check.detail}")
    for item in pipeline_report.ignored_files:
        print(f"  IGNORE {item['path']}: {item['reason']}")
    print("  => " + ("ALL CHECKS PASSED" if audit_report.passed else "CHECK FAILURES"))


def _calendar_year(root, cfg, args):
    """Audit every statement year that could contain this tax year's rows,
    then regroup accepted transactions by actual transaction date.

    Statement cycles cross calendar years, so the neighbouring statement
    folders are included as candidates. Nothing in records/ or annotations/ is
    moved or rewritten; only the derived export is new.
    """
    year = args.year
    candidates = [y for y in (year - 1, year, year + 1) if y in cfg["years"]]
    print(f"calendar year {year}: auditing contributing statement years "
          f"{candidates}")
    statement_years = {}
    states = {}
    resolved = {}
    approvals = _approvals(root, cfg)
    for folder_year in candidates:
        pipeline_report, rows = _load(root, cfg, folder_year)
        audit_report = audit(folder_year, pipeline_report)
        print(f"  {folder_year}: {len(rows)} row(s), audit "
              f"{'PASSED' if audit_report.passed else 'FAILED'}")
        if not audit_report.passed:
            _print_audit(audit_report, pipeline_report)
            raise RuntimeError(
                f"calendar-year export refused: {folder_year} statements do not "
                "reconcile, so their rows cannot be trusted in any view")
        statement_years[folder_year] = rows
        year_states = load_states(root / "annotations" / f"{folder_year}.csv")
        states.update(year_states)
        resolved.update(resolve_all(rows, year_states, approvals))

    in_year = [t for rows in statement_years.values() for t in rows
               if t.date.year == year]
    if args.final:
        missing = [t for t in in_year
                   if not (resolved.get(t.transaction_id)
                           and resolved[t.transaction_id].deliverable)]
        if missing:
            raise RuntimeError(
                f"calendar-year final export refused: {len(missing)} of "
                f"{len(in_year)} row(s) lack a resolved Category and Note")

    paths = write_calendar_year(root, year, statement_years, states, cfg,
                                resolved, final=args.final)
    contributions = {y: sum(1 for t in rows if t.date.year == year)
                     for y, rows in statement_years.items()}
    print(f"  rows dated in {year}: {len(in_year)}")
    for folder_year, count in sorted(contributions.items()):
        if count:
            print(f"    from {folder_year} statement folder: {count}")
    ready = sum(1 for t in in_year
                if resolved.get(t.transaction_id)
                and resolved[t.transaction_id].deliverable)
    print(f"  deliverable (Category + Note): {ready}/{len(in_year)}")
    print("  wrote")
    for path in paths:
        print(f"    {path.relative_to(root)}")
    print("  source statements and annotations were not modified")


def _print_coverage(report):
    print(f"coverage {report.year} (from printed statement periods, not filenames)")
    for entry in report.accounts:
        print(f"  {entry.institution} / {entry.account}")
        if entry.period_unmeasurable:
            print(f"    {entry.statements} export(s), day coverage UNMEASURABLE "
                  "(source prints no statement period)")
            print(f"    observed activity {entry.first} .. {entry.last}; "
                  "absence of rows is not evidence of no activity")
            continue
        print(f"    {entry.statements} statement(s), {entry.covered_days}/{entry.year_days} "
              f"days ({entry.percent:.1f}%), evidence {entry.first} .. {entry.last}")
        for start, end in entry.gaps:
            print(f"    GAP {start} .. {end} ({(end - start).days + 1}d) "
                  "- no statement period covers these days")
    for gap in report.known_gaps:
        print(f"  KNOWN MISSING: {gap.get('institution')} / {gap.get('account')} "
              f"[{gap.get('period', 'unknown')}]")
        print(f"    {' '.join(str(gap.get('reason', '')).split())}")
    print(f"  undeclared gap days: {report.undeclared_gap_days}")
    print("  => " + ("full-year coverage with nothing declared missing"
                     if report.complete else
                     "INCOMPLETE: this year's records do not cover the whole year"))


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

    if args.command == "coverage":
        # A year's late-December days are covered by the NEXT year's January
        # statement, so neighbouring years are scanned for evidence only.
        adjacent = []
        for neighbour in (year - 1, year + 1):
            if neighbour in cfg["years"]:
                adjacent.extend(run_year(root / cfg["records_root"], neighbour,
                                         ignored_sources=cfg.get("ignored_sources")).statements)
        report = coverage(year, pipeline_report, cfg.get("known_coverage_gaps"),
                          adjacent)
        _print_coverage(report)
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

    if args.command == "resolve":
        states = load_states(annotation_path)
        resolved = resolve_all(rows, states, _approvals(root, cfg))
        ready = [r for r in resolved.values() if r.deliverable]
        sources = {}
        for result in resolved.values():
            for name in (result.category_source, result.note_source):
                sources[name] = sources.get(name, 0) + 1
        print(f"{year}: field-level resolution (Category + Note both required)")
        print(f"  deliverable rows: {len(ready)}/{len(rows)}")
        for name, count in sorted(sources.items(), key=lambda kv: -kv[1]):
            print(f"  field values by source: {name:22} {count}")
        blocked = [(t, resolved[t.transaction_id]) for t in rows
                   if not resolved[t.transaction_id].deliverable]
        if blocked:
            print(f"  blocked rows: {len(blocked)}")
            for txn, result in blocked[:15]:
                print(f"    {txn.date:%m/%d/%Y} {txn.amount:>10} "
                      f"{txn.merchant[:34]:34} {', '.join(result.blockers)}")
        return

    if args.command == "approvals":
        states = load_states(annotation_path)
        approvals = _approvals(root, cfg)
        pending = rule_approval_queue(rows, states, approvals)
        print(f"{year}: {len(approvals)} stored approval(s); "
              f"{len(pending)} rule(s) awaiting owner approval")
        for (rule_id, version), entry in pending:
            label = "STALE (version changed since approval)" if entry["state"] == STALE else "not yet approved"
            print(f"  {entry['rows']:>5} row(s)  {rule_id} v{version}  [{label}]")
            print(f"          suggests: {entry['category']} | {entry['note'][:70]}")
            print(f"          example:  {entry['example'].date:%m/%d/%Y} "
                  f"{entry['example'].amount} {entry['example'].merchant[:40]}")
        if pending:
            print("  approve with: python run.py approve-rule <year> <rule-id>")
        return

    if args.command == "approve-rule":
        rules = _rules(root, cfg)
        rule = next((r for r in rules if r["id"] == args.rule_id), None)
        if rule is None:
            raise RuntimeError(f"no such rule: {args.rule_id}")
        path = _approvals_path(root, cfg)
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
        existing = existing or {"approvals": []}
        entry = {"rule_id": args.rule_id, "version": str(rule["version"]),
                 "approved_at": datetime.now(timezone.utc).isoformat(),
                 "approved_by": "owner"}
        if not args.all_years:
            entry["years"] = [int(year)]
        kept = [a for a in existing["approvals"]
                if not (a.get("rule_id") == args.rule_id
                        and str(a.get("version")) == str(rule["version"])
                        and sorted(a.get("years") or []) == sorted(entry.get("years", [])))]
        kept.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"approvals": kept}, sort_keys=False),
                        encoding="utf-8")
        scope = "all years" if args.all_years else f"{year}"
        print(f"approved {args.rule_id} v{rule['version']} for {scope}")
        print(f"  recorded in {path.relative_to(root)}")
        return

    if args.command == "need-you":
        states = load_states(annotation_path)
        approvals = None if args.ignore_approvals else _approvals(root, cfg)
        queue = need_human(rows, states, args.order, not args.all, args.limit,
                           approvals)
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
        approvals = _approvals(root, cfg)
        resolved = resolve_all(rows, states, approvals)
        adjacent = []
        for neighbour in (year - 1, year + 1):
            if neighbour in cfg["years"]:
                adjacent.extend(run_year(root / cfg["records_root"], neighbour,
                                         ignored_sources=cfg.get("ignored_sources")).statements)
        coverage_report = coverage(year, pipeline_report,
                                   cfg.get("known_coverage_gaps"), adjacent)
        ready = sum(1 for r in resolved.values() if r.deliverable)
        print(f"  resolved rows: {ready}/{len(rows)} have both Category and Note")
        if not coverage_report.complete:
            print("  NOTE: statement coverage for this year is not proven complete "
                  f"({coverage_report.undeclared_gap_days} undeclared gap day(s), "
                  f"{len(coverage_report.known_gaps)} declared missing)")
        paths = write_year(root, year, rows, states, audit_report, cfg,
                           pipeline_report, final=args.command == "final",
                           resolved=resolved, coverage_report=coverage_report,
                           approvals=approvals)
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
