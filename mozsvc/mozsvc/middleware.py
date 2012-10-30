# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

import simplejson as json
from hashlib import md5

from mozsvc.util import maybe_resolve_name, randchars, safer_format_exc
from mozsvc.config import ConfigDict, load_config


class CatchErrorMiddleware(object):
    """WSGI middleware that catches errors, logs them and returns a 500.

    This WSGI middleare will intercept any uncaught exceptions raised by
    the underlying app, log a message with the details, and then return a
    "500 Server Error" response.

    The assist with debugging while avoiding exposure of traceback details,
    each error response includes a unique "crash id" which can be correlated
    with a particular traceback in the server-side logs.
    """

    def __init__(self, app, config={}):
        self.app = app
        try:
            logger_name = config['global.logger_name']
        except KeyError:
            logger_name = 'root'

        self.logger = logging.getLogger(logger_name)
        try:
            hook = config['global.logger_hook']
            self.hook = maybe_resolve_name(hook)
        except KeyError:
            self.hook = None

        try:
            self.ctype = config['global.logger_type']
        except KeyError:
            self.ctype = 'application/json'

    def __call__(self, environ, start_response):
        try:
            return self.app(environ, start_response)
        except BaseException as exc:
            err = safer_format_exc()
            hash = self.create_hash(err)

            # We want to return a 500 for all exceptions, but there's
            # no point in logging things like KeyboardInterrupt.
            if isinstance(exc, Exception):
                self.logger.error(hash)
                self.logger.error(err)

            start_response('500 Internal Server Error',
                           [('content-type', self.ctype)])

            response = json.dumps("application error: crash id %s" % hash)
            if self.hook:
                try:
                    new_response = self.hook({'error': err, 'crash_id': hash,
                                              'environ': environ})
                    if new_response is not None:
                        response = new_response
                except Exception:
                    pass

            return [response]

    def create_hash(self, data):
        """Create a unique hash from the given data and a bit of randomness."""
        return md5(data + randchars(10)).hexdigest()


def make_err_mdw(app, global_conf, **local_conf):
    """A paste "filter_app_factory" to load the CatchErrorMiddleware.

    This function is a CatchErrorMiddleware factory that can be used as a
    filter in a paste deploy .ini file.  Like this::

        [filter:catcherror]
        paste.filter_app_factory = mozsvc.middlewares:make_err_mdw

        [app:myapp]
        use = egg:MyAwesomeApp

        [pipeline:main]
        pipeline = catcherror
                   myapp

    This factory loads the configuration data from the .ini file and passes
    it on to the middleware.
    """
    config_file = global_conf.get("__file__")
    if config_file is not None:
        config = load_config(config_file)
    else:
        config = ConfigDict()
    config.update(**local_conf)
    return CatchErrorMiddleware(app, config)
