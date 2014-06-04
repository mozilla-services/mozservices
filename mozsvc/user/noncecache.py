# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
"""

Class for storing hawkauth nonces in memcached.

"""

import time
import math
from hashlib import sha1
from base64 import urlsafe_b64encode

from mozsvc.storage.mcclient import MemcachedClient


DEFAULT_TIMESTAMP_WINDOW = 60


class MemcachedNonceCache(object):
    """Object for managing a cache of used nonce values in memcached.

    This class allow easy timestamp-based management of client-generated
    nonces for hawkauthlib.

    It stores the nonces in memcached so that they can be shared between
    different webserver processes.  Each timestamp+nonce combo is stored
    under a key sha1(<timestamp>:<nonce>).
    """

    def __init__(self, window=None, get_time=None, cache_server=None,
                 cache_key_prefix="noncecache:", cache_pool_size=None,
                 cache_pool_timeout=60, **kwds):
        # Memcached ttls are in integer seconds, so round up to the nearest.
        if window is None:
            window = DEFAULT_TIMESTAMP_WINDOW
        else:
            window = int(math.ceil(window))
        self.window = window
        self.get_time = get_time or time.time
        self.mcclient = MemcachedClient(cache_server, cache_key_prefix,
                                        cache_pool_size, cache_pool_timeout)

    def __len__(self):
        raise NotImplementedError

    def check_nonce(self, timestamp, nonce):
        """Check if the given timestamp+nonce is fresh.

        This method checks that the given timestamp is within the configured
        time window, and that the given nonce has not previously been seen
        with that timestamp.  It returns True if the nonce is fresh and False
        if it is stale.

        Fresh nonces are stored in memcache so that subsequent checks of the
        same nonce will return False.
        """
        now = self.get_time()
        # Check if the timestamp is within the configured window.
        ts_min = now - self.window
        ts_max = now + self.window
        if not ts_min < timestamp < ts_max:
            return False
        # Check if it's in memcached, adding it if not.
        # Fortunately memcached 'add' has precisely the right semantics
        # of "create if not exists"
        key = urlsafe_b64encode(sha1("%d:%s" % (timestamp, nonce)).digest())
        try:
            if not self.mcclient.add(key, 1, time=self.window):
                return False
        except ValueError:
            return False
        # Successfully added, the nonce must be fresh.
        return True
