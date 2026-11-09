#!/usr/bin/env python3
"""
technical_lag.py — technical lag before vs after the dependency update (RQ2).

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

import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import cmp_to_key
from pathlib import Path

CENTRAL = "https://repo.maven.apache.org/maven2"

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

def _http(url, method="GET", retries=4):
    """(status, headers, body). 200 and 404 are definitive; anything else is transient."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, method=method,
                                         headers={"User-Agent": "technical-lag-collector/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, dict(r.headers), (r.read() if method == "GET" else b"")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, {}, b""
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            return e.code, {}, b""
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            return 0, {}, b""
    return 0, {}, b""


class Central:
    """Release lists and release dates from Maven Central, cached on disk."""

    def __init__(self, cache_path, refresh=False, workers=4, delay=0.05):
        self.path = Path(cache_path)
        self.workers, self.delay = workers, delay
        self.lock = threading.Lock()
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

    # network (overridden in tests)
    def _fetch_versions(self, g, a):
        status, _, body = _http(f"{CENTRAL}/{g.replace('.', '/')}/{a}/maven-metadata.xml")
        time.sleep(self.delay)
        if status == 200:
            root = ET.fromstring(body)
            return [e.text.strip() for e in root.findall("./versioning/versions/version") if e.text]
        return [] if status == 404 else None       # None = transient failure, do not cache

    def _fetch_date(self, g, a, v):
        status, headers, _ = _http(f"{CENTRAL}/{g.replace('.', '/')}/{a}/{v}/{a}-{v}.pom", method="HEAD")
        time.sleep(self.delay)
        if status == 200:
            lm = {k.lower(): val for k, val in headers.items()}.get("last-modified")
            if lm:
                return parsedate_to_datetime(lm).astimezone(timezone.utc).isoformat()
            return ""
        return "" if status == 404 else None

    # cached access
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
    modules: list of (key, target_dir). Returns ({key: metrics}, detail_rows).
    mode: 'major' | 'minor' | 'patch' | anything else (no range policy check).
    """
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
                row["status"] = "no_central_data"
                rows.append(row)
                continue
            lat, stable = latest[ga]
            m["lag_deps"] += 1
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
    return results, rows


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


def _module_dirs(buildcache):
    """{MODULE name: target dir} for every comparison report under a buildcache folder."""
    out = {}
    for report in sorted(Path(buildcache).rglob("dependency-comparison-report.txt")):
        for line in report.read_text(errors="replace").splitlines():
            if line.startswith("MODULE="):
                out.setdefault(line.split("=", 1)[1].strip(), report.parent)
                break
    return out


def enrich(results, mode, cache_path, refresh=False, workers=4, scopes=None, detail_path=None,
           root=None, buildcache=None):
    """
    Fill the LAG_FIELDS of the ModuleResult objects, write the per-dependency CSV and print the summary.
    This is the only function the collector needs to call.

    Each result's target folder is found by matching its repo and module against the comparison reports in
    <root>/repos/<repo>/RQ2<mode>/buildcache (or in `buildcache` when a single buildcache was given), so the
    collector does not have to remember where a result came from.
    """
    client = Central(cache_path, refresh=refresh, workers=workers)

    scanned = {}
    def dirs_for(repo):
        if buildcache is not None:
            key = str(buildcache)
            bc = Path(buildcache)
        elif root is not None:
            bc = Path(root) / "repos" / repo / f"RQ2{mode}" / "buildcache"
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
    if not modules:
        print("  [lag] could not match any result to a buildcache folder; nothing measured", file=sys.stderr)

    metrics, rows = compute_lag(client, modules, mode, scopes)
    for i, m in metrics.items():
        for name, value in m.items():
            setattr(results[i], name, value)
    if detail_path and rows:
        write_detail(rows, detail_path, {i: (results[i].repo, results[i].module) for i in metrics})
    print_summary(results, client.as_of)