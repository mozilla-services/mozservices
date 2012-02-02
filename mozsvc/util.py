# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****


import time
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
