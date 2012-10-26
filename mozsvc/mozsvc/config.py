# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****
""" Configuration file reader / writer

https://wiki.mozilla.org/index.php?title=Services/Sync/Server/GlobalConfFile

You can specify a section in your config file like this::

    [plugin1]
    backend = mymodule.MyPluginImpl
    foo = frob
    bar = baz

Then when you come to initialize your Pyramid app configuration, you
just ask it to load and register your plugin like so::

    from mozsvc.plugin import load_and_register

    config = Configurator(...etc...)
    plugin = load_and_register("plugin1", config)

This will read the configuration to find the "backend" declaration and resolve
it to a class, parse each of the other configuration options to use as keyword
arguments, and create an instance of the class for you.

    plugin = load_from_settings(section_name, settings_dict)

"""

import re
import os
from ConfigParser import SafeConfigParser


# Section separator character for config dict keys.
SEPARATOR = "."

# Regular expression to quickly check if a string might be a number.
_MAYBE_A_NUMBER = re.compile('^-?[0-9].*')

# Regular expression to identify ${VAR} env var substitutions.
_ENV_VAR_SUBST = re.compile('\$\{(\w.*)?\}')


class EnvironmentNotFoundError(ValueError):
    """Exception raised when config file references an undefined env var."""
    pass


class ConfigDict(dict):
    """A dict subclass with some extra helpers for dealing with app configs.

    This class extends the standard dictionary interface with some extra helper
    methods that are handy when dealing with application config.  It expects
    the keys to be dotted setting names, where each component indicates one
    section in the configuration heirarchy.  For example::

        config = ConfigDict({
            "app.name": "example",
            "db.backend": "mysql",
            "db.auth.user": "myuser",
            "db.auth.password": "supersecret",
        })

    You get the following extras helper methods:

        * setdefaults:  copy any unset settings from another dict
        * getsection:   return a dict of settings for just one subsection

    """

    def copy(self):
        """D.copy() -> a shallow copy of D.

        This overrides the default dict.copy method to ensure that the
        copy is also an instance of ConfigDict.
        """
        new_items = self.__class__()
        for k, v in self.iteritems():
            new_items[k] = v
        return new_items

    def getsection(self, section):
        """Get a dict for just one sub-section of the config.

        This method extracts all the keys belonging to the named section and
        returns those values in a dict.  The section name is removed from
        each key.  For example::

            >>> c = ConfigDict({"a.one": 1, "a.two": 2, "b.three": 3})
            >>> c.getsection("a")
            {"one": 1, "two", 2}
            >>>
            >>> c.getsection("b")
            {"three": 3}
            >>>
            >>> c.getsection("c")
            {}

        """
        section_items = self.__class__()
        # If the section is "" then get keys without a section.
        if not section:
            for key, value in self.iteritems():
                if SEPARATOR not in key:
                    section_items[key] = value
        # Otherwise, get keys prefixed with that section name.
        else:
            prefix = section + SEPARATOR
            for key, value in self.iteritems():
                if key.startswith(prefix):
                    section_items[key[len(prefix):]] = value
        return section_items

    def setdefaults(self, *args, **kwds):
        """Import unset keys from another dict.

        This method lets you update the dict using defaults from another
        dict and/or using keyword arguments.  It's like the standard update()
        method except that it doesn't overwrite existing keys.
        """
        for arg in args:
            if hasattr(arg, "keys"):
                for k in arg:
                    self.setdefault(k, arg[k])
            else:
                for k, v in arg:
                    self.setdefault(k, v)
        for k, v in kwds.iteritems():
            self.setdefault(k, v)



