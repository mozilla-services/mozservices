# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Sync Server
#
# The Initial Developer of the Original Code is the Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2010
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Ryan Kelly (rkelly@mozilla.com)
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

import unittest

from zope.interface import implements

from pyramid.interfaces import IRequestFactory, IAuthenticationPolicy
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid.request import Request
import pyramid.testing

import mozsvc.user


class HeaderAuthenticationPolicy(object):
    """Authentication policy taking creds from request headers."""

    implements(IAuthenticationPolicy)

    def authenticated_userid(self, request):
        username = request.environ.get("HTTP_X_USERNAME")
        if not username:
            return None
        password = request.environ.get("HTTP_X_PASSWORD")
        if not password:
            return None
        credentials = {"username": username, "password": password}
        if not mozsvc.user.authenticate(request, credentials, ["mail"]):
            return None
        request.user["x-was-ere"] = True
        return username

    def unauthenticated_userid(self, request):
        raise RuntimeError("tests shouldn't call this")  # pragma: nocover

    def effective_principals(self, request):
        raise RuntimeError("tests shouldn't call this")  # pragma: nocover


class UserTestCase(unittest.TestCase):

    def setUp(self):
        self.config = pyramid.testing.setUp()
        self.config.add_settings({
            "auth.backend": "services.user.memory.MemoryUser",
            'cef.vendor': 'mozilla',
            'cef.device_version': '1.3',
            'cef.product': 'weave',
            'cef.use': True,
            'cef.version': 0,
            'cef.file': 'syslog',
        })
        self.config.include("mozsvc")
        self.config.include("mozsvc.user")
        self.config.set_authorization_policy(ACLAuthorizationPolicy())
        self.config.set_authentication_policy(HeaderAuthenticationPolicy())
        self.auth = self.config.registry["auth"]
        self.auth.create_user("user1", "password1", "test@mozilla.com")

    def tearDown(self):
        pyramid.testing.tearDown()

    def _make_request(self, environ=None, factory=None):
        my_environ = {}
        my_environ["REQUEST_METHOD"] = "GET"
        my_environ["SCRIPT_NAME"] = ""
        my_environ["PATH_INFO"] = "/"
        if environ is not None:
            my_environ.update(environ)
        if factory is None:
            factory = self.config.registry.getUtility(IRequestFactory)
        request = factory(my_environ)
        request.registry = self.config.registry
        return request

    def test_auth_backend_is_loaded(self):
        self.assertEquals(self.config.registry["auth"].__class__.__name__,
                          "MemoryUser")

    def test_authenticate(self):
        request = self._make_request()
        # We have no IAuthenticationPolicy, so initially req.user is False.
        self.assertFalse(request.user)
        # After authenticating, it will be replaced with the user object.
        credentials = {"username": "user1", "password": "password1"}
        mozsvc.user.authenticate(request, credentials)
        self.assertEquals(request.user["username"], "user1")

    def test_authenticate_with_normal_request_object(self):
        request = self._make_request(factory=Request)
        # Initially it has no user attribute.
        self.assertRaises(AttributeError, getattr, request, "user")
        # After authenticating, it will have the user object.
        credentials = {"username": "user1", "password": "password1"}
        mozsvc.user.authenticate(request, credentials)
        self.assertEquals(request.user["username"], "user1")

    def test_authenticate_with_no_backend(self):
        del self.config.registry["auth"]
        request = self._make_request()
        credentials = {"username": "user1", "password": "password1"}
        self.assertFalse(mozsvc.user.authenticate(request, credentials))
        self.assertEquals(request.user, {})

    def test_authenticate_with_repozewho_style_credentials(self):
        request = self._make_request()
        credentials = {"login": "user1", "password": "password1"}
        mozsvc.user.authenticate(request, credentials)
        self.assertEquals(request.user["username"], "user1")

    def test_authenticate_with_bad_password(self):
        request = self._make_request()
        credentials = {"username": "user1", "password": "BAD BAD BAD"}
        self.assertFalse(mozsvc.user.authenticate(request, credentials))
        self.assertEquals(request.user, {})

    def test_authenticate_with_unicode_password(self):
        credentials = {"username": "user1", "password": "password1"}
        new_password = u"password\N{GREEK SMALL LETTER ALPHA}"
        self.auth.update_password({"username": "user1"}, credentials,
                                  new_password)
        # Auth works with unicode password.
        request = self._make_request()
        credentials = {"username": "user1", "password": new_password}
        self.assertTrue(mozsvc.user.authenticate(request, credentials))
        # Auth works with utf-encoded password.
        request = self._make_request()
        credentials = {"username": "user1",
                       "password": new_password.encode("utf8")}
        self.assertTrue(mozsvc.user.authenticate(request, credentials))
        # Auth fails with badly-encoded password
        request = self._make_request()
        credentials = {"username": "user1",
                       "password": new_password.encode("utf16")}
        self.assertFalse(mozsvc.user.authenticate(request, credentials))

    def test_authenticate_with_unknown_username(self):
        request = self._make_request()
        credentials = {"username": "user2", "password": "password1"}
        self.assertFalse(mozsvc.user.authenticate(request, credentials))
        self.assertEquals(request.user, {})

    def test_authenticate_with_no_username(self):
        request = self._make_request()
        credentials = {"usernme": "user2", "password": "password1"}
        self.assertFalse(mozsvc.user.authenticate(request, credentials))
        self.assertEquals(request.user, {})

    def test_includeme_with_bad_backend(self):
        config = pyramid.testing.setUp()
        self.config.add_settings({
            "auth.backend": "this.does.not.exist",
        })
        config.include("mozsvc.user")
        self.assertEquals(config.registry["auth"], None)
        request = self._make_request()
        self.assertEquals(request.user, {})

    def test_req_user_success(self):
        request = self._make_request({
                    "HTTP_X_USERNAME": "user1",
                    "HTTP_X_PASSWORD": "password1",
                  })
        self.assertEquals(request.user["username"], "user1")
        self.assertEquals(request.user.get("password"), None)
        self.assertEquals(request.user["mail"], "test@mozilla.com")
        self.assertEquals(request.user["x-was-ere"], True)

    def test_req_user_bad_password(self):
        request = self._make_request({
                    "HTTP_X_USERNAME": "user1",
                    "HTTP_X_PASSWORD": "random_guess",
                  })
        self.assertFalse(request.user)

    def test_req_user_no_username(self):
        request = self._make_request({
                    "HTTP_X_PASSWORD": "password1",
                  })
        self.assertFalse(request.user)

    def test_req_user_no_password(self):
        request = self._make_request({
                    "HTTP_X_USERNAME": "user1",
                  })
        self.assertFalse(request.user)

    def test_req_user_exposes_repoze_who_identity(self):
        # An existing r.w.i dict is exposed as req.user.
        request = self._make_request({
                    "repoze.who.identity": {"repoze-was-ere": True},
                  })
        self.assertEquals(request.user["repoze-was-ere"], True)
        # Setting a key in req.user also sets it in r.w.i.
        request.user["testing"] = "testing"
        self.assertEquals(request.environ["repoze.who.identity"]["testing"],
                          "testing")
        # Replacing req.user also replaces r.w.i
        request.user = {"replacement": "text"}
        self.assertEquals(request.environ["repoze.who.identity"].keys(),
                          ["replacement"])

    def test_registry_is_stored_in_environment(self):
        request = self._make_request()
        self.assertEquals(self.config.registry, request.registry)
        self.assertEquals(self.config.registry,
                          request.environ["mozsvc.user.registry"])
        del request.environ["mozsvc.user.registry"]
        self.assertRaises(AttributeError, getattr, request, "registry")
