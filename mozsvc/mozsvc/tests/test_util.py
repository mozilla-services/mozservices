# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest
import os.path

from mozsvc.util import (resolve_name, maybe_resolve_name, dnslookup,)


class TestUtil(unittest.TestCase):

    def test_resolve_name(self):
        abspath = os.path.abspath

        # Resolving by absolute path
        self.assertEquals(abspath, resolve_name("os.path.abspath"))
        self.assertEquals(abspath, resolve_name("os.path:abspath"))

        # Resolving by relative path to package object
        self.assertEquals(abspath, resolve_name(".path.abspath", os))
        self.assertEquals(abspath, resolve_name(".path:abspath", os))
        self.assertEquals(abspath, resolve_name(".abspath", os.path))
        self.assertEquals(abspath, resolve_name(":abspath", os.path))

        # Resolving by relative path to package name
        self.assertEquals(abspath, resolve_name(".path.abspath", "os"))
        self.assertEquals(abspath, resolve_name(".path:abspath", "os"))
        self.assertEquals(abspath, resolve_name("..os.path.abspath", "os"))
        self.assertEquals(abspath, resolve_name("..os.path:abspath", "os"))
        self.assertEquals(abspath, resolve_name(".abspath", "os.path"))
        self.assertEquals(abspath, resolve_name(":abspath", "os.path"))
        self.assertEquals(abspath, resolve_name("..path.abspath", "os.path"))
        self.assertEquals(abspath, resolve_name("..path:abspath", "os.path"))

    def test_maybe_resolve_name(self):
        self.assertEquals(os.path, maybe_resolve_name("os.path"))
        self.assertEquals(os.path, maybe_resolve_name(os.path))
        self.assertEquals(None, maybe_resolve_name(None))

    def test_dnslookup(self):
        self.assertEqual(dnslookup('http://ziade.org/'),
                         'http://88.191.140.69/')

        self.assertEqual(dnslookup('http://user:pass@ziade.org:80/path'),
                        'http://user:pass@88.191.140.69:80/path')
