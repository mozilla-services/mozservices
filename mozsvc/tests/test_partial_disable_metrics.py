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
from metlog.decorators import timeit, incr_count
from mozsvc.config import Config
from mozsvc.plugin import load_and_register
from pyramid.config import Configurator
from textwrap import dedent
import unittest
import json


class TestDisabledTimers(unittest.TestCase):
    """
    We want the counter decorators to fire, but the timer decorators
    should not
    """
    def setUp(self):
        config = Config(StringIO(dedent("""
        [test1]
        enabled=true
        backend = mozsvc.metrics.MetlogPlugin
        sender_class=metlog.senders.DebugCaptureSender
        disable_timeit=true
        """)))
        settings = {"config": config}
        config = Configurator(settings=settings)
        self.plugin = load_and_register("test1", config)
        config.commit()

    def test_only_some_decorators(self):
        '''
        decorator ordering may matter when Ops goes to look at the
        logs. Make sure we capture stuff in the right order
        '''
        plugin = self.plugin

        plugin.client.sender.msgs.clear()
        assert len(plugin.client.sender.msgs) == 0

        @incr_count
        @timeit
        def no_timer(x, y):
            return x + y

        no_timer(5, 6)
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        assert len(msgs) == 1

        for msg in msgs:
            expected = 'mozsvc.tests.test_partial_disable_metrics:no_timer'
            actual = msg['fields']['name']
            assert actual == expected

        # First msg should be counter, then timer as decorators are
        # applied inside to out, but execution is outside -> in
        assert msgs[0]['type'] == 'counter'

        plugin.client.sender.msgs.clear()
