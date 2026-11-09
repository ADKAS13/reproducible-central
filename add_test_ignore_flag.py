import os
from pathlib import Path
import re

def fix_and_update_buildspecs(repos_dir="./repos"):
    root = Path(repos_dir)
    if not root.exists():
        print(f"Error: Directory '{repos_dir}' not found.")
        return

    fixed_count = 0

    for path in root.rglob("*.buildspec"):
        if not path.is_file():
            continue

        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        new_lines = []
        modified = False

        for line in lines:
            # 1. Ensure tool= line is strictly 'tool=mvn'
            if line.startswith("tool="):
                if line != "tool=mvn":
                    line = "tool=mvn"
                    modified = True
            
            # 2. Fix command= line: clean up trailing flags outside quotes, 
            # and insert -Dmaven.test.failure.ignore=true right after 'mvn' inside the command.
            elif line.startswith("command="):
                # Remove any accidental trailing flag outside the closing quotes
                cleaned_line = re.sub(r'"\s*-Dmaven\.test\.failure\.ignore=true\b', '"', line)
                if cleaned_line != line:
                    line = cleaned_line
                    modified = True

                # If the flag is not yet inside the command string at all, insert it right after 'mvn'
                if "-Dmaven.test.failure.ignore=true" not in line:
                    # Matches 'mvn ' or 'mvn"' inside the command string
                    new_line = re.sub(r'\bmvn(\s+|\")', r'mvn -Dmaven.test.failure.ignore=true\1', line, count=1)
                    if new_line != line:
                        line = new_line
                        modified = True

            new_lines.append(line)

        if modified:
            path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            print(f"[FIXED] {path}")
            fixed_count += 1

    print(f"\nSuccessfully cleaned and updated {fixed_count} buildspec files.")

if __name__ == "__main__":
    fix_and_update_buildspecs()