# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****

import time
import unittest2
import tempfile

from zope.interface import implements

import pyramid.testing
import pyramid.request
from pyramid.interfaces import IAuthenticationPolicy
from pyramid.httpexceptions import HTTPUnauthorized

import tokenlib
import hawkauthlib

from mozsvc.exceptions import BackendError
from mozsvc.tests.support import TestCase
from mozsvc.secrets import DerivedSecrets
from mozsvc.user.permissivenoncecache import PermissiveNonceCache
from mozsvc.user import TokenServerAuthenticationPolicy

try:
    from mozsvc.storage.mcclient import MemcachedClient
    from mozsvc.user.noncecache import MemcachedNonceCache
    # We'll test for a live memcached server when we actually run the tests.
    MEMCACHED = None
except (ImportError, BackendError):
    MEMCACHED = False


class ExpandoRequest(object):
    """Proxy class for setting arbitrary attributes on a request.

    This class allows us to easily stub out various derived properties of
    a Request object.  Mostly notable, Request.host_url which is usually
    a read-only property derviced from the request evnironment.
    """

    def __init__(self, req):
        self.__dict__["_ExpandoRequest__req"] = req

    def __getattr__(self, attr):
        return getattr(self.__req, attr)

    def __setattr__(self, attr, value):
        try:
            setattr(self.__req, attr, value)
        except AttributeError:
            self.__dict__[attr] = value


class StubAuthenticationPolicy(object):
    """Authentication policy taking creds from request headers.

    This is a stub authentication policy that takes username from the
    X-Username header, checks that it matches the password provided in
    the X-Password header, and returns that as the userid.
    """

    implements(IAuthenticationPolicy)

    def authenticated_userid(self, request):
        username = request.environ.get("HTTP_X_USERNAME")
        if not username:
            return None
        password = request.environ.get("HTTP_X_PASSWORD")
        if not password:
            return None
        # Don't panic!  This is only used in the tests as an easy way
        # to simulate both failed and successfull logins.
        if password != username:
            return None
        request.user["x-was-ere"] = True
        return username

    def unauthenticated_userid(self, request):
        raise RuntimeError("tests shouldn't call this")  # pragma: nocover

    def effective_principals(self, request):
        raise RuntimeError("tests shouldn't call this")  # pragma: nocover


