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
# Portions created by the Initial Developer are Copyright (C) 2011
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
"""

Utilities for authentication via a generic user backend.

Include mozsvc.user into your pyramid config to get the following niceties:

    * user database backend loaded as a plugin from "auth" config section
    * user database backend available as request.registry["auth"]
    * authenticated user's data as a dict at request.user

You can also use the function mozsvc.user.authenticate(req, creds) as a
shortcut for authenticating against the configured backend.

"""

from pyramid.decorator import reify
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
    """

    @reify
    def user(self):
        # Create an empty user dict and store it on the request.
        # This makes it available for authenticated_userid to populate.
        user = self.__dict__["user"] = {}
        # Do the authentication through the standard pyramid interface.
        username = authenticated_userid(self)
        if username is not None:
            user["username"] = username
            # Suck in extra information from likely sources.
            # Currently this just looks for a repoze.who identity dict.
            if "repoze.who.identity" in self.environ:
                user.update(self.environ["repoze.who.identity"])
        return user


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
    # In the end, we must have credentials["username"].
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

        * using RequestWithUser as the request object factory
        * loading a user database backend from config section "auth"

    """
    config.set_request_factory(RequestWithUser)
    try:
        config.registry["auth"] = load_and_register("auth", config)
    except Exception, e:
        logger.exception("Unable to load auth backend. Problem? %s" % e)
        config.registry["auth"] = None
