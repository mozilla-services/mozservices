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
