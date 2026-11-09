#!/usr/bin/env python3
"""
technical_lag.py — technical lag before vs after the dependency update (RQ2).

Also reads build outcome and build time (Maven's "Total time") from the pipeline logs; see enrich().

Commands (no collector needed):
    python3 scripts/technical_lag.py check org.apache.commons:commons-lang3 3.12.0     # do the lookups work from here?
    python3 scripts/technical_lag.py build-times --root . --range major                # build times only, offline

Technical lag of a dependency = how far the version in use is behind the latest available release.
For every module this compares the original resolution (target/dependency-tree-before.txt) with the
flattened/updated one (target/dependency-tree-after.txt) and measures, per dependency:

  time lag        days between the release of the version in use and the release of the latest stable
                  version (0 when already on the latest)
  version lag     number of stable releases newer than the version in use ("releases behind")
  staleness level the highest component by which it trails the latest: major / minor / patch / current

"Reduction" = lag before - lag after; positive means the update brought the project closer to the latest.

Choices worth knowing about
  * Only dependencies present in BOTH snapshots are compared. Added/removed ones have no counterpart.
  * "Latest" means the highest stable release (no alpha/beta/rc/milestone/snapshot) on Maven Central.
  * Dependencies of the project's own groupId, SNAPSHOTs, and artifacts Maven Central does not know
    (private repositories) are skipped and counted in lag_unknown.
  * Release dates are the Last-Modified header of the artifact's .pom on repo.maven.apache.org. That is
    when the file was published; it is not guaranteed to be the author's release date.
  * The reference ("latest") is frozen in a cache file so every flag is measured against the same snapshot.
    Delete the cache or pass refresh=True to measure against today's releases.
"""

import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import cmp_to_key
from pathlib import Path

CENTRAL = "https://repo.maven.apache.org/maven2"
SEARCH = "https://search.maven.org/solrsearch/select"   # fallback source for release dates

# (name, default) — paste these as dataclass fields into ModuleResult in collect_rq2_results.py
LAG_FIELDS = [
    ("lag_deps", 0),               # dependencies compared (version lag measured)
    ("lag_days_deps", 0),          # ... of which release dates were available (time lag measured)
    ("lag_days_before", 0.0),      # summed time lag in days, original resolution
    ("lag_days_after", 0.0),       # summed time lag in days, after the update
    ("lag_days_reduction", 0.0),   # before - after
    ("behind_before", 0),          # summed releases behind
    ("behind_after", 0),
    ("behind_reduction", 0),
    ("stale_major_before", 0),     # dependencies trailing by at least a major version
    ("stale_minor_before", 0),
    ("stale_patch_before", 0),
    ("stale_major_after", 0),
    ("stale_minor_after", 0),
    ("stale_patch_after", 0),
    ("lag_unknown", 0),            # compared dependencies with no usable Maven Central data
    ("not_at_policy_latest", 0),   # after-version below the newest version the range allowed
]


# ------------------------------------------------------------------------------ versions

_QUALIFIERS = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "milestone": 2, "m": 2, "rc": 3, "cr": 3,
               "snapshot": 4, "": 5, "ga": 5, "final": 5, "release": 5, "sp": 6}
_PRERELEASE = re.compile(r"(?i)(^|[.\-_])(alpha|beta|rc|cr|m|milestone|snapshot|preview|pre|dev|ea|a|b)(\d*)([.\-_]|$)")
_TIMESTAMPED = re.compile(r"\d{8}\.\d{6}-\d+$")


def _tokens(v):
    return re.findall(r"\d+|[A-Za-z]+", v)


def _rank(tok):
    return _QUALIFIERS.get(tok.lower(), 7)      # unknown qualifiers (e.g. "jre") sort after a release


