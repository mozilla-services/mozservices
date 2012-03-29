# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
import functools
import unittest

from pyramid import testing
from webtest import TestApp

from cornice.tests import CatchErrors
from mozsvc.metrics import MetricsService

service3 = MetricsService(name="service3", path="/service3")
service4 = MetricsService(name="service4", path="/service4")
service5 = MetricsService(name="service5", path="/service5")


def wrap_fn(fn):
    if not hasattr(fn, '_wrap_count'):
        fn._wrap_count = 0
    else:
        fn._wrap_count += 1

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        result["wrapped%d" % fn._wrap_count] = "yes"
        return result
    return wrapper


@service3.get(decorators=[wrap_fn])
def wrapped_get3(request):
    return {"test": "succeeded"}


@service4.post(decorators=[wrap_fn])
@service4.get(decorators=[wrap_fn])
def wrapped_get4(request):
    return {"test": "succeeded"}


@service5.get(decorators=[wrap_fn])
@service5.get(accept="application/json", renderer="simplejson")
@service5.get(accept="application/newlines", renderer="newlines")
@service5.post(decorators=[wrap_fn])
def wrapped_get5(request):
    return {"test": "succeeded"}


class TestServiceDefinition(unittest.TestCase):

    def setUp(self):
        self.config = testing.setUp()
        self.config.include("cornice")
        self.config.scan("mozsvc.tests.test_service_definition")
        self.app = TestApp(CatchErrors(self.config.make_wsgi_app()))

    def tearDown(self):
        testing.tearDown()

    def test_decorated_view_fn(self):
        # passing a decorator in to the service api call should result in a
        # decorated view callable
        resp = self.app.get("/service3")
        self.assertEquals(resp.json, {'test': 'succeeded', 'wrapped0': 'yes'})

    def test_stacked_decorated_view(self):
        # passing a decorator in to the service api call should result in a
        # decorated view callable, ordering of the particular decorators
        # shouldn't break things
        resp = self.app.get("/service4")
        self.assertEquals(resp.json, {'test': 'succeeded', 'wrapped0': 'yes'})

        resp = self.app.get("/service5")
        self.assertEquals(resp.json, {'test': 'succeeded', 'wrapped0': 'yes'})
