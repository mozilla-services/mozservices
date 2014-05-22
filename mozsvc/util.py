# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****

import json
import time
import socket
import urllib
import logging
import urlparse
import traceback
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pyramid.util import DottedNameResolver


def round_time(value=None, precision=2):
    """Transforms a timestamp into a two digits Decimal.

    Arg:
        value: timestamps representation - float or str.
        If None, uses time.time()

        precision: number of digits to keep. defaults to 2.

    Return:
        A Decimal two-digits instance.
    """
    if value is None:
        value = time.time()
    if not isinstance(value, str):
        value = str(value)
    try:
        digits = '0' * precision
        return Decimal(value).quantize(Decimal('1.' + digits))
    except InvalidOperation:
        raise ValueError(value)


def resolve_name(name, package=None):
    """Resolve dotted name into a python object.

    This function resolves a dotted name as a reference to a python object,
    returning whatever object happens to live at that path.  It's a simple
    convenience wrapper around pyramid's DottedNameResolver.

    The optional argument 'package' specifies the package name for relative
    imports.  If not specified, only absolute paths will be supported.
    """
    return DottedNameResolver(package).resolve(name)


def maybe_resolve_name(name_or_object, package=None):
    """Resolve dotted name or object into a python object.

    This function resolves a dotted name as a reference to a python object,
    returning whatever object happens to live at that path.  If the given
    name is not a string, it is returned unchanged.

    The optional argument 'package' specifies the package name for relative
    imports.  If not specified, only absolute paths will be supported.
    """
    return DottedNameResolver(package).maybe_resolve(name_or_object)


def dnslookup(url):
    """Replaces a hostname by its IP in an url.

    Uses gethostbyname to do a DNS lookup, so the nscd cache is used.

    If gevent has patched the standard library, makes sure it uses the
    original version because gevent uses its own mechanism based on
    the async libevent's evdns_resolve_ipv4, which does not use
    glibc's resolver.
    """
    try:
        from gevent.socket import _socket
        gethostbyname = _socket.gethostbyname
    except ImportError:
        import socket
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


class JsonLogFormatter(logging.Formatter):
    """Log formatter that outputs machine-readable json.

    This log formatter outputs JSON format messages that are compatible with
    Mozilla's standard heka-based log aggregation infrastructure.  It ignores
    any user-specific message and instead outouts a JSON dict of all relevant
    log-record attributes.
    """

    DEFAULT_LOGRECORD_ATTRS = set((
        'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
        'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs',
        'message', 'msg', 'name', 'pathname', 'process', 'processName',
        'relativeCreated', 'thread', 'threadName'
    ))

    DEFAULT_DETAILS = {
        "v": 1,
        "hostname": socket.gethostname(),
    }

    def format(self, record):
        # Take default values from the record and the environment.
        details = self.DEFAULT_DETAILS.copy()
        details.update({
            "op": record.name,
            "name": record.name,
            "time": datetime.utcfromtimestamp(record.created).isoformat()+"Z",
            "pid": record.process,
        })
        # Include any custom attributes set on the record.
        # These would usually be collected metrics data.
        for key, value in record.__dict__.iteritems():
            if key not in self.DEFAULT_LOGRECORD_ATTRS:
                details[key] = value
        # Only include the 'message' key if it has useful content
        # and is not already a JSON blob.
        message = record.getMessage()
        if message:
            if not message.startswith("{") and not message.endswith("}"):
                details["message"] = message
        # If there is an error, format it for nice output.
        if record.exc_info is not None:
            details["error"] = repr(record.exc_info[1])
            details["traceback"] = safer_format_traceback(*record.exc_info)
        return json.dumps(details)


def safer_format_traceback(exc_typ, exc_val, exc_tb):
    """Format an exception traceback into safer string.

    We don't want to let users write arbitrary data into our logfiles,
    which could happen if they e.g. managed to trigger a ValueError with
    a carefully-crafted payload.  This function formats the traceback
    using "%r" for the actual exception data, which passes it through repr()
    so that any special chars are safely escaped.
    """
    lines = ["Uncaught exception:\n"]
    lines.extend(traceback.format_tb(exc_tb))
    lines.append("%r\n" % (exc_typ,))
    lines.append("%r\n" % (exc_val,))
    return "".join(lines)
