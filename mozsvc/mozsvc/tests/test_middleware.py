# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from webtest import TestApp

from mozsvc.middleware import CatchErrorMiddleware

from mozsvc.tests.support import unittest


class ErrorfulWSGIApp(object):
    """A WSGI app that just raises a given error."""

    def __init__(self, exc_type, *exc_args, **exc_kwds):
        self.exc_type = exc_type
        self.exc_args = exc_args
        self.exc_kwds = exc_kwds

    def __call__(self, environ, start_response):
        raise self.exc_type(*self.exc_args, **self.exc_kwds)


class TestCatchErrorMiddleware(unittest.TestCase):

    def setUp(self):
        self.captured_errors = []
        config = {
          "global.logger_hook": self.captured_errors.append
        }
        self.wsgi_app = ErrorfulWSGIApp(ValueError, "MOZSVC_TEST")
        self.test_app = TestApp(CatchErrorMiddleware(self.wsgi_app, config))

    def test_that_exceptions_get_reported_with_crash_id(self):
        r = self.test_app.get("/", status=500)
        self.assertEquals(len(self.captured_errors), 1)
        self.assertTrue("MOZSVC_TEST" in self.captured_errors[0]["error"])
        self.assertTrue(self.captured_errors[0]["crash_id"] in r.body)

    def test_that_newlines_arent_written_into_logs(self):
        self.wsgi_app.exc_args = ("Malicious\nErrorData",)
        self.test_app.get("/", status=500)
        self.assertEquals(len(self.captured_errors), 1)
        errlog = self.captured_errors[0]["error"]
        self.assertTrue("Malicious\nErrorData" not in errlog)
        self.assertTrue("Malicious\\nErrorData" in errlog)
