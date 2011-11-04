# -*- coding: utf-8 -*-
# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Sync Server
#
# The Initial Developer of the Original Code is the Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2010
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Tarek Ziade (tarek@mozilla.com)
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

import unittest
import os.path

from mozsvc.util import round_time, resolve_name, maybe_resolve_name


class TestUtil(unittest.TestCase):

    def test_round_time(self):

        # returns a two-digits decimal of the current time
        res = round_time()
        self.assertEqual(len(str(res).split('.')[-1]), 2)

        # can take a timestamp
        res = round_time(129084.198271987)
        self.assertEqual(str(res), '129084.20')

        # can take a str timestamp
        res = round_time('129084.198271987')
        self.assertEqual(str(res), '129084.20')

        # bad values raise ValueErrors
        self.assertRaises(ValueError, round_time, 'bleh')
        self.assertRaises(ValueError, round_time, object())

        # changing the precision
        res = round_time(129084.198271987, precision=3)
        self.assertEqual(str(res), '129084.198')

    def test_resolve_name(self):

        # Resolving by absolute path
        self.assertEquals(os.path.abspath, resolve_name("os.path.abspath"))
        self.assertEquals(os.path.abspath, resolve_name("os.path:abspath"))

        # Resolving by relative path to package object
        self.assertEquals(os.path.abspath, resolve_name(".path.abspath", os))
        self.assertEquals(os.path.abspath, resolve_name(".path:abspath", os))

        # Resolving by relative path to package name
        self.assertEquals(os.path.abspath, resolve_name(".abspath", "os.path"))
        self.assertEquals(os.path.abspath, resolve_name(":abspath", "os.path"))

    def test_maybe_resolve_name(self):

        self.assertEquals(os.path, maybe_resolve_name("os.path"))
        self.assertEquals(os.path, maybe_resolve_name(os.path))
        self.assertEquals(None, maybe_resolve_name(None))