def cmp_versions(x, y):
    """Maven-like version ordering (a simplified ComparableVersion)."""
    tx, ty = _tokens(x), _tokens(y)
    for i in range(max(len(tx), len(ty))):
        a = tx[i] if i < len(tx) else None
        b = ty[i] if i < len(ty) else None
        if a is None:
            a = "0" if b.isdigit() else ""
        if b is None:
            b = "0" if a.isdigit() else ""
        if a.isdigit() and b.isdigit():
            c = (int(a) > int(b)) - (int(a) < int(b))
        elif a.isdigit():
            c = 1
        elif b.isdigit():
            c = -1
        else:
            ra, rb = _rank(a), _rank(b)
            c = (ra > rb) - (ra < rb)
            if c == 0 and ra == 7:
                c = (a.lower() > b.lower()) - (a.lower() < b.lower())
        if c:
            return c
    return 0


def is_snapshot(v):
    return "SNAPSHOT" in v.upper() or bool(_TIMESTAMPED.search(v))


def is_stable(v):
    return not is_snapshot(v) and not _PRERELEASE.search(v)


def lead_nums(v):
    out = []
    for t in _tokens(v):
        if not t.isdigit():
            break
        out.append(int(t))
    return out


def staleness(used, latest):
    """'current', or the highest component by which `used` trails `latest`."""
    if cmp_versions(used, latest) >= 0:
        return "current"
    u, l = lead_nums(used), lead_nums(latest)
    for name, i in (("major", 0), ("minor", 1), ("patch", 2)):
        ui = u[i] if i < len(u) else 0
        li = l[i] if i < len(l) else 0
        if li > ui:
            return name
        if li < ui:
            break
    return "patch"           # behind only by a qualifier or a later component


def newest(versions):
    return max(versions, key=cmp_to_key(cmp_versions))


def policy_latest(before, stable, mode):
    """Newest stable version the range written for `mode` could reach, starting from `before`."""
    nums = lead_nums(before)
    cands = [v for v in stable if cmp_versions(v, before) >= 0]
    if mode == "minor":
        if not nums:
            return before
        cands = [v for v in cands if lead_nums(v)[:1] == nums[:1]]
    elif mode == "patch":
        if len(nums) < 2:
            return before
        cands = [v for v in cands if lead_nums(v)[:2] == nums[:2]]
    return newest(cands) if cands else before


# ------------------------------------------------------------------------------ Maven Central

