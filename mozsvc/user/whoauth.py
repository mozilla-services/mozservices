# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
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

    This function takes a Configurator object using pyramid_whoauth and
    applies some default settings to authenticate against the configured
    user database backend.  Specifically:

        * if no authenticators are configured, create one to authenticate
          against the user database backend.

        * if no identifiers or challengers are configured, create a
          basic-auth plugin and use it.

    Eventually this will introspect the backend and add plugins for each auth
    scheme that it supports.
    """
    settings = config.registry.settings
    # Add settings for a plugin named "backend".
    BACKENDAUTH_DEFAULTS = {
        "use": "mozsvc.user.whoauth:BackendAuthPlugin"
    }
    for key, value in BACKENDAUTH_DEFAULTS.iteritems():
        settings.setdefault("who.plugin.backend." + key, value)
    # Add settings for a plugin named "basicauth".
    BASICAUTH_DEFAULTS = {
        "use": "repoze.who.plugins.basicauth:make_plugin",
        "realm": "Sync",
    }
    for key, value in BASICAUTH_DEFAULTS.iteritems():
        settings.setdefault("who.plugin.basic." + key, value)
    # Use "backend" as the default authenticator.
    settings.setdefault("who.authenticators.plugins", "backend")
    # Use "basic" as the default identifier and challenger.
    settings.setdefault("who.identifiers.plugins", "basic")
    settings.setdefault("who.challengers.plugins", "basic")


def includeme(config):
    # Make sure mozsvc.user is being used.
    # If already included then this is a no-op.
    config.include("mozsvc.user")

    # Set sensible default settings for whoauth.
    configure_who_defaults(config)

    # Use pyramid_whoauth for the authentication.
    config.include("pyramid_whoauth")
