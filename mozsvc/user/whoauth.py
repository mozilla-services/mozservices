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
# The Original Code is mozservices
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

Integration between mozsvc.user and pyramid_whoauth.

"""

from zope.interface import implements

from repoze.who.interfaces import IAuthenticator
from repoze.who.plugins.basicauth import BasicAuthPlugin

from pyramid.interfaces import IAuthenticationPolicy, PHASE2_CONFIG
from pyramid.threadlocal import get_current_request

import mozsvc.user


class BackendAuthPlugin(object):
    """IAuthenticator plugin using mozsvc.user.authenticate().

    This is a repoze.who IAuthenticator plugin that checks user credentials
    against the mozsvc user database backend.  You must configure a backend
    for your application and should probably use mozsvc.user.RequestWithUser
    as your request factory.
    """
    implements(IAuthenticator)

    def authenticate(self, environ, identity):
        # We need a pyramid Request object to pass to the authenticator.
        # If mozsvc.user.RequestWithUser is being used as the request factory
        # then we can re-create the request object from the environ.  If not
        # then we will need to pull it out of the threadlocals.
        if "mozsvc.user.registry" in environ:
            request = mozsvc.user.RequestWithUser(environ)
        else:
            request = get_current_request()
        # Authenticate against the backend.  This has the side-effect of
        # setting identity["username"] to the authenticated username.
        if not mozsvc.user.authenticate(request, identity):
            return None
        return identity["username"]


def configure_who_defaults(config):
    """Configure default settings for authentication via repoze.who.

    This function takes a Configurator containing a pyramid_whoauth authn
    policy, and applies some default settings to authenticate against the
    configured user database backend.  Specifically:

        * if no authenticators are configured, create one to authenticate
          against the user database backend.

        * if no identifiers or challengers are configured, create a
          basic-auth plugin and use it.

    Eventually this will introspect the backend and add plugins for each auth
    scheme that it supports.
    """
    # Due to the way pyramid's configurator handles conflict resolution,
    # it's entirely possible for this to be called when there's no suitable
    # authentication policy.  Handle such situations gracefully.
    try:
        authn_policy = config.registry.queryUtility(IAuthenticationPolicy)
        api_factory = authn_policy.api_factory
    except AttributeError:
        return
    # If there are no authenticators, set one up using the backend.
    if not api_factory.authenticators:
        api_factory.authenticators.append(("backend", BackendAuthPlugin()))
    # If there are no identifiers and no challengers, set up basic auth.
    if not api_factory.identifiers and not api_factory.challengers:
        basic = BasicAuthPlugin(realm="Sync")
        api_factory.identifiers.append(("basic", basic))
        api_factory.challengers.append(("basic", basic))


def includeme(config):
    # Make sure mozsvc.user is being used.
    # If already included then this is a no-op.
    config.include("mozsvc.user")

    # Use pyramid_whoauth for the authentication.
    config.include("pyramid_whoauth")

    # Use a callback to set sensible defaults at config commit time.
    def do_configure_who_defaults():
        configure_who_defaults(config)
    config.action(None, do_configure_who_defaults, order=PHASE2_CONFIG)