class UserTestCase(TestCase):

    def setUp(self):
        super(UserTestCase, self).setUp()
        self.config.commit()
        self.policy = self.config.registry.queryUtility(IAuthenticationPolicy)

    def get_configurator(self):
        config = super(UserTestCase, self).get_configurator()
        config.include("mozsvc.user")
        return config

    def test_that_the_correct_policy_defaults_are_used(self):
        policy = self.policy
        self.assertTrue(isinstance(policy, TokenServerAuthenticationPolicy))
        self.assertTrue(isinstance(policy.nonce_cache, PermissiveNonceCache))
        self.assertTrue(policy.secrets is None)

    def test_that_authn_policy_can_be_overridden(self):
        self.config.set_authentication_policy(StubAuthenticationPolicy())
        self.config.commit()
        # Good password => successful auth via request.user
        request = self.make_request(environ={
            "HTTP_X_USERNAME": "user1",
            "HTTP_X_PASSWORD": "user1",
        })
        self.assertEquals(request.user["uid"], "user1")
        self.assertEquals(request.user["x-was-ere"], True)
        # Bad password => request.user is empty
        request = self.make_request(environ={
            "HTTP_X_USERNAME": "user1",
            "HTTP_X_PASSWORD": "BAD PASSWORD",
        })
        self.assertFalse(request.user)
        # No username => request.user is empty
        request = self.make_request(environ={
            "HTTP_X_PASSWORD": "password1",
        })
        self.assertFalse(request.user)
        # No password => request.user is empty
        request = self.make_request(environ={
            "HTTP_X_USERNAME": "user1",
        })
        self.assertFalse(request.user)

    def test_that_hawkauth_is_used_by_default(self):
        # Generate signed request.
        req = self.make_request()
        tokenid, key = self.policy.encode_hawk_id(req, 42)
        hawkauthlib.sign_request(req, tokenid, key)
        # That should be enough to authenticate.
        self.assertEquals(req.authenticated_userid, 42)
        self.assertEquals(req.user.get("uid"), 42)
        # Check that it rejects invalid Hawk ids.
        req = self.make_request()
        hawkauthlib.sign_request(req, tokenid, key)
        authz = req.environ["HTTP_AUTHORIZATION"]
        req.environ["HTTP_AUTHORIZATION"] = authz.replace(tokenid, "XXXXXX")
        with self.assertRaises(HTTPUnauthorized):
            req.authenticated_userid
        # And that the rejection gets raised when accessing request.user
        self.assertRaises(HTTPUnauthorized, getattr, req, "user")

    def test_that_req_user_can_be_replaced(self):
        req = self.make_request()
        tokenid, key = self.policy.encode_hawk_id(req, 42)
        hawkauthlib.sign_request(req, tokenid, key)
        req.user = {"uid": 7}
        self.assertEquals(req.user, {"uid": 7})

    def test_that_hawkauth_cant_use_both_secret_and_secrets_file(self):
        config2 = pyramid.testing.setUp()
        config2.add_settings({
            "hawkauth.secret": "DARTH VADER IS LUKE'S FATHER",
            "hawkauth.secrets_file": "/dev/null",
        })
        self.assertRaises(ValueError, config2.include, "mozsvc.user")

    def test_that_hawkauth_can_use_custom_secrets_backend(self):
        config2 = pyramid.testing.setUp()
        config2.add_settings({
            "hawkauth.secrets.backend": "mozsvc.secrets.DerivedSecrets",
            "hawkauth.secrets.master_secrets": "abcd 123456",
        })
        config2.include("mozsvc.user")
        policy2 = config2.registry.queryUtility(IAuthenticationPolicy)
        self.assertTrue(isinstance(policy2.secrets, DerivedSecrets))

    def test_that_hawkauth_can_use_per_node_hostname_secrets(self):
        with tempfile.NamedTemporaryFile() as sf:
            # Write some secrets to a file.
            sf.write("http://host1.com,0001:secret11,0002:secret12\n")
            sf.write("https://host2.com,0001:secret21,0002:secret22\n")
            sf.write("https://host3.com:444,0001:secret31,0002:secret32\n")
            sf.flush()
            # Configure the plugin to load them.
            config2 = pyramid.testing.setUp()
            config2.add_settings({
                "hawkauth.secrets_file": sf.name,
            })
            config2.include("mozsvc.user")
            config2.commit()
            # It should accept a request signed with the old secret on host1.
            req = self.make_request(config=config2, environ={
                "HTTP_HOST": "host1.com",
            })
            id = tokenlib.make_token({"uid": 42, "node": req.host_url},
                                     secret="secret11")
            key = tokenlib.get_token_secret(id, secret="secret11")
            hawkauthlib.sign_request(req, id, key)
            self.assertEquals(req.authenticated_userid, 42)
            # It should accept a request signed with the new secret on host1.
            req = self.make_request(config=config2, environ={
                "HTTP_HOST": "host1.com",
            })
            id = tokenlib.make_token({"uid": 42, "node": req.host_url},
                                     secret="secret12")
            key = tokenlib.get_token_secret(id, secret="secret12")
            hawkauthlib.sign_request(req, id, key)
            self.assertEquals(req.authenticated_userid, 42)
            # It should reject a request signed with secret from other host.
            req = self.make_request(config=config2, environ={
                "HTTP_HOST": "host2.com",
            })
            id = tokenlib.make_token({"uid": 42, "node": req.host_url},
                                     secret="secret12")
            key = tokenlib.get_token_secret(id, secret="secret12")
            hawkauthlib.sign_request(req, id, key)
            with self.assertRaises(HTTPUnauthorized):
                req.authenticated_userid
            # It should reject a request over plain http when host2 is ssl.
            req = self.make_request(config=config2, environ={
                "HTTP_HOST": "host2.com",
            })
            id = tokenlib.make_token({"uid": 42, "node": req.host_url},
                                     secret="secret22")
            key = tokenlib.get_token_secret(id, secret="secret22")
            hawkauthlib.sign_request(req, id, key)
            with self.assertRaises(HTTPUnauthorized):
                req.authenticated_userid
            # It should accept a request signed with the new secret on host2.
            req = self.make_request(config=config2, environ={
                "HTTP_HOST": "host2.com",
                "wsgi.url_scheme": "https",
            })
            id = tokenlib.make_token({"uid": 42, "node": req.host_url},
                                     secret="secret22")
            key = tokenlib.get_token_secret(id, secret="secret22")
            hawkauthlib.sign_request(req, id, key)
            self.assertEquals(req.authenticated_userid, 42)
            # It should accept a request to host1 with an explicit port number.
            # Use some trickery to give host_url a value with default port.
            req = ExpandoRequest(self.make_request(config=config2, environ={
                "HTTP_HOST": "host1.com:80",
                "wsgi.url_scheme": "http",
            }))
            req.host_url = "http://host1.com:80"
            id = tokenlib.make_token({"uid": 42, "node": req.host_url[:-3]},
                                     secret="secret11")
            key = tokenlib.get_token_secret(id, secret="secret11")
            hawkauthlib.sign_request(req, id, key)
            self.assertEquals(req.authenticated_userid, 42)
            # It should accept a request to host2 with an explicit port number.
            # Use some trickery to give host_url a value with default port.
            req = ExpandoRequest(self.make_request(config=config2, environ={
                "HTTP_HOST": "host2.com:443",
                "wsgi.url_scheme": "https",
            }))
            req.host_url = "https://host2.com:443"
            id = tokenlib.make_token({"uid": 42, "node": req.host_url[:-4]},
                                     secret="secret22")
            key = tokenlib.get_token_secret(id, secret="secret22")
            hawkauthlib.sign_request(req, id, key)
            self.assertEquals(req.authenticated_userid, 42)
            # It should accept a request to host3 on a custom port.
            req = self.make_request(config=config2, environ={
                "HTTP_HOST": "host3.com:444",
                "wsgi.url_scheme": "https",
            })
            id = tokenlib.make_token({"uid": 42, "node": req.host_url},
                                     secret="secret32")
            key = tokenlib.get_token_secret(id, secret="secret32")
            hawkauthlib.sign_request(req, id, key)
            self.assertEquals(req.authenticated_userid, 42)
            # It should reject unknown hostnames.
            req = self.make_request(config=config2, environ={
                "HTTP_HOST": "host4.com",
            })
            id = tokenlib.make_token({"uid": 42, "node": req.host_url},
                                     secret="secret12")
            key = tokenlib.get_token_secret(id, secret="secret12")
            hawkauthlib.sign_request(req, id, key)
            with self.assertRaises(HTTPUnauthorized):
                req.authenticated_userid

    def test_checking_of_token_node_assignment(self):
        # Generate a token for one node
        req = self.make_request(environ={
            "HTTP_HOST": "host1.com",
        })
        tokenid, key = self.policy.encode_hawk_id(req, 42)
        # It can authenticate for requests to that node.
        hawkauthlib.sign_request(req, tokenid, key)
        self.assertEquals(req.authenticated_userid, 42)
        self.assertEquals(req.user.get("uid"), 42)
        # But not requests to some other node.
        req = self.make_request(environ={
            "HTTP_HOST": "host2.com",
        })
        hawkauthlib.sign_request(req, tokenid, key)
        with self.assertRaises(HTTPUnauthorized):
            req.authenticated_userid


