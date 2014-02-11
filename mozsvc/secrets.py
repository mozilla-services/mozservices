# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
"""

Classes for the management of auth-token signing secrets.

The classes in this module can be used to obtain a hex-encoded secret key
corresponding to a given webhead node name.  This key can be used for
making or verifying auth-token signatures via e.g. HMAC.

There are three options for managing this mapping of nodes to secrets:

  * maintain a text file with secrets for each node (Secrets class)
  * use a fixed set of secrets for all nodes (FixedSecrets class)
  * derive node-specific secrets from a master secret (DerivedSecrets class)

The most appropriate choice will depend on operational and security
requirements.

"""

import sys
import csv
import binascii
import os
import time
import hashlib
from collections import defaultdict

from tokenlib.utils import HKDF


class Secrets(object):
    """Load node-specific secrets from a file.

    This class provides a method to get a list of secrets for a node
    ordered by timestamps. The secrets are stored in a CSV file which
    is loaded when the object is created.

    Options:

    - **filename**: a list of file paths, or a single path.

    """
    def __init__(self, filename=None):
        self._secrets = defaultdict(list)
        if filename is not None:
            self.load(filename)

    def keys(self):
        return self._secrets.keys()

    def load(self, filename):
        if not isinstance(filename, (list, tuple)):
            filename = [filename]

        for name in filename:
            with open(name, 'rb') as f:

                reader = csv.reader(f, delimiter=',')
                for line, row in enumerate(reader):
                    if len(row) < 2:
                        continue
                    node = row[0]
                    if node in self._secrets:
                        raise ValueError("Duplicate node line %d" % line)
                    secrets = []
                    for secret in row[1:]:
                        secret = secret.split(':')
                        if len(secret) != 2:
                            raise ValueError("Invalid secret line %d" % line)
                        secrets.append(tuple(secret))
                    secrets.sort()
                    self._secrets[node] = secrets

    def save(self, filename):
        with open(filename, 'wb') as f:
            writer = csv.writer(f, delimiter=',')
            for node, secrets in self._secrets.items():
                secrets = ['%s:%s' % (timestamp, secret)
                           for timestamp, secret in secrets]
                secrets.insert(0, node)
                writer.writerow(secrets)

    def get(self, node):
        return [secret for timestamp, secret in self._secrets[node]]

    def add(self, node, size=256):
        timestamp = str(int(time.time()))
        secret = binascii.b2a_hex(os.urandom(size))[:size]
        # The new secret *must* sort at the end of the list.
        # This forbids you from adding multiple secrets per second.
        try:
            if timestamp <= self._secrets[node][-1][0]:
                assert False, "You can only add one secret per second"
        except IndexError:
            pass
        self._secrets[node].append((timestamp, secret))


class FixedSecrets(object):
    """Use a fixed set of secrets for all nodes.

    This class provides the same API as the Secrets class, but uses a
    single list of secrets for all nodes rather than using different
    secrets for each node.

    Options:

    - **secrets**: a list of hex-encoded secrets to use for all nodes.

    """
    def __init__(self, secrets):
        if isinstance(secrets, basestring):
            secrets = secrets.split()
        self._secrets = secrets

    def get(self, node):
        return list(self._secrets)

    def keys(self):
        return []


class DerivedSecrets(object):
    """Use a HKDF-derived secret for each nodes.

    This class provides the same API as the Secrets class, but rather than
    keeping a big mapping of node-names to secrets, it uses a single list of
    master secrets and HKDF-derives a unique secret for each node.

    Options:

    - **secrets**: a list of hex-encoded master secrets to use.

    """

    # Namespace prefix for HKDF "info" parameter.
    HKDF_INFO_NODE_SECRET = b"services.mozilla.com/mozsvc/v1/node_secret/"

    def __init__(self, master_secrets):
        if isinstance(master_secrets, basestring):
            master_secrets = master_secrets.split()
        self._master_secrets = master_secrets

    def get(self, node):
        hkdf_params = {
            "salt": None,
            "info": self.HKDF_INFO_NODE_SECRET + node,
            "hashmod": hashlib.sha256,
        }
        node_secrets = []
        for master_secret in self._master_secrets:
            # We want each hex-encoded derived secret to be the same
            # size as its (presumably hex-encoded) master secret.
            size = len(master_secret) / 2
            node_secret = HKDF(master_secret, size=size, **hkdf_params)
            node_secrets.append(binascii.b2a_hex(node_secret))
        return node_secrets

    def keys(self):
        return []


def manage(args):
    """Helper for command-line secrets management.

    This function provides some simple command-line helpers for managing
    secrets.

    To generate a new random secret:

        python -m mozsvc.secrets new [size=32]

    To derive a node-specific secret from a master secret:

        python -m mozsvc.secrets derive <master_secret> <node_name>

    """
    def report_usage_error():
        print>>sys.stderr, "\n".join(manage.__doc__.split("\n")[1:])
        return 1

    if len(args) < 2:
        return report_usage_error()

    if args[1] == "new":
        if len(args) > 3:
            return report_usage_error()
        try:
            size = int(args[2])
        except ValueError:
            return report_usage_error()
        except IndexError:
            size = 32
        print os.urandom(size).encode('hex')
        return 0

    if args[1] == "derive":
        if len(args) != 4:
            return report_usage_error()
        print DerivedSecrets([args[2]]).get(args[3])[0]
        return 0

    return report_usage_error()


if __name__ == "__main__":
    manage(sys.argv)
