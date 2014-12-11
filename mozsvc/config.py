# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****

import os

from konfig import Config, SettingsDict

from pyramid.config import Configurator


def load_into_settings(filename, settings):
    """Load config file contents into a Pyramid settings dict.

    This is a helper function for initialising a Pyramid settings dict from
    a config file.  It flattens the config file sections into dotted settings
    names and updates the given dictionary in place.

    You would typically use this when constructing a Pyramid Configurator
    object, like so::

        def main(global_config, **settings):
            config_file = global_config['__file__']
            load_info_settings(config_file, settings)
            config = Configurator(settings=settings)

    """
    filename = os.path.expandvars(os.path.expanduser(filename))
    filename = os.path.abspath(os.path.normpath(filename))
    config = Config(filename)

    # Konfig keywords are added to every section when present, we have to
    # filter them out, otherwise plugin.load_from_config and
    # plugin.load_from_settings are unable to create instances.
    konfig_keywords = ['extends', 'overrides']

    # Put values from the config file into the pyramid settings dict.
    for section in config.sections():
        setting_prefix = section.replace(":", ".")
        for name, value in config.get_map(section).iteritems():
            if name not in konfig_keywords:
                settings[setting_prefix + "." + name] = value

    # Store a reference to the Config object itself for later retrieval.
    settings['config'] = config
    return config


def get_configurator(global_config, **settings):
    """Create a pyramid Configurator and populate it with sensible defaults.

    This function is a helper to create and pre-populate a Configurator
    object using the given paste-deploy settings dicts.  It uses the
    mozsvc.config module to flatten the config paste-deploy config file
    into the settings dict so that non-mozsvc pyramid apps can read values
    from it easily.
    """
    # Populate a SettingsDict with settings from the deployment file.
    settings = SettingsDict(settings)
    config_file = global_config.get('__file__')
    if config_file is not None:
        load_into_settings(config_file, settings)
    # Update with default pyramid settings, and then insert for all to use.
    config = Configurator(settings={})
    settings.setdefaults(config.registry.settings)
    config.registry.settings = settings
    return config
