# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import tempfile
from StringIO import StringIO
from textwrap import dedent

from mozsvc.config import (ConfigDict, load_config, EnvironmentNotFoundError,
                           convert_value, create_from_config)

from mozsvc.tests.support import unittest


# These are the contents of some test .ini file.
# They are written out to the fileystem for use during the tests.

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
location = %(here)s
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

[multi.once]
storage.i = j
storage.k = l

[multi.thrice]
storage.i = jjj
storage.k = lll
"""

_EXTRA = """\
[some]
stuff = True

[other]
thing = ok
"""


class StubClass(object):
    """A simple class that just records any keyword arguments."""

    def __init__(self, **kwds):
        for key, value in kwds.iteritems():
            setattr(self, key, value)


class ConversionTestCase(unittest.TestCase):

    def test_convert_booleans(self):
        self.assertEquals(convert_value("true"), True)
        self.assertEquals(convert_value("TrUe"), True)
        self.assertEquals(convert_value("false"), False)
        self.assertEquals(convert_value("FaLsE"), False)

    def test_convert_integers(self):
        # Things that are integers
        self.assertEquals(convert_value("0"), 0)
        self.assertEquals(convert_value("42"), 42)
        self.assertEquals(convert_value("-41"), -41)
        # Things that are not integers
        self.assertEquals(convert_value("-12e6"), "-12e6")
        self.assertEquals(convert_value("0x1234ABCD"), "0x1234ABCD")

    def test_convert_quoted_strings(self):
        TEST_VALUES = ("", "true", "42", "test-${ENV}-var")
        for value in TEST_VALUES:
            self.assertEquals(convert_value('"%s"' % (value,)), value)
            self.assertEquals(convert_value("'%s'" % (value,)), value)

    def test_env_var_subst(self):
        os.environ.pop("MOZSVC_TEST_MISSING_ENVVAR", None)
        os.environ["MOZSVC_TEST_PRESENT_ENVVAR"] = "TEST"
        # Things with env var substitutions
        self.assertEquals(convert_value("hello ${MOZSVC_TEST_PRESENT_ENVVAR}"),
                          "hello TEST")
        with self.assertRaises(EnvironmentNotFoundError):
            convert_value("hello ${MOZSVC_TEST_MISSING_ENVVAR}")
        self.assertEquals(convert_value("hello world"),
                         "hello world")
        # Things that are not env var subsitutions
        TEST_VALUES = ("${MISSING_CLOSE_BRACE",
                       "$MISSING_BRACES",
                       "$MISSING_OPEN_BRACE}",)
        for value in TEST_VALUES:
            self.assertEquals(convert_value(value), value)

    def test_newline_lists(self):
        self.assertEquals(convert_value("one\ntwo\nthree"),
                          ["one", "two", "three"])


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

    def test_reading_config_files(self):
        config = load_config(self.file_one)

        # values conversion
        self.assertEquals(config['one.foo'], 'bar')
        self.assertEquals(config['one.num'], -12)
        self.assertEquals(config['one.st'], 'o=k')
        self.assertEquals(config['one.lines'], [1, 'two', 3])
        self.assertEquals(config['one.env'], 'some stuff')

        # getting a subsection
        subconfig = config.getsection('one')
        self.assertEquals(subconfig['foo'], 'bar')

        # values read via extends
        self.assertEquals(config['three.more'], 'stuff')
        self.assertEquals(config['one.two'], 'a')

    def test_missing_env_var_gives_an_error(self):
        del os.environ['__STUFF__']
        self.assertRaises(EnvironmentNotFoundError, load_config, self.file_one)

    def test_nofile(self):
        # if a user tries to use an inexistant file in extensions,
        # pops an error
        self.assertRaises(IOError, load_config, self.file_three)

    def test_dotted_section_names(self):
        config = load_config(self.file_four)
        self.assertEquals(config["storage.e"], "f")
        self.assertEquals(config["storage.g"], "h")
        self.assertEquals(config["multi.once.storage.i"], "j")
        self.assertEquals(config["multi.thrice.storage.i"], "jjj")
        self.assertEquals(config.getsection("multi")["once.storage.i"], "j")
        self.assertEquals(config.getsection("multi.once")["storage.i"], "j")
        self.assertEquals(config.getsection("multi.once.storage")["i"], "j")

    def test_configdict_copy(self):
        config = ConfigDict({
          "a.one": 1,
          "a.two": 2,
          "b.three": 3,
          "four": 4,
        })
        new_config = config.copy()
        self.assertEqual(config, new_config)
        self.failUnless(isinstance(new_config, ConfigDict))

    def test_configdict_getsection(self):
        config = ConfigDict({
          "a.one": 1,
          "a.two": 2,
          "b.three": 3,
          "four": 4,
        })
        self.assertEquals(config.getsection("a"), {"one": 1, "two": 2})
        self.assertEquals(config.getsection("b"), {"three": 3})
        self.assertEquals(config.getsection("c"), {})
        self.assertEquals(config.getsection(""), {"four": 4})

    def test_configdict_setdefaults(self):
        config = ConfigDict({
          "a.one": 1,
          "a.two": 2,
          "b.three": 3,
          "four": 4,
        })
        config.setdefaults({"a.two": "TWO", "a.five": 5, "new": "key"})
        self.assertEquals(config.getsection("a"),
                         {"one": 1, "two": 2, "five": 5})
        self.assertEquals(config.getsection("b"), {"three": 3})
        self.assertEquals(config.getsection("c"), {})
        self.assertEquals(config.getsection(""), {"four": 4, "new": "key"})

    def test_location_interpolation(self):
        config = load_config(self.file_one)
        file_two_loc = os.path.dirname(self.file_two)
        self.assertEquals(config['three.location'], file_two_loc)

    def test_loading_plugin_from_config(self):
        config = load_config(StringIO(dedent("""
        [test1]
        backend = mozsvc.tests.test_config.StubClass
        arg1 = 1
        hello = world
        [test2]
        dontusethis =  seriously
        """)))
        plugin = create_from_config(config, "test1")
        self.failUnless(isinstance(plugin, StubClass))
        self.assertEquals(plugin.arg1, 1)
        self.assertEquals(plugin.hello, "world")
