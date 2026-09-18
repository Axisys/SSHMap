"""A single run of all the tests of SSHMap (parallel).

ROADMAP "Preparation for 1.0": the task "the single runner" (mandatory before v1.0) — executed
early in v0.9.9.2: smoke_test.py + all the regression_v*.py + check_i18n_keys.py are replaced
by a single run over the thematic files tests/test_*.py.

Run from the project root:
    python tests/run_all.py                 # all test_*.py + check_i18n_keys.py, the auto workers
    python tests/run_all.py --workers 8     # the number of the workers (1 = sequential)
    python tests/run_all.py keyring         # only the files whose name contains the substring
    python tests/run_all.py --fast          # the daily profile: without the tags slow/network
    python tests/run_all.py --tag network   # only the files with this tag
    python tests/run_all.py --failed-only   # only the files that failed in the previous run
    python tests/run_all.py --junit [PATH]  # the JUnit XML (by default test-results/junit.xml)

The schedule (v1.4.1): the workers default to the cores (capped by WORKER_CAP = 16) and the files
are submitted LONGEST FIRST — the run is WAIT-bound (a "slow" file spends 6–27 % of its wall time
on the CPU, the rest is Qt event-loop waiting), so the core count is the cheap win and the LPT
order shaves off the tail. Measured on 16 cores: 8 workers alphabetical = 20.2 s,
8 + longest-first = 17.7 s, 16 alphabetical = 13.9 s, 16 + longest-first = 11.2 s.

The tags of the files: the comment `# tags: slow network` in the header of the file (the first such
line in the first 40 lines). The known tags:
    slow    — deliberately long wait budgets/teardown (part of the specification, not a "slowdown");
    network — the file contains a real network section. The section is executed ONLY with
              the explicit choice of `--tag network`: the runner passes the tag to the child process
              through the env SSHMAP_TEST_TAGS, and the test switches to the real mode
              (for example, test_diagnostics.py — the real ping TEST-NET-1). The regular
              run of such a file — hermetic (without the network, fast).
--fast excludes the files with slow OR network; --tag NAME chooses the files with the tag NAME.

The artifacts of the run (gitignored, the test-results/ folder):
    junit.xml      — the JUnit report per file (CI: parsed by the standard tools);
    last_run.json  — the cache of the statuses for --failed-only (updated after each run).

Every file — a separate process (the isolation of HOME/offscreen does the bootstrap() inside).
The files are independent: the working folder per file is passed via SSHMAP_TEST_WORKDIR
(otherwise the parallel bootstrap() would clobber the shared _tmp_testdata), the run folder
is created in %TEMP% and removed on the finish.
exit code 0 = everything green; at the end — the table of the results (sorted by name).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
RESULTS_DIR = os.path.join(ROOT, "test-results")
JUNIT_DEFAULT = os.path.join(RESULTS_DIR, "junit.xml")
CACHE_PATH = os.path.join(RESULTS_DIR, "last_run.json")

# The auto workers: the machine cores, but no more than WORKER_CAP (each worker — a process with
# PySide6, ~110 MB peak). v1.4.1: the cap was 8, which left half of a 16-core machine idle — the
# suite is WAIT-bound, not CPU-bound (measured: a "slow" file spends 6–27 % of its wall time on the
# CPU, the rest is Qt event-loop waiting), so the processes oversubscribe the cores safely.
# Measured on 16 cores: 8 workers = 20.2 s wall, 16 = 13.9 s, 16 + the longest-first order below = 11.2 s.
WORKER_CAP = 16
# The tags excluded by the --fast profile.
FAST_EXCLUDE = {"slow", "network"}
TAG_LINE_RE = re.compile(r"^\s*#\s*tags:\s*(.+?)\s*$")
ALL_PASS_RE = re.compile(r"^ALL PASS \((\d+)\)")
FAILURES_RE = re.compile(r"^FAILURES \((\d+)\) of (\d+):")


def default_workers():
    try:
        n = os.cpu_count() or 4
    except Exception:
        n = 4
    return max(1, min(n, WORKER_CAP))


def read_tags(name):
    """The tags of the file: the first line `# tags: …` in the first 40 lines (without the import of the file)."""
    path = os.path.join(TESTS, name)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 40:
                    break
                m = TAG_LINE_RE.match(line)
                if m:
                    return {t for t in re.split(r"[,\s]+", m.group(1)) if t}
    except OSError:
        pass
    return set()


def collect_files(filter_sub=None):
    """The suite = all the test_*.py + check_i18n_keys.py.

    The other .py in the directory (run_all.py itself, the future meta-scripts) are NOT part of the suite —
    otherwise the runner would recursively start itself (each nested run
    collects the same list and spawns the next level).
    """
    files = []
    for name in sorted(os.listdir(TESTS)):
        if not name.endswith(".py"):
            continue
        if name.startswith("_"):
            continue  # _common.py — the harness, not a test
        if not (name.startswith("test_") or name == "check_i18n_keys.py"):
            continue  # run_all.py and other non-test scripts are not part of the suite
        if filter_sub and filter_sub not in name:
            continue
        files.append(name)
    return files


def run_one(name, workdir_root, tag_env=None):
    """One test file — a separate process; the output is captured (the parallelism).

    tag_env: the explicitly requested tag (--tag NAME) is passed into the env SSHMAP_TEST_TAGS —
    the files with the "opt-in" network sections (test_diagnostics.py) switch to it
    into the real mode; the regular run goes without the variable (hermetic).
    """
    env = dict(os.environ)
    env["SSHMAP_TEST_WORKDIR"] = os.path.join(workdir_root, name[:-3])
    if tag_env:
        env["SSHMAP_TEST_TAGS"] = tag_env
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, os.path.join(TESTS, name)],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    return name, proc.returncode, time.time() - t0, proc.stdout or "", proc.stderr or ""


def parse_summary(out):
    """(number of checks, number of failures) from the file's summary; we look for the last summary line.

    Formats: `ALL PASS (N)` / `FAILURES (F) of N:` (finish() in _common.py).
    Files without finish() (check_i18n_keys.py, a crash before the summary) — 1 "check" = the file itself.
    """
    for line in reversed((out or "").splitlines()):
        line = line.strip()
        m = ALL_PASS_RE.match(line)
        if m:
            return int(m.group(1)), 0
        m = FAILURES_RE.match(line)
        if m:
            return int(m.group(2)), int(m.group(1))
    return 1, None  # not to count the failures (a crash before the finish) — the exit code will decide


def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        runs = data.get("runs", {})
        return runs if isinstance(runs, dict) else {}
    except (OSError, ValueError):
        return {}


def order_files(files, cache=None):
    """The submission order: LONGEST FIRST (v1.4.1 — the LPT rule of the scheduling theory).

    The wall time of the run is set by the file that finishes LAST, so feeding the long
    files first lets them overlap with everything else instead of being started at the
    end by the only still-free worker. Measured on 16 cores: alphabetical = 13.9 s,
    longest-first = 11.2 s (and 17.7 vs 20.2 s with 8 workers).

    The expected duration comes from the cache of the previous run (test-results/last_run.json,
    written by main()); a file with no history is placed by its SIZE (bytes are a decent proxy
    for "this file builds a lot of Qt objects"), then by name for a stable order.
    """
    cache = load_cache() if cache is None else cache

    def expected(name):
        entry = cache.get(name)
        if isinstance(entry, dict) and entry.get("time_s") is not None:
            return float(entry["time_s"] or 0.0)
        try:
            return float(os.path.getsize(os.path.join(TESTS, name))) / 1024.0
        except OSError:
            return 0.0

    return sorted(files, key=lambda n: (-expected(n), n))


def save_cache(cache):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "runs": cache}, f, ensure_ascii=False, indent=2)


def write_junit(path, results):
    """JUnit XML per file: one testsuite per file, the time/status from the run."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    total_tests = 0
    total_failures = 0
    total_time = 0.0
    suites = []
    for name, code, dt, out, err in sorted(results):
        n_checks, n_fail = parse_summary(out)
        failed = code != 0
        if n_fail is None:
            n_fail = 1 if failed else 0
        total_tests += max(n_checks, 1)
        total_failures += n_fail
        total_time += dt
        parts = [f'    <testsuite name="{escape(name)}" tests="{max(n_checks, 1)}" '
                 f'failures="{n_fail}" errors="0" time="{dt:.2f}">']
        if failed:
            tail = (out or "")[-4000:]
            parts.append(
                f'      <testcase name="{escape(name)}" classname="sshmap">'
                f'\n        <failure message="exit code {code}"></failure>'
                f"\n      </testcase>")
            if tail.strip():
                parts.append(f"      <system-out>{escape(tail)}</system-out>")
            if (err or "").strip():
                parts.append(f"      <system-err>{escape(err[-2000:])}</system-err>")
        parts.append("    </testsuite>")
        suites.append("\n".join(parts))
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        + f'<testsuites name="sshmap" tests="{total_tests}" failures="{total_failures}" '
          + f'time="{total_time:.2f}">\n'
        + "\n".join(suites)
        + "\n</testsuites>\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


