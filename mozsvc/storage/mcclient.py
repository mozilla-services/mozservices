# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Simplified API for accessing memcached.

This module provides a simplified API for accessing memcache, modelled on
the API of python-memcached/pylibmc.  It offers useful default behaviours
for serialization, error reporting and connection pooling.
"""

import sys
import time
import json
import traceback
import contextlib
import Queue

import umemcache

import mozsvc
from mozsvc.exceptions import BackendError


class MemcachedClient(object):
    """Helper class for interacting with memcache.

    This class provides the basic methods of the pylibmc Client class, but
    wraps them with some extra functionality:

        * all values are transparently serialized via JSON instead of pickle.
        * connections are taken from an underlying pool.
        * errors are converted into BackendError instances.
        * cas() transparently falls back to add() when appropriate.

    """

    def __init__(self, servers=None, key_prefix="", pool_size=None,
                 pool_timeout=60, logger=None, **kwds):
        if servers is None:
            servers = ["127.0.0.1:11211"]
        elif isinstance(servers, basestring):
            servers = [servers]
        self.key_prefix = key_prefix
        self._logger = logger
        # XXX TODO: umemcache doesn't support clustering.
        # We could implement this ourselves, but is it worth it?
        if len(servers) > 1:
            msg = "Multiple servers are not currently supported. "
            msg += "Consider using moxi for transparent clustering support."
            raise ValueError(msg)
        self.pool = MCClientPool(servers[0], pool_size, pool_timeout)

    @property
    def logger(self):
        """Property to lazily extract a default logger from runtime environ."""
        if self._logger is None:
            try:
                from pyramid.threadlocal import get_current_registry
                self._logger = get_current_registry()["metlog"]
            except (ImportError, KeyError):
                self._logger = mozsvc.logger
        return self._logger

    @contextlib.contextmanager
    def _connect(self):
        """Context mananager for getting a connection to memcached."""
        # We could get an error while trying to create a new connection,
        # or when trying to use an existing connection.  This outer
        # try-except handles the logging for both cases.
        try:
            with self.pool.reserve() as mc:
                # If we get an error while using the client object,
                # disconnect so that it will be removed from the pool.
                try:
                    yield mc
                except (EnvironmentError, RuntimeError), err:
                    if mc is not None:
                        mc.disconnect()
                    raise
        except (EnvironmentError, RuntimeError), err:
            err = traceback.format_exc()
            self.logger.error(err)
            raise BackendError(str(err))

    def get(self, key):
        """Get the value stored under the given key."""
        with self._connect() as mc:
            res = mc.get(self.key_prefix + key)
        if res is None:
            return None
        data, flags = res
        data = json.loads(data)
        return data

    def gets(self, key):
        """Get the current value and casid for the given key."""
        with self._connect() as mc:
            res = mc.gets(self.key_prefix + key)
        if res is None:
            return None, None
        data, flags, casid = res
        data = json.loads(data)
        return data, casid

    def get_multi(self, keys):
        """Get the values stored under the given keys in a single request."""
        with self._connect() as mc:
            prefixed_keys = [self.key_prefix + key for key in keys]
            prefixed_items = mc.get_multi(prefixed_keys)
        items = {}
        for key, res in prefixed_items.iteritems():
            assert key.startswith(self.key_prefix)
            assert res is not None
            data, flags = res
            items[key[len(self.key_prefix):]] = json.loads(data)
        return items

    def set(self, key, value, time=0):
        """Set the value stored under the given key."""
        data = json.dumps(value)
        with self._connect() as mc:
            res = mc.set(self.key_prefix + key, data, time)
        if res != "STORED":
            return False
        return True

    def add(self, key, value, time=0):
        """Add the given key to memcached if not already present."""
        data = json.dumps(value)
        with self._connect() as mc:
            res = mc.add(self.key_prefix + key, data, time)
        if res != "STORED":
            return False
        return True

    def replace(self, key, value, time=0):
        """Replace the given key in memcached if it is already present."""
        data = json.dumps(value)
        with self._connect() as mc:
            res = mc.replace(self.key_prefix + key, data, time)
        if res != "STORED":
            return False
        return True

    def cas(self, key, value, casid, time=0):
        """Set the value stored under the given key if casid matches."""
        data = json.dumps(value)
        with self._connect() as mc:
            # Memcached's CAS only works properly on existing keys.
            # Fortunately ADD has the same semantics for missing keys.
            if casid is None:
                res = mc.add(self.key_prefix + key, data, time)
            else:
                res = mc.cas(self.key_prefix + key, data, casid, time)
        if res != "STORED":
            return False
        return True

    def delete(self, key):
        """Delete the value stored under the given key."""
        with self._connect() as mc:
            res = mc.delete(self.key_prefix + key)
        if res != "DELETED":
            return False
        return True


# Sentinel used to mark an empty slot in the MCClientPool queue.
# Using sys.maxint as the timestamp ensures that empty slots will always
# sort *after* live connection objects in the queue.
EMPTY_SLOT = (sys.maxint, None)


class MCClientPool(object):
    """Pool of umemcache.Client objects, with periodic purging of connections.

    This class implements a simple pool of umemcache Client objects, with
    periodically closing and refreshing of the pooled Client objects.  This
    seems to work around some occasional hangs that were occurring with
    long-lived clients.

    To initialise the pool you must provide the list of server addresses
    to access.  You may also specify the maximum size of the pool and the
    time after which old connections will be recycled.

    To obtain a Client object from the pool, call reserve() as a context
    manager like this::

        with pool.reserve() as mc:
            mc.set("hello", "world")
            assert ms.get("hello") == "world"

    """

    def __init__(self, server, maxsize=None, timeout=60):
        self.server = server
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
        ts, client = self._checkout_client()
        try:
            yield client
        finally:
            self._checkin_client(ts, client)

    def _create_client(self):
        """Create a new Client object."""
        client = umemcache.Client(self.server)
        client.connect()
        return client

    def _checkout_client(self):
        """Checkout a Client ojbect from the pool.

        This method checks out a Client object from the pool, creating a new
        one if necessary.  It will block if a maxsize has been set and there
        are no objects left in the pool
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
                return now, self._create_client()
            else:
                now = int(time.time())
                # If we got an empty slot placeholder, create a new connection.
                if client is None:
                    return now, self._create_client()
                # If the connection is not stale, go ahead and use it.
                if ts + self.timeout > now:
                    return ts, client
                # Otherwise, the connection is stale.
                # Close it, push an empty slot onto the queue, and retry.
                client.disconnect()
                self.clients.put(EMPTY_SLOT)
                continue

    def _checkin_client(self, ts, client):
        """Return a Client object to the pool."""
        # If the connection is now stale, don't return it to the pool.
        # Push an empty slot instead so that it will be refreshed when needed.
        if client.is_connected():
            now = int(time.time())
            if ts + self.timeout > now:
                self.clients.put((ts, client))
            else:
                if self.maxsize is not None:
                    self.clients.put(EMPTY_SLOT)
