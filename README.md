# check_gitlab_version

An Icinga check plugin for on premise GitLab version against tags.

## Installation

Python 3 is required, and you need the Python [requests](https://pypi.org/project/requests/) module.

Please prefer installation via system packages like `python3-requests`.

Alternatively you can install with pip:

    pip3 install -r requirements.txt

## Usage

The check plugins uses the Git tags from gitlab.com to retrieve the current version. The URL can be adjusted using the environment variable `CHECK_GITLAB_VERSION_URL`.

```
check_gitlab_version.py' '--host' 'git.netways.de' '--token' 'XXX-API-TOKEN-XXX'
Version: OK - Version is <strong>UpToDate</strong> - premise=13.9.3, gitlab=13.9.3
```

## License

```
MIT License

Copyright (c) 2021 NETWAYS GmbH

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
