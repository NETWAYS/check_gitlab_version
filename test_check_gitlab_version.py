#!/usr/bin/env python3

import base64
import contextlib
import io
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import check_gitlab_version as plugin

PLUGIN = Path(__file__).resolve().parent / "check_gitlab_version.py"
TOKEN = "glpat-test-token-do-not-print"


def upstream_response(severity="success", latest="19.5.3", minor="19.5.3", newer=None, critical=False):
    return {
        "latest_stable_versions": newer or [],
        "latest_stable_version_of_minor": minor,
        "latest_version": latest,
        "severity": severity,
        "critical_vulnerability": critical,
        "details": "",
    }


class _LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer.server_bind() resolves the FQDN of the host, which stalls
        # the tests for seconds where reverse DNS is slow.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class FakeServer:
    """Local HTTP server that plays both the GitLab instance and version.gitlab.com."""

    def __init__(self):
        self.routes = {}
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # pylint: disable=invalid-name
                parsed = urllib.parse.urlsplit(self.path)
                server.requests.append((parsed.path, parsed.query, self.headers))
                status, headers, body, delay = server.routes.get(parsed.path, (404, {}, b'{"message":"404 Not Found"}', 0))
                if delay:
                    time.sleep(delay)
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # pylint: disable=redefined-builtin
                pass

        self.httpd = _LocalHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def route(self, path, status=200, body=None, headers=None, delay=0):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.routes[path] = (status, headers or {"Content-Type": "application/json"}, body or b"", delay)

    def metadata(self, version="19.5.3", enterprise=False):
        self.route("/api/v4/metadata", body={"version": version, "revision": "0d4c9a9a2fa", "enterprise": enterprise})

    def upstream(self, **kwargs):
        self.route("/check.json", body=upstream_response(**kwargs))

    def sent_version(self):
        query = next(q for p, q, _ in self.requests if p == "/check.json")
        info = urllib.parse.parse_qs(query)["gitlab_info"][0]
        return json.loads(base64.urlsafe_b64decode(info))

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def run_main(server, *extra):
    args = plugin.commandline(["-H", server.url, "-t", TOKEN,
                               "--version-check-url", f"{server.url}/check.json", "--timeout", "2", *extra])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        state = plugin.main(args)
    return state, out.getvalue()


class CommandlineTesting(unittest.TestCase):

    def test_arguments(self):
        args = plugin.commandline(["-H", "git.example.com", "--token", "secret", "--timeout", "5"])
        self.assertEqual(args.host, "git.example.com")
        self.assertEqual(args.token, "secret")
        self.assertEqual(args.timeout, 5)
        self.assertEqual(args.version_check_url, "https://version.gitlab.com/check.json")

    def test_token_from_environment(self):
        with mock.patch.dict(os.environ, {plugin.TOKEN_ENV: "from-env"}):
            args = plugin.commandline(["-H", "git.example.com"])
        self.assertEqual(args.token, "from-env")

    def test_token_argument_overrides_environment(self):
        with mock.patch.dict(os.environ, {plugin.TOKEN_ENV: "from-env"}):
            args = plugin.commandline(["-H", "git.example.com", "-t", "from-arg"])
        self.assertEqual(args.token, "from-arg")

    def test_usage_errors_are_unknown(self):
        cases = [
            [],
            ["-H", "git.example.com"],
            ["-H", "git.example.com", "-t", ""],
            ["-H", "git.example.com", "-t", "x", "--timeout", "0"],
            ["-H", "git.example.com", "-t", "x", "--timeout", "abc"],
            ["--unknown"],
        ]
        for argv in cases:
            with self.subTest(argv=argv), mock.patch.dict(os.environ, clear=True):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
                    plugin.commandline(argv)
                self.assertEqual(ctx.exception.code, 3)
                self.assertTrue(out.getvalue().startswith("[UNKNOWN] "), out.getvalue())

    def test_token_is_stripped(self):
        args = plugin.commandline(["-H", "git.example.com", "-t", " secret\n"])
        self.assertEqual(args.token, "secret")

    def test_token_with_control_characters_is_not_printed(self):
        for token in ["glpat-se\ncret", "glpat-se\rcret", "glpat-\x00secret", "glpat-säcret"]:
            with self.subTest(token=token):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
                    plugin.commandline(["-H", "git.example.com", "-t", token])
                self.assertEqual(ctx.exception.code, 3)
                self.assertTrue(out.getvalue().startswith("[UNKNOWN] "))
                self.assertNotIn("cret", out.getvalue())

    def test_base_url(self):
        self.assertEqual(plugin.base_url("git.example.com"), "https://git.example.com")
        self.assertEqual(plugin.base_url("git.example.com:8443"), "https://git.example.com:8443")
        self.assertEqual(plugin.base_url("https://example.com/gitlab/"), "https://example.com/gitlab")
        self.assertEqual(plugin.base_url("http://127.0.0.1:8080"), "http://127.0.0.1:8080")


