import os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cache = {}


def small_dataset(tickets=400, articles=60, messages=1600, seed=20261022):
    """Generate (once per test run) a small dataset into a temp dir and return its path."""
    key = (tickets, articles, messages, seed)
    if key not in _cache:
        d = tempfile.mkdtemp(prefix="edusupport_")
        subprocess.run([sys.executable, "-m", "datagen.generate", "--out", d, "--tickets", str(tickets), "--articles", str(articles),
                        "--messages", str(messages), "--seed", str(seed)], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
        _cache[key] = d
    return _cache[key]


def cleanup():
    for d in _cache.values():
        shutil.rmtree(d, ignore_errors=True)
