#!/usr/bin/env python3
"""
rq3_fix.py — helper for the RQ3 pipeline.

  classify   Decide what happened in one build (pass / compile / resolve / test /
             plugin / other / incomplete), using the Maven log and the test reports.
  fix        Ask an LLM for dependency edits to the failing modules' flattened pom.xml,
             apply them, and write a patch tree (all flattened poms + the repairs).
  summarize  Aggregate the per-attempt JSON files of a pipeline run into a CSV.

The LLM never rewrites XML. It returns a short list of edits (set_version, set_scope,
remove_dependency, add_exclusion, add_dependency) which are validated and applied here,
so a bad answer cannot corrupt a POM, and every change is recorded for analysis.

Environment:
  ANTHROPIC_API_KEY   required for `fix` (unless RQ3_DRY_RUN=1)
  RQ3_MODEL           model name (default below); --model overrides
  RQ3_DRY_RUN=1       skip the API; revert the first few upgraded dependencies (smoke test)
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

POM_NS = "http://maven.apache.org/POM/4.0.0"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
MARKER = "counter.flatten.skip"          # FlattenMojo leaves POMs carrying this property alone
DEFAULT_MODEL = "gemini-8-flash"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
GOAL_FAIL = re.compile(r"Failed to execute goal (?:(\S+) (?:\([^)]*\) )?)?on project (\S+?): (.*)")
SKIP_DIRS = {"target", ".git", "node_modules"}
VERSION_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")   # concrete versions only, no ranges
SCOPES = {"compile", "provided", "runtime", "test"}


# ----------------------------------------------------------------------------- helpers

def strip_ansi(s):
    return ANSI.sub("", s)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def child(el, name):
    for c in el:
        if local(c.tag) == name:
            return c
    return None


def child_text(el, name):
    c = child(el, name)
    return (c.text or "").strip() if c is not None else None


def find_checkout(flavor_dir):
    bc = Path(flavor_dir) / "buildcache"
    if not bc.is_dir():
        return None
    subs = sorted(p for p in bc.iterdir() if p.is_dir())
    return subs[0] if subs else None


def walk(checkout):
    for dirpath, dirnames, filenames in os.walk(checkout):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        yield Path(dirpath), dirnames, filenames


def iter_poms(checkout):
    for dirpath, dirnames, filenames in walk(checkout):
        dirnames[:] = [d for d in dirnames if d != "target"]
        if "pom.xml" in filenames:
            yield dirpath / "pom.xml"


def modules_by_artifact(checkout):
    """artifactId -> module directory relative to the checkout ('.' for the root)."""
    result = {}
    for pom in iter_poms(checkout):
        try:
            aid = child_text(ET.parse(pom).getroot(), "artifactId")
        except ET.ParseError:
            continue
        if aid:
            result.setdefault(aid, pom.parent.relative_to(checkout).as_posix())
    return result


def failing_tests(checkout):
    """{module::class#test: message} for every failed or errored test case found in the reports."""
    found = {}
    if checkout is None:
        return found
    for dirpath, _, filenames in walk(checkout):
        if dirpath.name not in ("surefire-reports", "failsafe-reports"):
            continue
        parts = dirpath.relative_to(checkout).parts
        if "target" not in parts:
            continue
        module = "/".join(parts[:parts.index("target")]) or "."
        for fn in filenames:
            if not (fn.startswith("TEST-") and fn.endswith(".xml")):
                continue
            try:
                root = ET.parse(dirpath / fn).getroot()
            except ET.ParseError:
                continue
            for tc in root.iter("testcase"):
                bad = tc.find("failure")
                if bad is None:
                    bad = tc.find("error")
                if bad is None:
                    continue
                tid = f"{module}::{tc.get('classname', '?')}#{tc.get('name', '?')}"
                found[tid] = (bad.get("message") or bad.text or "").strip()[:600]
    return found


# ----------------------------------------------------------------------------- classify

def analyse_log(text):
    if "BUILD SUCCESS" in text and "BUILD FAILURE" not in text:
        return {"status": "pass", "goal": None, "modules": [], "message": ""}
    if "BUILD FAILURE" not in text:
        return {"status": "incomplete", "goal": None, "modules": [], "message": "no BUILD SUCCESS/FAILURE in log"}

    hits = GOAL_FAIL.findall(text)
    if not hits:
        return {"status": "other", "goal": None, "modules": [], "message": ""}
    goal, _, msg = hits[0]
    modules = []
    for _, project, _ in hits:
        if project not in modules:
            modules.append(project)

    if "counter-maven-plugin" in goal:
        status = "plugin"
    elif "maven-compiler-plugin" in goal:
        status = "compile"
    elif "surefire" in goal or "failsafe" in goal:
        status = "test"
    elif re.search(r"Could not resolve dependencies|Could not find artifact|"
                   r"Failed to collect dependencies|Could not transfer artifact", text):
        status = "resolve"
    else:
        status = "other"
    return {"status": status, "goal": goal, "modules": modules, "message": msg[:300]}


def cmd_classify(a):
    text = strip_ansi(Path(a.log).read_text(errors="replace")) if Path(a.log).exists() else ""
    info = analyse_log(text)

    cand = failing_tests(find_checkout(a.flavor_dir))
    ref = failing_tests(find_checkout(a.reference_dir)) if a.reference_dir else {}
    regressions = sorted(t for t in cand if t not in ref)

    if info["status"] == "pass" and regressions:
        info["status"] = "test"

    info.update({
        "failing_tests_total": len(cand),
        "reference_failing_total": len(ref),
        "regressions": regressions,
        "reference_used": bool(a.reference_dir),
    })
    if a.json:
        Path(a.json).write_text(json.dumps(info, indent=2))
    print(info["status"])
    return 0


# ----------------------------------------------------------------------------- context for the LLM

def error_excerpt(text, limit_lines=80, limit_chars=10000):
    keep = []
    for line in text.splitlines():
        if not line.startswith("[ERROR]"):
            continue
        body = line[len("[ERROR]"):].strip()
        if not body or body.startswith("-> [Help") or body.startswith("To see the full stack") \
                or body.startswith("Re-run Maven") or body.startswith("For more information"):
            continue
        keep.append(body)
        if len(keep) >= limit_lines:
            break
    return "\n".join(keep)[:limit_chars]


def dependency_delta(checkout, module_rel, work_dir):
    """UPGRADED/ADDED/... lines written by FlattenMojo; cached because `mvn clean` removes them."""
    cache = Path(work_dir) / f"delta_{module_rel.replace('/', '_')}.txt"
    report = Path(checkout) / module_rel / "target" / "dependency-comparison-report.txt"
    if report.exists():
        text = report.read_text(errors="replace")
        cache.write_text(text)
        return text
    return cache.read_text() if cache.exists() else ""


def compact_dependencies(pom_path):
    root = ET.parse(pom_path).getroot()
    deps = child(root, "dependencies")
    lines = []
    if deps is not None:
        for d in deps:
            if local(d.tag) != "dependency":
                continue
            ex = child(d, "exclusions")
            n_ex = len(list(ex)) if ex is not None else 0
            lines.append(":".join(filter(None, [
                child_text(d, "groupId"), child_text(d, "artifactId"), child_text(d, "type"),
                child_text(d, "classifier"), child_text(d, "version"), child_text(d, "scope")]))
                + (f"   [{n_ex} exclusions]" if n_ex else ""))
    return "\n".join(lines)


SYSTEM_PROMPT = """You repair Maven build failures by editing the dependency section of a flattened pom.xml.

The POM was machine-generated: every resolved dependency, transitive ones included, is listed
explicitly with a concrete version. A dependency-update step (version ranges) then moved some of
those versions, and the build now fails. You are given the failure, the exact list of changes the
update step made (UPGRADED lines show old -> new), and the POM.

Rules:
- You may only change dependencies in this POM. You cannot edit source code or other modules.
- Prefer the smallest change: usually setting the dependency that causes the failure back to the
  version it had before the update. Do not revert everything.
- Versions must be concrete (no ranges, no properties).
- Do not touch tests or failures that are listed as pre-existing; they are not your problem.
- If you cannot identify a fix, return an empty edits list and say why.

Answer with one JSON object and nothing else:
{"explanation": "<one or two sentences>",
 "edits": [
   {"op": "set_version", "groupId": "...", "artifactId": "...", "version": "..."},
   {"op": "set_scope", "groupId": "...", "artifactId": "...", "scope": "compile|provided|runtime|test"},
   {"op": "remove_dependency", "groupId": "...", "artifactId": "..."},
   {"op": "add_exclusion", "groupId": "...", "artifactId": "...",
    "exclusionGroupId": "...", "exclusionArtifactId": "..."},
   {"op": "add_dependency", "groupId": "...", "artifactId": "...", "version": "...", "scope": "compile"}
 ]}"""


def build_user_prompt(ctx):
    parts = [
        f"Repository: {ctx['repo']}   Module: {ctx['module']} ({ctx['module_rel']})   Attempt: {ctx['attempt']}",
        f"Failure type: {ctx['status']}",
    ]
    if ctx["previous"]:
        parts.append("Edits already tried in earlier attempts for this repository (they did not fix it):\n"
                     + json.dumps(ctx["previous"], indent=1))
    parts.append("=== Errors ===\n" + (ctx["errors"] or "(none captured)"))
    if ctx["test_details"]:
        parts.append("=== Failing tests (not failing in the reference build) ===\n" + ctx["test_details"])
    if ctx["preexisting"]:
        parts.append(f"{ctx['preexisting']} other failing tests also fail in the reference build; ignore them.")
    parts.append("=== Changes made by the dependency update (before -> after) ===\n"
                 + (ctx["delta"] or "(not available)"))
    parts.append(ctx["pom_heading"] + "\n" + ctx["pom_body"])
    return "\n\n".join(parts)


# ----------------------------------------------------------------------------- LLM

def call_llm(system, user, model, max_tokens=4000):
    if os.environ.get("RQ3_DRY_RUN") == "1":
        reverts = []
        for m in re.finditer(r"^UPGRADED\s+(\S+):(\S+)\s+(\S+) -> \S+", user, re.M):
            reverts.append({"op": "set_version", "groupId": m.group(1),
                            "artifactId": m.group(2), "version": m.group(3)})
            if len(reverts) == 3:
                break
        return json.dumps({"explanation": "dry run: revert first upgrades", "edits": reverts}), {"input": 0, "output": 0}

    key = os.environ.get("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0,
                            "responseMimeType": "application/json"},
    }).encode()
    req = urllib.request.Request(url, data=body,
            headers={"x-goog-api-key": key, "content-type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
                cands = data.get("candidates") or []
                parts = cands[0].get("content", {}).get("parts", []) if cands else []
                text = "".join(p.get("text", "") for p in parts)
                u = data.get("usageMetadata", {})
                return text, {"input": u.get("promptTokenCount", 0),
                              "output": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                time.sleep(15 * (attempt + 1))
                continue
            raise RuntimeError(f"API error {e.code}: {e.read().decode(errors='replace')[:300]}")
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(15 * (attempt + 1))
                continue
            raise RuntimeError(f"API unreachable: {e}")


def parse_json_object(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model answer")
    return json.loads(m.group(0))


# ----------------------------------------------------------------------------- applying edits

def _q(ns):
    return (lambda t: f"{{{ns}}}{t}") if ns else (lambda t: t)


def _matches(dep, g, a, classifier=None):
    if child_text(dep, "groupId") != g or child_text(dep, "artifactId") != a:
        return False
    return classifier is None or (child_text(dep, "classifier") or "") == classifier


def apply_edits(pom_in, pom_out, edits):
    """Apply validated edits, add the skip marker, write the result. Returns (applied, rejected)."""
    ET.register_namespace("", POM_NS)
    ET.register_namespace("xsi", XSI_NS)
    tree = ET.parse(pom_in)
    root = tree.getroot()
    ns = root.tag[1:].split("}")[0] if root.tag.startswith("{") else ""
    q = _q(ns)

    deps = root.find(q("dependencies"))
    applied, rejected = [], []

    def reject(e, why):
        rejected.append({**e, "reason": why})

    for e in edits[:40]:
        op, g, a = e.get("op"), e.get("groupId"), e.get("artifactId")
        if not g or not a:
            reject(e, "missing groupId/artifactId")
            continue
        found = [d for d in (deps if deps is not None else []) if local(d.tag) == "dependency"
                 and _matches(d, g, a, e.get("classifier"))]

        if op == "add_dependency":
            if found:
                reject(e, "already present")
                continue
            ver = e.get("version", "")
            if not VERSION_OK.match(ver or ""):
                reject(e, "version must be concrete")
                continue
            if deps is None:
                deps = ET.SubElement(root, q("dependencies"))
            d = ET.SubElement(deps, q("dependency"))
            for tag, val in (("groupId", g), ("artifactId", a), ("version", ver)):
                ET.SubElement(d, q(tag)).text = val
            if e.get("scope") in SCOPES:
                ET.SubElement(d, q("scope")).text = e["scope"]
            applied.append(e)
            continue

        if not found:
            reject(e, "dependency not in this POM")
            continue

        if op == "set_version":
            ver = e.get("version", "")
            if not VERSION_OK.match(ver or ""):
                reject(e, "version must be concrete")
                continue
            for d in found:
                v = child(d, "version")
                if v is None:
                    v = ET.SubElement(d, q("version"))
                v.text = ver
            applied.append(e)
        elif op == "set_scope":
            if e.get("scope") not in SCOPES:
                reject(e, "unsupported scope")
                continue
            for d in found:
                s = child(d, "scope")
                if s is None:
                    s = ET.SubElement(d, q("scope"))
                s.text = e["scope"]
            applied.append(e)
        elif op == "remove_dependency":
            for d in found:
                deps.remove(d)
            applied.append(e)
        elif op == "add_exclusion":
            eg, ea = e.get("exclusionGroupId"), e.get("exclusionArtifactId")
            if not eg or not ea:
                reject(e, "missing exclusion coordinates")
                continue
            for d in found:
                exs = child(d, "exclusions")
                if exs is None:
                    exs = ET.SubElement(d, q("exclusions"))
                if not any(child_text(x, "groupId") == eg and child_text(x, "artifactId") == ea for x in exs):
                    x = ET.SubElement(exs, q("exclusion"))
                    ET.SubElement(x, q("groupId")).text = eg
                    ET.SubElement(x, q("artifactId")).text = ea
            applied.append(e)
        else:
            reject(e, f"unknown op {op!r}")

    add_marker(root, q)
    write_pom(tree, pom_out)
    return applied, rejected


def add_marker(root, q):
    props = root.find(q("properties"))
    if props is None:
        props = ET.SubElement(root, q("properties"))
    marker = props.find(q(MARKER))
    if marker is None:
        marker = ET.SubElement(props, q(MARKER))
    marker.text = "true"


def write_pom(tree, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(ET, "indent"):
        ET.indent(tree)
    tree.write(out, encoding="utf-8", xml_declaration=True)


def is_flattened(pom):
    """Flattened by FlattenMojo in this attempt (after-snapshot) or in an earlier one (marker)."""
    if (pom.parent / "target" / "dependency-tree-after.txt").exists():
        return True
    try:
        return MARKER in pom.read_text(errors="replace")
    except OSError:
        return False


# ----------------------------------------------------------------------------- fix

def previous_edits(work_dir, attempt):
    out = []
    for n in range(1, attempt):
        f = Path(work_dir) / f"attempt{n}.fix.json"
        if f.exists():
            for m in json.loads(f.read_text()).get("modules", []):
                out.append({"attempt": n, "module": m["module"], "applied": m["applied"]})
    return out


def cmd_fix(a):
    flavor_dir, work_dir, patch_dir = Path(a.flavor_dir), Path(a.work_dir), Path(a.patch_dir)
    checkout = find_checkout(flavor_dir)
    if checkout is None:
        print("no checkout found", file=sys.stderr)
        return 2

    cls = json.loads(Path(a.classify_json).read_text())
    text = strip_ansi(Path(a.log).read_text(errors="replace"))
    by_artifact = modules_by_artifact(checkout)

    # which modules to repair
    targets = []   # (artifactId, module_rel)
    if cls["status"] == "test" and cls.get("regressions"):
        rels = []
        for tid in cls["regressions"]:
            rel = tid.split("::", 1)[0]
            if rel not in rels:
                rels.append(rel)
        inverse = {v: k for k, v in by_artifact.items()}
        targets = [(inverse.get(r, r), r) for r in rels]
    else:
        targets = [(m, by_artifact[m]) for m in cls.get("modules", []) if m in by_artifact]
    targets = targets[: a.max_modules]

    if not targets:
        print("no repairable module identified", file=sys.stderr)
        return 3

    # 1) snapshot every flattened pom so the retry can restore them (git checkout resets them)
    patch_dir.mkdir(parents=True, exist_ok=True)
    for pom in iter_poms(checkout):
        if not is_flattened(pom):
            continue
        rel = pom.relative_to(checkout)
        ET.register_namespace("", POM_NS)
        ET.register_namespace("xsi", XSI_NS)
        tree = ET.parse(pom)
        r = tree.getroot()
        ns = r.tag[1:].split("}")[0] if r.tag.startswith("{") else ""
        add_marker(r, _q(ns))
        write_pom(tree, patch_dir / rel)

    # 2) ask the model, module by module, and apply its edits to the snapshot
    ref_failing = cls.get("reference_failing_total", 0)
    report = {"attempt": a.attempt, "model": a.model, "modules": [], "input_tokens": 0, "output_tokens": 0}
    prev = previous_edits(work_dir, a.attempt)
    total_applied = 0

    for artifact, module_rel in targets:
        pom_path = patch_dir / module_rel / "pom.xml"
        if not pom_path.exists():
            continue
        pom_text = pom_path.read_text(errors="replace")
        if len(pom_text) <= a.max_pom_chars:
            heading, body = "=== Flattened pom.xml ===", pom_text
        else:
            heading = "=== Flattened dependencies (pom.xml too large to include in full) ==="
            body = compact_dependencies(pom_path)

        tests = ""
        if cls["status"] == "test":
            tests = "\n".join(f"- {t.split('::', 1)[1]}: {failing_tests(checkout).get(t, '')[:300]}"
                              for t in cls["regressions"] if t.startswith(module_rel + "::"))[:6000]

        ctx = {
            "repo": flavor_dir.parent.name, "module": artifact, "module_rel": module_rel,
            "attempt": a.attempt, "status": cls["status"], "previous": prev,
            "errors": error_excerpt(text) if cls["status"] != "test" else "",
            "test_details": tests, "preexisting": ref_failing,
            "delta": dependency_delta(checkout, module_rel, work_dir)[:15000],
            "pom_heading": heading, "pom_body": body,
        }
        try:
            answer, usage = call_llm(SYSTEM_PROMPT, build_user_prompt(ctx), a.model)
            parsed = parse_json_object(answer)
        except Exception as e:                       # noqa: BLE001 - record and move on
            report["modules"].append({"module": artifact, "error": str(e), "applied": [], "rejected": []})
            continue

        applied, rejected = apply_edits(pom_path, pom_path, parsed.get("edits", []))
        total_applied += len(applied)
        report["input_tokens"] += usage["input"]
        report["output_tokens"] += usage["output"]
        report["modules"].append({
            "module": artifact, "module_rel": module_rel, "explanation": parsed.get("explanation", ""),
            "applied": applied, "rejected": rejected})

    Path(work_dir).mkdir(parents=True, exist_ok=True)
    (Path(work_dir) / f"attempt{a.attempt}.fix.json").write_text(json.dumps(report, indent=2))
    print(f"{total_applied} edit(s) applied", file=sys.stderr)
    return 0 if total_applied else 3


# ----------------------------------------------------------------------------- summarize

def cmd_summarize(a):
    rows = []
    for work in sorted(Path(a.log_dir).iterdir()):
        cls_files = sorted(work.glob("attempt*.classify.json"), key=lambda p: int(re.findall(r"\d+", p.name)[0]))
        if not cls_files:
            continue
        cls = [json.loads(p.read_text()) for p in cls_files]
        fixes = [json.loads(p.read_text()) for p in work.glob("attempt*.fix.json")]
        repo, _, flavor = work.name.rpartition("_")
        initial, final = cls[0]["status"], cls[-1]["status"]
        rows.append({
            "repo": repo, "flavor": flavor, "reference_used": cls[0].get("reference_used", False),
            "initial_status": initial, "final_status": final,
            "fixed": initial != "pass" and final == "pass", "attempts": len(cls),
            "regressions_initial": len(cls[0].get("regressions", [])),
            "regressions_final": len(cls[-1].get("regressions", [])),
            "edits_applied": sum(len(m["applied"]) for f in fixes for m in f["modules"]),
            "edits_rejected": sum(len(m["rejected"]) for f in fixes for m in f["modules"]),
            "llm_input_tokens": sum(f["input_tokens"] for f in fixes),
            "llm_output_tokens": sum(f["output_tokens"] for f in fixes),
        })
    if not rows:
        print("no RQ3 runs found")
        return 0

    if a.csv:
        Path(a.csv).parent.mkdir(parents=True, exist_ok=True)
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    print(f"\n{'Repo':<28} {'Initial':<10} {'Final':<10} {'Tries':>5} {'Regr':>9} {'Edits':>6}")
    print("-" * 74)
    for r in rows:
        print(f"{r['repo']:<28} {r['initial_status']:<10} {r['final_status']:<10} {r['attempts']:>5} "
              f"{r['regressions_initial']:>4}->{r['regressions_final']:<4} {r['edits_applied']:>6}")
    broken = [r for r in rows if r["initial_status"] != "pass"]
    fixed = [r for r in broken if r["fixed"]]
    print("-" * 74)
    print(f"Initially broken: {len(broken)}   fixed by the LLM: {len(fixed)}"
          + (f" ({100 * len(fixed) / len(broken):.0f}%)" if broken else ""))
    if a.csv:
        print(f"CSV written to {a.csv}")
    return 0


# ----------------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("classify")
    c.add_argument("--flavor-dir", required=True)
    c.add_argument("--log", required=True)
    c.add_argument("--reference-dir")
    c.add_argument("--json")
    c.set_defaults(fn=cmd_classify)

    f = sub.add_parser("fix")
    f.add_argument("--flavor-dir", required=True)
    f.add_argument("--log", required=True)
    f.add_argument("--classify-json", required=True)
    f.add_argument("--patch-dir", required=True)
    f.add_argument("--work-dir", required=True)
    f.add_argument("--attempt", type=int, default=1)
    f.add_argument("--max-modules", type=int, default=3)
    f.add_argument("--max-pom-chars", type=int, default=60000)
    f.add_argument("--model", default=os.environ.get("RQ3_MODEL") or DEFAULT_MODEL)
    f.set_defaults(fn=cmd_fix)

    s = sub.add_parser("summarize")
    s.add_argument("--log-dir", required=True)
    s.add_argument("--csv")
    s.set_defaults(fn=cmd_summarize)

    a = p.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()