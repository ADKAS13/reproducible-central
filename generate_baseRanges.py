#!/usr/bin/env python3
"""
Generate the base<Flavor> buildspecs for the dual-mojo setup (range-test -> range-compare -> real build).

For every repos/<repo>/base/<repo>*.buildspec this writes, per flavor:
    repos/<repo>/base<Flavor>/<repo>Base<Flavor>.buildspec

The command becomes three separate Maven invocations (see run_base_pipeline.sh):
    1. <plugin>:range-test     rewrites the pom with ranges (+ baseline snapshot)
    2. <plugin>:range-compare  fresh JVM, resolves the rewritten pom, writes the real comparison report
    3. the original base command (the build/tests on the ranged pom)

The -D / -P properties are read from repos/<repo>/RQ2<flavor>/*.buildspec, so base runs use
the same per-repo workarounds (excludes, compiler executable, ...) as the RQ2 runs.
Existing base<Flavor> buildspecs are overwritten; stale *.buildspec files in that folder are removed.
"""
import argparse
import re
from pathlib import Path

DEFAULT_PLUGIN = "com.baeldung:counter-maven-plugin:1.0-SNAPSHOT"

# Properties that belong to a specific stage or to the plugin, never copied from RQ2.
DEFAULT_EXCLUDE = [
    "allowVersionRanges", "useVersionRanges", "skipTests",
    "depTreeSnapshotFile", "comparisonReportFile", "rangeTestForce",
]

COMMAND_RE = re.compile(r'^command="((?:[^"\\]|\\.)*)"[ \t]*$', re.M | re.S)
WRAPPED_RE = re.compile(r'\s*sh -c \\"(.*)\\"\s*', re.S)
PROP_RE = re.compile(
    r'(?<![\w-])-D(?P<name>[\w.\-]+)'
    r'(?P<val>=(?:\\+"[^"]*?\\+"|"[^"]*"|\'[^\']*\'|[^\s"\']*))?'
)
PROFILE_RE = re.compile(r'(?<=\s)(?P<tok>-P[\w.,!\-]+)')


def parse_command(buildspec_text: str):
    """Return (match, inner_command, wrapped). `inner` is the text of the command at the sh -c level."""
    m = COMMAND_RE.search(buildspec_text)
    if not m:
        return None, None, False
    value = m.group(1)
    w = WRAPPED_RE.fullmatch(value)
    if w:
        return m, w.group(1), True
    return m, value, False


def to_wrapped_level(text: str, was_wrapped: bool) -> str:
    """Quotes written for a bare command="..." need one more level of escaping inside sh -c \\"...\\"."""
    return text if was_wrapped else text.replace('\\"', '\\\\\\"')


def extract_props(inner: str, wrapped: bool, exclude: set):
    """Ordered, de-duplicated list of (key, token) for -D properties and -P profiles."""
    found, seen = [], set()
    for m in PROP_RE.finditer(inner):
        name = m.group("name")
        if name in exclude or ("D", name) in seen:
            continue
        seen.add(("D", name))
        found.append((("D", name), to_wrapped_level(m.group(0), wrapped)))
    for m in PROFILE_RE.finditer(inner):
        tok = m.group("tok")
        if ("P", tok) not in seen:
            seen.add(("P", tok))
            found.append((("P", tok), tok))
    return found


def has_prop(command: str, key) -> bool:
    kind, name = key
    if kind == "D":
        return re.search(r'(?<![\w-])-D' + re.escape(name) + r'(?![\w.\-])', command) is not None
    return name in command


def merge_into_base(base_inner: str, props):
    """Add RQ2 properties the base command lacks, right after its first mvn invocation."""
    missing = [tok for key, tok in props if not has_prop(base_inner, key)]
    if not missing:
        return base_inner, []
    m = re.search(r'\bmvnw?\s', base_inner)
    if not m:
        return base_inner, missing
    return base_inner[:m.end()] + " ".join(missing) + " " + base_inner[m.end():], []


def strip_clean(command: str):
    """`clean` in the last stage would delete target/ and with it the baseline snapshot and the comparison report."""
    new = re.sub(r'(?<=\s)clean(?=\s|$)[ \t]*', '', command)
    return new, new != command


