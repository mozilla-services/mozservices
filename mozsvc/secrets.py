# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
import csv
import binascii
import os
import time
from collections import defaultdict

# XXX we don't watch the file for v1
# so a restart is needed to reload new secrets


class Secrets(object):
    """Loads into memory secret files.

    Provides a method to get a list of secrets for a
    node, ordered by timestamps.

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