class TestMemcachedNonceCache(unittest2.TestCase):

    def setUp(self):
        global MEMCACHED
        if MEMCACHED is None:
            try:
                MemcachedClient().get("")
            except BackendError:
                MEMCACHED = False
            else:
                MEMCACHED = True
        if not MEMCACHED:
            raise unittest2.SkipTest("no memcache")
        self.nc = None
        self.keys_to_delete = set()

    def tearDown(self):
        if self.nc is not None:
            for key in self.keys_to_delete:
                self.nc.mcclient.delete(key)

    def _monkeypatch_mcclient(self, mcclient):
        # Ultramemcache has no API for clearing all keys.
        # Monkeypatch it to remember any keys we use,
        # so we can delete them during cleanup.
        orig_add = mcclient.add

        def add_and_remember(key, *args, **kwds):
            self.keys_to_delete.add(key)
            return orig_add(key, *args, **kwds)

        mcclient.add = add_and_remember

    def test_operation(self, now=lambda: int(time.time())):
        window = 5
        nc = self.nc = MemcachedNonceCache(window=window)
        self._monkeypatch_mcclient(nc.mcclient)
        # Initially nothing is cached, so all nonces as fresh.
        ts = now()
        try:
            self.assertTrue(nc.check_nonce(ts, "abc"))
        except BackendError:
            raise unittest2.SkipTest("no memcache")
        # After that check, the (ts, nonce) pair should be stale.
        # Changing either the ts or the nonce will make it fresh.
        self.assertFalse(nc.check_nonce(ts, "abc"))
        self.assertTrue(nc.check_nonce(ts, "xyz"))
        self.assertTrue(nc.check_nonce(ts + 1, "abc"))
        # Timestamps outside the configured window are rejected.
        self.assertFalse(nc.check_nonce(now() - window - 1, "abc"))
        self.assertFalse(nc.check_nonce(now() + window + 1, "abc"))


class TestPermissiveNonceCache(unittest2.TestCase):

    def test_permissiveness(self):
        nc = PermissiveNonceCache()
        self.assertTrue(nc.check_nonce(time.time(), "abcd"))
        self.assertTrue(nc.check_nonce(1234, "abcd"))
        self.assertTrue(nc.check_nonce(1234, "abcd"))
        self.assertTrue(nc.check_nonce(987654321987654321, "hijk"))
