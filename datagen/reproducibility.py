"""Step 10 - regenerate twice with the same seed (in separate processes with different PYTHONHASHSEED) and compare
row counts + SHA-256 checksums of every exported file.  A run with another seed is included as a negative control.

    python -m datagen.reproducibility --tickets 5000 --articles 200 --messages 20000
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

from edu_support import config as C


def run_once(out, tickets, articles, messages, seed, hashseed):
    env = dict(os.environ, PYTHONHASHSEED=str(hashseed))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.run([sys.executable, "-m", "datagen.generate", "--out", out, "--tickets", str(tickets), "--articles", str(articles),
                    "--messages", str(messages), "--seed", str(seed)], check=True, cwd=root, env=env, stdout=subprocess.DEVNULL)
    with open(os.path.join(out, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickets", type=int, default=C.DEFAULT_TICKETS)
    ap.add_argument("--articles", type=int, default=C.DEFAULT_ARTICLES)
    ap.add_argument("--messages", type=int, default=C.DEFAULT_MESSAGES)
    ap.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
    ap.add_argument("--report", default=None, help="optional path of a markdown report")
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        runs = []
        for i, (seed, hs) in enumerate([(a.seed, 1), (a.seed, 777), (a.seed + 1, 1)]):
            runs.append(run_once(os.path.join(tmp, "run%d" % i), a.tickets, a.articles, a.messages, seed, hs))
    same_counts = runs[0]["row_counts"] == runs[1]["row_counts"]
    mismatched = [f for f in runs[0]["sha256"] if runs[0]["sha256"][f] != runs[1]["sha256"].get(f)]
    control_diff = [f for f in runs[0]["sha256"] if runs[0]["sha256"][f] != runs[2]["sha256"].get(f)]
    ok = same_counts and not mismatched and bool(control_diff)
    lines = ["# Reproducibility report", "",
             "Seed **%d**, scale: %d tickets / %d articles / %d messages." % (a.seed, a.tickets, a.articles, a.messages), "",
             "| run | seed | PYTHONHASHSEED | tickets | messages | files hashed |", "|---|---:|---:|---:|---:|---:|"]
    for i, (r, hs) in enumerate(zip(runs, [1, 777, 1])):
        lines.append("| %d | %d | %d | %d | %d | %d |" % (i + 1, r["seed"], hs, r["row_counts"]["ticket"], r["row_counts"]["message"], len(r["sha256"])))
    lines += ["", "* Row counts identical for run 1 vs run 2: **%s**" % same_counts,
              "* Files whose SHA-256 differs between run 1 and run 2: **%d** of %d" % (len(mismatched), len(runs[0]["sha256"])),
              "* Negative control (seed+1) changes %d of %d files, so the checksums are sensitive." % (len(control_diff), len(runs[0]["sha256"])),
              "", "**Result: %s**" % ("REPRODUCIBLE" if ok else "NOT REPRODUCIBLE"), "",
              "Checksums of run 1 (excerpt):", ""]
    for f in sorted(runs[0]["sha256"])[:12]:
        lines.append("* `%s` `%s`" % (f, runs[0]["sha256"][f][:16]))
    text = "\n".join(lines) + "\n"
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
