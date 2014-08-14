# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****
"""
Custom gevent-based worker class for gunicorn.

This module provides a custom GeventWorker subclass for gunicorn, with some
extra operational niceties.
"""

import os
import gc
import sys
import time
import thread
import signal
import logging
import traceback

import greenlet
import gevent.hub

from gunicorn.workers.ggevent import GeventWorker


logger = logging.getLogger("mozsvc.gunicorn_worker")

# Take references to un-monkey-patched versions of stuff we need.
# Monkey-patching will have already been done by the time we come to
# use these functions at runtime.
_real_sleep = time.sleep
_real_start_new_thread = thread.start_new_thread
_real_get_ident = thread.get_ident


# The maximum amount of time that the eventloop can be blocked
# without causing an error to be logged.
MAX_BLOCKING_TIME = float(os.environ.get("GEVENT_MAX_BLOCKING_TIME", 0.1))


# The maximum amount of memory the worker is allowed to consume, in KB.
# If it exceeds this amount it will (attempt to) gracefully terminate.
MAX_MEMORY_USAGE = os.environ.get("MOZSVC_MAX_MEMORY_USAGE", "").lower()
if MAX_MEMORY_USAGE:
    import psutil
    if MAX_MEMORY_USAGE.endswith("k"):
        MAX_MEMORY_USAGE = MAX_MEMORY_USAGE[:-1]
    MAX_MEMORY_USAGE = int(MAX_MEMORY_USAGE) * 1024
    # How frequently to check memory usage, in seconds.
    MEMORY_USAGE_CHECK_INTERVAL = 2
    # If a gc brings us back below this threshold, we can avoid termination.
    MEMORY_USAGE_RECOVERY_THRESHOLD = MAX_MEMORY_USAGE * 0.8


# The filename for dumping memory usage data.
MEMORY_DUMP_FILE = os.environ.get("MOZSVC_MEMORY_DUMP_FILE",
                                  "/tmp/mozsvc-memdump")