def _http_once(url, method="GET"):
    """(status, headers, body); status 0 = network error."""
    try:
        req = urllib.request.Request(url, method=method, headers={"User-Agent": "technical-lag-collector/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), (r.read() if method == "GET" else b"")
    except urllib.error.HTTPError as e:
        return e.code, {}, b""
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return 0, {}, b""


class Central:
    """Release lists and release dates from Maven Central, cached on disk."""

    def __init__(self, cache_path, refresh=False, workers=4, delay=0.05, backoff=10):
        self.path = Path(cache_path)
        self.workers, self.delay, self.backoff = workers, delay, backoff
        self.lock = threading.Lock()
        self.pause_until = 0.0                 # shared: when Central says "slow down", every thread waits
        self.failures = {}                     # status code -> requests that never succeeded
        self.date_sources = {}                 # which source produced each fetched release date
        self.cache = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "versions": {}, "dates": {}}
        if self.path.exists():
            loaded = json.loads(self.path.read_text())
            if refresh:
                loaded["versions"] = {}            # keep known release dates, refetch the release lists
                loaded["created"] = self.cache["created"]
            self.cache = loaded

    @property
    def as_of(self):
        return self.cache["created"]

    def _request(self, url, method="GET"):
        status, headers, body = 0, {}, b""
        for attempt in range(5):
            wait = self.pause_until - time.time()
            if wait > 0:
                time.sleep(wait)
            status, headers, body = _http_once(url, method)
            time.sleep(self.delay)
            if status in (200, 404):
                return status, headers, body
            if status in (0, 429, 500, 502, 503, 504):
                with self.lock:
                    self.pause_until = max(self.pause_until, time.time() + min(120, self.backoff * 2 ** attempt))
                continue
            break                                  # 403, 405, ... will not improve by retrying
        with self.lock:
            self.failures[status] = self.failures.get(status, 0) + 1
        return status, {}, b""

    # --- network lookups (overridden in tests). None = transient failure, do not cache; "" = definitively unknown.
    def _fetch_versions(self, g, a):
        status, _, body = self._request(f"{CENTRAL}/{g.replace('.', '/')}/{a}/maven-metadata.xml")
        if status == 200:
            root = ET.fromstring(body)
            return [e.text.strip() for e in root.findall("./versioning/versions/version") if e.text]
        return [] if status == 404 else None

    def _date_from_pom(self, g, a, v):
        status, headers, _ = self._request(f"{CENTRAL}/{g.replace('.', '/')}/{a}/{v}/{a}-{v}.pom", method="HEAD")
        if status == 200:
            lm = {k.lower(): val for k, val in headers.items()}.get("last-modified")
            return parsedate_to_datetime(lm).astimezone(timezone.utc).isoformat() if lm else ""
        return "" if status == 404 else None

    def _date_from_search(self, g, a, v):
        q = urllib.parse.quote(f'g:"{g}" AND a:"{a}" AND v:"{v}"')
        status, _, body = self._request(f"{SEARCH}?q={q}&core=gav&rows=1&wt=json")
        if status == 200:
            try:
                docs = json.loads(body).get("response", {}).get("docs", [])
            except ValueError:
                return None
            if docs and docs[0].get("timestamp"):
                return datetime.fromtimestamp(docs[0]["timestamp"] / 1000, tz=timezone.utc).isoformat()
            return ""
        return "" if status == 404 else None

    def _fetch_date(self, g, a, v):
        """Last-Modified of the .pom first; Maven Central's search index as a fallback."""
        iso = self._date_from_pom(g, a, v)
        if iso:
            self._count("pom")
            return iso
        alt = self._date_from_search(g, a, v)
        if alt:
            self._count("search")
            return alt
        return None if (iso is None or alt is None) else ""

    def _count(self, source):
        with self.lock:
            self.date_sources[source] = self.date_sources.get(source, 0) + 1

    # --- cached access
    def versions(self, ga):
        return self.cache["versions"].get(ga) or []

    def date(self, ga, v):
        iso = self.cache["dates"].get(f"{ga}:{v}")
        return datetime.fromisoformat(iso) if iso else None

    def prefetch_versions(self, gas):
        todo = [ga for ga in gas if ga not in self.cache["versions"]]
        self._run(todo, lambda ga: self._store("versions", ga, self._fetch_versions(*ga.split(":", 1))), "release lists")

    def prefetch_dates(self, gavs):
        todo = [(ga, v) for ga, v in gavs if f"{ga}:{v}" not in self.cache["dates"]]
        def one(item):
            ga, v = item
            g, a = ga.split(":", 1)
            self._store("dates", f"{ga}:{v}", self._fetch_date(g, a, v))
        self._run(todo, one, "release dates")

    def _store(self, section, key, value):
        if value is None:
            return
        with self.lock:
            self.cache[section][key] = value

    def _run(self, items, fn, what):
        if not items:
            return
        print(f"  [lag] fetching {len(items)} {what} from Maven Central ...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(fn, items))
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache))


# ------------------------------------------------------------------------------ measuring

def read_snapshot(path, scopes=None):
    """(group of the module, {g:a: version}) from a dependency-tree-*.txt file."""
    path = Path(path)
    if not path.exists():
        return None, {}
    deps, group = {}, None
    for i, line in enumerate(path.read_text(errors="replace").splitlines()):
        if i == 0:
            group = line.split(":")[0]
            continue
        s = line.strip()
        if not s.startswith("+-"):
            continue
        p = s[2:].strip().split(":")
        if len(p) < 5:
            continue
        g, a, v, scope = p[0], p[1], p[3], p[4]
        if (scopes and scope not in scopes) or is_snapshot(v) or v.startswith(("[", "(", "$")):
            continue
        deps.setdefault(f"{g}:{a}", v)
    return group, deps


def _days(client, ga, used, lat):
    if cmp_versions(used, lat) >= 0:
        return 0.0
    du, dl = client.date(ga, used), client.date(ga, lat)
    if du is None or dl is None:
        return None
    return max(0.0, (dl - du).total_seconds() / 86400)


