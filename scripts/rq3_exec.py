#!/usr/bin/env python3
"""
rq3_exec.py

Reads build failure logs directly from STDIN and modifies the pom.xml file directly 
to resolve dependency, repository, or plugin issues.
"""

import os
import sys
import re
import argparse
from dotenv import load_dotenv
from google import genai

def analyze_and_fix_pom(log_content: str, pom_path: str) -> bool:
    if not os.path.exists(pom_path):
        print(f"[LLM-Fixer] Error: pom.xml not found at {pom_path}")
        return False

    # Truncate log content if too large (keep head and tail)
    if len(log_content) > 100000:
        log_content = log_content[:20000] + "\n\n... [TRUNCATED] ...\n\n" + log_content[-80000:]

    with open(pom_path, "r", encoding="utf-8", errors="ignore") as f:
        pom_content = f.read()

    # Plain text formatting for the prompt to avoid backtick crashes
    prompt = (
        "You are an expert Java Maven build engineer fixing reproducible build dependency failures.\n"
        "Analyze the following build failure log and determine if the failure is related to missing, "
        "incompatible, or unpinned dependencies/plugins/repositories.\n\n"
        "Current pom.xml:\n"
        f"{pom_content}\n\n"
        "Build failure log:\n"
        f"{log_content}\n\n"
        "Instructions:\n"
        "1. First line MUST be either 'DEPENDENCY_ISSUE: YES' or 'DEPENDENCY_ISSUE: NO'.\n"
        "2. If DEPENDENCY_ISSUE: YES, provide the full, updated pom.xml file content starting "
        "immediately after a line labeled 'UPDATED_POM:'.\n"
        "3. Do NOT wrap the UPDATED_POM content in markdown triple backticks.\n"
    )
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[LLM-Fixer] Error: GEMINI_API_KEY not found in environment variables.")
        return False
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )

    text = response.text.strip()
    print(f"[LLM-Fixer Response Summary]:\n{text[:300]}...\n")

    if "DEPENDENCY_ISSUE: YES" in text:
        pom_match = re.search(r"UPDATED_POM:\s*(.*)", text, re.DOTALL)
        if pom_match:
            new_pom = pom_match.group(1).strip()
            
            # Clean up potential residual backticks if the model ignores instruction #3
            new_pom = re.sub(r"^```xml\s*", "", new_pom)
            new_pom = re.sub(r"^```\s*", "", new_pom)
            new_pom = re.sub(r"\s*```$", "", new_pom)

            # Backup original pom.xml
            backup_path = f"{pom_path}.orig"
            if not os.path.exists(backup_path):
                with open(backup_path, "w", encoding="utf-8") as bk:
                    bk.write(pom_content)

            # Overwrite pom.xml with the fixed version
            with open(pom_path, "w", encoding="utf-8") as f:
                f.write(new_pom)
            
            print(f"[LLM-Fixer] Successfully updated {pom_path}")
            return True
        else:
            print("[LLM-Fixer] DEPENDENCY_ISSUE was YES, but UPDATED_POM section was missing.")
            return False
    else:
        print("[LLM-Fixer] Issue is not dependency-related. No changes made.")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM pom.xml Fixer for RQ3")
    parser.add_argument("--pom", required=True, help="Path to pom.xml file")
    args = parser.parse_args()

    log_content = sys.stdin.read()
    if not log_content.strip():
        print("[LLM-Fixer] Error: STDIN log content was empty.")
        sys.exit(1)

    success = analyze_and_fix_pom(log_content, args.pom)
    sys.exit(0 if success else 1)