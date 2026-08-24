import json
import os
import subprocess
import unittest

from helpers import HOOKS, RepoCase

T = os.path.join(HOOKS, "tier.sh")


class TierCommand(RepoCase):
    def run_tier(self, *args, env=None):
        return subprocess.run(["bash", T, *args], cwd=self.repo, capture_output=True, text=True,
                              env={**os.environ, **(env or {})})

    def state(self):
        with open(os.path.join(self.repo, ".claude", "state", "agentkeel-tier.json")) as fh:
            return json.load(fh)

    def test_declare_writes_state(self):
        out = self.run_tier("medium", "json-flag")
        self.assertEqual(out.returncode, 0, out.stderr)
        s = self.state()
        self.assertEqual((s["tier"], s["slug"], s["branch"]), ("medium", "json-flag", "main"))
        self.assertGreater(s["expires_at"], s["declared_at"])

    def test_bad_tier_and_slug_rejected(self):
        self.assertEqual(self.run_tier("huge", "x").returncode, 2)
        self.assertEqual(self.run_tier("small", "Not Kebab").returncode, 2)
        self.assertEqual(self.run_tier("small").returncode, 2)

    def test_redeclare_recorded_and_noted(self):
        self.run_tier("small", "x")
        out = self.run_tier("large", "x")
        self.assertIn("re-declared small -> large", out.stderr)
        self.assertEqual(self.state()["previous"]["tier"], "small")

    def test_ttl_env(self):
        self.run_tier("small", "x", env={"AGENTKEEL_TIER_TTL_HOURS": "1"})
        s = self.state()
        self.assertEqual(s["expires_at"] - s["declared_at"], 3600)


if __name__ == "__main__":
    unittest.main()