def compute_lag(client, modules, mode, scopes=None):
    """
    modules: list of (key, target_dir). Returns ({key: metrics}, detail_rows, coverage_stats).
    mode: 'major' | 'minor' | 'patch' | anything else (no range policy check).
    """
    stats = {"modules": len(modules), "modules_with_snapshots": 0, "deps_matched": 0,
             "deps_no_central_data": 0, "deps_measured": 0, "deps_without_dates": 0}
    matched_by_key, gas = {}, set()
    for key, d in modules:
        d = Path(d)
        g1, before = read_snapshot(d / "dependency-tree-before.txt", scopes)
        g2, after = read_snapshot(d / "dependency-tree-after.txt", scopes)
        if not before or not after:
            continue
        own = g1 or g2
        matched = {ga: (before[ga], after[ga]) for ga in before
                   if ga in after and ga.split(":")[0] != own}
        matched_by_key[key] = matched
        stats["modules_with_snapshots"] += 1
        stats["deps_matched"] += len(matched)
        gas |= set(matched)

    client.prefetch_versions(sorted(gas))
    latest = {}
    for ga in gas:
        stable = [v for v in client.versions(ga) if is_stable(v)]
        if stable:
            latest[ga] = (newest(stable), stable)

    need = set()
    for matched in matched_by_key.values():
        for ga, (b, a) in matched.items():
            if ga in latest:
                lat = latest[ga][0]
                for v in (b, a):
                    if cmp_versions(v, lat) < 0:
                        need |= {(ga, v), (ga, lat)}
    client.prefetch_dates(sorted(need))

    results, rows = {}, []
    for key, matched in matched_by_key.items():
        m = {name: default for name, default in LAG_FIELDS}
        for ga, (b, a) in sorted(matched.items()):
            row = {"module_key": key, "dependency": ga, "before": b, "after": a}
            if ga not in latest:
                m["lag_unknown"] += 1
                stats["deps_no_central_data"] += 1
                row["status"] = "no_central_data"
                rows.append(row)
                continue
            lat, stable = latest[ga]
            m["lag_deps"] += 1
            stats["deps_measured"] += 1
            beh_b = sum(1 for v in stable if cmp_versions(v, b) > 0)
            beh_a = sum(1 for v in stable if cmp_versions(v, a) > 0)
            lvl_b, lvl_a = staleness(b, lat), staleness(a, lat)
            m["behind_before"] += beh_b
            m["behind_after"] += beh_a
            if lvl_b != "current":
                m[f"stale_{lvl_b}_before"] += 1
            if lvl_a != "current":
                m[f"stale_{lvl_a}_after"] += 1

            db, da = _days(client, ga, b, lat), _days(client, ga, a, lat)
            if db is None or da is None:
                stats["deps_without_dates"] += 1
            if db is not None and da is not None:
                m["lag_days_deps"] += 1
                m["lag_days_before"] += db
                m["lag_days_after"] += da

            policy = None
            if mode in ("major", "minor", "patch"):
                policy = policy_latest(b, stable, mode)
                if cmp_versions(a, policy) < 0:
                    m["not_at_policy_latest"] += 1

            row.update({"status": "ok", "latest_stable": lat, "policy_latest": policy or "",
                        "behind_before": beh_b, "behind_after": beh_a,
                        "level_before": lvl_b, "level_after": lvl_a,
                        "days_before": None if db is None else round(db, 1),
                        "days_after": None if da is None else round(da, 1)})
            rows.append(row)

        m["lag_days_before"] = round(m["lag_days_before"], 1)
        m["lag_days_after"] = round(m["lag_days_after"], 1)
        m["lag_days_reduction"] = round(m["lag_days_before"] - m["lag_days_after"], 1)
        m["behind_reduction"] = m["behind_before"] - m["behind_after"]
        results[key] = m
    stats["failures"] = dict(client.failures)
    stats["date_sources"] = dict(client.date_sources)
    return results, rows, stats


# ------------------------------------------------------------------------------ reporting

