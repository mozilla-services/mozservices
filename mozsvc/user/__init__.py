# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****
"""

Utilities for authentication via Mozilla's TokenServer auth system.

"""

from zope.interface import implements

from pyramid.request import Request
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid.interfaces import IAuthenticationPolicy
from pyramid.httpexceptions import HTTPUnauthorized

from pyramid_hawkauth import HawkAuthenticationPolicy

import tokenlib

import mozsvc
import mozsvc.secrets
from mozsvc.util import resolve_name
from mozsvc.user.permissivenoncecache import PermissiveNonceCache

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
            userid = self.authenticated_userid
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


class TokenServerAuthenticationPolicy(HawkAuthenticationPolicy):
    """Pyramid authentication policy for use with Tokenserver auth tokens.

    This class provides an IAuthenticationPolicy implementation based on
    the Mozilla TokenServer authentication tokens as described here:

        https://docs.services.mozilla.com/token/

    For verification of token signatures, this plugin can use either a
    single fixed secret (via the argument 'secret') or a file mapping
    node hostnames to secrets (via the argument 'secrets_file').  The
    two arguments are mutually exclusive.
    """

    implements(IAuthenticationPolicy)

    def __init__(self, secrets=None, **kwds):
        if not secrets:
            # Using secret=None will cause tokenlib to use a randomly-generated
            # secret.  This is useful for getting started without having to
            # twiddle any configuration files, but probably not what anyone
            # wants to use long-term.
            secrets = None
            msgs = ["WARNING: using a randomly-generated token secret.",
                    "You probably want to set 'secret' or 'secrets_file' in "
                    "the [hawkauth] section of your configuration"]
            for msg in msgs:
                mozsvc.logger.warn(msg)
        elif isinstance(secrets, (basestring, list)):
            secrets = mozsvc.secrets.FixedSecrets(secrets)
        elif isinstance(secrets, dict):
            secrets = resolve_name(secrets.pop("backend"))(**secrets)
        self.secrets = secrets
        if kwds.get("nonce_cache") is None:
            kwds["nonce_cache"] = PermissiveNonceCache()
        super(TokenServerAuthenticationPolicy, self).__init__(**kwds)

    @classmethod
    def _parse_settings(cls, settings):
        """Parse settings for an instance of this class."""
        supercls = super(TokenServerAuthenticationPolicy, cls)
        kwds = supercls._parse_settings(settings)
        # collect leftover settings into a config for a Secrets object,
        # wtih some b/w compat for old-style secret-handling settings.
        secrets_prefix = "secrets."
        secrets = {}
        if "secrets_file" in settings:
            if "secret" in settings:
                raise ValueError("can't use both 'secret' and 'secrets_file'")
            secrets["backend"] = "mozsvc.secrets.Secrets"
            secrets["filename"] = settings.pop("secrets_file")
        elif "secret" in settings:
            secrets["backend"] = "mozsvc.secrets.FixedSecrets"
            secrets["secrets"] = settings.pop("secret")
        for name in settings.keys():
            if name.startswith(secrets_prefix):
                secrets[name[len(secrets_prefix):]] = settings.pop(name)
        kwds['secrets'] = secrets
        return kwds

    def _check_signature(self, request, key):
        """Check the Hawk auth signature on the request.

        This method checks the Hawk signature on the request against the
        supplied signing key.  If missing or invalid then HTTPUnauthorized
        is raised.

        The TokenServerAuthenticationPolicy implementation wraps the default
        HawkAuthenticationPolicy implementation with some logging.
        """
        supercls = super(TokenServerAuthenticationPolicy, self)
        try:
            return supercls._check_signature(request, key)
        except HTTPUnauthorized:
            logger.warn("Authentication Failed: invalid hawk signature")
            raise

    def decode_hawk_id(self, request, tokenid):
        """Decode a Hawk token id into its userid and secret key.

        This method determines the appropriate secrets to use for the given
        request, then passes them on to tokenlib to handle the given Hawk
        token.

        If the id is invalid then ValueError will be raised.
        """
        # There might be multiple secrets in use, if we're in the
        # process of transitioning from one to another.  Try each
        # until we find one that works.
        node_name = self._get_node_name(request)
        secrets = self._get_token_secrets(node_name)
        for secret in secrets:
            try:
                data = tokenlib.parse_token(tokenid, secret=secret)
                userid = data["uid"]
                token_node_name = data["node"]
                if token_node_name != node_name:
                    raise ValueError("incorrect node for this token")
                key = tokenlib.get_derived_secret(tokenid, secret=secret)
                break
            except (ValueError, KeyError):
                pass
        else:
            logger.warn("Authentication Failed: invalid hawk id")
            raise ValueError("invalid Hawk id")
        return userid, key

    def encode_hawk_id(self, request, userid):
        """Encode the given userid into a Hawk id and secret key.

        This method is essentially the reverse of decode_hawk_id.  It is
        not needed for consuming authentication tokens, but is very useful
        when building them for testing purposes.
        """
        node_name = self._get_node_name(request)
        # There might be multiple secrets in use, if we're in the
        # process of transitioning from one to another.  Always use
        # the last one aka the "most recent" secret.
        secret = self._get_token_secrets(node_name)[-1]
        data = {"uid": userid, "node": node_name}
        tokenid = tokenlib.make_token(data, secret=secret)
        key = tokenlib.get_derived_secret(tokenid, secret=secret)
        return tokenid, key

    def _get_node_name(self, request):
        """Get the canonical node name for the given request."""
        # Secrets are looked up by hostname.
        # We need to normalize some port information for this work right.
        node_name = request.host_url
        if node_name.startswith("http:") and node_name.endswith(":80"):
            node_name = node_name[:-3]
        elif node_name.startswith("https:") and node_name.endswith(":443"):
            node_name = node_name[:-4]
        return node_name + request.script_name

    def _get_token_secrets(self, node_name):
        """Get the list of possible secrets for signing tokens."""
        if self.secrets is None:
            return [None]
        return self.secrets.get(node_name)


def includeme(config):
    """Include mozsvc user-handling into a pyramid config.

    This function will set up user-handling via the mozsvc.user system.
    Things configured include:

        * use RequestWithUser as the request object factory
        * use TokenServerAuthenticationPolicy as the default authn policy

    """
    # Use RequestWithUser as the request object factory.
    config.set_request_factory(RequestWithUser)

    # Hook up a default AuthorizationPolicy.
    # ACLAuthorizationPolicy is usually what you want.
    # If the app configures one explicitly then this will get overridden.
    # In auto-commit mode this needs to be set before adding an authn policy.
    authz_policy = ACLAuthorizationPolicy()
    config.set_authorization_policy(authz_policy)

    # Build a TokenServerAuthenticationPolicy from the deployment settings.
    settings = config.get_settings()
    authn_policy = TokenServerAuthenticationPolicy.from_settings(settings)
    config.set_authentication_policy(authn_policy)

    # Set the forbidden view to use the challenge() method from the policy.
    config.add_forbidden_view(authn_policy.challenge)
