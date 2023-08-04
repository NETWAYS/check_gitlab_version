#!/usr/bin/env python3

import unittest
import unittest.mock as mock
import sys
import json

sys.path.append('..')


from check_gitlab_version import return_plugin
from check_gitlab_version import commandline
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

        mock_print.assert_called_with('Version: WARNING - foobar')

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
                MockRequest(200, '[{"name": "v16.2", "commit": {"id": "dfa9a102b1b08b9a102b1b08b"}}, {"name": "v16.1", "commit": {"id": "9a102b1b08b9a102b1b08b"}}]'),
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
                MockRequest(200, '[{"name": "v16.2", "commit": {"id": "9a102b1b08b9a102b1b08b"}}, {"name": "v666-rc", "commit": {"id": "foobar9a102b1b08b"}}]'),
                'https://localhost/api/v4/version':
                MockRequest(200, '{"version":"16.2","revision":"9a102b1b08b"}')
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
                MockRequest(200, '[{"name": "v16.2", "commit": {"id": "dfa9a102b1b08b9a102b1b08b"}}, {"name": "v16.1", "commit": {"id": "9a102b1b08b9a102b1b08b"}}]'),
                'https://localhost/api/v4/version':
                MockRequest(200, '{"version":"16.1","revision":"9a102b1b08b"}')
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
                MockRequest(200, '[{"name": "v16.2", "commit": {"id": "foobar"}}]'),
                'https://localhost/api/v4/version':
                MockRequest(200, '{"version":"16.2","revision":"9a102b1b08b"}')
            }
            return values[url]

        mock_get.side_effect = side_effect

        args = commandline(['-H', 'localhost', '--token', 'foobar'])
        actual = main(args)

        self.assertEqual(actual, 3)
