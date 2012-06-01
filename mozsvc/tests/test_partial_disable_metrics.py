# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# The Initial Developer of the Original Code is the Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2012
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Rob Miller (rmiller@mozilla.com)
#   Victor Ng (vng@mozilla.com)

# ***** END LICENSE BLOCK *****

from StringIO import StringIO
from mozsvc.config import Config
from mozsvc.plugin import load_and_register
from pyramid.config import Configurator
from textwrap import dedent
import unittest2
import json

metlog = True
try:
    from metlog.decorators import timeit, incr_count
    from metlog.holder import CLIENT_HOLDER
except ImportError:
    metlog = False


class TestDisabledTimers(unittest2.TestCase):
    """
    We want the counter decorators to fire, but the timer decorators should not
    """
    def setUp(self):
        if not metlog:
            raise(unittest2.SkipTest('no metlog'))
        self.orig_globals = CLIENT_HOLDER.global_config.copy()
        config = Config(StringIO(dedent("""
        [test1]
        backend = mozsvc.metrics.MetlogPlugin
        logger = test
        sender_class=metlog.senders.DebugCaptureSender
        global_disabled_decorators = timeit
                                     something
        """)))
        settings = {"config": config}
        config = Configurator(settings=settings)
        self.plugin = load_and_register("test1", config)
        config.commit()

    def tearDown(self):
        CLIENT_HOLDER.delete_client('test')
        CLIENT_HOLDER.global_config = self.orig_globals

    def test_only_some_decorators(self):
        plugin = self.plugin

        plugin.client.sender.msgs.clear()
        self.assertEqual(len(plugin.client.sender.msgs), 0)

        @incr_count
        @timeit
        def no_timer(x, y):
            return x + y

        no_timer(5, 6)
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        self.assertEqual(len(msgs), 1)

        expected = 'mozsvc.tests.test_partial_disable_metrics.no_timer'
        self.assertEqual(msgs[0]['fields']['name'], expected)
        self.assertEqual(msgs[0]['type'], 'counter')

        plugin.client.sender.msgs.clear()
