# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest

import pyramid.testing

from mozsvc.exceptions import BackendError
from mozsvc.tests.support import make_request


class TestTweens(unittest.TestCase):

    def setUp(self):
        self.app = None
        self.config = pyramid.testing.setUp()
        self.config.registry.settings["mozsvc.retry_after"] = "17"
        self.config.include("mozsvc")
        self.config.add_route("backend_error", "/backend_error")

    def tearDown(self):
        pyramid.testing.tearDown()

    def _make_request(self, *args, **kwds):
        return make_request(self.config, *args, **kwds)

    def _do_request(self, *args, **kwds):
        if self.app is None:
            self.app = self.config.make_wsgi_app()
        req = self._make_request(*args, **kwds)
        return self.app.handle_request(req)

    def _set_backend_error_view(self, func):
        self.config.add_view(func, route_name="backend_error")

    def test_that_backend_errors_are_captured(self):
        @self._set_backend_error_view
        def backend_error(request):
            raise BackendError

        r = self._do_request("/backend_error")
        self.assertEquals(r.status_int, 503)
        self.assertEquals(r.headers["Retry-After"], "17")

    def test_that_backend_errors_can_set_retry_after(self):
        @self._set_backend_error_view
        def backend_error(request):
            raise BackendError(retry_after=42)

        r = self._do_request("/backend_error")
        self.assertEquals(r.status_int, 503)
        self.assertEquals(r.headers["Retry-After"], "42")

    def test_that_retry_after_doesnt_get_set_to_zero(self):
        @self._set_backend_error_view
        def backend_error(request):
            raise BackendError(retry_after=0)

        r = self._do_request("/backend_error")
        self.assertEquals(r.status_int, 503)
        self.assertEquals(r.headers.get("Retry-After"), None)
