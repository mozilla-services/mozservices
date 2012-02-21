# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from webob import Response
import urllib2
import socket
import base64
from urlparse import urlparse, urlunparse


def get_url(url, method='GET', data=None, user=None, password=None, timeout=5,
            get_body=True, extra_headers=None):
    """Performs a synchronous url call and returns the status and body.

    This function is to be used to provide a gateway service.

    If the url is not answering after `timeout` seconds, the function will
    return a (504, {}, error).

    If the url is not reachable at all, the function will
    return (502, {}, error)

    Other errors are managed by the urrlib2.urllopen call.

    Args:
        - url: url to visit
        - method: method to use
        - data: data to send
        - user: user to use for Basic Auth, if needed
        - password: password to use for Basic Auth
        - timeout: timeout in seconds.
        - extra headers: mapping of headers to add
        - get_body: if set to False, the body is not retrieved

    Returns:
        - tuple : status code, headers, body
    """
    if isinstance(password, unicode):
        password = password.encode('utf-8')

    req = urllib2.Request(url, data=data)
    req.get_method = lambda: method

    if user is not None and password is not None:
        auth = base64.encodestring('%s:%s' % (user, password))
        req.add_header("Authorization", "Basic %s" % auth.strip())

    if extra_headers is not None:
        for name, value in extra_headers.items():
            req.add_header(name, value)

    try:
        res = urllib2.urlopen(req, timeout=timeout)
    except urllib2.HTTPError, e:
        if hasattr(e, 'headers'):
            headers = dict(e.headers)
        else:
            headers = {}

        if hasattr(e, 'read'):
            body = e.read()
        else:
            body = ''

        return e.code, headers, body

    except urllib2.URLError, e:
        if isinstance(e.reason, socket.timeout):
            return 504, {}, str(e)
        return 502, {}, str(e)

    if get_body:
        body = res.read()
    else:
        body = ''

    return res.getcode(), dict(res.headers), body


def proxy(request, scheme, netloc, timeout=5):
    """Proxies and return the result from the other server.

    - scheme: http or https
    - netloc: proxy location
    """
    parsed = urlparse(request.url)
    path = parsed.path
    params = parsed.params
    query = parsed.query
    fragment = parsed.fragment
    url = urlunparse((scheme, netloc, path, params, query, fragment))
    method = request.method
    data = request.body

    # copying all X- headers
    xheaders = {}
    for header, value in request.headers.items():
        if not header.startswith('X-'):
            continue
        xheaders[header] = value

    if 'X-Forwarded-For' not in request.headers:
        xheaders['X-Forwarded-For'] = request.remote_addr

    if hasattr(request, '_authorization'):
        xheaders['Authorization'] = request._authorization

    status, headers, body = get_url(url, method, data, timeout=timeout,
                                    extra_headers=xheaders)

    return Response(body, status, headers.items())
