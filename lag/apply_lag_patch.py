#!/usr/bin/env python3
"""
apply_lag_patch.py — add technical-lag collection to collect_rq2_results.py.

    python3 apply_lag_patch.py scripts/collect_rq2_results.py

Copy technical_lag.py next to collect_rq2_results.py first. The script makes four small edits, checks that
every anchor text is found exactly once, writes a .bak copy, and only then saves. If an anchor is missing
(your file differs from the version this was written against) nothing is changed and it says which edit
to make by hand.
"""
import re
import sys
from pathlib import Path

LAG_FIELDS = """
    # technical lag, filled in when run with --lag (see technical_lag.py)
    lag_deps: int = 0
    lag_days_deps: int = 0
    lag_days_before: float = 0.0
    lag_days_after: float = 0.0
    lag_days_reduction: float = 0.0
    behind_before: int = 0
    behind_after: int = 0
    behind_reduction: int = 0
    stale_major_before: int = 0
    stale_minor_before: int = 0
    stale_patch_before: int = 0
    stale_major_after: int = 0
    stale_minor_after: int = 0
    stale_patch_after: int = 0
    lag_unknown: int = 0
    not_at_policy_latest: int = 0
"""

LAG_ARGS = '''    parser.add_argument("--lag", action="store_true",
                        help="Also measure technical lag (version and time) before vs after the update")
    parser.add_argument("--lag-cache", type=Path, default=Path("results/.lag_cache.json"),
                        help="Frozen Maven Central snapshot used as 'latest' (delete it to start a new one)")
    parser.add_argument("--lag-refresh", action="store_true",
                        help="Refetch the release lists even if they are cached")
    parser.add_argument("--lag-scopes", type=str, default=None,
                        help="Comma separated scopes to include, e.g. compile,runtime (default: all)")
    parser.add_argument("--lag-workers", type=int, default=4,
                        help="Parallel requests to Maven Central (default 4; keep low, Central rate-limits)")
'''

LAG_CALL = '''    if args.lag:
        out = args.output or Path(f"results_{args.range}.csv")
        technical_lag.enrich(results, args.range, args.lag_cache, refresh=args.lag_refresh,
                             workers=args.lag_workers, root=getattr(args, "root", None), buildcache=getattr(args, "buildcache", None),
                             scopes=set(args.lag_scopes.split(",")) if args.lag_scopes else None,
                             detail_path=out.with_name(out.stem + "_lag_detail.csv"))

'''

EDITS = [
    ("import (after 'from typing import Optional')",
     "from typing import Optional\n",
     "from typing import Optional\n\nimport technical_lag  # lives next to this script\n"),
    ("command line options (before parser.parse_args())",
     "    args = parser.parse_args()\n",
     LAG_ARGS + "\n    args = parser.parse_args()\n"),
    ("call the lag computation (before 'Print summary' in main)",
     "    # Print summary\n    print_summary(results, args.range)\n",
     LAG_CALL + "    # Print summary\n    print_summary(results, args.range)\n"),
]


def add_fields(text):
    """Insert LAG_FIELDS after the last annotated field of class ModuleResult. Returns None if not found."""
    m = re.search(r"^class ModuleResult[^\n]*:\n", text, re.M)
    if not m:
        return None
    lines = text[m.end():].split("\n")
    last_field = None
    for i, line in enumerate(lines):
        if re.match(r"    \w+\s*:\s*[^=\n]+", line) and not line.lstrip().startswith(("def ", "return ")):
            last_field = i
        elif line.startswith("    @") or line.startswith("    def ") or (line and not line.startswith((" ", "\t", "#"))):
            break
    if last_field is None:
        return None
    lines[last_field + 1:last_field + 1] = LAG_FIELDS.rstrip("\n").split("\n")
    return text[:m.end()] + "\n".join(lines)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1])
    original = text = path.read_text()
    if "technical_lag" in text:
        sys.exit("already patched (technical_lag is already referenced)")

    problems = []
    for what, old, new in EDITS:
        n = text.count(old)
        if n != 1:
            problems.append(f"- {what}: anchor found {n} times (expected 1)\n  anchor: {old.strip()!r}")
            continue
        text = text.replace(old, new, 1)

    with_fields = add_fields(text)
    if with_fields is None:
        problems.append("- dataclass fields: could not find `class ModuleResult` with annotated fields")
    else:
        text = with_fields

    if problems:
        sys.exit("No changes made. These edits could not be applied:\n" + "\n".join(problems) +
                 "\n\nMake them by hand (see EDITS and LAG_FIELDS in this file) or paste the relevant part of your "
                 "collector.")
    path.with_suffix(path.suffix + ".bak").write_text(original)
    path.write_text(text)
    print(f"patched {path} (backup: {path}.bak)")


if __name__ == "__main__":
    main()