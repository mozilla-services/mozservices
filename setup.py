import os
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(here, 'README.txt')) as f:
    README = f.read()

with open(os.path.join(here, 'CHANGES.txt')) as f:
    CHANGES = f.read()

requires = ['pyramid', 'simplejson', 'cef']

tests_requires = requires + [
            'pyramid_macauth', 'tokenlib', 'macauthlib>=0.3.0',
            'cornice', 'wsgiproxy', 'unittest2']

extras_require = {
    'metlog': ['metlog-py>=0.9.1'],
    'memcache': ['umemcache>=1.3'],
}


setup(name='mozsvc',
      version='0.6',
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
      extras_require=extras_require,
      tests_require=tests_requires,
      test_suite="mozsvc.tests",
      paster_plugins=['pyramid'])