class MozSvcGeventWorker(GeventWorker):
    """Custom gunicorn worker with extra operational niceties.

    This is a custom gunicorn worker class, based on the standard gevent worker
    but with some extra operational- and debugging-related features:

        * a background thread that monitors execution by checking for:

            * blocking of the gevent event-loop, with tracebacks
              logged if blocking code is found.

            * overall memory usage, with forced-gc and graceful shutdown
              if memory usage goes beyond a defined limit.

        * a timeout enforced on each individual request, rather than on
          inactivity of the worker as a whole.

        * a signal handler to dump memory usage data on SIGUSR2.

    To detect eventloop blocking, the worker installs a greenlet trace
    function that increments a counter on each context switch.  A background
    (os-level) thread monitors this counter and prints a traceback if it has
    not changed within a configurable number of seconds.
    """

    def init_process(self):
        # Check if we need a background thread to monitor memory use.
        needs_monitoring_thread = False
        if MAX_MEMORY_USAGE:
            self._last_memory_check_time = time.time()
            needs_monitoring_thread = True

        # Set up a greenlet tracing hook to monitor for event-loop blockage,
        # but only if monitoring is both possible and required.
        if hasattr(greenlet, "settrace") and MAX_BLOCKING_TIME > 0:
            # Grab a reference to the gevent hub.
            # It is needed in a background thread, but is only visible from
            # the main thread, so we need to store an explicit reference to it.
            self._active_hub = gevent.hub.get_hub()
            # Set up a trace function to record each greenlet switch.
            self._active_greenlet = None
            self._greenlet_switch_counter = 0
            greenlet.settrace(self._greenlet_switch_tracer)
            self._main_thread_id = _real_get_ident()
            needs_monitoring_thread = True

        # Create a real thread to monitor out execution.
        # Since this will be a long-running daemon thread, it's OK to
        # fire-and-forget using the low-level start_new_thread function.
        if needs_monitoring_thread:
            _real_start_new_thread(self._process_monitoring_thread, ())

        # Continue to superclass initialization logic.
        # Note that this runs the main loop and never returns.
        super(MozSvcGeventWorker, self).init_process()

    def init_signals(self):
        # Leave all signals defined by the superclass in place.
        super(MozSvcGeventWorker, self).init_signals()

        # Hook up SIGUSR2 to dump memory usage information.
        # This will be useful for debugging memory leaks and the like.
        signal.signal(signal.SIGUSR2, self._dump_memory_usage)
        if hasattr(signal, "siginterrupt"):
            signal.siginterrupt(signal.SIGUSR2, False)

    def handle_request(self, *args):
        # Apply the configured 'timeout' value to each individual request.
        # Note that self.timeout is set to half the configured timeout by
        # the arbiter, so we use the value directly from the config.
        with gevent.Timeout(self.cfg.timeout):
            return super(MozSvcGeventWorker, self).handle_request(*args)

    def _greenlet_switch_tracer(self, what, (origin, target)):
        """Callback method executed on every greenlet switch.

        The worker arranges for this method to be called on every greenlet
        switch.  It keeps track of which greenlet is currently active and
        increments a counter to track how many switches have been performed.
        """
        # Increment the counter to indicate that a switch took place.
        # This will periodically be reset to zero by the monitoring thread,
        # so we don't need to worry about it growing without bound.
        self._active_greenlet = target
        self._greenlet_switch_counter += 1

    def _process_monitoring_thread(self):
        """Method run in background thread that monitors our execution.

        This method is an endless loop that gets executed in a background
        thread.  It periodically wakes up and checks:

            * whether the active greenlet has switched since last checked
            * whether memory usage is within the defined limit

        """
        # Find the minimum interval between checks.
        if MAX_MEMORY_USAGE:
            sleep_interval = MEMORY_USAGE_CHECK_INTERVAL
            if MAX_BLOCKING_TIME and MAX_BLOCKING_TIME < sleep_interval:
                sleep_interval = MAX_BLOCKING_TIME
        else:
            sleep_interval = MAX_BLOCKING_TIME
        # Run the checks in an infinite sleeping loop.
        try:
            while True:
                _real_sleep(sleep_interval)
                self._check_greenlet_blocking()
                self._check_memory_usage()
        except Exception:
            # Swallow any exceptions raised during interpreter shutdown.
            # Daemonic Thread objects have this same behaviour.
            if sys is not None:
                raise

    def _check_greenlet_blocking(self):
        if not MAX_BLOCKING_TIME:
            return
        # If there have been no greenlet switches since we last checked,
        # grab the stack trace and log an error.  The active greenlet's frame
        # is not available from the greenlet object itself, we have to look
        # up the current frame of the main thread for the traceback.
        if self._greenlet_switch_counter == 0:
            active_greenlet = self._active_greenlet
            # The hub gets a free pass, since it blocks waiting for IO.
            if active_greenlet not in (None, self._active_hub):
                frame = sys._current_frames()[self._main_thread_id]
                stack = traceback.format_stack(frame)
                err_log = ["Greenlet appears to be blocked\n"] + stack
                logger.error("".join(err_log))
        # Reset the count to zero.
        # This might race with it being incremented in the main thread,
        # but not often enough to cause a false positive.
        self._greenlet_switch_counter = 0

    def _check_memory_usage(self):
        if not MAX_MEMORY_USAGE:
            return
        elapsed = time.time() - self._last_memory_check_time
        if elapsed > MEMORY_USAGE_CHECK_INTERVAL:
            mem_usage = psutil.Process().memory_info().rss
            if mem_usage > MAX_MEMORY_USAGE:
                logger.info("memory usage %d > %d, forcing gc",
                            mem_usage, MAX_MEMORY_USAGE)
                # Try to clean it up by forcing a full collection.
                gc.collect()
                mem_usage = psutil.Process().memory_info().rss
                if mem_usage > MEMORY_USAGE_RECOVERY_THRESHOLD:
                    # Didn't clean up enough, we'll have to terminate.
                    logger.warn("memory usage %d > %d after gc, quitting",
                                mem_usage, MAX_MEMORY_USAGE)
                    self.alive = False
            self._last_memory_check_time = time.time()

    def _dump_memory_usage(self, *args):
        """Dump memory usage data to a file.

        This method writes out memory usage data for the current process into
        a timestamped file.  By default the data is written to a file named
        /tmp/mozsvc-memdump.<pid>.<timestamp> but this can be customized
        with the environment variable "MOSVC_MEMORY_DUMP_FILE".

        If the "meliae" package is not installed or if an error occurs during
        processing, then the file "mozsvc-memdump.error.<pid>.<timestamp>"
        will be written with a traceback of the error.
        """
        now = int(time.time())
        try:
            filename = "%s.%d.%d" % (MEMORY_DUMP_FILE, os.getpid(), now)
            from meliae import scanner
            scanner.dump_all_objects(filename)
        except Exception:
            filename = "%s.error.%d.%d" % (MEMORY_DUMP_FILE, os.getpid(), now)
            with open(filename, "w") as f:
                f.write("ERROR DUMPING MEMORY USAGE\n\n")
                traceback.print_exc(file=f)
