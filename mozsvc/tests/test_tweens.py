# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest

import pyramid.testing
from pyramid.response import Response

from mozsvc.exceptions import BackendError
from mozsvc.tests.support import make_request


class TestErrorHandlingTweens(unittest.TestCase):

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
        retry_after = int(r.headers["Retry-After"])
        self.assertTrue(17 <= retry_after <= 22)

    def test_that_backend_errors_can_set_retry_after(self):
        @self._set_backend_error_view
        def backend_error(request):
            raise BackendError(retry_after=42)

        r = self._do_request("/backend_error")
        self.assertEquals(r.status_int, 503)
        retry_after = int(r.headers["Retry-After"])
        self.assertTrue(42 <= retry_after <= 47)

    def test_that_retry_after_doesnt_get_set_to_zero(self):
        @self._set_backend_error_view
        def backend_error(request):
            raise BackendError(retry_after=0)

        r = self._do_request("/backend_error")
        self.assertEquals(r.status_int, 503)
        self.assertEquals(r.headers.get("Retry-After"), None)


class TestBackoffResponseTween(unittest.TestCase):

    def setUp(self):
        self.app = None
        self.config = pyramid.testing.setUp()
        self.config.add_route("root", "/")
        self.config.add_view(lambda r: Response("ok"), route_name="root")

    def tearDown(self):
        pyramid.testing.tearDown()

    def _make_request(self, *args, **kwds):
        return make_request(self.config, *args, **kwds)

    def _do_request(self, *args, **kwds):
        if self.app is None:
            self.app = self.config.make_wsgi_app()
        req = self._make_request(*args, **kwds)
        return self.app.handle_request(req)

    def _do_requests(self, count=100):
        # Do some requests and return the total number performed, the number
        # that had backoff headers, and the number that had unavailable errors.
        backoff_count = 0
        unavail_count = 0
        for _ in xrange(count):
            r = self._do_request("/")
            self.assertTrue(r.status_int in (200, 503))
            if r.status_int == 503:
                unavail_count += 1
            if "X-Backoff" in r.headers:
                backoff_count += 1
        return count, backoff_count, unavail_count

    def test_that_backoff_responses_are_not_sent_by_default(self):
        self.config.include("mozsvc")
        count, backoff_count, unavail_count = self._do_requests()
        self.assertEquals(backoff_count, 0)
        self.assertEquals(unavail_count, 0)

    def test_that_backoff_headers_can_be_sent_uniformly(self):
        self.config.registry.settings["mozsvc.backoff_probability"] = 1
        self.config.include("mozsvc")
        count, backoff_count, unavail_count = self._do_requests()
        self.assertEquals(backoff_count, count)
        self.assertEquals(unavail_count, 0)

    def test_that_backoff_headers_can_be_sent_probabilistically(self):
        self.config.registry.settings["mozsvc.backoff_probability"] = 0.5
        self.config.include("mozsvc")
        count, backoff_count, unavail_count = self._do_requests()
        self.assertTrue(backoff_count > 0)
        self.assertTrue(backoff_count < count)
        self.assertEquals(unavail_count, 0)

    def test_that_unavail_responses_can_be_sent_uniformly(self):
        self.config.registry.settings["mozsvc.unavailable_probability"] = 1
        self.config.include("mozsvc")
        count, backoff_count, unavail_count = self._do_requests()
        self.assertEquals(backoff_count, 0)
        self.assertEquals(unavail_count, count)

    def test_that_unavail_responses_can_be_sent_probabilistically(self):
        self.config.registry.settings["mozsvc.unavailable_probability"] = 0.5
        self.config.include("mozsvc")
        count, backoff_count, unavail_count = self._do_requests()
        self.assertEquals(backoff_count, 0)
        self.assertTrue(unavail_count > 0)
        self.assertTrue(unavail_count < count)

    def test_that_unavail_and_backoff_can_be_used_together(self):
        self.config.registry.settings["mozsvc.backoff_probability"] = 0.5
        self.config.registry.settings["mozsvc.unavailable_probability"] = 0.5
        self.config.include("mozsvc")
        count, backoff_count, unavail_count = self._do_requests()
        self.assertTrue(backoff_count > 0)
        self.assertTrue(backoff_count < count)
        self.assertTrue(unavail_count > 0)
        self.assertTrue(unavail_count < count)

    def test_that_unavail_and_backoff_can_be_passed_as_strings(self):
        self.config.registry.settings["mozsvc.backoff_probability"] = "0.5"
        self.config.registry.settings["mozsvc.unavailable_probability"] = "0.5"
        self.config.include("mozsvc")
        count, backoff_count, unavail_count = self._do_requests()
        self.assertTrue(backoff_count > 0)
        self.assertTrue(backoff_count < count)
        self.assertTrue(unavail_count > 0)
        self.assertTrue(unavail_count < count)
