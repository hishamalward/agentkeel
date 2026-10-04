import unittest

from helpers import run_hook

H = "secret-guard.py"


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


class SecretGuard(unittest.TestCase):
    def assert_block(self, cmd):
        code, err = run_hook(H, bash(cmd))
        self.assertEqual(code, 2, cmd); self.assertIn("SECRET GUARD", err)

    def assert_allow(self, cmd):
        self.assertEqual(run_hook(H, bash(cmd))[0], 0, cmd)

    def test_env_files_blocked(self):
        for c in ("cat .env", "less apps/web/.env.local", "head -n 5 .env.production", "bat .env",
                  "cd apps/web && cat .env", "grep KEY .env"):
            self.assert_block(c)

    def test_example_env_allowed(self):
        for c in ("cat .env.example", "cat .env.sample", "cp .env.example .env", "ls -la .env"):
            self.assert_allow(c)

    def test_environment_dumps_blocked(self):
        for c in ("env", "printenv", "printenv | grep KEY", "printenv GITHUB_TOKEN"):
            self.assert_block(c)

    def test_env_used_not_shown_allowed(self):
        for c in ("printenv PATH", "env FOO=1 npm test", "source .env && npm test", ". .env; make",
                  "export $(cat .env | xargs) && npm run dev", "test -n \"$API_KEY\" && echo set"):
            self.assert_allow(c)

    def test_echo_of_secret_names_blocked(self):
        for c in ("echo $API_KEY", "echo \"${DB_PASSWORD}\"", "printf '%s' $GITHUB_TOKEN", "echo $AWS_SECRET_ACCESS_KEY"):
            self.assert_block(c)

    def test_echo_of_ordinary_vars_allowed(self):
        for c in ("echo $HOME", "echo $PATH", "echo done", "echo $AGENT_SLOT"):
            self.assert_allow(c)

    def test_git_show_of_env_blocked(self):
        for c in ("git show HEAD:.env", "git diff .env", "git log -p -- .env.local"):
            self.assert_block(c)

    def test_key_material_blocked(self):
        for c in ("cat ~/.ssh/id_rsa", "cat server.pem", "cat ~/.aws/credentials", "cat ~/.netrc"):
            self.assert_block(c)

    def test_inline_override_works_and_is_logged(self):
        import json, os, tempfile
        with tempfile.TemporaryDirectory() as home:
            env = {"AGENTKEEL_HOME": home}
            self.assertEqual(run_hook(H, bash("AGENTKEEL_SHOW_SECRETS=1 cat .env"), env=env)[0], 0)
            with open(os.path.join(home, "overrides.jsonl")) as fh:
                self.assertEqual(json.loads(fh.readline())["override"], "AGENTKEEL_SHOW_SECRETS")
            # the harness's own environment is not an override: it would apply silently to everything
            self.assertEqual(run_hook(H, bash("cat .env"), env={**env, "AGENTKEEL_SHOW_SECRETS": "1"})[0], 2)

    def test_other_tools_and_malformed_allowed(self):
        self.assertEqual(run_hook(H, {"tool_name": "Write", "tool_input": {"file_path": ".env"}})[0], 0)
        self.assertEqual(run_hook(H, "")[0], 0)


if __name__ == "__main__":
    unittest.main()
