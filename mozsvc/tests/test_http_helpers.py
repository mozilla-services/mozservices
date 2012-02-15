# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest
import urllib2
import socket
from mozsvc.http_helpers import get_url, proxy


class FakeResult(object):
    headers = {}
    body = '{}'

    def getcode(self):
        return 200

    def read(self):
        return self.body


class TestHttp(unittest.TestCase):

    def setUp(self):
        self.oldopen = urllib2.urlopen
        urllib2.urlopen = self._urlopen

    def tearDown(self):
        urllib2.urlopen = self.oldopen

    def _urlopen(self, req, timeout=None):
        url = req.get_full_url()
        if url == 'impossible url':
            raise ValueError()
        if url == 'http://dwqkndwqpihqdw.com':
            msg = 'Name or service not known'
            raise urllib2.URLError(socket.gaierror(-2, msg))

        if url in ('http://google.com', 'http://goodauth'):
            return FakeResult()
        if url == 'http://badauth':
            raise urllib2.HTTPError(url, 401, '', {}, None)
        if url == 'http://timeout':
            raise urllib2.URLError(socket.timeout())
        if url == 'http://error':
            raise urllib2.HTTPError(url, 500, 'Error', {}, None)
        if url == 'http://newplace':
            res = FakeResult()
            res.body = url + ' ' + req.headers['Authorization']
            return res
        if url == 'http://xheaders':
            res = FakeResult()
            headers = req.headers.items()
            headers.sort()
            res.body = str(headers)
            return res

        raise ValueError(url)

    def test_get_url(self):

        # malformed url
        self.assertRaises(ValueError, get_url, 'impossible url')

        # unknown location
        code, headers, body = get_url('http://dwqkndwqpihqdw.com',
                                      get_body=False)
        self.assertEquals(code, 502)
        self.assertTrue('Name or service not known' in body)

        # any page
        code, headers, body = get_url('http://google.com', get_body=False)
        self.assertEquals(code, 200)
        self.assertEquals(body, '')

        # page with auth failure
        code, headers, body = get_url('http://badauth',
                                      user='tarek',
                                      password='xxxx')
        self.assertEquals(code, 401)

        # page with right auth
        code, headers, body = get_url('http://goodauth',
                                      user='tarek',
                                      password='passat76')
        self.assertEquals(code, 200)
        self.assertEquals(body, '{}')

        # page that times out
        code, headers, body = get_url('http://timeout', timeout=0.1)
        self.assertEquals(code, 504)

        # page that fails
        code, headers, body = get_url('http://error', get_body=False)
        self.assertEquals(code, 500)

    def test_proxy(self):
        class FakeRequest(object):
            url = 'http://locahost'
            method = 'GET'
            body = 'xxx'
            headers = {'Content-Length': 3, 'X-Me-This': 1,
                       'X-Me-That': 2}
            remote_addr = '192.168.1.1'
            _authorization = 'Basic SomeToken'

        request = FakeRequest()
        response = proxy(request, 'http', 'newplace')
        self.assertEqual(response.content_length, 31)
        self.assertEqual(response.body, 'http://newplace Basic SomeToken')

        # we want to make sure that X- headers are proxied
        request = FakeRequest()
        response = proxy(request, 'http', 'xheaders')
        self.assertTrue("('X-me-that', 2), ('X-me-this', 1)" in response.body)
        self.assertTrue("X-forwarded-for" in response.body)
