import os
import tempfile
import time
import unittest

from creative_factory.auth import AuthError, GoogleAuth
from creative_factory.jobs import JobStore, Worker


class Claims(unittest.TestCase):
    def setUp(self):
        self.auth = GoogleAuth("cid", "secret", "https://x.example", "appodeal.com")
        self.ok = {"aud": "cid", "email": "Pavel@Appodeal.com", "email_verified": "true", "hd": "appodeal.com"}

    def test_accepts_company_account(self):
        self.assertEqual(self.auth.check_claims(self.ok), "pavel@appodeal.com")

    def test_rejects_other_domain_unverified_and_wrong_audience(self):
        for change in ({"email": "a@gmail.com", "hd": ""}, {"email_verified": "false"}, {"aud": "other"},
                       {"email": "a@evil-appodeal.com"}, {"hd": "evil.com"}):
            with self.assertRaises(AuthError, msg=str(change)):
                self.auth.check_claims({**self.ok, **change})

    def test_login_url_carries_state_and_domain_hint(self):
        url, state = self.auth.login_url()
        self.assertIn("state=" + state, url)
        self.assertIn("hd=appodeal.com", url)


class Queue(unittest.TestCase):
    def test_runs_jobs_and_records_failure(self):
        with tempfile.TemporaryDirectory() as d:
            store = JobStore(os.path.join(d, "jobs.json"))

            def handler(spec, work, say):
                say("working")
                if spec.get("boom"):
                    raise ValueError("bad input")
                return {"ok": True}

            worker = Worker(store, handler, os.path.join(d, "work"))
            good = worker.submit("a@appodeal.com", {})
            bad = worker.submit("a@appodeal.com", {"boom": True})
            for _ in range(100):
                if all(store.get(j["id"])["status"] in ("done", "failed") for j in (good, bad)):
                    break
                time.sleep(0.05)
            self.assertEqual(store.get(good["id"])["status"], "done")
            self.assertEqual(store.get(good["id"])["steps"][0]["text"], "working")
            self.assertEqual(store.get(bad["id"])["status"], "failed")
            self.assertEqual(store.get(bad["id"])["error"], "bad input")

    def test_restart_marks_running_jobs_failed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "jobs.json")
            store = JobStore(path)
            job = store.create("a@appodeal.com", {})
            store.update(job["id"], status="running")
            self.assertEqual(JobStore(path).get(job["id"])["status"], "failed")


if __name__ == "__main__":
    unittest.main()
