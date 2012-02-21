# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from pyramid.request import Request
from pyramid.interfaces import IRequestFactory

from mozsvc.config import get_configurator

DEFAULT_SETTINGS = {
    'cef.vendor': 'mozilla',
    'cef.device_version': '1.3',
    'cef.product': 'test',
    'cef.use': True,
    'cef.version': 0,
    'cef.file': 'syslog',
}


def get_test_configurator(root, ini_file="tests.ini"):
    """Find a file with testing settings, turn it into a configurator."""
    ini_dir = root
    while True:
        ini_path = os.path.join(ini_dir, ini_file)
        if os.path.exists(ini_path):
            break
        if ini_path == ini_file or ini_path == "/" + ini_file:
            raise RuntimeError("cannot locate " + ini_file)
        ini_dir = os.path.split(ini_dir)[0]

    config = get_configurator({"__file__": ini_path}, **DEFAULT_SETTINGS)
    return config


# Try to convince test-loading tools to ignore this function
# despite the fact that it has "test" in the name.
get_test_configurator.__test__ = False


def make_request(config, path="/", environ=None, factory=None):
    my_environ = {}
    my_environ["wsgi.version"] = "1.0"
    my_environ["REQUEST_METHOD"] = "GET"
    my_environ["SCRIPT_NAME"] = ""
    my_environ["PATH_INFO"] = path
    my_environ["SERVER_NAME"] = "localhost"
    my_environ["SERVER_PORT"] = "5000"
    if environ is not None:
        my_environ.update(environ)
    if factory is None:
        factory = config.registry.queryUtility(IRequestFactory)
        if factory is None:
            factory = Request
    request = factory(my_environ)
    request.registry = config.registry
    return request
