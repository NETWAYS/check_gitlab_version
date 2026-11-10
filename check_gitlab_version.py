#! /usr/bin/env python3

# MIT License
#
# Copyright (c) 2021 NETWAYS GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Icinga check plugin that compares the version of a self-managed GitLab
instance against the upstream releases.

The installed version is read from the GitLab API (/api/v4/metadata). It is
then rated by the GitLab version check service (version.gitlab.com), the same
service GitLab uses for the version badge in its Admin area.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

__version__ = "0.2.0"

OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3
STATE_NAMES = {OK: "OK", WARNING: "WARNING", CRITICAL: "CRITICAL", UNKNOWN: "UNKNOWN"}

DEFAULT_VERSION_CHECK_URL = "https://version.gitlab.com/check.json"
DEFAULT_TIMEOUT = 10
TOKEN_ENV = "CHECK_GITLAB_VERSION_TOKEN"
USER_AGENT = f"check_gitlab_version/{__version__}"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_DETAIL_LENGTH = 200

# 19.5.3, v19.5.3, 19.5.3-ee, 19.6.0-pre, 19.5.0-rc42
VERSION_PATTERN = re.compile(r"v?(?P<release>\d+\.\d+\.\d+)(?:-[0-9A-Za-z.-]+)?")

# Printable ASCII, as GitLab tokens are
TOKEN_PATTERN = re.compile(r"[\x21-\x7e]+")

SEVERITIES = ("success", "warning", "danger")


