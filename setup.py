# coding: utf-8

import re
import os
from setuptools import setup, find_packages

current_dir = os.path.abspath(os.path.dirname(__file__))
package = 'ngta_ui'

requires = [
    'jinja2',
    'psutil',
    'pyyaml',
    'assertpy',
    'deepdiff',
    'coupling>=1.1.8',
    'pydantic',

    # for agent
    'jmespath',
    'etcd3gw',
    'kombu',
    'tornado',
    'gitpython',
    'requests',
    'PySide6-QtAds',
    'PySide6',
]


with open('README.md', encoding='utf8') as f:
    long_description = f.read()


with open(os.path.join(current_dir, package, '__init__.py'), encoding='utf8') as f:
    meta = {}
    for line in f.readlines():
        match = re.search(r'__(\w+?)__\s*=\s*(.*)', line.strip())
        if match:
            name, value = match.group(1, 2)
            meta[name] = value.strip("\"'")


def package_files(directory):
    paths = []
    for (path, directories, filenames) in os.walk(directory):
        if not path.endswith('__pycache__'):
            for filename in filenames:
                paths.append(os.path.join('..', path, filename))
    return paths


package_extras = []
package_extras.extend(package_files('{}/agent'.format(package)))
package_extras.extend(package_files('{}/ext'.format(package)))
package_extras.extend(package_files('{}/init'.format(package)))
package_extras.extend(package_files('{}/report'.format(package)))
package_extras.extend(package_files('{}/schema'.format(package)))


setup(
    name=package,
    description="Next generation test automation.",
    long_description=long_description,
    long_description_content_type='text/markdown',
    version=meta['version'],
    author=meta['author'],
    author_email="shibo.huang@calterah@calterah.com",
    packages=find_packages(exclude=['tests']),
    package_data={"": package_extras},
    python_requires='>=3.10.5',
    install_requires=requires,
    tests_require=[],
    extras_require={
        'api': ['sqlalchemy', 'records', 'pypika'],
        'web': ['selenium'],
        'doc': ['sphinx', 'sphinx-intl', 'recommonmark', 'sphinx_markdown_tables'],
    },
    scripts=[],
    platforms='Posix; MacOS X; Windows',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Software Development :: Testing',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ],
)
