import argparse
import os
import re
import xml.etree.ElementTree as ET
import requests


def parse_github_url(commit_url: str):
    """
    Extracts owner, repo, and commit hash from a GitHub commit URL.
    Example URL: https://github.com/LearnLib/automatalib/commit/3cfc64a
    """
    pattern = r"github\.com/([^/]+)/([^/]+)/commit/([a-f0-9]+)"
    match = re.search(pattern, commit_url)
    if not match:
        raise ValueError(
            "Invalid GitHub commit URL format. Expected: https://github.com/owner/repo/commit/hash"
        )

    owner, repo, commit_hash = match.groups()
    return owner, repo, commit_hash


def extract_pom_info(owner: str, repo: str, commit_hash: str, token: str = None):
    """
    Fetches raw pom.xml from GitHub at the given commit hash and extracts metadata.
    """
    raw_pom_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_hash}/pom.xml"
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"

    response = requests.get(raw_pom_url, headers=headers)

    if response.status_code == 404:
        raise FileNotFoundError(
            f"pom.xml not found at root for repository '{owner}/{repo}' at commit '{commit_hash}'."
        )
    elif response.status_code != 200:
        raise Exception(
            f"Failed to fetch pom.xml from {raw_pom_url} (HTTP Status: {response.status_code})"
        )

    # Parse XML handling namespaces
    root = ET.fromstring(response.content)
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}

    def find_text(path: str, default=None):
        node = root.find(path, ns)
        if node is None:
            path_no_ns = path.replace("m:", "")
            node = root.find(path_no_ns)
        return node.text.strip() if node is not None and node.text else default

    # 1. Group ID (check root, fallback to parent)
    group_id = find_text("m:groupId")
    if not group_id:
        group_id = find_text("m:parent/m:groupId", default="")

    # 2. Artifact ID
    artifact_id = find_text("m:artifactId", default="")

    # 3. JDK Version parsing
    jdk = "11"  # Modern fallback default for newer Maven plugins using --release

    java_version_keys = [
        "m:properties/m:java.version",
        "m:properties/m:maven.compiler.release",
        "m:properties/m:maven.compiler.source",
        "m:properties/m:maven.compiler.target",
    ]

    for key in java_version_keys:
        val = find_text(key)
        if val:
            cleaned_val = val.replace("1.", "")
            if cleaned_val.isdigit():
                jdk = cleaned_val
                break

    return {
        "groupId": group_id,
        "artifactId": artifact_id,
        "jdk": jdk,
    }


def create_buildspec_files(
    commit_url: str,
    output_dir: str = ".",
    token: str = None,
    override_jdk: str = None,
    extra_flags: str = "",
):
    owner, repo, commit_hash = parse_github_url(commit_url)
    output_dir = output_dir.replace("reponame", repo)
    pom_info = extract_pom_info(owner, repo, commit_hash, token=token)

    # Use explicit CLI JDK argument if provided; otherwise fallback to parsed pom.xml value
    jdk_version = override_jdk if override_jdk else pom_info["jdk"]

    # Normalize extra_flags to have a leading space if provided
    flags_str = f" {extra_flags.strip()}" if extra_flags else ""

    # Capitalized name for buildinfo line (e.g., "Automata" from "automatalib")
    buildinfo_name = repo.capitalize()
    if buildinfo_name.lower().endswith("lib"):
        buildinfo_name = buildinfo_name[:-3].capitalize()

    git_repo_url = f"https://github.com/{owner}/{repo}.git"

    template = (
        f"groupId={pom_info['groupId']}\n"
        f"artifactId={pom_info['artifactId']}\n"
        f"version=9\n\n"
        f"gitRepo={git_repo_url}\n"
        f"gitTag={commit_hash}\n\n"
        f"tool=mvn\n"
        f"jdk={jdk_version}\n"
        f"newline=lf\n"
        f"umask=022\n\n"
        f'command="{"{command}"}"\n\n'
        f"buildinfo=target/{buildinfo_name}.buildinfo\n"
    )

    # Map each variant to a tuple of (subfolder_flavor, shell_command)
    variants = {
        f"{repo}.buildspec": (
            "base",
            rf"sh -c \"find . -name 'pom.deps.xml' -delete && mvn clean install{flags_str}\"",
        ),
        f"{repo}RQ1.buildspec": (
            "RQ1",
            rf"sh -c \"find . -name 'pom.deps.xml' -delete && mvn clean "
            rf"com.baeldung:counter-maven-plugin:1.0-SNAPSHOT:init "
            rf"com.baeldung:counter-maven-plugin:1.0-SNAPSHOT:flatten install{flags_str}\"",
        ),
        f"{repo}RQ2major.buildspec": (
            "RQ2major",
            rf"sh -c \"find . -name 'pom.deps.xml' -delete && mvn clean "
            rf"com.baeldung:counter-maven-plugin:1.0-SNAPSHOT:init "
            rf"-DallowVersionRanges=major "
            rf"com.baeldung:counter-maven-plugin:1.0-SNAPSHOT:flatten install{flags_str}\"",
        ),
        f"{repo}RQ2minor.buildspec": (
            "RQ2minor",
            rf"sh -c \"find . -name 'pom.deps.xml' -delete && mvn clean "
            rf"com.baeldung:counter-maven-plugin:1.0-SNAPSHOT:init "
            rf"-DallowVersionRanges=minor "
            rf"com.baeldung:counter-maven-plugin:1.0-SNAPSHOT:flatten install{flags_str}\"",
        ),
        f"{repo}RQ2patch.buildspec": (
            "RQ2patch",
            rf"sh -c \"find . -name 'pom.deps.xml' -delete && mvn clean "
            rf"com.baeldung:counter-maven-plugin:1.0-SNAPSHOT:init "
            rf"-DallowVersionRanges=patch "
            rf"com.baeldung:counter-maven-plugin:1.0-SNAPSHOT:flatten install{flags_str}\"",
        ),
    }

    for filename, (flavor, cmd) in variants.items():
        flavor_dir = os.path.join(output_dir, flavor)
        os.makedirs(flavor_dir, exist_ok=True)

        file_content = template.format(command=cmd)
        filepath = os.path.join(flavor_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(file_content)
        print(f"Generated: {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate .buildspec files from a GitHub commit URL."
    )
    parser.add_argument(
        "url",
        type=str,
        help="GitHub commit URL (e.g., https://github.com/LearnLib/automatalib/commit/3cfc64a)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default="./repos/reponame",
        help="Directory where buildspec files will be saved (default: ./repos/reponame)",
    )
    parser.add_argument(
        "-j",
        "--jdk",
        type=str,
        default=None,
        help="Override JDK version (e.g., 8, 11, 17, 21). If omitted, auto-detects from pom.xml",
    )
    parser.add_argument(
        "-f",
        "--flags",
        type=str,
        default="",
        help="Extra flags to append to the mvn command (e.g., '-Dmaven.javadoc.skip=true -Dgpg.skip')",
    )
    parser.add_argument(
        "-t",
        "--token",
        type=str,
        default=None,
        help="Optional GitHub Personal Access Token to avoid API rate limiting or for private repos",
    )

    args = parser.parse_args()

    try:
        create_buildspec_files(
            args.url,
            output_dir=args.output_dir,
            token=args.token,
            override_jdk=args.jdk,
            extra_flags=args.flags,
        )
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()