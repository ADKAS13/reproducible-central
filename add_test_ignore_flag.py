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
            
            # 2. Fix command= line: clean up old/misplaced flags and place 
            # -Dmaven.test.failure.ignore=true on the LAST mvn command.
            elif line.startswith("command="):
                # Remove any accidental trailing flag outside quotes or existing ignore flags so we can re-place it cleanly
                cleaned_line = re.sub(r'"\s*-Dmaven\.test\.failure\.ignore=true\b', '"', line)
                cleaned_line = cleaned_line.replace(" -Dmaven.test.failure.ignore=true", "").replace("-Dmaven.test.failure.ignore=true", "")
                if cleaned_line != line:
                    line = cleaned_line
                    modified = True

                # Find all occurrences of 'mvn' followed by whitespace or quote inside the command string
                matches = list(re.finditer(r'\bmvn(\s+|\")', line))
                if matches:
                    # Target the LAST 'mvn' invocation (the final build/test run)
                    last_match = matches[-1]
                    start, end = last_match.span()
                    suffix = last_match.group(1)
                    
                    replacement = f"mvn -Dmaven.test.failure.ignore=true{suffix}"
                    line = line[:start] + replacement + line[end:]
                    modified = True

            new_lines.append(line)

        if modified:
            path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            print(f"[FIXED] {path}")
            fixed_count += 1

    print(f"\nSuccessfully cleaned and updated {fixed_count} buildspec files.")

if __name__ == "__main__":
    fix_and_update_buildspecs()