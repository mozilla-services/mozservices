# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
"""

Class for storing macauth nonces in memcached.

"""

import time
import math
from hashlib import sha1
from base64 import urlsafe_b64encode

from mozsvc.storage.mcclient import MemcachedClient


DEFAULT_NONCE_TTL = 30  # 30 seconds
DEFAULT_ID_TTL = 3660   # 1 hour


class MemcachedNonceCache(object):
    """Object for managing a cache of used nonce values in memcached.

    This class allow easy timestamp-based management of client-generated
    nonces according to the rules of RFC-TODO:

        * Maintain a measure of clock skew for each MAC id.
        * Reject nonces with a timestamp outside the configured range.
        * Reject nonces that have already been seen.

    It stores the nonces in memcached so that they can be shared between
    different webserver processes.  The clock-skew for each id token is
    stored under they key sha1(<id>:skew), while each nonce seen for the id
    is marked by a key sha1(<id>:nonce:<timestamp>:<nonce>).

    NOTE: the "MAC id" here corresponds to the full authentication token
    issues by the tokenserver, not to the numeric userid of an individual
    user.  So it is entirely possible to have multiple skew records for
    each user, corresponding to different active tokens.
    """

    def __init__(self, nonce_ttl=None, id_ttl=None, cache_servers=None,
                 cache_key_prefix="noncecache:", cache_pool_size=None,
                 cache_pool_timeout=60, **kwds):
        # Memcached ttls are in integer seconds, so round up to the nearest.
        if nonce_ttl is None:
            nonce_ttl = DEFAULT_NONCE_TTL
        else:
            nonce_ttl = int(math.ceil(nonce_ttl))
        if id_ttl is None:
            id_ttl = DEFAULT_ID_TTL
        else:
            id_ttl = int(math.ceil(id_ttl))
        self.nonce_ttl = nonce_ttl
        self.id_ttl = id_ttl
        self.mcclient = MemcachedClient(cache_servers, cache_key_prefix,
                                        cache_pool_size, cache_pool_timeout)

    def _key(self, *names):
        """Get a memcached key built from the given component names.

        This method returns the memcached key to use for the given component
        names, by contatentating them together and then hashing them.  The
        hashing serves both to ensure confidentiality of the macauth tokens
        store in memcached, and the reduce the size of the keys.
        """
        return urlsafe_b64encode(sha1(":".join(names)).digest())

    def check_nonce(self, id, timestamp, nonce):
        """Check if the given timestamp+nonce is fresh for the given id.

        This method checks that the given timestamp+nonce has not previously
        been seen for the given id.  It returns True if the nonce is fresh
        and False if not.

        Fresh nonces are added to the cache, so that subsequent checks of the
        same nonce will return False.
        """
        # We want to fetch the recorded clock skew for this id, along with
        # any existing cache entry for the provided nonce.
        key_skew = self._key(id, "skew")
        key_nonce = self._key(id, "nonce", str(timestamp), nonce)
        # Use get_multi to fetch both keys in a single request.
        # If the data appears to be corrupted then fail out for safety.
        try:
            cached = self.mcclient.get_multi([key_skew, key_nonce])
        except ValueError:
            return False
        # If the nonce appears in the cache, it must be stale.
        if key_nonce in cached:
            return False
        # If we've never recorded a clock skew for this id, record it now.
        try:
            skew = cached[key_skew]
        except KeyError:
            skew = int(time.time() - timestamp)
            self.mcclient.add(key_skew, skew, time=self.id_ttl)
        # If the adjusted timestamp is too old or too new, it is stale.
        # XXX TODO: we should use a monotonic clock here.
        if abs(timestamp + skew - time.time()) >= self.nonce_ttl:
            return False
        # The nonce is fresh, add it into the cache.
        self.mcclient.add(key_nonce, True, time=self.nonce_ttl)
        return True
