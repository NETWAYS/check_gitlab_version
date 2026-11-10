# check_gitlab_version

An Icinga check plugin that compares the version of a self-managed GitLab
instance against the upstream releases.

The plugin makes two HTTPS requests:

1. It reads the installed version from the GitLab API (`/api/v4/metadata`).
2. It sends this version to the GitLab version check service
   (`https://version.gitlab.com/check.json`). This is the same service and the same request that
   GitLab uses for the version badge on its help page and in the Admin area.

The rating of the version check service decides the state:

| State    | Meaning                                                                      |
|----------|------------------------------------------------------------------------------|
| OK       | The installed version is up to date.                                         |
| WARNING  | A newer version is available, without security relevance.                    |
| CRITICAL | The installed version is vulnerable, a security update is available.         |
| UNKNOWN  | A request failed, a response was invalid, or the arguments are wrong.        |

The output names the installed version, the latest patch release of the installed minor version
and the latest release, so the difference is visible at a glance.

Only the version number (for example `19.5.3`) is sent to `version.gitlab.com`. The token is only
sent to your GitLab instance.

## Installation

Python 3.9 or newer is required. The plugin uses only the Python standard library.

    install -m 755 check_gitlab_version.py /usr/lib/nagios/plugins/

The monitoring host needs HTTPS access to your GitLab instance and to `version.gitlab.com`.
Proxies are honored through the `https_proxy` and `no_proxy` environment variables.

## Access token

The GitLab API returns the version only to authenticated users, so the plugin needs a token.
The plugin only calls `GET /api/v4/metadata`. Use a token that can do as little else as possible.

### Recommended: group or project access token with the `ai_features` scope

Create a group or project access token with the role `Guest` and only the `ai_features` scope.
In the GitLab Community Edition, the REST API accepts this scope only for `/api/v4/metadata`
and `/api/v4/version`. The token cannot read projects, groups, users or repositories, neither
through the REST API nor through GraphQL or Git, and it is not bound to a person.
Tested with GitLab 19.5 CE.

If the web form does not offer the scope, create the token through the API. This needs the Owner
role in the group:

```
curl --request POST \
  --header "PRIVATE-TOKEN: <token of a group owner>" \
  --header "Content-Type: application/json" \
  --data '{"name": "check-gitlab-version", "scopes": ["ai_features"], "access_level": 10, "expires_at": "<YYYY-MM-DD>"}' \
  "https://gitlab.example.com/api/v4/groups/<group ID>/access_tokens"
```

In the Enterprise Edition (Premium, Ultimate), the `ai_features` scope also grants access to the
GitLab Duo API. If that is not acceptable, use a personal access token with the `read_user` scope.

### Alternative: personal access token with the `read_user` scope

Create a regular user, not an administrator and without any group or project memberships, and a
personal access token for this user with only the `read_user` scope. The token can read user
profiles, but no projects, groups or repositories. Group and project access tokens cannot have
this scope.

### Avoid the `read_api` and `api` scopes

Both grant read access to every internal project of the instance, even for a bot user with the
role `Guest` in an empty project.

### Expiry

Access tokens expire. Monitor the expiry date, or renew the token in time.

## Usage

```
usage: check_gitlab_version.py [-h] [-V] -H HOST [-t TOKEN]
                               [--version-check-url VERSION_CHECK_URL]
                               [--timeout TIMEOUT]

options:
  -h, --help            show this help message and exit
  -V, --version         show program's version number and exit
  -H, --host HOST       GitLab host name (uses https://<host>) or base URL,
                        e.g. https://example.com/gitlab
  -t, --token TOKEN     GitLab access token with the ai_features or read_user
                        scope (default: $CHECK_GITLAB_VERSION_TOKEN)
  --version-check-url VERSION_CHECK_URL
                        URL of the GitLab version check service (default:
                        https://version.gitlab.com/check.json)
  --timeout TIMEOUT     timeout in seconds for each of the two HTTP requests
                        (default: 10)
```

Pass the token in the environment variable `CHECK_GITLAB_VERSION_TOKEN`. A token passed with
`--token` is visible in the process list of the monitoring host.

The plugin never follows HTTP redirects, so the token cannot be sent to a redirect target.
Use the final URL of your GitLab instance.

### Examples

```
$ CHECK_GITLAB_VERSION_TOKEN=... check_gitlab_version.py --host gitlab.example.com
[OK] GitLab 19.5.3 is up to date (latest release: 19.5.3)
 \_ installed version: 19.5.3 (Community Edition)
 \_ latest patch release of 19.5: 19.5.3
 \_ latest release: 19.5.3
 \_ critical vulnerability: no
```

```
[WARNING] GitLab 19.4.4 is outdated, update available: 19.4.5 (latest patch release of 19.4), 19.5.3 (latest release)
 \_ installed version: 19.4.4 (Community Edition)
 \_ latest patch release of 19.4: 19.4.5
 \_ latest release: 19.5.3
 \_ newer maintained releases: 19.5.3, 19.4.5
 \_ critical vulnerability: no
```

```
[CRITICAL] GitLab 19.3.1-ee is affected by a critical vulnerability, update now: 19.3.7 (latest patch release of 19.3), 19.5.3 (latest release)
 \_ installed version: 19.3.1-ee (Enterprise Edition)
 \_ latest patch release of 19.3: 19.3.7
 \_ latest release: 19.5.3
 \_ newer maintained releases: 19.5.3, 19.4.5, 19.3.7
 \_ critical vulnerability: yes
```

```
[UNKNOWN] https://gitlab.example.com/api/v4/metadata returned HTTP 401: 401 Unauthorized
```

## Icinga 2

```
object CheckCommand "gitlab_version" {
  command = [ PluginDir + "/check_gitlab_version.py" ]

  arguments = {
    "--host" = {
      value = "$gitlab_version_host$"
      required = true
    }
    "--timeout" = "$gitlab_version_timeout$"
  }

  env = {
    CHECK_GITLAB_VERSION_TOKEN = "$gitlab_version_token$"
  }
}

apply Service "gitlab-version" {
  check_command = "gitlab_version"
  check_interval = 1h
  retry_interval = 15m

  vars.gitlab_version_host = host.vars.gitlab_host

  assign where host.vars.gitlab_host
}
```

GitLab publishes releases at most a few times a week, so an hourly check is enough.
The Icinga Director does not support `env` on commands. There, pass the token with `--token`.

## Upgrading from 0.1.0

* The state comes from the GitLab version check service instead of the Git tags on gitlab.com.
  An installed version that is not the latest release is now WARNING, and CRITICAL only if it is
  vulnerable. Before, every difference was CRITICAL.
* Enterprise Edition instances work. Before, they always ended as UNKNOWN.
* The output format changed and no longer contains HTML.
* The environment variable `CHECK_GITLAB_VERSION_URL` is replaced by `--version-check-url`.
* The token can be passed in `CHECK_GITLAB_VERSION_TOKEN`, and it needs only the `ai_features`
  or `read_user` scope instead of `read_api`, see [Access token](#access-token).
* The `requests` module is no longer needed.

## Development

    python -m pip install -r requirements-dev.txt
    make lint
    make test
    make coverage

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
