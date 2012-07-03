# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****
"""

Utilities for authentication via the Sagrada auth system.

"""

from zope.interface import implements

from pyramid.request import Request
from pyramid.security import authenticated_userid
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid.interfaces import IAuthenticationPolicy
from pyramid.httpexceptions import HTTPUnauthorized

from pyramid_macauth import MACAuthenticationPolicy

import tokenlib

from cef import log_cef, AUTH_FAILURE

import mozsvc
import mozsvc.secrets

import logging
logger = logging.getLogger("mozsvc.user")


ENVIRON_KEY_IDENTITY = "mozsvc.user.identity"


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

    def _get_user(self):
        # Return an existing identity if there is one.
        user = self.environ.get(ENVIRON_KEY_IDENTITY)
        if user is not None:
            return user
        # Put an empty identity dict in place before calling the authn policy.
        # This lets the policy store stuff in req.user.
        user = self.environ[ENVIRON_KEY_IDENTITY] = {}
        # Call the standard authn framework to authenticate.
        try:
            userid = authenticated_userid(self)
        except Exception:
            self.environ.pop(ENVIRON_KEY_IDENTITY, None)
            raise
        # If the auth was successful, store the userid in the identity.
        if userid is not None:
            user.setdefault("uid", userid)
        return user

    def _set_user(self, user):
        self.environ["mozsvc.user.identity"] = user

    user = property(_get_user, _set_user)


class SagradaAuthenticationPolicy(MACAuthenticationPolicy):
    """Pyramid authentication policy for use with Sagrada auth tokens.

    This class provides an IAuthenticationPolicy implementation based on
    Sagrada authentication tokens as described here:

        https://wiki.mozilla.org/Services/Sagrada/TokenServer

    For verification of token signatures, this plugin can use either a
    single fixed secret (via the argument 'secret') or a file mapping
    node hostnames to secrets (via the argument 'secrets_file').  The
    two arguments are mutually exclusive.
    """

    implements(IAuthenticationPolicy)

    def __init__(self, secret=None, secrets_file=None, **kwds):
        if secret is not None and secrets_file is not None:
            msg = "Can only specify one of 'secret' or 'secrets_file'"
            raise ValueError(msg)
        elif secret is None and secrets_file is None:
            # Using secret=None will cause tokenlib to use a randomly-generated
            # secret.  This is useful for getting started without having to
            # twiddle any configuration files, but probably not what anyone
            # wants to use long-term.
            msgs = ["WARNING: using a randomly-generated token secret.",
                    "You probably want to set 'secret' or 'secrets_file' in"
                    "the [macauth] section of your configuration"]
            for msg in msgs:
                mozsvc.logger.warn(msg)
        if secrets_file is not None:
            self.secret = None
            self.secrets = mozsvc.secrets.Secrets(secrets_file)
        else:
            self.secret = secret
            self.secrets = None
        super(SagradaAuthenticationPolicy, self).__init__(**kwds)

    @classmethod
    def _parse_settings(cls, settings):
        """Parse settings for an instance of this class."""
        supercls = super(SagradaAuthenticationPolicy, cls)
        kwds = supercls._parse_settings(settings)
        for setting in ("secret", "secrets_file"):
            if setting in settings:
                kwds[setting] = settings.pop(setting)
        return kwds

    def _check_signature(self, request, key):
        """Check the MACAuth signature on the request.

        This method checks the MAC signature on the request against the
        supplied signing key.  If missing or invalid then HTTPUnauthorized
        is raised.

        The SagradaAuthenticationPolicy implementation wraps the default
        MACAuthenticationPolicy implementation with some cef logging.
        """
        supercls = super(SagradaAuthenticationPolicy, self)
        try:
            return supercls._check_signature(request, key)
        except HTTPUnauthorized:
            log_cef("Authentication Failed: invalid MAC signature", 5,
                    request.environ, request.registry.settings,
                    "", signature=AUTH_FAILURE)
            raise

    def decode_mac_id(self, request, tokenid):
        """Decode a MACAuth token id into its userid and MAC secret key.

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
                data = tokenlib.parse_token(tokenid, secret=secret)
                userid = data["uid"]
                key = tokenlib.get_token_secret(tokenid, secret=secret)
                break
            except (ValueError, KeyError):
                pass
        else:
            log_cef("Authentication Failed: invalid MAC id", 5,
                    request.environ, request.registry.settings,
                    "", signature=AUTH_FAILURE)
            raise ValueError("invalid MAC id")
        return userid, key

    def encode_mac_id(self, request, userid):
        """Encode the given userid into a MAC id and secret key.

        This method is essentially the reverse of decode_mac_id.  It is
        not needed for consuming authentication tokens, but is very useful
        when building them for testing purposes.
        """
        # There might be multiple secrets in use, if we're in the
        # process of transitioning from one to another.  Always use
        # the last one aka the "most recent" secret.
        secret = self._get_token_secrets(request)[-1]
        tokenid = tokenlib.make_token({"uid": userid}, secret=secret)
        key = tokenlib.get_token_secret(tokenid, secret=secret)
        return tokenid, key

    def _get_token_secrets(self, request):
        """Get the list of possible secrets for signing tokens."""
        if self.secrets is None:
            return [self.secret]
        # Secrets are looked up by hostname.
        # We need to normalize some port information for this work right.
        node_name = request.host_url
        if node_name.startswith("http:") and node_name.endswith(":80"):
            node_name = node_name[:-3]
        elif node_name.startswith("https:") and node_name.endswith(":443"):
            node_name = node_name[:-4]
        return self.secrets.get(node_name)


def includeme(config):
    """Include mozsvc user-handling into a pyramid config.

    This function will set up user-handling via the mozsvc.user system.
    Things configured include:

        * use RequestWithUser as the request object factory
        * use SagradaAuthenticationPolicy as the default authn policy

    """
    # Use RequestWithUser as the request object factory.
    config.set_request_factory(RequestWithUser)

    # Hook up a default AuthorizationPolicy.
    # ACLAuthorizationPolicy is usually what you want.
    # If the app configures one explicitly then this will get overridden.
    # In auto-commit mode this needs to be set before adding an authn policy.
    authz_policy = ACLAuthorizationPolicy()
    config.set_authorization_policy(authz_policy)

    # Build a SagradaAuthenticationPolicy from the deployment settings.
    settings = config.get_settings()
    authn_policy = SagradaAuthenticationPolicy.from_settings(settings)
    config.set_authentication_policy(authn_policy)

    # Set the forbidden view to use the challenge() method from the policy.
    config.add_forbidden_view(authn_policy.challenge)
