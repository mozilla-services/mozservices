import os
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(here, 'README.txt')) as f:
    README = f.read()

with open(os.path.join(here, 'CHANGES.txt')) as f:
    CHANGES = f.read()

requires = ['pyramid', 'simplejson', 'cef']

tests_requires = requires + [
            'repoze.who.plugins.macauth', 'pyramid_whoauth',
            'tokenlib', 'macauthlib', 'metlog-py[zeromqpub]>=0.8.2',
            'cornice']


setup(name='mozsvc',
      version='0.3',
      description='Various utilities for Mozilla apps',
      long_description=README + '\n\n' + CHANGES,
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Pylons",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        ],
      author='Mozilla Services',
      author_email='services-dev@mozilla.org',
      url='https://github.com/mozilla-services/mozservices',
      keywords='web pyramid pylons',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      tests_require=tests_requires,
      test_suite="mozsvc",
      paster_plugins=['pyramid'])
