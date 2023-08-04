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

import argparse
import os
import sys
# TODO needs replacement, deprecated
from distutils.version import LooseVersion  # pylint: disable=deprecated-module

import requests


gitlab_url = "https://gitlab.com/api/v4/projects/13083/repository/tags"

states = ["OK", "WARNING", "CRITICAL", "UNKNOWN"]


def return_plugin(status, msg):
    print("Version: {0} - {1}".format(states[status], msg))
    return status


def main():
    scriptname = os.path.basename(sys.argv[0])
    parser = argparse.ArgumentParser(prog=scriptname)

    parser.add_argument('-H', '--host', type=str, required=True,
                    help='GitLab Hostname (Premise)')
    parser.add_argument('-t', '--token', type=str, required=True,
                    help='GitLab Token (Premise)')

    args = parser.parse_args()

    tags = requests.get(gitlab_url, timeout=30)
    if tags.status_code != 200:
        return return_plugin(
            3,
            "GitLab check failed - http={0}, text={1}".format(
                tags.status_code, tags.text
            ),
        )

    versions = []
    commits = {}

    def fix_version_number(version):
        return version[1:].replace("-", "")

    for tag in tags.json():
        if "rc" in tag["name"]:
            continue
        version = fix_version_number(tag["name"])
        versions.append(version)
        commits[tag["commit"]["id"][0:11]] = version

    versions.sort(key=LooseVersion)

    premise_headers = {"PRIVATE-TOKEN": args.token}

    check = requests.get("https://{0}/api/v4/version".format(args.host), headers=premise_headers, timeout=30)
    if check.status_code != 200:
        return return_plugin(
            3,
            "Premise check failed - http={0}, text={1}".format(
                check.status_code, check.text
            ),
        )

    premise = check.json()

    try:
        premise_version = commits[premise["revision"]]
        current_version = versions.pop()

        if premise_version == current_version:
            return return_plugin(0,"Version is <strong>UpToDate</strong> - premise={0}, gitlab={1}".format(premise_version, current_version),)

        return return_plugin(2, "Version <strong>Mismatch</strong> - premise={0}, gitlab={1}".format(premise_version, current_version),)
    except KeyError:
        return return_plugin(3, "Error get version from data")


if __name__ == "__main__":
    sys.exit(main())