def write_detail(rows, path, names):
    """Per-dependency CSV. `names` maps module_key -> (repo, module)."""
    import csv
    cols = ["repo", "module", "dependency", "before", "after", "latest_stable", "policy_latest", "status",
            "behind_before", "behind_after", "level_before", "level_after", "days_before", "days_after"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            repo, module = names[r["module_key"]]
            w.writerow({**r, "repo": repo, "module": module})
    print(f"Per-dependency lag written to {path} ({len(rows)} rows)")


def print_summary(results, as_of):
    by_repo = {}
    for r in results:
        if getattr(r, "lag_deps", 0):
            by_repo.setdefault(r.repo, []).append(r)
    if not by_repo:
        print("\nTechnical lag: no data (missing dependency-tree snapshots or no Maven Central data).")
        return

    def agg(rs):
        n = sum(r.lag_deps for r in rs)
        nd = sum(r.lag_days_deps for r in rs)
        stale_b = sum(r.stale_major_before + r.stale_minor_before + r.stale_patch_before for r in rs)
        stale_a = sum(r.stale_major_after + r.stale_minor_after + r.stale_patch_after for r in rs)
        db = sum(r.lag_days_before for r in rs) / nd if nd else float("nan")
        da = sum(r.lag_days_after for r in rs) / nd if nd else float("nan")
        bb = sum(r.behind_before for r in rs) / n
        ba = sum(r.behind_after for r in rs) / n
        return n, db, da, bb, ba, stale_b / n * 100, stale_a / n * 100, sum(r.not_at_policy_latest for r in rs)

    print(f"\n{'=' * 104}")
    print(f"  Technical lag, original vs updated (mean per dependency; latest stable release as of {as_of[:10]})")
    print(f"{'=' * 104}")
    print(f"{'Repo':<28}{'Deps':>6}{'Days before':>13}{'Days after':>12}{'Releases behind':>20}{'Stale %':>16}{'Below policy':>13}")
    print(f"{'':<28}{'':>6}{'':>13}{'':>12}{'before -> after':>20}{'before -> after':>16}{'latest':>13}")
    print("-" * 104)
    for repo in sorted(by_repo):
        n, db, da, bb, ba, sb, sa, miss = agg(by_repo[repo])
        print(f"{repo:<28}{n:>6}{db:>13.0f}{da:>12.0f}{f'{bb:.1f} -> {ba:.1f}':>20}{f'{sb:.0f}% -> {sa:.0f}%':>16}{miss:>13}")
    n, db, da, bb, ba, sb, sa, miss = agg([r for rs in by_repo.values() for r in rs])
    print("-" * 104)
    print(f"{'ALL':<28}{n:>6}{db:>13.0f}{da:>12.0f}{f'{bb:.1f} -> {ba:.1f}':>20}{f'{sb:.0f}% -> {sa:.0f}%':>16}{miss:>13}")
    print(f"{'=' * 104}")
    print("  'Below policy latest' = dependencies whose updated version is below the newest one the range allowed.")


def print_coverage(stats):
    """Say what was and was not measured, so an all-zero result is explainable."""
    print("\n  Technical lag coverage")
    print(f"    modules matched to a buildcache folder : {stats['modules']}")
    print(f"    ... with before+after snapshots        : {stats['modules_with_snapshots']}")
    print(f"    dependencies present in both snapshots : {stats['deps_matched']}")
    print(f"    ... measured (release list from Central): {stats['deps_measured']}")
    print(f"    ... no Maven Central data              : {stats['deps_no_central_data']}")
    print(f"    ... measured but no release dates      : {stats['deps_without_dates']}  (version lag only)")
    if stats.get("date_sources"):
        print(f"    release dates obtained from            : {stats['date_sources']}")
    failures = stats.get("failures") or {}
    if failures:
        unresolved = stats["deps_no_central_data"] or stats["deps_without_dates"]
        print(f"    {'!! ' if unresolved else ''}requests that did not succeed (status: count): {failures}")
        hints = {429: "429 = Maven Central is rate limiting you: wait a while and rerun; what was fetched is cached.",
                 0: "0 = no network connection (proxy, VPN or DNS?).",
                 403: "403 = Maven Central refused the request from your network.",
                 405: "405 = HEAD requests are refused; the search index is used for release dates instead."}
        for code in failures:
            if code in hints:
                print(f"       {hints[code]}")
    if stats["modules"] and not stats["modules_with_snapshots"]:
        print("    !! no module had both dependency-tree-before.txt and dependency-tree-after.txt in its target/ folder")
    elif stats["deps_matched"] and not stats["deps_measured"]:
        print("    !! nothing could be looked up on Maven Central; run:  python3 scripts/technical_lag.py check "
              "org.apache.commons:commons-lang3 3.12.0")


# ------------------------------------------------------------------------------ build time (from the pipeline logs)

_TOTAL_TIME = re.compile(r"Total time:\s+(?:(\d+):(\d+)\s*h|(\d+):(\d+)\s*min|([\d.,]+)\s*s)\b")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def parse_maven_log(path):
    """(outcome, seconds) from a rebuild.sh log: Maven's final 'Total time' and BUILD SUCCESS/FAILURE."""
    text = _ANSI.sub("", Path(path).read_text(errors="replace"))
    if "BUILD SUCCESS" in text and "BUILD FAILURE" not in text:
        outcome = "success"
    elif "BUILD FAILURE" in text:
        outcome = "failure"
    else:
        outcome = "incomplete"
    seconds = None
    last = None
    for last in _TOTAL_TIME.finditer(text):
        pass
    if last:
        h, hm, m, ms, s_ = last.groups()
        if h is not None:                      # "03:58 h"   (hours:minutes)
            seconds = int(h) * 3600 + int(hm) * 60
        elif m is not None:                    # "15:37 min" (minutes:seconds)
            seconds = int(m) * 60 + int(ms)
        else:                                  # "26.337 s"
            seconds = float(s_.replace(",", "."))
    return outcome, seconds


def find_log(log_dir, repo):
    """The pipeline names its logs <repo>_<spec>.log and the spec starts with the repo name."""
    d = Path(log_dir) if log_dir else None
    if d is None or not d.is_dir():
        return None
    cands = sorted(p for p in d.glob("*.log") if p.stem.startswith(f"{repo}_{repo}"))
    if not cands:
        cands = sorted(d.glob(f"{repo}_*.log"))
    return cands[0] if cands else None


def build_info(log_dir, repo):
    log = find_log(log_dir, repo)
    if log is None:
        return None, None
    return parse_maven_log(log)


# ------------------------------------------------------------------------------ module/repo reports

def _module_dirs(buildcache):
    """{MODULE name: target dir} for every comparison report under a buildcache folder."""
    out = {}
    for report in sorted(Path(buildcache).rglob("dependency-comparison-report.txt")):
        for line in report.read_text(errors="replace").splitlines():
            if line.startswith("MODULE="):
                out.setdefault(line.split("=", 1)[1].strip(), report.parent)
                break
    return out


def repo_rows(results, mode, log_dir=None, baselines=None):
    """One row per repository: build time/outcome (from the logs) and mean technical lag."""
    baselines = baselines or {}
    by_repo = {}
    for r in results:
        by_repo.setdefault(r.repo, []).append(r)
    rows = []
    for repo, rs in sorted(by_repo.items()):
        outcome, seconds = build_info(log_dir, repo)
        row = {"repo": repo, "range": mode, "modules": len(rs),
               "build_outcome": outcome or "no_log", "build_time_s": "" if seconds is None else round(seconds, 1)}
        for name, d in baselines.items():
            b_out, b_sec = build_info(d, repo)
            row[f"{name}_build_time_s"] = "" if b_sec is None else round(b_sec, 1)
            both_ok = outcome == "success" and b_out == "success" and seconds is not None and b_sec
            row[f"overhead_vs_{name}_pct"] = round((seconds - b_sec) / b_sec * 100, 1) if both_ok else ""
        n = sum(getattr(r, "lag_deps", 0) for r in rs)
        nd = sum(getattr(r, "lag_days_deps", 0) for r in rs)
        row["deps_compared"] = n
        if n:
            stale_b = sum(r.stale_major_before + r.stale_minor_before + r.stale_patch_before for r in rs)
            stale_a = sum(r.stale_major_after + r.stale_minor_after + r.stale_patch_after for r in rs)
            row["mean_behind_before"] = round(sum(r.behind_before for r in rs) / n, 2)
            row["mean_behind_after"] = round(sum(r.behind_after for r in rs) / n, 2)
            row["stale_before_pct"] = round(stale_b / n * 100, 1)
            row["stale_after_pct"] = round(stale_a / n * 100, 1)
            row["not_at_policy_latest"] = sum(r.not_at_policy_latest for r in rs)
        if nd:
            row["mean_days_before"] = round(sum(r.lag_days_before for r in rs) / nd, 1)
            row["mean_days_after"] = round(sum(r.lag_days_after for r in rs) / nd, 1)
            row["mean_days_reduction"] = round(row["mean_days_before"] - row["mean_days_after"], 1)
        rows.append(row)
    return rows


def write_repo_rows(rows, path):
    import csv
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"Per-repository build time and lag written to {path} ({len(rows)} repos)")


