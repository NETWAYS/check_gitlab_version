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
