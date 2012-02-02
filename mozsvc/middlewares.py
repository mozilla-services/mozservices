# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****
"""
Various utilities
"""
from hashlib import md5
import traceback
import random
import string
import simplejson as json
import re
import os
import logging
from ConfigParser import NoOptionError


random.seed()
_RE_CODE = re.compile('[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}')


def randchar(chars=string.digits + string.letters):
    """Generates a random char using urandom.

    If the system does not support it, the function fallbacks on random.choice

    See Haypo's explanation on the used formula to pick a char:
    http://bitbucket.org/haypo/hasard/src/tip/doc/common_errors.rst
    """
    try:
        pos = int(float(ord(os.urandom(1))) * 256. / 255.)
        return chars[pos % len(chars)]
    except NotImplementedError:
        return random.choice(chars)


def _resolve_name(name):
    """Resolves the name and returns the corresponding object."""
    ret = None
    parts = name.split('.')
    cursor = len(parts)
    module_name = parts[:cursor]
    last_exc = None

    while cursor > 0:
        try:
            ret = __import__('.'.join(module_name))
            break
        except ImportError, exc:
            last_exc = exc
            if cursor == 0:
                raise
            cursor -= 1
            module_name = parts[:cursor]

    for part in parts[1:]:
        try:
            ret = getattr(ret, part)
        except AttributeError:
            if last_exc is not None:
                raise last_exc
            raise ImportError(name)

    if ret is None:
        if last_exc is not None:
            raise last_exc
        raise ImportError(name)

    return ret


class CatchErrorMiddleware(object):
    """Middleware that catches error, log them and return a 500"""
    def __init__(self, app, config):
        self.app = app
        try:
            logger_name = config.get('global', 'logger_name')
        except NoOptionError:
            logger_name = 'root'

        self.logger = logging.getLogger(logger_name)
        try:
            hook = config.get('global', 'logger_hook')
            self.hook = _resolve_name(hook)
        except NoOptionError:
            self.hook = None

        try:
            self.ctype = config.get('global', 'logger_type')
        except NoOptionError:
            self.ctype = 'application/json'

    def __call__(self, environ, start_response):
        try:
            return self.app(environ, start_response)
        except:
            err = traceback.format_exc()
            hash = create_hash(err)
            self.logger.error(hash)
            self.logger.error(err)
            start_response('500 Internal Server Error',
                           [('content-type', self.ctype)])

            response = json.dumps("application error: crash id %s" % hash)
            if self.hook:
                try:
                    response = self.hook({'error': err, 'crash_id': hash,
                                          'environ': environ})
                except Exception:
                    pass

            return [response]


def make_err_mdw(app, global_conf, **conf):
    config = app.registry.settings['config']
    return CatchErrorMiddleware(app, config)


def create_hash(data):
    """Creates a unique hash using the data provided
    and a bit of randomness
    """
    rand = ''.join([randchar() for x in range(10)])
    data += rand
    return md5(data + rand).hexdigest()