def build_command(flag: str, plugin: str, props, final_stage: str) -> str:
    prop_s = "".join(tok + " " for _, tok in props)
    failure_ignore = "" if any(k == ("D", "maven.test.failure.ignore") for k, _ in props) \
        else "-Dmaven.test.failure.ignore=true "
    stages = [
        "find . -name 'pom.deps.xml' -delete",
        f"mvn {prop_s}{failure_ignore}{plugin}:range-test -DallowVersionRanges={flag} install",
        # stage-1 test reports must not be mistaken for results of the ranged build
        "find . -type d \\( -name surefire-reports -o -name failsafe-reports \\) -exec rm -rf {} +",
        f"mvn {prop_s}-DskipTests {plugin}:range-compare install",
        final_stage.strip(),
    ]
    return 'command="sh -c \\"' + " &&\n    ".join(stages) + '\\""'


def find_single(folder: Path):
    specs = sorted(folder.glob("*.buildspec")) if folder.is_dir() else []
    return specs[0] if specs else None


def generate(root: Path, flags, plugin, exclude, allow_missing_rq2):
    repos_dir = root / "repos"
    if not repos_dir.exists():
        print(f"[ERROR] Repos directory not found at {repos_dir}")
        return

    repo_count = generated = 0
    for repo_path in sorted(repos_dir.iterdir()):
        if not repo_path.is_dir():
            continue
        repo = repo_path.name
        base_spec = find_single(repo_path / "base")
        if base_spec is None:
            print(f"[SKIP] No base buildspec for repo: {repo}")
            continue

        base_text = base_spec.read_text(encoding="utf-8")
        base_match, base_inner, base_wrapped = parse_command(base_text)
        if base_match is None:
            print(f"[SKIP] {repo}: no double-quoted command=\"...\" in {base_spec.name}")
            continue
        final_stage_template = to_wrapped_level(base_inner, base_wrapped)
        repo_count += 1

        for flag in flags:
            suffix = flag.capitalize()
            rq2_spec = find_single(repo_path / f"RQ2{flag.lower()}")
            props = []
            if rq2_spec is not None:
                rq2_match, rq2_inner, rq2_wrapped = parse_command(rq2_spec.read_text(encoding="utf-8"))
                if rq2_match is None:
                    print(f"[WARN] {repo}/{rq2_spec.name}: no command=\"...\" found, using base command only")
                else:
                    props = extract_props(rq2_inner, rq2_wrapped, exclude)
            elif not allow_missing_rq2:
                print(f"[SKIP] {repo}: no RQ2{flag.lower()} buildspec (use --allow-missing-rq2 to fall back to base properties)")
                continue
            else:
                print(f"[WARN] {repo}: no RQ2{flag.lower()} buildspec, using base command only")

            final_stage, unplaced = merge_into_base(final_stage_template, props)
            if unplaced:
                print(f"[WARN] {repo}: no 'mvn' found in base command, RQ2 properties not added to final stage: {' '.join(unplaced)}")

            final_stage, had_clean = strip_clean(final_stage)
            if had_clean:
                print(f"[INFO] {repo}: removed 'clean' from the final stage (it would delete the snapshot/report in target/)")

            command = build_command(flag.lower(), plugin, props, final_stage)
            new_text = base_text[:base_match.start()] + command + base_text[base_match.end():]

            flag_dir = repo_path / f"base{suffix}"
            flag_dir.mkdir(parents=True, exist_ok=True)
            dest = flag_dir / f"{repo}Base{suffix}.buildspec"

            # replace whatever was generated before
            for stale in flag_dir.glob("*.buildspec"):
                if stale != dest:
                    stale.unlink()
                    print(f"[REMOVED] {stale.relative_to(root)}")
            existed = dest.exists()
            dest.write_text(new_text, encoding="utf-8", newline="\n")
            print(f"[{'REPLACED' if existed else 'CREATED '}] ./{dest.relative_to(root)}")
            generated += 1

    print(f"\nProcessed {repo_count} repositories, wrote {generated} buildspecs.")


def main():
    ap = argparse.ArgumentParser(description="Generate base<Flavor> buildspecs for the range-test/range-compare setup.")
    ap.add_argument("--root", type=Path, default=Path("."), help="reproducible-central root")
    ap.add_argument("--flags", nargs="+", default=["major", "minor", "patch"])
    ap.add_argument("--plugin", default=DEFAULT_PLUGIN, help="groupId:artifactId:version of the plugin")
    ap.add_argument("--exclude-props", nargs="*", default=DEFAULT_EXCLUDE,
                    help="property names never copied from the RQ2 buildspec")
    ap.add_argument("--allow-missing-rq2", action="store_true",
                    help="still generate when a repo has no RQ2<flag> buildspec (base properties only)")
    args = ap.parse_args()
    generate(args.root.resolve(), args.flags, args.plugin, set(args.exclude_props), args.allow_missing_rq2)


if __name__ == "__main__":
    main()