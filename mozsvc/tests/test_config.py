# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Sync Server
#
# The Initial Developer of the Original Code is the Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2010
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Tarek Ziade (tarek@mozilla.com)
#   Rob Miller (rob@mozilla.com)
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****
import unittest
import tempfile
import os
from StringIO import StringIO

from mozsvc.config import (Config, EnvironmentNotFoundError, SettingsDict,
                           load_into_settings, get_configurator)


_FILE_ONE = """\
[DEFAULT]
extends = %s

[one]
foo = bar
num = -12
st = "o=k"
lines = 1
        two
        3

env = some ${__STUFF__}

[two]
a = b
"""

_FILE_TWO = """\
[one]
foo = baz
two = "a"

[three]
more = stuff
"""

_FILE_THREE = """\
[DEFAULT]
extends = no-no,no-no-no-no,no-no-no-no,theresnolimit

[one]
foo = bar
"""

_FILE_FOUR = """\
[global]
foo = bar
baz = bawlp

[auth]
a = b
c = d

[storage]
e = f
g = h

[multi:once]
storage.i = j
storage.k = l

[multi:thrice]
storage.i = jjj
storage.k = lll
"""

_EXTRA = """\
[some]
stuff = True

[other]
thing = ok
"""


class ConfigTestCase(unittest.TestCase):

    def setUp(self):
        os.environ['__STUFF__'] = 'stuff'
        fp, filename = tempfile.mkstemp()
        f = os.fdopen(fp, 'w')
        f.write(_FILE_TWO)
        f.close()
        self.file_one = StringIO(_FILE_ONE % filename)
        self.file_two = filename
        self.file_three = StringIO(_FILE_THREE)

        fp, filename = tempfile.mkstemp()
        f = os.fdopen(fp, 'w')
        f.write(_FILE_FOUR)
        f.close()
        self.file_four = filename

    def tearDown(self):
        if '__STUFF__' in os.environ:
            del os.environ['__STUFF__']
        os.remove(self.file_two)

    def test_reader(self):
        config = Config(self.file_one)

        # values conversion
        self.assertEquals(config.get('one', 'foo'), 'bar')
        self.assertEquals(config.get('one', 'num'), -12)
        self.assertEquals(config.get('one', 'st'), 'o=k')
        self.assertEquals(config.get('one', 'lines'), [1, 'two', 3])
        self.assertEquals(config.get('one', 'env'), 'some stuff')

        # getting a map
        map = config.get_map()
        self.assertEquals(map['one.foo'], 'bar')

        map = config.get_map('one')
        self.assertEquals(map['foo'], 'bar')

        del os.environ['__STUFF__']
        self.assertRaises(EnvironmentNotFoundError, config.get, 'one', 'env')

        # extends
        self.assertEquals(config.get('three', 'more'), 'stuff')
        self.assertEquals(config.get('one', 'two'), 'a')

    def test_nofile(self):
        # if a user tries to use an inexistant file in extensions,
        # pops an error
        self.assertRaises(IOError, Config, self.file_three)

    def test_load_into_settings(self):
        settings = {}
        load_into_settings(self.file_four, settings)
        self.assertEquals(settings["storage.e"], "f")
        self.assertEquals(settings["storage.g"], "h")
        self.assertEquals(settings["multi.once.storage.i"], "j")
        self.assertEquals(settings["multi.thrice.storage.i"], "jjj")

    def test_get_configurator(self):
        global_config = {"__file__": self.file_four}
        settings = {"pyramid.testing": "test"}
        config = get_configurator(global_config, **settings)
        settings = config.get_settings()
        self.assertEquals(settings["pyramid.testing"], "test")
        self.assertEquals(settings["storage.e"], "f")
        self.assertEquals(settings["storage.g"], "h")
        self.assertEquals(settings["multi.once.storage.i"], "j")
        self.assertEquals(settings.getsection("multi")["once.storage.i"], "j")
        self.assertEquals(settings.getsection("multi.once")["storage.i"], "j")
        self.assertEquals(settings.getsection("multi.once.storage")["i"], "j")

    def test_get_configurator_nofile(self):
        global_config = {"blah": "blech"}
        settings = {"pyramid.testing": "test"}
        config = get_configurator(global_config, **settings)
        settings = config.get_settings()
        self.assertEquals(settings["pyramid.testing"], "test")

    def test_settings_dict_getsection(self):
        settings = SettingsDict({
          "a.one": 1,
          "a.two": 2,
          "b.three": 3,
          "four": 4,
        })
        self.assertEquals(settings.getsection("a"), {"one": 1, "two": 2})
        self.assertEquals(settings.getsection("b"), {"three": 3})
        self.assertEquals(settings.getsection("c"), {})
        self.assertEquals(settings.getsection(""), {"four": 4})

    def test_settings_dict_setdefaults(self):
        settings = SettingsDict({
          "a.one": 1,
          "a.two": 2,
          "b.three": 3,
          "four": 4,
        })
        settings.setdefaults({"a.two": "TWO", "a.five": 5, "new": "key"})
        self.assertEquals(settings.getsection("a"),
                         {"one": 1, "two": 2, "five": 5})
        self.assertEquals(settings.getsection("b"), {"three": 3})
        self.assertEquals(settings.getsection("c"), {})
        self.assertEquals(settings.getsection(""), {"four": 4, "new": "key"})
