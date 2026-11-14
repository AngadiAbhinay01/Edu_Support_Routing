import csv, json, os, subprocess, sys, unittest
from . import support
from edu_support import config as C


def rows(d, t):
    with open(os.path.join(d, "csv", t + ".csv"), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Generator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = support.small_dataset()

    def test_exact_volumes(self):
        self.assertEqual(len(rows(self.d, "ticket")), 400)
        self.assertEqual(len(rows(self.d, "knowledge_article")), 60)
        self.assertEqual(len(rows(self.d, "message")), 1600)

    def test_id_formats(self):
        import re
        for t in rows(self.d, "ticket"):
            self.assertRegex(t["ticket_id"], r"^TKT-2026-\d{6}$")
        for m in rows(self.d, "message"):
            self.assertRegex(m["message_id"], r"^MSG-TKT-2026-\d{6}-\d{3}$")
        for a in rows(self.d, "knowledge_article"):
            self.assertRegex(a["article_id"], r"^KB-\d{6}$")
        for p in rows(self.d, "policy_document"):
            self.assertRegex(p["policy_id"], r"^POL-[A-Z]+-2026-\d{3}$")
        for s in rows(self.d, "sla"):
            self.assertEqual(s["sla_id"], "SLA-" + s["ticket_id"])

    def test_five_anomaly_types_labelled(self):
        gt = rows(self.d, "../ground_truth/ground_truth_anomalies") if False else None
        with open(os.path.join(self.d, "ground_truth", "ground_truth_anomalies.csv"), encoding="utf-8", newline="") as fh:
            an = list(csv.DictReader(fh))
        self.assertEqual({a["issue_type"] for a in an}, {"EXPIRED_POLICY_CITATION", "UNAUTHORIZED_ROUTING", "UNSUPPORTED_CLAIM", "SLA_IGNORES_BUSINESS_HOURS", "ESCALATION_NOT_TRIGGERED"})

    def test_ground_truth_not_in_input_tables(self):
        for f in os.listdir(os.path.join(self.d, "csv")):
            with open(os.path.join(self.d, "csv", f), encoding="utf-8") as fh:
                head = fh.readline().lower()
            for bad in ("ground_truth", "injected", "anomaly", "expected_"):
                self.assertNotIn(bad, head, f)

    def test_validator_passes_all_checks(self):
        r = subprocess.run([sys.executable, "-m", "datagen.validate", "--data", self.d], cwd=support.ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-800:])

    def test_same_seed_same_checksums_different_seed_differs(self):
        import tempfile, shutil
        other = tempfile.mkdtemp()
        again = tempfile.mkdtemp()
        try:
            for out, seed in ((again, 20261022), (other, 7)):
                subprocess.run([sys.executable, "-m", "datagen.generate", "--out", out, "--tickets", "400", "--articles", "60", "--messages", "1600", "--seed", str(seed)],
                               check=True, cwd=support.ROOT, stdout=subprocess.DEVNULL, env=dict(os.environ, PYTHONHASHSEED="123"))
            def m(d):
                with open(os.path.join(d, "manifest.json"), encoding="utf-8") as fh:
                    j = json.load(fh)
                return {"rows": j["row_counts"], "sha": j["sha256"]}
            a, b, c = m(self.d), m(again), m(other)
            self.assertEqual(a, b)
            self.assertNotEqual(a["sha"], c["sha"])
        finally:
            shutil.rmtree(other, ignore_errors=True); shutil.rmtree(again, ignore_errors=True)

    def test_rejects_too_few_articles(self):
        r = subprocess.run([sys.executable, "-m", "datagen.generate", "--out", self.d + "_x", "--articles", "10"], cwd=support.ROOT, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
