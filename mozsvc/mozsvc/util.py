# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****

import os
import sys
import socket
import string
import random
import traceback
import urlparse
import urllib


def resolve_name(name):
    """Resolve dotted name into a python object.

    This function resolves a dotted name as a reference to a python object,
    returning whatever object happens to live at that path.  The given
    name must be an absolute module reference.
    """
    ret = None
    parts = name.split('.')
    cursor = len(parts)
    last_exc = None

    # Try successively short prefixes of the name
    # until we find something that can be imported.
    module_name = parts[:cursor]
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

    # The import will have given us the object corresponding
    # to the first component of the name.  Resolve all remaining
    # components by looking them up as attribute references.
    for part in parts[1:]:
        try:
            ret = getattr(ret, part)
        except AttributeError:
            if last_exc is not None:
                raise last_exc
            raise ImportError(name)

    return ret


def maybe_resolve_name(name_or_object):
    """Resolve dotted name or object into a python object.

    This function resolves a dotted name as a reference to a python object,
    returning whatever object happens to live at that path.  If the given
    name is not a string, it is returned unchanged.
    """
    if not isinstance(name_or_object, basestring):
        return name_or_object
    return resolve_name(name_or_object)


def randchar(chars=string.digits + string.letters):
    """Generates a random char using urandom.

    If the system does not support it, the function fallbacks on random.choice
    """
    return randchars(1, chars)


def randchars(size, chars=string.digits + string.letters):
    """Generates a string of random chars using urandom.

    If the system does not support it, the function fallbacks on random.choice
    """
    try:
        data = os.urandom(size)
        # See Haypo's explanation on the used formula to pick a char here:
        # http://bitbucket.org/haypo/hasard/src/tip/doc/common_errors.rst
        choices = [chars[int(ord(c) * 256. / 255.) % len(chars)] for c in data]
    except NotImplementedError:
        choices = [random.choice(chars) for _ in xrange(size)]
    return "".join(choices)


def safer_format_exc(exc_typ=None, exc_val=None, exc_tb=None):
    """Format an exception traceback that's safer for logging.

    This function performs basically the same job as traceback.format_exc(),
    except that it tries not to include raw user-provided data that might
    show up in e.g. the payload of a ValueError exception.

    The idea here is to prevent clients being able to inject arbitrary data
    into the logfiles, a capability that could be used to cover their tracks
    after some sort of attack.
    """
    if None in (exc_typ, exc_val, exc_tb):
        current_exc = sys.exc_info()
        exc_typ = exc_typ or current_exc[0]
        exc_val = exc_val or current_exc[1]
        exc_tb = exc_tb or current_exc[2]
    lines = traceback.format_tb(exc_tb)
    lines.append("%r : %r\n" % (exc_type, exc_val))
    return "".join(lines)


def dnslookup(url):
    """Replaces a hostname by its IP in an url.

    Uses gethostbyname to do a DNS lookup, so the nscd cache is used.

    If gevent has patched the standard library, makes sure it uses the
    original version because gevent uses its own mechanism based on
    the async libevent's evdns_resolve_ipv4, which does not use
    glibc's resolver.
    """
    # ensure we use unmonkeypatched socket module
    gevent_socket = sys.modules.get("gevent.socket")
    if gevent_socket is not None:
        gethostbyname = gevent_socket._socket.gethostbyname
    else:
        gethostbyname = socket.gethostbyname

    # parsing
    parsed_url = urlparse.urlparse(url)
    host, port = urllib.splitport(parsed_url.netloc)
    user, host = urllib.splituser(host)

    # resolving the host
    host = gethostbyname(host)

    # recomposing
    if port is not None:
        host = '%s:%s' % (host, port)

    if user is not None:
        host = '%s@%s' % (user, host)

    parts = [parsed_url[0]] + [host] + list(parsed_url[2:])
    return urlparse.urlunparse(parts)