class VersionTesting(unittest.TestCase):

    def test_parse_version(self):
        cases = {
            "19.5.3": "19.5.3",
            "v19.5.3": "19.5.3",
            "19.5.3-ee": "19.5.3",
            "19.6.0-pre": "19.6.0",
            "19.5.0-rc42": "19.5.0",
            "18.11.14": "18.11.14",
        }
        for version, expected in cases.items():
            with self.subTest(version=version):
                self.assertEqual(plugin.parse_version(version), expected)

    def test_parse_invalid_version(self):
        for version in ["", "19.5", "19", "garbage", "19.5.3 ", "19.5.x", "19.5.3-", "19.5.3\n", "19.5.3-ee\nfoo"]:
            with self.subTest(version=version), self.assertRaises(plugin.CheckError):
                plugin.parse_version(version)


class EvaluateTesting(unittest.TestCase):

    @staticmethod
    def installed(version="19.5.3", enterprise=False):
        return plugin.Installed(version=version, release=plugin.parse_version(version), enterprise=enterprise)

    @staticmethod
    def upstream(**kwargs):
        data = upstream_response(**kwargs)
        return plugin.Upstream(
            severity=data["severity"],
            critical_vulnerability=data["critical_vulnerability"],
            latest_version=data["latest_version"],
            latest_of_minor=data["latest_stable_version_of_minor"],
            newer_versions=data["latest_stable_versions"],
        )

    def test_up_to_date(self):
        state, text = plugin.evaluate(self.installed(), self.upstream())
        self.assertEqual(state, plugin.OK)
        self.assertEqual(text.splitlines()[0], "GitLab 19.5.3 is up to date (latest release: 19.5.3)")
        self.assertIn(" \\_ installed version: 19.5.3 (Community Edition)", text)
        self.assertIn(" \\_ critical vulnerability: no", text)
        self.assertNotIn("newer maintained releases", text)

    def test_patch_release_available(self):
        state, text = plugin.evaluate(self.installed("19.4.4"), self.upstream(
            severity="warning", minor="19.4.5", newer=["19.5.3", "19.4.5"]))
        self.assertEqual(state, plugin.WARNING)
        self.assertEqual(text.splitlines()[0],
                         "GitLab 19.4.4 is outdated, update available: "
                         "19.4.5 (latest patch release of 19.4), 19.5.3 (latest release)")
        self.assertIn(" \\_ newer maintained releases: 19.5.3, 19.4.5", text)

    def test_only_newer_minor_available(self):
        state, text = plugin.evaluate(self.installed("19.4.5"), self.upstream(
            severity="warning", minor="19.4.5", newer=["19.5.3"]))
        self.assertEqual(state, plugin.WARNING)
        self.assertEqual(text.splitlines()[0],
                         "GitLab 19.4.5 is outdated, update available: 19.5.3 (latest release)")

    def test_patch_of_latest_minor_available(self):
        state, text = plugin.evaluate(self.installed("19.5.2"), self.upstream(
            severity="warning", minor="19.5.3", newer=["19.5.3"]))
        self.assertEqual(state, plugin.WARNING)
        self.assertEqual(text.splitlines()[0],
                         "GitLab 19.5.2 is outdated, update available: 19.5.3 (latest patch release of 19.5)")

    def test_security_update(self):
        state, text = plugin.evaluate(self.installed("19.3.1"), self.upstream(
            severity="danger", minor="19.3.7", newer=["19.5.3", "19.4.5", "19.3.7"]))
        self.assertEqual(state, plugin.CRITICAL)
        self.assertEqual(text.splitlines()[0],
                         "GitLab 19.3.1 is vulnerable, security update required: "
                         "19.3.7 (latest patch release of 19.3), 19.5.3 (latest release)")

    def test_critical_vulnerability(self):
        state, text = plugin.evaluate(self.installed("18.11.3-ee", enterprise=True), self.upstream(
            severity="danger", minor="18.11.14", newer=["19.5.3", "19.4.5", "19.3.7"], critical=True))
        self.assertEqual(state, plugin.CRITICAL)
        self.assertTrue(text.startswith("GitLab 18.11.3-ee is affected by a critical vulnerability, update now: "
                                        "18.11.14 (latest patch release of 18.11)"))
        self.assertIn(" \\_ installed version: 18.11.3-ee (Enterprise Edition)", text)
        self.assertIn(" \\_ critical vulnerability: yes", text)

    def test_critical_vulnerability_overrides_severity(self):
        state, _ = plugin.evaluate(self.installed(), self.upstream(severity="warning", critical=True))
        self.assertEqual(state, plugin.CRITICAL)

    def test_newer_than_latest_release(self):
        state, text = plugin.evaluate(self.installed("19.6.0-pre"), self.upstream(minor=None))
        self.assertEqual(state, plugin.OK)
        self.assertEqual(text.splitlines()[0], "GitLab 19.6.0-pre is up to date (latest release: 19.5.3)")
        self.assertNotIn("latest patch release", text)

    def test_unknown_edition(self):
        _, text = plugin.evaluate(self.installed(enterprise=None), self.upstream())
        self.assertIn(" \\_ installed version: 19.5.3\n", text)


