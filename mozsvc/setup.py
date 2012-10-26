import os
import sys
from setuptools import setup, find_packages

# Importing this up front prevents a pointless error traceback
# from being printed after running `python setup.py test.`
import multiprocessing

here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(here, 'README.txt')) as f:
    README = f.read()

with open(os.path.join(here, 'CHANGES.txt')) as f:
    CHANGES = f.read()

requires = ['simplejson']

tests_requires = list(requires)
if sys.version_info < (2, 7):
    tests_requires.append('unittest2')


setup(name='mozsvc',
      version='0.7',
      description='Various utilities for Mozilla Services apps',
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
      keywords='web mozilla'
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      extras_require=extras_require,
      tests_require=tests_requires,
      test_suite="mozsvc.tests")
