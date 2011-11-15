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
# The Original Code is Cornice (Sagrada)
#
# The Initial Developer of the Original Code is the Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2010
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Tarek Ziade (tarek@mozilla.com)
#   Ryan Kelly (rkelly@mozilla.com)
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


def load_and_register(section_name, config, registry_name=u""):
    """Load a plugin from the named configuration section.

    Given a Pyramid Configurator object and the name of a config section,
    this function loads the plugin as specified in that section and then.
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
    # Register the plugin for each interface that it provides.
    # Use the Configurators delayed-registration machinery to get
    # conflict-resolution and so-forth for free.
    for interface in providedBy(plugin):

        def register(interface=interface):
            config.registry.registerUtility(plugin, interface, registry_name)

        config.action(interface, register)
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
