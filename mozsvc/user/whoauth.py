# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****


"""
Integration between mozsvc.user and pyramid_whoauth.
"""

from urlparse import urlparse

from zope.interface import implements

from repoze.who.interfaces import IAuthenticator
from repoze.who.plugins.macauth import MACAuthPlugin

from pyramid.threadlocal import get_current_request

import tokenlib

import mozsvc
import mozsvc.user
import mozsvc.secrets


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
        # Mark the user object as "under construction".
        # Otherwise when the call to mozsvc.user.authenticate() tries to
        # access request.user, it will recurse back into this function.
        environ.setdefault("mozsvc.user.temp_user", {})
        # Authenticate against the backend.  This has the side-effect of
        # setting identity["username"] to the authenticated username.
        if not mozsvc.user.authenticate(request, identity):
            return None
        return identity["username"]


class SagradaMACAuthPlugin(MACAuthPlugin):
    """MAC Auth plugin designed for use with Sagrada auth tokens.

    This is a repoze.who IIdentifier/IAuthenticator/IChallenger that
    consumes Sagrada authentication tokens as described here:

        https://wiki.mozilla.org/Services/Sagrada/TokenServer

    For verification of token signatures, this plugin can use either a
    single fixed secret (via the argument 'secret') or a file mapping
    node hostnames to secrets (via the argument 'secrets_file').  The
    two arguments are mutually exclusive.
    """

    def __init__(self, secret=None, secrets_file=None, **kwds):
        if secret is not None and secrets_file is not None:
            msg = "Can only specify one of 'secret' or 'secrets_file'"
            raise ValueError(msg)
        elif secret is None and  secrets_file is None:
            # Using secret=None will cause tokenlib to use a randomly-generated
            # secret.  This is useful for getting started without having to
            # twiddle any configuration files, but probably not what anyone
            # wants to use long-term.
            msgs = ["WARNING: using a randomly-generated token secret.",
                    "You probably want to set 'secret' or 'secrets_file' in"
                    "the [who.plugin.macauth] section of your configuration"]
            for msg in msgs:
                mozsvc.logger.warn(msg)
        if secrets_file is not None:
            self.secret = None
            self.secrets = mozsvc.secrets.Secrets(secrets_file)
        else:
            self.secret = secret
            self.secrets = None
        super(SagradaMACAuthPlugin, self).__init__(**kwds)

    def decode_mac_id(self, request, id):
        """Decode the MAC id into its secret key and dict of user data.

        This method determines the appropriate secrets to use for the given
        request, then passes them on to tokenlib to handle the given MAC id
        token.

        If the id is invalid then ValueError will be raised.
        """
        # There might be multiple secrets in use, if we're in the
        # process of transitioning from one to another.  Try each
        # until we find one that works.
        secrets = self._get_token_secrets(request)
        for secret in secrets:
            try:
                data = tokenlib.parse_token(id, secret=secret)
                key = tokenlib.get_token_secret(id, secret=secret)
                break
            except ValueError:
                pass
        else:
            raise ValueError("invalid MAC id")
        return key, data

    def encode_mac_id(self, request, data):
        """Encode the given data into a MAC id and secret key.

        This method is essentially the reverse of decode_mac_id.  It is
        not needed for consuming authentication tokens, but is very useful
        when building them for testing purposes.
        """
        # There might be multiple secrets in use, if we're in the
        # process of transitioning from one to another.  Always use
        # the last one aka the "most recent" secret.
        secret = self._get_token_secrets(request)[-1]
        id = tokenlib.make_token(data, secret=secret)
        key = tokenlib.get_token_secret(id, secret=secret)
        return id, key

    def _get_token_secrets(self, request):
        """Get the list of possible secrets for signing tokens."""
        if self.secrets is None:
            return [self.secret]
        # Secrets are looked up by hostname.
        # We need to normalize some port information for this work right.
        node_name = request.host_url
        host_url = urlparse(request.host_url)
        if host_url.scheme == "http" and host_url.port == 80:
            assert node_name.endswith(":80")
            node_name = node_name[:-3]
        elif host_url.scheme == "http" and host_url.port == 443:
            assert node_name.endswith(":443")
            node_name = node_name[:-4]
        return self.secrets.get(node_name)


def configure_who_defaults(config):
    """Configure default settings for authentication via repoze.who.

    This function takes a Configurator object using pyramid_whoauth and
    applies some default settings to authenticate against the configured
    user database backend.  Specifically:

        * add a plugin to identify/challenge/authenticate using Sagrada
          MAC Auth tokens.

        * if there is a configured authentication backend, add a plugin to
          authenticate against it.

        * if there is a configured authentication backend, add a plugin to
          identify/challenge using HTTP Basic Auth.

    All of these defaults may be overridden in the application config file.
    """
    settings = config.registry.settings
    BACKENDAUTH_DEFAULTS = {
        "use": "mozsvc.user.whoauth:BackendAuthPlugin"
    }
    for key, value in BACKENDAUTH_DEFAULTS.iteritems():
        settings.setdefault("who.plugin.backend." + key, value)
    BASICAUTH_DEFAULTS = {
        "use": "repoze.who.plugins.basicauth:make_plugin",
        "realm": "Sync",
    }
    for key, value in BASICAUTH_DEFAULTS.iteritems():
        settings.setdefault("who.plugin.basicauth." + key, value)
    MACAUTH_DEFAULTS = {
        "use": "mozsvc.user.whoauth:SagradaMACAuthPlugin",
    }
    for key, value in MACAUTH_DEFAULTS.iteritems():
        settings.setdefault("who.plugin.macauth." + key, value)
    # If there is an auth backend, enable basicauth by default.
    # Enable macauth by default regardless, since it doesn't need a backend.
    if config.registry.get("auth") is not None:
        settings.setdefault("who.authenticators.plugins", "backend macauth")
        settings.setdefault("who.identifiers.plugins", "basicauth macauth")
        settings.setdefault("who.challengers.plugins", "basicauth macauth")
    else:
        settings.setdefault("who.authenticators.plugins", "macauth")
        settings.setdefault("who.identifiers.plugins", "macauth")
        settings.setdefault("who.challengers.plugins", "macauth")


def includeme(config):
    # Make sure mozsvc.user is being used.
    # If already included then this is a no-op.
    config.include("mozsvc.user")

    # Set sensible default settings for whoauth.
    configure_who_defaults(config)

    # Use pyramid_whoauth for the authentication.
    config.include("pyramid_whoauth")