def print_build_summary(rows):
    if not any(r["build_time_s"] != "" for r in rows):
        print("\nBuild time: no Maven 'Total time' found (are the log folders there?).")
        return
    extra = [k[:-len("_build_time_s")] for k in rows[0] if k.endswith("_build_time_s") and k != "build_time_s"]
    head = f"{'Repo':<28}{'Outcome':<11}{'Build time':>12}" + "".join(f"{n + ' time':>12}{'overhead':>10}" for n in extra)
    print(f"\n{'=' * len(head)}\n  Build time (Maven 'Total time' from the logs)\n{'=' * len(head)}\n{head}\n{'-' * len(head)}")

    def fmt(s):
        if s == "" or s is None:
            return "-"
        s = float(s)
        return f"{s:.0f}s" if s < 120 else (f"{s / 60:.1f}min" if s < 7200 else f"{s / 3600:.1f}h")

    for r in rows:
        line = f"{r['repo']:<28}{r['build_outcome']:<11}{fmt(r['build_time_s']):>12}"
        for n in extra:
            ov = r.get(f"overhead_vs_{n}_pct", "")
            line += f"{fmt(r.get(f'{n}_build_time_s')):>12}{(f'{ov:+.0f}%' if ov != '' else '-'):>10}"
        print(line)
    print("=" * len(head))
    print("  Includes dependency downloads and tests. Overhead is shown only when both builds succeeded.")


