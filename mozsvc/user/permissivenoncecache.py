# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
"""

Hawk nonce-checking class that doesn't actually check them.

"""

import time
import logging


logger = logging.getLogger("mozsvc.user")


class PermissiveNonceCache(object):
    """Object for not really managing a cache of used nonce values.

    This class implements the timestamp/nonce checking interface required
    by hawkauthlib, but doesn't actually check them.  Instead it just logs
    timestamps that are too far out of the timestamp window for future
    analysis.
    """

    def __init__(self, log_window=60, get_time=None):
        self.log_window = log_window
        self.get_time = get_time or time.time

    def __len__(self):
        raise NotImplementedError

    def check_nonce(self, timestamp, nonce):
        """Check if the given timestamp+nonce is fresh."""
        now = self.get_time()
        skew = now - timestamp
        if abs(skew) > self.log_window:
            logger.warn("Large timestamp skew detected: %d", skew)
        return True
