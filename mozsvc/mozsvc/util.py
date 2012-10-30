# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
import socket
import string
import random
import traceback
import urlparse
import urllib


def resolve_name(name, package=None):
    """Resolve dotted name into a python object.

    This function resolves a dotted name as a reference to a python object,
    returning whatever object happens to live at that path.

    If the given name is a relative import reference, the optional second
    argument "package" must be provided to name starting point of the search.
    """
    # The caller can either use "module.name:object.name" syntax
    # or just use dots everywhere with no colon.
    colon_pos = name.find(":")
    if colon_pos != -1:
        module_parts = name[:colon_pos].split(".")
        object_parts = name[colon_pos + 1:].split(".")
    else:
        module_parts = name.split(".")
        object_parts = []

    if not module_parts and not object_parts:
        raise ImportError("invalid dotted-name: %r" % (name,))

    # If it's a relative import, prepend the supplied package name.
    if not module_parts or not module_parts[0]:
        if package is None:
            raise ImportError("relative import without package: %r" % (name,))
        if not isinstance(package, basestring):
            package = package.__name__
        module_parts = package.split(".") + module_parts[1:]
        # Resolve backreferences.
        # Each empty part cancels out the part preceeding it.
        i = 1
        while i < len(module_parts):
            if module_parts[i]:
                i += 1
            else:
                i -= 1
                if i < 0:
                    raise ImportError("too many backrefences: %r" % (name,))
                module_parts.pop(i)
                module_parts.pop(i)

    # Try successively shorter prefixes of the module name
    # until we find something that can be imported.
    obj = None
    last_exc = None
    while True:
        try:
            obj = __import__(".".join(module_parts))
            break
        except ImportError, exc:
            if not module_parts:
                raise
            last_exc = exc
            object_parts.insert(0, module_parts.pop(-1))

    # The import will have given us the object corresponding
    # to the first component of the name.  Resolve all remaining
    # components by looking them up as attribute references.
    for part in module_parts[1:] + object_parts:
        try:
            obj = getattr(obj, part)
        except AttributeError:
            if last_exc is not None:
                raise last_exc
            raise ImportError(name)

    return obj


def maybe_resolve_name(name_or_object):
    """Resolve dotted name or object into a python object.

    This function resolves a dotted name as a reference to a python object,
    returning whatever object happens to live at that path.  If the given
    name is not a string, it is returned unchanged.
    """
    if not isinstance(name_or_object, basestring):
        return name_or_object
    return resolve_name(name_or_object)


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
    lines.append("%r : %r\n" % (exc_typ, exc_val))
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