def load_config(filename, config=None):
    """Load a ConfigDict from the specified .ini file.

    This function reads the specified .ini file and loads it into a
    ConfigDict instance.  The section/option heirarchy is translated into
    dotted keys in the dict, so that this config file::

        [app]
        name = example

        [db.auth]
        user = myuser
        password = supersecret

    Would be translated into the following ConfigDict instance::

        ConfigDict({
            "app.name": "example",
            "db.auth.user": "myuser",
            "db.auth.password": "supersecret",
        })

    By default a new ConfigDict instance is created; if you pass an existing
    instance as the second argument then it will be updated in place.
    """
    if config is None:
        config = ConfigDict()

    # Parse the file, from either filename or file-like object.
    # Using SafeConfigParser allows %()s string interpolation in values.
    if not isinstance(filename, basestring):
        parser = SafeConfigParser()
        parser.readfp(filename)
    else:
        parser = SafeConfigParser({"here": os.path.dirname(filename)})
        # We use open() and readfp() because the parser's read() method
        # will ignore unreadable files, and that's bad.
        with open(filename, "r") as f:
            parser.readfp(f, filename)

    # Extract all the values and store them into the dict.
    for section in parser.sections():
        for option, value in parser.items(section):
            key = section + SEPARATOR + option
            config[key] = convert_value(value)

    # If we need to extend the config by loading additional files,
    # then handle each of them recursively.
    extends = parser.defaults().get("extends")
    if isinstance(extends, basestring):
        extends = (extends,)
    for extfilename in extends:
        config.setdefaults(load_config(extfilename))
    
    return config


def convert_value(value):
    """Convert a plain string value into a rich datatype.

    This function converts string values as loaded from file into one
    of several richer datatypes, according to the following rules:

        * "true" and "false" are converted to boolean type
        * well-formed integers are converted to an integer
        * strings containing newlines are converted into a list of items
        * environment variable substitutions are performed

    """
    # If it has already been converted, return it unchanged.
    if not isinstance(value, basestring):
        return value

    value = value.strip()

    # If there is no newline then it's just a single item.
    if "\n" not value:
        return _convert_single_value(value)

    # Otherwise it's a newline-separated list of items.
    values = []
    for ln in value.split("\n"):
        ln = ln.strip()
        if ln:
            values.append(_convert_single_value(value))
    return values


def _convert_single_value(value):
    """Helper to convert a plain string value into a rich datatype.

    This is a function for convert_value, which handles only single
    items rather than newline-separated lists of items.
    """
    # If it's a quoted string literal then return it with no further change.
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]

    # If it's a well-formed number then convert it into an integer.
    if _MAYBE_A_NUMBER.match(value):
        try:
            return int(value)
        except ValueError:
            pass

    # If it looks like a boolean, make it one.
    if value.lower() in ('true', 'false'):
        return value.lower() == 'true'

    # Otherwise, it's an unquoted string value.
    # Interpolate environment variables and return.
    return substitute_env_vars(value)


def substitute_env_vars(value, environ=None):
    """Interpolate environment variables into a string.

    This function replaces occurences of ${VAR} in the given string with the
    value of environment variable "VAR".  If there is not such environment
    variable then EnvironmentNotFoundError will be raised.

    The environment is taken from os.environ by default, but this can be
    overridden with the "environ" keyword argument.
    """
    if environ is None:
        environ = os.environ

    def get_replacement(matchobj):
        varname = matchobj.groups()[0]
        if varname not in os.environ:
            raise EnvironmentNotFoundError(varname)
        return os.environ[varname]
    
    return _IS_ENV_VAR.sub(get_replacement, value)


def create_from_config(config, section="", cls_param="backend"):
    """Instanciate an object as defined by a config section.

    This function provides a simple plugin-loading mechanism, by allowing you
    to interpret a config file section as a constructor call.  The config
    key "backend" names the class or other callable to be executed, while
    any sibling keys are passed in as keyword arguments.

    Suppose you have loaded a config file with the following section::

        [myplugin]
        backend = my.module.SomeClass
        arg1 = "example"
        arg2 = "testing"

    Then calling this function like so::

        plugin = create_from_config(config, "myplugin")

    Is equivalent to instantiating an object like this::

        plugin = my.module.SomeClass(arg1="example", arg2="testing")

    """
    kwargs = {}
    try:
        kwargs = config.getsection(section)
    except AttributeError:
        kwargs = ConfigDict(config).getsection(section)
    cls = resolve_name(kwargs.pop(cls_param))
    return cls(**kwargs)
