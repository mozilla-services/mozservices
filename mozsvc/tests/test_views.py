# -*- coding: utf-8 -*-

# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****

import unittest

import pyramid.testing

from mozsvc.tests.support import make_request


class TestUtil(unittest.TestCase):

    def setUp(self):
        self.app = None
        self.config = pyramid.testing.setUp()
        self.config.include("mozsvc")

    def tearDown(self):
        pyramid.testing.tearDown()

    def _make_request(self, *args, **kwds):
        return make_request(self.config, *args, **kwds)

    def _do_request(self, *args, **kwds):
        if self.app is None:
            self.app = self.config.make_wsgi_app()
        req = self._make_request(*args, **kwds)
        return self.app.handle_request(req)

    def test_heartbeat_view(self):
        r = self._do_request("/__heartbeat__")
        self.assertEquals(r.status_int, 200)
        self.assertEquals(r.body, "OK")

    def test_non_utf8_url_path(self):
        r = self._do_request("/test/\xFF/path")
        self.assertEquals(r.status_int, 404)
