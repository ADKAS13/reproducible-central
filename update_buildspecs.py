#!/usr/bin/env python3
"""
Normalise RQ1 / RQ2* buildspec commands into the two-stage form:

  <prefix, e.g. find ...> && mvn clean <init> [-DallowVersionRanges=x] <flatten> install -DskipTests <shared props>
                          && mvn <original final goals, no clean> <shared props>

- -DallowVersionRanges stays on the first (init/flatten) invocation, right after the init goal, and is
  removed from the final invocation.
- The final invocation loses `clean` (keeps target/) and -DskipTests.
- Shared -D properties are copied to both invocations without duplicates.
- base* buildspecs are NOT touched: generate_base_buildspecs.py owns them (range-test/range-compare stages).
- Safe to re-run (idempotent).
"""
import argparse
import re
from pathlib import Path

STAGE_ONLY = {"skipTests", "allowVersionRanges", "useVersionRanges"}
COMMAND_RE = re.compile(r'command="sh -c \\"(.+)\\""')
DEFAULT_PREFIX = "find . -name 'pom.deps.xml' -delete"


def should_update_buildspec(path: Path) -> bool:
    """Only RQ1 / RQ2* folders (by the buildspec's own folder name, not the whole path)."""
    folder = path.parent.name.lower()
    return folder == "rq1" or folder.startswith("rq2")


def tokenize(s: str):
    """Split on whitespace outside double quotes; quotes are kept verbatim in the tokens."""
    tokens, cur, in_q = [], [], False
    for ch in s:
        if ch == '"':
            in_q = not in_q
            cur.append(ch)
        elif ch.isspace() and not in_q:
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        tokens.append("".join(cur))
    return tokens


def prop_name(tok: str):
    return tok[2:].split("=", 1)[0] if tok.startswith("-D") else None


def split_segments(tokens):
    segs, cur = [], []
    for t in tokens:
        if t == "&&":
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    return [s for s in segs if s]


def is_plugin_stage(seg):
    return any(re.search(r"counter-maven-plugin.*:(init|flatten)$", t) for t in seg)


def update_command_line(content: str) -> str:
    m = COMMAND_RE.search(content)
    if not m:
        return content
    inner = m.group(1)
    if "range-test" in inner or "range-compare" in inner:
        return content  # base-style command, handled by generate_base_buildspecs.py

    segs = split_segments(tokenize(inner))
    mvn_segs = [s for s in segs if s[0] == "mvn"]
    prefix_segs = [s for s in segs if s[0] != "mvn"]

    stage1 = next((s for s in mvn_segs if is_plugin_stage(s)), None)
    if stage1 is None:
        return content  # nothing we know how to normalise
    others = [s for s in mvn_segs if s is not stage1]
    final = others[-1] if others else ["mvn", "install"]

    # shared properties from every mvn invocation, de-duplicated by name
    shared, seen = [], set()
    for seg in mvn_segs:
        for t in seg:
            n = prop_name(t)
            if n and n not in STAGE_ONLY and n not in seen:
                seen.add(n)
                shared.append(t)

    # the allowVersionRanges flag, wherever it currently sits
    allow = next((t for seg in mvn_segs for t in seg if prop_name(t) == "allowVersionRanges"), None)
    use_old = next((t for seg in mvn_segs for t in seg if prop_name(t) == "useVersionRanges"), None)

    # ---- stage 1: init + flatten + install (tests skipped) ----
    s1 = [t for t in stage1 if prop_name(t) != "allowVersionRanges"]
    flag = allow or use_old
    if flag:
        idx = next((i for i, t in enumerate(s1) if re.search(r":init$", t)), None)
        if idx is None:
            idx = next((i for i, t in enumerate(s1) if re.search(r":flatten$", t)), len(s1) - 1)
            s1.insert(idx, flag)           # no init goal: put it before flatten
        else:
            s1.insert(idx + 1, flag)       # directly after init
    if "-DskipTests" not in s1:
        s1.append("-DskipTests")
    have = {prop_name(t) for t in s1 if prop_name(t)}
    s1 += [t for t in shared if prop_name(t) not in have]

    # ---- stage 2: the real build, no clean, no skipTests, no range flag ----
    s2 = [t for t in final if t != "clean" and prop_name(t) not in STAGE_ONLY]
    have = {prop_name(t) for t in s2 if prop_name(t)}
    s2 += [t for t in shared if prop_name(t) not in have]

    prefix = [" ".join(s) for s in prefix_segs] or [DEFAULT_PREFIX]
    new_inner = " && ".join(prefix + [" ".join(s1), " ".join(s2)])
    new_line = 'command="sh -c \\"' + new_inner + '\\""'
    return content[:m.start()] + new_line + content[m.end():]


def process_buildspecs(root_dir: Path):
    repos_dir = root_dir / "repos"
    if not repos_dir.exists():
        print(f"[ERROR] Repos directory not found at {repos_dir}")
        return

    updated = skipped = 0
    for path in sorted(repos_dir.rglob("*.buildspec")):
        if not should_update_buildspec(path):
            skipped += 1
            continue
        content = path.read_text(encoding="utf-8")
        new = update_command_line(content)
        if new != content:
            path.write_text(new, encoding="utf-8", newline="\n")
            print(f"[UPDATED] ./{path.relative_to(root_dir)}")
            updated += 1
        else:
            skipped += 1
    print(f"\nDone! Updated {updated} buildspecs (skipped {skipped}: already normalised, base*, or unmatched).")


def main():
    ap = argparse.ArgumentParser(description="Normalise RQ1/RQ2 buildspecs to two-stage Maven execution.")
    ap.add_argument("--root", type=Path, default=Path("."), help="reproducible-central root")
    args = ap.parse_args()
    process_buildspecs(args.root.resolve())


if __name__ == "__main__":
    main()