class CheckError(Exception):
    """An error that makes the check result UNKNOWN."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    # Redirects are never followed: urllib would send the token header to the
    # redirect target, and neither API is expected to redirect.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirectHandler)


@dataclass(frozen=True)
class Installed:
    version: str
    release: str
    enterprise: bool | None

    @property
    def edition(self) -> str:
        if self.enterprise is None:
            return ""
        return "Enterprise Edition" if self.enterprise else "Community Edition"


@dataclass(frozen=True)
class Upstream:
    severity: str
    critical_vulnerability: bool
    latest_version: str
    latest_of_minor: str | None
    newer_versions: list[str]


class _ArgumentParser(argparse.ArgumentParser):
    # Usage errors must result in UNKNOWN with the state in the first line;
    # argparse exits with 2 (CRITICAL).
    def error(self, message):
        print(f"[UNKNOWN] {self.prog}: error: {message}")
        self.print_usage(sys.stdout)
        sys.exit(UNKNOWN)


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1: {value!r}")
    return number


def commandline(args: list[str]) -> argparse.Namespace:
    parser = _ArgumentParser(
        prog="check_gitlab_version.py",
        description="Compare the version of a self-managed GitLab instance against the upstream releases.",
        epilog=f"Prefer the environment variable {TOKEN_ENV} over --token, "
        "it keeps the token out of the process list.",
    )

    parser.add_argument("-V", "--version", action="version", version=__version__)
    parser.add_argument("-H", "--host", required=True,
                        help="GitLab host name (uses https://<host>) or base URL, e.g. https://example.com/gitlab")
    parser.add_argument("-t", "--token", default=os.environ.get(TOKEN_ENV),
                        help=f"GitLab access token with the ai_features or read_user scope (default: ${TOKEN_ENV})")
    parser.add_argument("--version-check-url", default=DEFAULT_VERSION_CHECK_URL,
                        help="URL of the GitLab version check service (default: %(default)s)")
    parser.add_argument("--timeout", type=_positive_int, default=DEFAULT_TIMEOUT,
                        help="timeout in seconds for each of the two HTTP requests (default: %(default)s)")

    parsed = parser.parse_args(args)
    parsed.token = (parsed.token or "").strip()

    if not parsed.token:
        parser.error(f"a token is required, set {TOKEN_ENV} or use --token")
    # http.client rejects such header values with an error message that
    # contains the value, which would print the token.
    if not TOKEN_PATTERN.fullmatch(parsed.token):
        parser.error("the token contains characters that are not allowed in an HTTP header")

    return parsed


def base_url(host: str) -> str:
    if "://" in host:
        return host.rstrip("/")
    return f"https://{host.strip('/')}"


def _error_detail(body: bytes) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    for key in ("message", "error_description", "error"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value[:MAX_DETAIL_LENGTH]
    return ""


def fetch_json(url: str, headers: dict[str, str], timeout: int) -> object:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT, **headers}
    )

    # Messages name the URL without its query string
    name = url.split("?", 1)[0]

    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        with error:
            if 300 <= error.code < 400:
                location = error.headers.get("Location", "an unknown location")
                raise CheckError(f"{name} redirects to {location} (HTTP {error.code}), "
                                 "redirects are not followed") from None
            detail = _error_detail(error.read(MAX_RESPONSE_BYTES))
            raise CheckError(f"{name} returned HTTP {error.code}" + (f": {detail}" if detail else "")) from None
    except urllib.error.URLError as error:
        raise CheckError(f"cannot connect to {name}: {error.reason}") from None
    except (OSError, http.client.HTTPException) as error:
        # Timeouts and broken connections while reading the response
        raise CheckError(f"request to {name} failed: {str(error) or type(error).__name__}") from None

    if len(body) > MAX_RESPONSE_BYTES:
        raise CheckError(f"response from {name} exceeds {MAX_RESPONSE_BYTES} bytes")

    try:
        return json.loads(body)
    except ValueError:
        raise CheckError(f"response from {name} is not valid JSON") from None


def parse_version(version: str) -> str:
    """Return the release part of a GitLab version, e.g. 19.5.3 for 19.5.3-ee."""
    match = VERSION_PATTERN.fullmatch(version)
    if not match:
        raise CheckError(f"cannot parse GitLab version {version!r}")
    return match.group("release")


def get_installed(url: str, token: str, timeout: int) -> Installed:
    data = fetch_json(f"{url}/api/v4/metadata", {"PRIVATE-TOKEN": token}, timeout)

    if not isinstance(data, dict) or not isinstance(data.get("version"), str):
        raise CheckError(f"no version in the response from {url}/api/v4/metadata")

    enterprise = data.get("enterprise")
    return Installed(
        version=data["version"],
        release=parse_version(data["version"]),
        enterprise=enterprise if isinstance(enterprise, bool) else None,
    )


def get_upstream(check_url: str, release: str, timeout: int) -> Upstream:
    # Same request as the version check of GitLab itself (VersionCheckCronWorker).
    # The plain release is sent: version.gitlab.com mis-rates suffixes like -ee.
    gitlab_info = base64.urlsafe_b64encode(json.dumps({"version": release}).encode()).decode()
    separator = "&" if urllib.parse.urlsplit(check_url).query else "?"
    data = fetch_json(f"{check_url}{separator}{urllib.parse.urlencode({'gitlab_info': gitlab_info})}", {}, timeout)

    if not isinstance(data, dict):
        raise CheckError(f"unexpected response from {check_url}")

    severity = data.get("severity")
    latest_version = data.get("latest_version")
    latest_of_minor = data.get("latest_stable_version_of_minor")
    newer_versions = data.get("latest_stable_versions") or []

    if severity not in SEVERITIES:
        raise CheckError(f"unknown severity {severity!r} in the response from {check_url}")
    if not isinstance(latest_version, str) or not latest_version:
        raise CheckError(f"no latest version in the response from {check_url}")
    if latest_of_minor is not None and not isinstance(latest_of_minor, str):
        raise CheckError(f"invalid latest_stable_version_of_minor in the response from {check_url}")
    if not isinstance(newer_versions, list) or not all(isinstance(v, str) for v in newer_versions):
        raise CheckError(f"invalid latest_stable_versions in the response from {check_url}")

    return Upstream(
        severity=severity,
        # GitLab itself reads this field with to_boolean
        critical_vulnerability=data.get("critical_vulnerability") in (True, "true"),
        latest_version=latest_version,
        latest_of_minor=latest_of_minor or None,
        newer_versions=newer_versions,
    )


def evaluate(installed: Installed, upstream: Upstream) -> tuple[int, str]:
    minor = installed.release.rsplit(".", 1)[0]

    if upstream.critical_vulnerability:
        state, summary = CRITICAL, f"GitLab {installed.version} is affected by a critical vulnerability, update now"
    elif upstream.severity == "danger":
        state, summary = CRITICAL, f"GitLab {installed.version} is vulnerable, security update required"
    elif upstream.severity == "warning":
        state, summary = WARNING, f"GitLab {installed.version} is outdated, update available"
    else:
        state, summary = OK, f"GitLab {installed.version} is up to date"

    if state == OK:
        summary += f" (latest release: {upstream.latest_version})"
    else:
        targets = []
        if upstream.latest_of_minor and upstream.latest_of_minor != installed.release:
            targets.append(f"{upstream.latest_of_minor} (latest patch release of {minor})")
        if upstream.latest_version not in (installed.release, upstream.latest_of_minor):
            targets.append(f"{upstream.latest_version} (latest release)")
        if targets:
            summary += ": " + ", ".join(targets)

    details = [f"installed version: {installed.version}" + (f" ({installed.edition})" if installed.edition else "")]
    if upstream.latest_of_minor:
        details.append(f"latest patch release of {minor}: {upstream.latest_of_minor}")
    details.append(f"latest release: {upstream.latest_version}")
    if upstream.newer_versions:
        details.append(f"newer maintained releases: {', '.join(upstream.newer_versions)}")
    details.append(f"critical vulnerability: {'yes' if upstream.critical_vulnerability else 'no'}")

    return state, summary + "\n" + "\n".join(f" \\_ {line}" for line in details)


def output(state: int, message: str) -> int:
    print(f"[{STATE_NAMES[state]}] {message}")
    return state


def main(args: argparse.Namespace) -> int:
    try:
        installed = get_installed(base_url(args.host), args.token, args.timeout)
        upstream = get_upstream(args.version_check_url, installed.release, args.timeout)
    except CheckError as error:
        return output(UNKNOWN, str(error))

    return output(*evaluate(installed, upstream))


if __name__ == "__main__":  # pragma: no cover
    try:
        sys.exit(main(commandline(sys.argv[1:])))
    except Exception as error:  # pylint: disable=broad-except
        print(f"[UNKNOWN] Unexpected error: {type(error).__name__}: {error}")
        sys.exit(UNKNOWN)
