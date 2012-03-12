# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****


"""

Utilities for authentication via a generic user backend.

Include mozsvc.user into your pyramid config to get the following niceties:

    * user database backend loaded as a plugin from "auth" config section
    * user database backend available as request.registry["auth"]
    * authenticated user's data as a dict at request.user

You can also use the function mozsvc.user.authenticate(req, creds) as a
shortcut for authenticating against the configured backend, which is useful
for writing your own authentication plugins.

This module is also designed to "play nice" with authentication schemes using
repoze.who and the pyramid_whoauth package.  For example, the request.user
attribute actually just exposes environ["repoze.who.identity"].  For some
additional integration with pyramid_whoauth, see the mozsvc.user.whoauth
module.

"""

from pyramid.request import Request
from pyramid.security import authenticated_userid

from cef import log_cef, AUTH_FAILURE

from mozsvc.plugin import load_and_register

import logging
logger = logging.getLogger("mozsvc.user")


class RequestWithUser(Request):
    """Request object that exposes the current user as "request.user".

    This is a custom Pyramid Request class that does user authentication
    on demand.  When you access the "user" attribute it will automatically
    search for credentials in the request, authenticate them, create a dict
    of user data and return it.

    If there are no credentials in the request then the "user" attribute will
    be an empty dict.  If the call to authenticated_userid() raises an error
    it will *not* be intercepted, you will receive it as an error from the
    attribute access attempt.

    This class also provides some conveniences for integrating with repoze.who,
    by storing the registry and user object in the WSGI environ rather than on
    the request object itself.  This lets us write repoze.who plugins that can
    access the higher-level pyramid config data.
    """

    # Expose the "repoze.who.identity" dict as request.user.
    # This allows for convenient integration between pyramid-level code
    # and repoze.who plugins.

    def _get_user(self):
        # Return an existing identity if there is one.
        user = self.environ.get("repoze.who.identity")
        if user is not None:
            return user

        # Return an under-construction identity if there is one.
        # This lets pyramid-level auth plugins store stuff in req.user.
        user = self.environ.get("mozsvc.user.temp_user")
        if user is not None:
            return user

        # Otherwise, we need to authenticate.
        # Do it through the standard pyramid interface, while providing an
        # under-construction user dict for plugins to scribble on.
        extra = self.environ["mozsvc.user.temp_user"] = {}
        try:
            username = authenticated_userid(self)
        finally:
            self.environ.pop("mozsvc.user.temp_user", None)

        # Now that we've authed, cached the result as repoze.who.identity.
        # For a successful auth it might already exist.  For a failed auth
        # we set it to the empty dict.
        user = self.environ.get("repoze.who.identity")
        if user is None:
            user = self.environ["repoze.who.identity"] = {}

        # If the auth was successful, make sure the identity contains
        # all the expected keys.
        if username is not None:
            user.update(extra)
            user.setdefault("username", username)
            user.setdefault("repoze.who.userid", username)
        return user

    def _set_user(self, user):
        self.environ["repoze.who.identity"] = user

    user = property(_get_user, _set_user)

    # Store the pyramid application registry in the WSGI environ.
    # This allows repoze.who plugins to access pyramid config despite
    # the fact that they aren't passed a request object.

    def _get_registry(self):
        try:
            return self.environ["mozsvc.user.registry"]
        except KeyError:
            raise AttributeError("registry")

    def _set_registry(self, registry):
        self.environ["mozsvc.user.registry"] = registry
        self.__dict__["registry"] = registry

    registry = property(_get_registry, _set_registry)


def authenticate(request, credentials, attrs=()):
    """Authenticate a dict of credentials against the configured user backend.

    This is a handy callback that you can use to check a dict of credentials
    against the configured auth backend.  It will accept credentials from any
    of the auth schemes supported by the backend.  If the authentication is
    successful it will update request.user with the user object loaded from
    the backend.
    """
    # Use whatever auth backend has been configured.
    auth = request.registry.get("auth")
    if auth is None:
        return False

    # Update an existing user object if one exists on the request.
    user = getattr(request, "user", None)
    if user is None:
        user = {}

    # Ensure that we have credentials["username"] for use by the backend.
    # Some repoze.who plugins like to use "login" instead of "username".
    if "username" not in credentials:
        if "login" in credentials:
            credentials["username"] = credentials.pop("login")
        else:
            log_cef("Authentication attemped without username", 5,
                    request.environ, request.registry.settings,
                    "", signature=AUTH_FAILURE)
            return False

    # Normalize the password, if any, to be unicode.
    password = credentials.get("password")
    if password is not None and not isinstance(password, unicode):
        try:
            credentials["password"] = password.decode("utf8")
        except UnicodeDecodeError:
            return None

    # Authenticate against the configured backend.
    if not auth.authenticate_user(user, credentials, attrs):
        log_cef("Authentication Failed", 5,
                request.environ, request.registry.settings,
                credentials["username"],
                signature=AUTH_FAILURE)
        return False

    # Store the user dict on the request, and return it for conveience.
    if getattr(request, "user", None) is None:
        request.user = user
    return user


def includeme(config):
    """Include mozsvc user-handling into a pyramid config.

    This function will set up user-handling via the mozsvc.user system.
    Things configured include:

        * use RequestWithUser as the request object factory
        * load a user database backend from config section "auth"

    """
    config.set_request_factory(RequestWithUser)
    try:
        config.registry["auth"] = load_and_register("auth", config)
    except Exception, e:
        logger.warning("Unable to load auth backend. Problem? %s" % e)
        config.registry["auth"] = None
