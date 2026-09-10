"""Public source reporting and release-gate regressions."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class PublicSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.public = load("public_source_test", ROOT / "scripts/public_source.py")
        cls.package = load("package_test", ROOT / "scripts/package.py")

    def test_default_report_is_offline_and_explicit(self):
        def unexpected(*args, **kwargs):
            self.fail("default report attempted a network or Git call")

        lines, code = self.public.report(ROOT, runner=unexpected)
        self.assertEqual(code, 0)
        self.assertIn(self.public.PUBLIC_REPOSITORY_URL, lines[0])
        self.assertIn("latest not checked", lines[1])
        self.assertIn("local installation and source content only", lines[1])

    def check_runner(self, local, remote=None, remote_code=0, root=ROOT):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if "--show-toplevel" in command:
                return Result(stdout=str(root) + "\n")
            if "--verify" in command:
                return Result(stdout=local + "\n")
            return Result(remote_code, "" if remote is None else
                          remote + "\trefs/heads/main\n")

        return run, calls

    def test_equal_heads_are_current(self):
        head = "a" * 40
        runner, calls = self.check_runner(head, head)
        lines, code = self.public.report(ROOT, check_updates=True, runner=runner)
        self.assertEqual(code, 0)
        self.assertIn("current", lines[1])
        self.assertEqual(calls[-1][3], self.public.PUBLIC_REPOSITORY_URL)

    def test_different_heads_do_not_infer_ancestry(self):
        runner, _ = self.check_runner("a" * 40, "b" * 40)
        lines, code = self.public.report(ROOT, check_updates=True, runner=runner)
        self.assertEqual(code, 1)
        self.assertIn("differs", lines[1])
        self.assertIn("does not determine ancestry", lines[1])
        self.assertNotIn("behind", lines[1].lower())

    def test_remote_failure_is_unknown(self):
        runner, _ = self.check_runner("a" * 40, remote_code=2)
        lines, code = self.public.report(ROOT, check_updates=True, runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("unknown", lines[1])

    def test_timeout_and_malformed_remote_are_unknown(self):
        base, _ = self.check_runner("a" * 40)

        def timeout(command, **kwargs):
            if "ls-remote" in command:
                raise self.public.subprocess.TimeoutExpired(command, 15)
            return base(command, **kwargs)

        malformed, _ = self.check_runner("a" * 40, "b" * 41)
        for runner in (timeout, malformed):
            with self.subTest(runner=runner):
                lines, code = self.public.report(ROOT, check_updates=True,
                                                 runner=runner)
                self.assertEqual(code, 2)
                self.assertIn("unknown", lines[1])

    def test_nested_zip_does_not_masquerade_as_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / "unpacked" / "harness_codex"
            repo.mkdir(parents=True)
            runner, calls = self.check_runner("a" * 40, "a" * 40,
                                              root=Path(folder))
            lines, code = self.public.report(repo, check_updates=True, runner=runner)
        self.assertEqual(code, 2)
        self.assertEqual(len(calls), 1)
        self.assertIn("at this exact source root", lines[1])
        self.assertIn("download and extract a newer ZIP", lines[1])

    def test_package_gate_allows_only_the_exact_public_url_token(self):
        url = self.public.PUBLIC_REPOSITORY_URL
        self.assertFalse(self.package.has_personal_identifier('source = "' + url + '"'))
        self.assertFalse(self.package.has_personal_identifier("git clone " + url + ".git"))
        self.assertTrue(self.package.has_personal_identifier(url + "/issues"))
        self.assertTrue(self.package.has_personal_identifier(url + ".example"))
        self.assertTrue(self.package.has_personal_identifier(url + ".git.example"))
        self.assertTrue(self.package.has_personal_identifier("x" + url))
        self.assertTrue(self.package.has_personal_identifier("AR" + "CLIGHTS" + "TRVL"))

    def test_setup_check_hash_mode_does_not_add_source_reporting(self):
        checker = load("setup_check_public_test", ROOT / "scripts/setup-check.py")
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "bytes"
            target.write_bytes(b"test")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = checker.main(["--hash-file", str(target)])
        self.assertEqual(code, 0)
        self.assertEqual(len(output.getvalue().splitlines()), 1)

    def test_setup_check_forwards_update_flag_and_combines_exit_status(self):
        checker = load("setup_check_update_test", ROOT / "scripts/setup-check.py")
        with (mock.patch("scripts.community.findings", return_value=["local drift"]),
              mock.patch("scripts.community.public_source_report",
                         return_value=(["Public update status: unknown"], 2)) as report):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = checker.main(["--repo", str(ROOT), "--skip-hooks",
                                     "--check-updates"])
        self.assertEqual(code, 2)
        report.assert_called_once_with(ROOT, check_updates=True)
        self.assertIn("Drift: local drift", output.getvalue())
        self.assertIn("Public update status: unknown", output.getvalue())


if __name__ == "__main__":
    unittest.main()
