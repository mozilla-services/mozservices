# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Simplified API for accessing memcached.

This module builds upon the pylibmc.Client class to provide a slightly
higher-level interface to memcached.  It offers useful default behaviours
for serialization, error reporting and connection pooling.
"""

import sys
import time
import json
import traceback
import contextlib
import Queue

import pylibmc

from pyramid.threadlocal import get_current_registry

from mozsvc.exceptions import BackendError


class MemcachedClient(object):
    """Helper class for interfacing with pylibmc.

    This class provides the basic methods of the pylibmc.Client class, but
    wraps them with some extra functionality:

        * all values are transparently serialized via JSON instead of pickle.
        * connections are taken from an underlying pool.
        * errors are converted into BackendError instances.
        * cas() transparently falls back to add() when appropriate.

    """

    def __init__(self, servers=None, key_prefix="", pool_size=None,
                 pool_timeout=60, **kwds):
        if servers is None:
            servers = ["127.0.0.1:11211"]
        elif isinstance(servers, basestring):
            servers = [servers]
        self.key_prefix = key_prefix
        master = pylibmc.Client(servers, behaviors={"cas": 1})
        self.pool = MCClientPool(master, pool_size, pool_timeout)

    @property
    def logger(self):
        return get_current_registry()["metlog"]

    @contextlib.contextmanager
    def _connect(self):
        """Context mananager for getting a connection to memcached."""
        with self.pool.reserve() as mc:
            try:
                yield mc
            except pylibmc.Error, err:
                err = traceback.format_exc()
                self.logger.error(err)
                raise BackendError(str(err))

    def get(self, key):
        """Get the value stored under the given key."""
        with self._connect() as mc:
            data = mc.get(self.key_prefix + key)
        if data is not None:
            data = json.loads(data)
        return data

    def gets(self, key):
        """Get the current value and casid for the given key."""
        with self._connect() as mc:
            # Some libmemcached setups appear to be buggy here, raising
            # NotFound instead of returning None.  Work around them.
            try:
                data, casid = mc.gets(self.key_prefix + key)
            except pylibmc.NotFound:
                data = casid = None
        if data is not None:
            data = json.loads(data)
        return data, casid

    def get_multi(self, keys):
        """Get the values stored under the given keys in a single request."""
        with self._connect() as mc:
            myitems = mc.get_multi([self.key_prefix + key for key in keys])
        items = {}
        for key, value in myitems.iteritems():
            assert key.startswith(self.key_prefix)
            items[key[len(self.key_prefix):]] = json.loads(value)
        return items

    def set(self, key, value, **kwds):
        """Set the value stored under the given key."""
        data = json.dumps(value)
        with self._connect() as mc:
            res = mc.set(self.key_prefix + key, data, **kwds)
        return res

    def add(self, key, value, **kwds):
        """Add the given key to memcached if not already present."""
        data = json.dumps(value)
        with self._connect() as mc:
            res = mc.add(self.key_prefix + key, data, **kwds)
        return res

    def cas(self, key, value, casid, **kwds):
        """Set the value stored under the given key if casid matches."""
        data = json.dumps(value)
        with self._connect() as mc:
            # Memcached's CAS only works properly on existing keys.
            # Fortunately ADD has the same semantics for missing keys.
            if casid is None:
                res = mc.add(self.key_prefix + key, data, **kwds)
            else:
                res = mc.cas(self.key_prefix + key, data, casid, **kwds)
        return res

    def delete(self, key):
        """Delete the value stored under the given key."""
        with self._connect() as mc:
            try:
                res = mc.delete(self.key_prefix + key)
            except pylibmc.NotFound:
                res = False
        return res

    def flush_all(self):
        """Delete all keys from memcached.  Obviously very dangerous..."""
        with self._connect() as mc:
            return mc.flush_all()


# Sentinel used to mark an empty slot in the MCClientPool queue.
# Using sys.maxint as the timestamp ensures that empty slots will always
# sort *after* live connection objects in the queue.
EMPTY_SLOT = (sys.maxint, None)


class MCClientPool(object):
    """Pool of pylibmc.Client objects, with periodic purging of connections.

    This class implements roughly the same interface as pylibmc.ClientPool,
    but it includes functionality to periodically close and refresh the
    pooled Client objects.  This seems to work around some occasional hangs
    that were occurring with long-lived clients.

    To initialise the pool you must provide a master Client object from which
    pool entries will be cloned.  You may also specify the maximum size of the
    pool and the time after which old connections will be recycled.

    To obtain a Client object from the pool, call reserve() as a context
    manager like this::

        with pool.reserve() as mc:
            mc.set("hello", "world")
            assert ms.get("hello") == "world"

    """

    def __init__(self, master, maxsize=None, timeout=60):
        self.master = master
        self.maxsize = maxsize
        self.timeout = timeout
        # Use a synchronized Queue class to hold the active client objects.
        # It will contain tuples (connection_timestamp, client).
        # Using a PriorityQueue ensures that the oldest connection is always
        # used first, allowing them to be closed out when stale.  It also means
        # that a no-maxsize pool can grow and shink according to demand, as old
        # connections are expired and not replaced.
        self.clients = Queue.PriorityQueue(maxsize)
        # If there is a maxsize, prime the queue with empty slots.
        if maxsize is not None:
            for _ in xrange(maxsize):
                self.clients.put(EMPTY_SLOT)

    @contextlib.contextmanager
    def reserve(self):
        """Context-manager to obtain a Client object from the pool."""
        ts, client = self._checkout_connection()
        try:
            yield client
        finally:
            self._checkin_connection(ts, client)

    def _checkout_connection(self):
        """Checkout a connection from the pool.

        This method checks out a connection from the pool, creating a new one
        if necessary.  It will block if a maxsize has been set and there are
        no connections left in the pool
        """
        # If there's no maxsize, no need to block waiting for a connection.
        blocking = (self.maxsize is not None)
        # Loop until we get a non-stale connection, or we create a new one.
        while True:
            try:
                ts, client = self.clients.get(blocking)
            except Queue.Empty:
                # No maxsize and no free connections, create a new one.
                # XXX TODO: we should be using a monotonic clock here.
                now = int(time.time())
                return now, self.master.clone()
            else:
                now = int(time.time())
                # If we got an empty slot placeholder, create a new connection.
                if client is None:
                    return now, self.master.clone()
                # If the connection is not stale, go ahead and use it.
                if ts + self.timeout > now:
                    return ts, client
                # Otherwise, the connection is stale.
                # Close it, push an empty slot onto the queue, and retry.
                client.disconnect_all()
                self.clients.put(EMPTY_SLOT)
                continue

    def _checkin_connection(self, ts, client):
        """Return a connection to the pool."""
        # If the connection is now stale, don't return it to the pool.
        # Push an empty slot instead so that it will be refreshed when needed.
        now = int(time.time())
        if ts + self.timeout > now:
            self.clients.put((ts, client))
        else:
            if self.maxsize is not None:
                self.clients.put(EMPTY_SLOT)
