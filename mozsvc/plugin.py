# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****


"""
Plugin loading system using zope.interface and the pyramid registry.

This module provides a simple plugin-loading system on top of pyramid's
internal component registry.  Suppose you have a plugin interface declared
like so::

    from zope.interface import Interface

    class IMyPlugin(Interface):
        pass

And a concrete implementation of it in "mymodule.MyPluginImpl"::

    from zope.interface import implements

    class MyPluginImpl(object):
        implements(IMyPlugin)
        def __init__(self, foo, bar):
            pass

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

The load_and_register function also registers the loaded plugin with pyramid's
component registry.  This means you can look it up in any other part of your
code by doing the following:

    plugin = request.registry.queryUtility(IMyPlugin)

If you're not interested in this and want to skip all the zope interface
palaver, you can also use *just* the plugin loading functionality by using::

    plugin = load_from_config(section_name, config_obj)

or::

    plugin = load_from_settings(section_name, settings_dict)

"""

from zope.interface import providedBy

from mozsvc.util import resolve_name


def load_and_register(section_name, config, interface=None, registry_name=u""):
    """Load a plugin from the named configuration section.

    Given a Pyramid Configurator object and the name of a config section,
    this function loads the plugin as specified in that section and then
    registers it into the Pyramid registry as a utility for each of the
    interfaces that it provides.
    """
    settings = config.registry.settings
    # Load using the Config object if available, since it's faster.
    # If not then fall back to loading from dotted setting names.
    if "config" in settings:
        plugin = load_from_config(section_name, settings["config"])
    else:
        plugin = load_from_settings(section_name, settings)
    if interface is not None:
        interfaces = [interface]
    else:
        interfaces = providedBy(plugin)
    # Register the plugin for each interface that it provides.
    # Use the Configurators delayed-registration machinery to get
    # conflict-resolution and so-forth for free.
    for interface in interfaces:

        def register(interface=interface):
            config.registry.registerUtility(plugin, interface, registry_name)

        config.action((interface, registry_name), register)
    # And return it for user convenience.
    return plugin


def load_from_config(section_name, config):
    """Load the plugin from the given section in a Config object.

    This function loads a plugin using the settings specified in a Config
    object section.  The key "backend" must be present in the section and
    gives the dotted name of the plugin class to load.  Any other keys in
    the secton will be passed as keyword arguments to the class.
    """
    kwargs = dict(config.items(section_name))
    klass = resolve_name(kwargs.pop("backend"))
    return klass(**kwargs)


def load_from_settings(section_name, settings):
    """Load the plugin from the given section in a settings dict.

    This function loads a plugin using prefixed settings from the pyramid
    settings dict.  Any keys in the settings dict that start with the
    given section name plus a dot will be used.

    This a compatability function for use when a Config object is not
    available; load_from_config will usually be faster.
    """
    kwargs = {}
    prefix = section_name + "."
    for name, value in settings.iteritems():
        if name.startswith(prefix):
            kwargs[name[len(prefix):]] = value
    klass = resolve_name(kwargs.pop("backend"))
    return klass(**kwargs)
