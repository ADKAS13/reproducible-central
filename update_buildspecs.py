import os
import re
import argparse
from pathlib import Path

def should_update_buildspec(file_path: Path) -> bool:
    """
    Determine if a buildspec requires updating.
    Targets RQ1, RQ2*, and Base* variants, but ignores plain base buildspecs.
    """
    path_str = str(file_path).lower()
    
    # Ignore plain base directories/files (e.g., repos/foo/base/foo.buildspec)
    if "/base/" in path_str and not any(v in path_str for v in ["basemajor", "baseminor", "basepatch"]):
        return False
        
    # Target RQ1, RQ2 variants, and Base range variants
    target_keywords = ["rq1", "rq2", "basemajor", "baseminor", "basepatch"]
    return any(kw in path_str for kw in target_keywords)

def update_command_line(content: str) -> str:
    """
    Transforms a single-stage maven command into a two-stage command:
    1. Run init/flatten/install with -DskipTests
    2. Run ' && mvn clean install [original flags]'
    """
    # Regex to match the command line in the buildspec
    # Example: command="sh -c \"find . -name 'pom.deps.xml' -delete && mvn clean ... install -Dcheckstyle.skip=true ...\""
    match = re.search(r'command="sh -c \\"(.+)\\""', content)
    if not match:
        return content

    inner_cmd = match.group(1)

    # If it's already split into two mvn commands, don't duplicate it
    if inner_cmd.count("mvn ") > 1:
        return content

    # We want to split right before the compilation flags / options that belong to the final build
    # Typically, the first part ends with 'install' (or 'compile test-compile') followed by properties like -Dcheckstyle.skip=true
    # Let's find where plugin execution ends and general build flags begin.
    
    # Split on the first occurrence of common skip flags if present, or split after 'install'
    # Example pattern: "... flatten install -Dcheckstyle.skip=true ..."
    
    # Check if 'install' is in the command
    if " install " in inner_cmd or inner_cmd.endswith(" install"):
        # We want: [Part 1: find && mvn ... flatten install -DskipTests] && [Part 2: mvn clean install [original flags]]
        
        # Extract flags that were passed after 'install' or scattered
        parts = inner_cmd.split(" install")
        plugin_part = parts[0] + " install -DskipTests"
        
        # The remaining flags/arguments
        remainder = parts[1] if len(parts) > 1 else ""
        
        # Reconstruct the two-stage command
        # Part 2 should run 'mvn clean install' plus all original flags (like checkstyle.skip, enforcer.skip, etc.)
        new_inner = f'{plugin_part} && mvn clean install{remainder}'
        
        # Replace in original content
        new_command_line = f'command="sh -c \\"{new_inner}\\""'
        return content.replace(match.group(0), new_command_line)

    return content

def process_buildspecs(root_dir: Path):
    repos_dir = root_dir / "repos"
    if not repos_dir.exists():
        print(f"[ERROR] Repos directory not found at {repos_dir}")
        return

    updated_count = 0
    skipped_count = 0

    for buildspec_path in repos_dir.rglob("*.buildspec"):
        if not should_update_buildspec(buildspec_path):
            skipped_count += 1
            continue

        content = buildspec_path.read_text(encoding="utf-8")
        updated_content = update_command_line(content)

        if updated_content != content:
            buildspec_path.write_text(updated_content, encoding="utf-8")
            try:
                rel_path = buildspec_path.relative_to(root_dir)
                print(f"[UPDATED] ./{rel_path}")
            except ValueError:
                print(f"[UPDATED] {buildspec_path}")
            updated_count += 1
        else:
            skipped_count += 1

    print(f"\nDone! Updated {updated_count} buildspecs (Skipped {skipped_count} base/unmatched buildspecs).")

def main():
    parser = argparse.ArgumentParser(description="Update plugin-based buildspecs to use two-stage Maven execution.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Root workspace directory")
    args = parser.parse_args()

    process_buildspecs(args.root.resolve())

if __name__ == "__main__":
    main()