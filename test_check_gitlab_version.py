#!/usr/bin/env python3

import unittest
import unittest.mock as mock
import sys
import json

sys.path.append('..')


from check_gitlab_version import return_plugin
from check_gitlab_version import commandline
from check_gitlab_version import semver
from check_gitlab_version import main


class MockRequest():
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
    def json(self):
        return json.loads(self.text)


class CLITesting(unittest.TestCase):

    def test_commandline(self):
        actual = commandline(['-H', 'localhost', '--token', 'foobar'])
        self.assertEqual(actual.host, 'localhost')
        self.assertEqual(actual.token, 'foobar')

class UtilTesting(unittest.TestCase):

    @mock.patch('builtins.print')
    def test_return_plugin(self, mock_print):
        actual = return_plugin(1, 'foobar')
        self.assertEqual(actual, 1)

        mock_print.assert_called_with('[WARNING] GitLab Version Status - foobar')

    @mock.patch('builtins.print')
    def test_return_plugin_with_invalid_code(self, mock_print):
        actual = return_plugin(4, 'oh no!')
        self.assertEqual(actual, 4)

        mock_print.assert_called_with('[UNKNOWN] GitLab Version Status - oh no!')


    def test_semver_sort(self):

        versions = ['v16.2.4', 'v16.1.4', 'v16.2.3', 'v16.2.2', 'v16.0.8', 'v16.1.3', 'v15.11.13', 'v16.2.1', 'v16.2.0', 'v15.11.12', 'v15.11.11', 'v16.0.7', 'v16.1.2', 'v15.11.10', 'v16.0.6', 'v16.1.1']

        expected = ['v15.11.10', 'v15.11.11', 'v15.11.12', 'v15.11.13', 'v16.0.6', 'v16.0.7', 'v16.0.8', 'v16.1.1', 'v16.1.2', 'v16.1.3', 'v16.1.4', 'v16.2.0', 'v16.2.1', 'v16.2.2', 'v16.2.3', 'v16.2.4']

        actual = sorted(versions, key=semver)

        self.assertEqual(actual, expected)

        versions = ['v16.2.4', 'v15.11.10', 'v16.0', 'v16.1.1']

        expected = ['v15.11.10', 'v16.0', 'v16.1.1', 'v16.2.4']

        actual = sorted(versions, key=semver)

        self.assertEqual(actual, expected)


class MainTesting(unittest.TestCase):

    @mock.patch('requests.get')
    def test_main_gitlab_400(self, mock_get):

        def side_effect(url, headers={}, timeout=30):
            values = {
                'https://gitlab.com/api/v4/projects/13083/repository/tags':
                MockRequest(400, ''),
            }
            return values[url]

        mock_get.side_effect = side_effect

        args = commandline(['-H', 'localhost', '--token', 'foobar'])
        actual = main(args)

        self.assertEqual(actual, 3)

    @mock.patch('requests.get')
    def test_main_premise_400(self, mock_get):

        def side_effect(url, headers={}, timeout=30):
            values = {
                'https://gitlab.com/api/v4/projects/13083/repository/tags':
                MockRequest(200, '[{"name": "v16.2.0", "commit": {"id": "dfa9a102b1b08b9a102b1b08b"}}, {"name": "v16.1.0", "commit": {"id": "9a102b1b08b9a102b1b08b"}}]'),
                'https://localhost/api/v4/version':
                MockRequest(400, '')
            }
            return values[url]

        mock_get.side_effect = side_effect

        args = commandline(['-H', 'localhost', '--token', 'foobar'])
        actual = main(args)

        self.assertEqual(actual, 3)

    @mock.patch('requests.get')
    def test_main_ok(self, mock_get):

        def side_effect(url, headers={}, timeout=30):
            values = {
                'https://gitlab.com/api/v4/projects/13083/repository/tags':
                MockRequest(200, '[{"name": "v16.2.1", "commit": {"id": "9a102b1b08b9a102b1b08b"}}, {"name": "v666.2.0-rc", "commit": {"id": "foobar9a102b1b08b"}}, {"name": "v15.3.0", "commit": {"id": "bar9a102b1b08b"}}]'),
                'https://localhost/api/v4/version':
                MockRequest(200, '{"version":"v16.2.1","revision":"9a102b1b08b"}')
            }
            return values[url]

        mock_get.side_effect = side_effect

        args = commandline(['-H', 'localhost', '--token', 'foobar'])
        actual = main(args)

        self.assertEqual(actual, 0)

    @mock.patch('requests.get')
    def test_main_not_ok(self, mock_get):

        def side_effect(url, headers={}, timeout=30):
            values = {
                'https://gitlab.com/api/v4/projects/13083/repository/tags':
                MockRequest(200, '[{"name": "v16.2.1", "commit": {"id": "dfa9a102b1b08b9a102b1b08b"}}, {"name": "v16.1.0", "commit": {"id": "9a102b1b08b9a102b1b08b"}}]'),
                'https://localhost/api/v4/version':
                MockRequest(200, '{"version":"16.1.3","revision":"9a102b1b08b"}')
            }
            return values[url]

        mock_get.side_effect = side_effect

        args = commandline(['-H', 'localhost', '--token', 'foobar'])
        actual = main(args)

        self.assertEqual(actual, 2)

    @mock.patch('requests.get')
    def test_main_keyerror(self, mock_get):

        def side_effect(url, headers={}, timeout=30):
            values = {
                'https://gitlab.com/api/v4/projects/13083/repository/tags':
                MockRequest(200, '[{"name": "v16.2.1", "commit": {"id": "foobar"}}]'),
                'https://localhost/api/v4/version':
                MockRequest(200, '{"version":"16.2.2","revision":"9a102b1b08b"}')
            }
            return values[url]

        mock_get.side_effect = side_effect

        args = commandline(['-H', 'localhost', '--token', 'foobar'])
        actual = main(args)

        self.assertEqual(actual, 3)
