import os
import argparse
from pathlib import Path

def generate_buildspecs(root_dir: Path, flags: list[str], prefix: str, plugin_cmd_template: str):
    repos_dir = root_dir / "repos"
    if not repos_dir.exists():
        print(f"[ERROR] Repos directory not found at {repos_dir}")
        return

    repo_count = 0
    generated_count = 0

    for repo_path in sorted(repos_dir.iterdir()):
        if not repo_path.is_dir():
            continue
        
        repo_name = repo_path.name
        base_dir = repo_path / "base"
        if not base_dir.exists():
            print(f"[SKIP] No 'base' folder found for repo: {repo_name}")
            continue

        base_buildspecs = list(base_dir.glob("*.buildspec"))
        if not base_buildspecs:
            print(f"[SKIP] No .buildspec file found in {base_dir}")
            continue

        base_buildspec_path = base_buildspecs[0]
        base_content = base_buildspec_path.read_text(encoding="utf-8")
        repo_count += 1

        for flag in flags:
            # Subfolder structure: repos/reponame/RQ2major/
            sub_folder_name = f"{prefix}{flag}"
            flag_dir = repo_path / sub_folder_name
            flag_dir.mkdir(parents=True, exist_ok=True)

            # Filename structure: reponameRQ2major.buildspec
            new_filename = f"{repo_name}{prefix}{flag}.buildspec"
            dest_buildspec_path = flag_dir / new_filename
            
            # Format the plugin command for the specific flag
            plugin_cmd = plugin_cmd_template.format(flag=flag)

            # Insert the plugin command right before the primary 'mvn ' invocation
            modified_content = base_content
            target_mvn = "mvn "
            if target_mvn in modified_content:
                replacement = f"{plugin_cmd} &&\n    mvn "
                modified_content = modified_content.replace(target_mvn, replacement, 1)
            else:
                modified_content += f"\n# Run range-test plugin\n{plugin_cmd}\n"

            dest_buildspec_path.write_text(modified_content, encoding="utf-8")
            
            # Print clean relative path representation
            try:
                rel_path = dest_buildspec_path.relative_to(root_dir)
                print(f"[CREATED] ./{rel_path}")
            except ValueError:
                print(f"[CREATED] {dest_buildspec_path}")
                
            generated_count += 1

    print(f"\nSuccessfully processed {repo_count} repositories and generated {generated_count} buildspecs.")

def main():
    parser = argparse.ArgumentParser(description="Generate flag-specific buildspecs matching the RQ2 naming convention.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Root workspace directory")
    parser.add_argument("--flags", nargs="+", default=["major", "minor", "patch"], help="List of version range flags")
    parser.add_argument("--prefix", type=str, default="RQ2", help="Folder and filename prefix (default: RQ2)")
    parser.add_argument("--plugin-cmd", type=str, 
                        default="mvn com.baeldung:lock-plugin:1.0-SNAPSHOT:range-test -DallowVersionRanges={flag}",
                        help="Maven plugin command template")
    args = parser.parse_args()

    generate_buildspecs(args.root.resolve(), args.flags, args.prefix, args.plugin_cmd)

if __name__ == "__main__":
    main()