def enrich(results, mode, cache_path, refresh=False, workers=4, scopes=None, detail_path=None,
           root=None, buildcache=None, log_dir=None, baseline_dirs=None, repo_csv_path=None):
    """
    The one function the collector calls. It
      * measures technical lag (version and time) before vs after the update and fills the lag fields of the
        ModuleResult objects,
      * reads build outcome and build time from the pipeline logs (rq2_logs_<mode>/, plus rq1_logs/ and
        base_logs/ as baselines when they exist), and sets build_success from the log,
      * writes the per-dependency CSV and a per-repository CSV, and prints coverage and summaries.

    Each result's target folder is found by matching its repo and module against the comparison reports in
    <root>/repos/<repo>/RQ2<mode>/buildcache (or in `buildcache` when a single buildcache was given).
    """
    root = Path(root) if root is not None else None
    client = Central(cache_path, refresh=refresh, workers=workers)

    scanned = {}
    def dirs_for(repo):
        if buildcache is not None:
            key, bc = str(buildcache), Path(buildcache)
        elif root is not None:
            bc = root / "repos" / repo / f"RQ2{mode}" / "buildcache"
            key = str(bc)
        else:
            return {}
        if key not in scanned:
            scanned[key] = _module_dirs(bc) if bc.is_dir() else {}
        return scanned[key]

    modules = []
    for i, r in enumerate(results):
        d = getattr(r, "target_dir", None) or dirs_for(r.repo).get(r.module)
        if d:
            modules.append((i, d))

    metrics, rows, stats = compute_lag(client, modules, mode, scopes)
    for i, m in metrics.items():
        for name, value in m.items():
            setattr(results[i], name, value)
    if detail_path and rows:
        write_detail(rows, detail_path, {i: (results[i].repo, results[i].module) for i in metrics})
    print_coverage(stats)
    print_summary(results, client.as_of)

    # build time and outcome from the logs
    if log_dir is None and root is not None:
        log_dir = root / f"rq2_logs_{mode}"
    if baseline_dirs is None and root is not None:
        baseline_dirs = {n: root / d for n, d in (("rq1", "rq1_logs"), ("base", "base_logs")) if (root / d).is_dir()}
    repos = repo_rows(results, mode, log_dir, baseline_dirs)
    for r in results:
        outcome, _ = build_info(log_dir, r.repo)
        if outcome is not None:
            r.build_success = outcome == "success"
    print_build_summary(repos)
    if repo_csv_path is None and detail_path:
        repo_csv_path = Path(detail_path).with_name(Path(detail_path).name.replace("_lag_detail", "_repos"))
    if repo_csv_path and repos:
        write_repo_rows(repos, repo_csv_path)


