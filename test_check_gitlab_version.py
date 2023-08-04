#!/usr/bin/env python3

import unittest
import unittest.mock as mock
import sys

sys.path.append('..')


from check_gitlab_version import return_plugin
from check_gitlab_version import commandline

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
