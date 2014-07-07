
import time
import unittest2

from pyramid.request import Request, Response
from pyramid.httpexceptions import HTTPNotFound, HTTPForbidden

from webtest import TestApp
from testfixtures import LogCapture
import pyramid.testing

from mozsvc.metrics import metrics_timer, initialize_request_metrics

from cornice import Service
from cornice.pyramidhook import register_service_views


class TestMetrics(unittest2.TestCase):

    def setUp(self):
        self.logs = LogCapture()

    def tearDown(self):
        self.logs.uninstall()

    def test_service_metrics(self):
        stub_service = Service(name="stub", path="/stub")

        @stub_service.get()
        @metrics_timer("view_time")
        def stub_view(request):
            request.metrics["stub"] = "stub-a-dub-dub"
            return {}

        with pyramid.testing.testConfig() as config:
            config.include("cornice")
            config.include("mozsvc")
            register_service_views(config, stub_service)
            app = TestApp(config.make_wsgi_app())
            res = app.get("/stub")
            self.assertEquals(res.body, "{}")

        self.assertTrue(len(self.logs.records), 1)
        r = self.logs.records[0]
        self.assertEquals(r.stub, "stub-a-dub-dub")
        self.assertTrue(0 < r.request_time < 0.1)
        self.assertTrue(0 < r.view_time <= r.request_time)

    def test_timing_decorator(self):

        @metrics_timer("timer1")
        def doit1():
            time.sleep(0.01)

        def viewit(request):
            doit1()

        request = Request.blank("/")
        initialize_request_metrics(request)
        with pyramid.testing.testConfig(request=request):
            viewit(request)

        ts = request.metrics["timer1"]
        self.assertTrue(0.01 < ts < 0.1)

    def test_timing_contextmanager(self):

        def viewit(request):
            with metrics_timer("timer1"):
                time.sleep(0.01)

        request = Request.blank("/")
        initialize_request_metrics(request)
        with pyramid.testing.testConfig(request=request):
            viewit(request)

        ts = request.metrics["timer1"]
        self.assertTrue(0.01 < ts < 0.1)

    def test_timing_contextmanager_with_explicit_request_object(self):

        def viewit(request):
            with metrics_timer("timer1", request):
                time.sleep(0.01)

        request = Request.blank("/")
        initialize_request_metrics(request)
        viewit(request)

        ts = request.metrics["timer1"]
        self.assertTrue(0.01 < ts < 0.1)

    def test_timing_contextmanager_doesnt_fail_if_no_metrics_dict(self):

        def viewit(request):
            with metrics_timer("timer1"):
                time.sleep(0.01)

        request = Request.blank("/")
        with pyramid.testing.testConfig(request=request):
            viewit(request)

        self.assertFalse(hasattr(request, "metrics"))

    def test_timing_contextmanager_doesnt_fail_if_no_reqest_object(self):
        with metrics_timer("timer1"):
            time.sleep(0.01)

    def test_that_service_metrics_include_correct_response_codes(self):
        stub_service = Service(name="stub", path="/{what}")

        @stub_service.get()
        def stub_view(request):
            what = request.matchdict["what"]
            if what == "ok":
                return Response(status=200)
            if what == "notfound":
                return Response(status=404)
            if what == "forbidden":
                return Response(status=403)
            if what == "exc_forbidden":
                raise HTTPForbidden
            if what == "impl_forbidden":
                request.response.status_code = 403
                return ""
            raise HTTPNotFound

        with pyramid.testing.testConfig() as config:
            config.include("cornice")
            config.include("mozsvc")
            register_service_views(config, stub_service)
            app = TestApp(config.make_wsgi_app())

            app.get("/ok", status=200)
            r = self.logs.records[-1]
            self.assertEquals(r.code, 200)

            app.get("/notfound", status=404)
            r = self.logs.records[-1]
            self.assertEquals(r.code, 404)
            app.get("/forbidden", status=403)
            r = self.logs.records[-1]
            self.assertEquals(r.code, 403)

            app.get("/exc_notfound", status=404)
            r = self.logs.records[-1]
            self.assertEquals(r.code, 404)
            app.get("/exc_forbidden", status=403)
            r = self.logs.records[-1]
            self.assertEquals(r.code, 403)

            app.get("/impl_forbidden", status=403)
            r = self.logs.records[-1]
            self.assertEquals(r.code, 403)