# ------------------------------------------------------------------------------ command line

def _cmd_check(a):
    """Does Maven Central answer, and do we get release dates? Prints what the lag code would see."""
    ga, version = a.artifact, a.version
    g, ar = ga.split(":", 1)
    c = Central(a.cache or "/tmp/technical_lag_check.json", workers=1)
    print(f"Release list for {ga}:")
    vs = c._fetch_versions(g, ar)
    if not vs:
        print(f"  none (status/failures: {c.failures or 'not found'}) -> the lag code would report this artifact as unknown")
        return 1
    stable = [v for v in vs if is_stable(v)]
    latest = newest(stable) if stable else None
    print(f"  {len(vs)} versions, {len(stable)} stable; latest stable = {latest}")
    dates = {}
    for label, fn in (("HEAD Last-Modified of the .pom", c._date_from_pom), ("Maven Central search index", c._date_from_search)):
        for v in dict.fromkeys([version, latest]):
            if v:
                dates[(label, v)] = fn(g, ar, v)
    for (label, v), iso in dates.items():
        print(f"  {label:<32} {v:<14} -> {iso if iso else ('(none)' if iso == '' else 'REQUEST FAILED')}")
    ok = [iso for iso in dates.values() if iso]
    if not ok:
        print(f"\nNo release dates from either source; failures by status: {c.failures}")
        return 1
    d_used = next((dates[k] for k in dates if k[1] == version and dates[k]), None)
    d_lat = next((dates[k] for k in dates if k[1] == latest and dates[k]), None)
    if d_used and d_lat:
        days = (datetime.fromisoformat(d_lat) - datetime.fromisoformat(d_used)).days
        print(f"\nTime lag of {version} vs latest {latest}: {days} days; releases behind: "
              f"{sum(1 for v in stable if cmp_versions(v, version) > 0)}")
    return 0


def _cmd_build_times(a):
    root = Path(a.root).resolve()
    repos_dir = root / "repos"
    class R:
        def __init__(self, repo):
            self.repo = repo
    repos = [R(p.name) for p in sorted(repos_dir.iterdir()) if (p / f"RQ2{a.range}").is_dir()] if repos_dir.is_dir() else []
    baselines = {n: root / d for n, d in (("rq1", "rq1_logs"), ("base", "base_logs")) if (root / d).is_dir()}
    rows = repo_rows(repos, a.range, root / f"rq2_logs_{a.range}", baselines)
    print_build_summary(rows)
    if a.output:
        write_repo_rows(rows, a.output)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Technical lag and build time helpers.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="test the Maven Central lookups for one artifact")
    c.add_argument("artifact", help="groupId:artifactId")
    c.add_argument("version")
    c.add_argument("--cache")
    c.set_defaults(fn=_cmd_check)
    b = sub.add_parser("build-times", help="build outcome and time per repo from the pipeline logs (offline)")
    b.add_argument("--root", default=".")
    b.add_argument("--range", required=True, choices=["major", "minor", "patch"])
    b.add_argument("--output")
    b.set_defaults(fn=_cmd_build_times)
    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()