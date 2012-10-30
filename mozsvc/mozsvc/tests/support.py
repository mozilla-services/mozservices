# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
import urlparse

if sys.version_info < (2, 7):
    import unittest2 as unittest
else:
    import unittest  # NOQA

from webtest import TestApp
from wsgiproxy.app import WSGIProxyApp

from mozsvc.config import load_config


def get_test_config(root, ini_file="tests.ini"):
    """Find a file with testing settings, parse it into a ConfigDict."""
    ini_dir = root
    while True:
        ini_path = os.path.join(ini_dir, ini_file)
        if os.path.exists(ini_path):
            break
        if ini_path == ini_file or ini_path == "/" + ini_file:
            raise RuntimeError("cannot locate " + ini_file)
        ini_dir = os.path.split(ini_dir)[0]

    return load_config(ini_path)


# Try to convince test-loading tools to ignore this function
# despite the fact that it has "test" in the name.
get_test_config.__test__ = False


class TestCase(unittest.TestCase):
    """TestCase with some generic helper methods."""

    def setUp(self):
        super(TestCase, self).setUp()
        self.config = self.get_config()

    def get_config(self):
        """Load the config to use for the tests."""
        # Load config from the .ini file.
        # The file to use may be specified in the environment.
        self.ini_file = os.environ.get("MOZSVC_TEST_INI_FILE", "tests.ini")
        __file__ = sys.modules[self.__class__.__module__].__file__
        return get_test_config(__file__, self.ini_file)


class FunctionalTestCase(TestCase):
    """TestCase for writing functional tests using WebTest.

    This TestCase subclass provides an easy mechanism to write functional
    tests using WebTest.  It exposes a TestApp instance as self.app.

    If the environment variable MOZSVC_TEST_REMOTE is set to a URL, then
    self.app will be a WSGIProxy application that forwards all requests to
    that server.  This allows the functional tests to be easily run against
    a live server instance.
    """

    def setUp(self):
        super(FunctionalTestCase, self).setUp()

        # Test against a live server if instructed so by the environment.
        # Otherwise, test against an in-process WSGI application.
        test_remote = os.environ.get("MOZSVC_TEST_REMOTE")
        if not test_remote:
            self.distant = False
            self.host_url = "http://localhost:5000"
            application = self.make_wsgi_app()
        else:
            self.distant = True
            self.host_url = test_remote
            application = WSGIProxyApp(test_remote)

        host_url = urlparse.urlparse(self.host_url)
        self.app = TestApp(application, extra_environ={
            "HTTP_HOST": host_url.netloc,
            "wsgi.url_scheme": host_url.scheme or "http",
            "SERVER_NAME": host_url.hostname,
            "REMOTE_ADDR": "127.0.0.1",
            "SCRIPT_NAME": host_url.path,
        })

    def make_wsgi_app(self):
        raise NotImplementedError