class MainTesting(unittest.TestCase):

    def test_ok(self):
        with FakeServer() as server:
            server.metadata("19.5.3")
            server.upstream()
            state, out = run_main(server)

        self.assertEqual(state, 0)
        self.assertTrue(out.startswith("[OK] GitLab 19.5.3 is up to date (latest release: 19.5.3)\n"))
        self.assertEqual(server.requests[0][2].get("PRIVATE-TOKEN"), TOKEN)

    def test_warning(self):
        with FakeServer() as server:
            server.metadata("19.4.4")
            server.upstream(severity="warning", minor="19.4.5", newer=["19.5.3", "19.4.5"])
            state, out = run_main(server)

        self.assertEqual(state, 1)
        self.assertTrue(out.startswith("[WARNING] GitLab 19.4.4 is outdated"))

    def test_critical(self):
        with FakeServer() as server:
            server.metadata("19.3.1")
            server.upstream(severity="danger", minor="19.3.7", newer=["19.5.3", "19.4.5", "19.3.7"], critical=True)
            state, out = run_main(server)

        self.assertEqual(state, 2)
        self.assertTrue(out.startswith("[CRITICAL] GitLab 19.3.1 is affected by a critical vulnerability"))

    def test_sends_release_without_suffix_and_no_token_upstream(self):
        with FakeServer() as server:
            server.metadata("19.5.3-ee", enterprise=True)
            server.upstream()
            run_main(server)

        self.assertEqual(server.sent_version(), {"version": "19.5.3"})
        upstream_headers = next(h for p, _, h in server.requests if p == "/check.json")
        self.assertNotIn("PRIVATE-TOKEN", upstream_headers)
        self.assertTrue(upstream_headers["User-Agent"].startswith("check_gitlab_version/"))

    def test_critical_vulnerability_as_string(self):
        with FakeServer() as server:
            server.metadata()
            body = upstream_response()
            body["critical_vulnerability"] = "true"
            server.route("/check.json", body=body)
            state, _ = run_main(server)

        self.assertEqual(state, 2)

    def test_version_check_url_with_query(self):
        with FakeServer() as server:
            server.metadata()
            server.upstream()
            args = plugin.commandline(["-H", server.url, "-t", TOKEN, "--version-check-url",
                                       f"{server.url}/check.json?source=test"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(plugin.main(args), 0)
            query = urllib.parse.parse_qs(server.requests[1][1])

        self.assertEqual(query["source"], ["test"])
        self.assertIn("gitlab_info", query)

    def test_base_url_with_path(self):
        with FakeServer() as server:
            server.route("/gitlab/api/v4/metadata", body={"version": "19.5.3"})
            server.upstream()
            args = plugin.commandline(["-H", f"{server.url}/gitlab/", "-t", TOKEN,
                                       "--version-check-url", f"{server.url}/check.json"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(plugin.main(args), 0)


class ErrorTesting(unittest.TestCase):

    def assert_unknown(self, server, expected):
        state, out = run_main(server)
        self.assertEqual(state, 3)
        self.assertTrue(out.startswith("[UNKNOWN] "), out)
        self.assertIn(expected, out)
        self.assertNotIn(TOKEN, out)
        return out

    def test_unauthorized(self):
        with FakeServer() as server:
            server.route("/api/v4/metadata", 401, {"message": "401 Unauthorized"})
            self.assert_unknown(server, "/api/v4/metadata returned HTTP 401: 401 Unauthorized")

    def test_insufficient_scope(self):
        with FakeServer() as server:
            server.route("/api/v4/metadata", 403, {
                "error": "insufficient_scope",
                "error_description": "The request requires higher privileges than provided by the access token.",
            })
            self.assert_unknown(server, "HTTP 403: The request requires higher privileges")

    def test_server_error_with_html_body(self):
        with FakeServer() as server:
            server.route("/api/v4/metadata", 502, b"<html>" + b"x" * 5000 + b"</html>", {"Content-Type": "text/html"})
            out = self.assert_unknown(server, "returned HTTP 502")
            self.assertNotIn("<html>", out)

    def test_error_body_without_message(self):
        for body in ([{"message": "x"}], {"status": "failed"}, {"message": ""}):
            with self.subTest(body=body), FakeServer() as server:
                server.route("/api/v4/metadata", 500, body)
                out = self.assert_unknown(server, "/api/v4/metadata returned HTTP 500\n")
                self.assertNotIn("failed", out)

    def test_long_error_message_is_truncated(self):
        with FakeServer() as server:
            server.route("/api/v4/metadata", 500, {"message": "m" * 1000})
            out = self.assert_unknown(server, "returned HTTP 500: ")
            self.assertLess(len(out), 400)

    def test_redirect_is_not_followed(self):
        with FakeServer() as server:
            server.route("/api/v4/metadata", 302, b"", {"Location": f"{server.url}/elsewhere"})
            server.route("/elsewhere", body={"version": "19.5.3"})
            self.assert_unknown(server, f"redirects to {server.url}/elsewhere (HTTP 302)")
            self.assertNotIn("/elsewhere", [p for p, _, _ in server.requests])

    def test_invalid_json(self):
        with FakeServer() as server:
            server.route("/api/v4/metadata", 200, b"<html>login</html>", {"Content-Type": "text/html"})
            self.assert_unknown(server, "/api/v4/metadata is not valid JSON")

    def test_missing_version(self):
        for body in ({"revision": "abc"}, {"version": None}, [], "19.5.3"):
            with self.subTest(body=body), FakeServer() as server:
                server.route("/api/v4/metadata", body=json.dumps(body).encode())
                self.assert_unknown(server, "no version in the response")

    def test_unparsable_version(self):
        with FakeServer() as server:
            server.route("/api/v4/metadata", body={"version": "nightly"})
            self.assert_unknown(server, "cannot parse GitLab version 'nightly'")

    def test_oversized_response(self):
        with FakeServer() as server:
            server.route("/api/v4/metadata", body=b'"' + b"a" * (plugin.MAX_RESPONSE_BYTES + 10) + b'"')
            self.assert_unknown(server, "exceeds")

    def test_timeout(self):
        with FakeServer() as server:
            server.route("/api/v4/metadata", body={"version": "19.5.3"}, delay=3)
            started = time.monotonic()
            self.assert_unknown(server, "timed out")
            self.assertLess(time.monotonic() - started, 3)

    def test_connection_refused(self):
        with FakeServer() as server:
            url = server.url
        args = plugin.commandline(["-H", url, "-t", TOKEN, "--timeout", "2"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            state = plugin.main(args)
        self.assertEqual(state, 3)
        self.assertIn(f"cannot connect to {url}/api/v4/metadata", out.getvalue())

    def test_upstream_unavailable(self):
        with FakeServer() as server:
            server.metadata()
            server.route("/check.json", 503, b"Service Unavailable", {"Content-Type": "text/plain"})
            self.assert_unknown(server, "/check.json returned HTTP 503")

    def test_upstream_invalid_responses(self):
        cases = {
            "unknown severity": {**upstream_response(), "severity": "info"},
            "unknown severity None": {k: v for k, v in upstream_response().items() if k != "severity"},
            "no latest version": {**upstream_response(), "latest_version": None},
            "invalid latest_stable_version_of_minor": {**upstream_response(), "latest_stable_version_of_minor": 19},
            "invalid latest_stable_versions": {**upstream_response(), "latest_stable_versions": "19.5.3"},
            "unexpected response": ["19.5.3"],
        }
        for expected, body in cases.items():
            with self.subTest(expected=expected), FakeServer() as server:
                server.metadata()
                server.route("/check.json", body=json.dumps(body).encode())
                self.assert_unknown(server, expected)


class ScriptTesting(unittest.TestCase):
    """Runs the plugin as Icinga does: a separate process, exit code and stdout."""

    def run_plugin(self, *args, env=None):
        environment = {k: v for k, v in os.environ.items() if k != plugin.TOKEN_ENV}
        environment.update(env or {})
        return subprocess.run([sys.executable, str(PLUGIN), *args], capture_output=True, text=True,
                              env=environment, timeout=30, check=False)

    def test_version(self):
        result = self.run_plugin("--version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), plugin.__version__)

    def test_invalid_token_from_environment_is_not_printed(self):
        result = self.run_plugin("-H", "127.0.0.1:1", env={plugin.TOKEN_ENV: "glpat-se\ncret"})
        self.assertEqual(result.returncode, 3)
        self.assertTrue(result.stdout.startswith("[UNKNOWN] "))
        self.assertNotIn("cret", result.stdout + result.stderr)

    def test_usage_error(self):
        result = self.run_plugin("-H", "git.example.com")
        self.assertEqual(result.returncode, 3)
        self.assertTrue(result.stdout.startswith("[UNKNOWN] check_gitlab_version.py: error: a token is required"))
        self.assertEqual(result.stderr, "")

    def test_token_from_environment(self):
        with FakeServer() as server:
            server.metadata("19.4.4")
            server.upstream(severity="warning", minor="19.4.5", newer=["19.5.3", "19.4.5"])
            result = self.run_plugin("-H", server.url, "--version-check-url", f"{server.url}/check.json",
                                     env={plugin.TOKEN_ENV: TOKEN})

        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("[WARNING] GitLab 19.4.4 is outdated"))
        self.assertNotIn(TOKEN, result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertEqual(server.requests[0][2].get("PRIVATE-TOKEN"), TOKEN)


if __name__ == "__main__":
    unittest.main()