def parse_args(argv):
    """Parse the flags. Returns a dict or None (the error — the message is already printed)."""

    def err(msg):
        print(msg)
        print(__doc__.split("Run from the project root:")[1].split("\n\n")[0])
        return None

    opts = {"workers": None, "fast": False, "tag": None,
            "junit": JUNIT_DEFAULT, "failed_only": False, "filters": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--workers":
            i += 1
            if i >= len(argv):
                return err("--workers expects a number >= 1")
            try:
                opts["workers"] = max(1, int(argv[i]))
            except ValueError:
                return err(f"--workers: not a number — {argv[i]!r}")
        elif a == "--fast":
            opts["fast"] = True
        elif a == "--tag":
            i += 1
            if i >= len(argv):
                return err("--tag expects a tag name (e.g., network)")
            opts["tag"] = argv[i]
        elif a == "--junit":
            # --junit [PATH]: without a value — the default path; with one — your own.
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                opts["junit"] = argv[i + 1]
                i += 1
        elif a == "--failed-only":
            opts["failed_only"] = True
        elif a.startswith("--"):
            return err(f"unknown flag: {a}")
        else:
            opts["filters"].append(a)
        i += 1
    return opts


def main():
    opts = parse_args(sys.argv[1:])
    if opts is None:
        return 1

    try:
        # line_buffering: when redirected to a file (CI/log) the section headers
        # are written immediately, not together with the whole summary at the end (block-buffering).
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

    workers = opts["workers"] or default_workers()
    sub = opts["filters"][0] if opts["filters"] else None
    files = collect_files(sub)
    if not files:
        print(f"no test files match {sub!r}")
        return 1

    # Sampling by tags/profiles (the tags are read as text — without importing files).
    tags = {n: read_tags(n) for n in files}
    skipped = []
    if opts["fast"]:
        kept = [n for n in files if not (tags[n] & FAST_EXCLUDE)]
        skipped += [f"{n} ({', '.join(sorted(tags[n] & FAST_EXCLUDE))})"
                    for n in files if n not in set(kept)]
        files = kept
    if opts["tag"] is not None:
        kept = [n for n in files if opts["tag"] in tags[n]]
        skipped += [f"{n} (no tag {opts['tag']!r})" for n in files if n not in set(kept)]
        files = kept
    if opts["failed_only"]:
        cache = load_cache()
        if not cache:
            print("--failed-only: no cache of previous runs (test-results/last_run.json) — "
                  "running the full suite")
        else:
            failed = {f for f, r in cache.items() if isinstance(r, dict) and r.get("status") == "fail"}
            kept = [n for n in files if n in failed]
            if not kept:
                print(f"--failed-only: the previous run was all green ({len(files)} files) — nothing to run")
                return 0
            skipped += [f"{n} (was green)" for n in files if n not in set(kept)]
            files = kept
    if not files:
        print("no files left to run after filters/tags")
        return 1

    # v1.4.1: the LONGEST files go first (the LPT rule) — the tail of the schedule is what
    # the wall time really is. The artifacts below still report the results sorted by name.
    files = order_files(files)

    t_start = time.time()
    print(f"SSHMap test suite: {len(files)} file(s), workers={workers}"
          + (f" (filter: {sub})" if sub else "")
          + (" [--fast]" if opts["fast"] else "")
          + (f" [--tag {opts['tag']}]" if opts["tag"] is not None else "")
          + (" [--failed-only]" if opts["failed_only"] else ""))
    if skipped:
        print(f"skipped ({len(skipped)}): " + ", ".join(skipped))

    results = []
    run_root = tempfile.mkdtemp(prefix="sshmap_test_run_")
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(run_one, name, run_root, opts["tag"]) for name in files]
            for fut in as_completed(futures):
                name, code, dt, out, err = fut.result()
                results.append((name, code, dt, out, err))
                print(f"\n===== {name} =====")  # the sections — in completion order
                if out:
                    sys.stdout.write(out)
                if err:
                    sys.stdout.write("\n[stderr]\n" + err)
    finally:
        shutil.rmtree(run_root, ignore_errors=True)  # not leaving the working directories

    print("\n" + "=" * 64)
    print(f"{'file':<42} {'result':<10} time")
    failed = 0
    for name, code, dt, _, _ in sorted(results):
        status = "PASS" if code == 0 else f"FAIL({code})"
        if code != 0:
            failed += 1
        print(f"{name:<42} {status:<10} {dt:.1f}s")
    print("=" * 64)
    total = len(results)
    wall = time.time() - t_start
    if failed:
        print(f"{total - failed}/{total} files green — THERE ARE FAILURES (wall {wall:.1f}s)")
    else:
        print(f"{total}/{total} files green — ALL GREEN (wall {wall:.1f}s)")

    # Artifacts: JUnit XML + the status cache (for --failed-only).
    try:
        write_junit(opts["junit"], results)
        print(f"junit: {opts['junit']}")
    except OSError as e:
        print(f"junit: NOT written ({e})")
    cache = load_cache()
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    for name, code, dt, _, _ in results:
        cache[name] = {"status": "pass" if code == 0 else "fail",
                       "exit_code": code, "time_s": round(dt, 2), "ts": ts}
    try:
        save_cache(cache)
    except OSError as e:
        print(f"last_run.json: NOT written ({e})")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
