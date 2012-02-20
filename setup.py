#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

from setuptools import setup, find_packages

setup(
    name = 'TracLogs', version = '0.1',
    author = 'Tony Angerilli', author_email = 'tony.angerilli@sparkintegration.com',
    url = 'none',
    description = 'Manages daily logs and hours through Trac',
    license = 'BSD',
    packages = find_packages(exclude=['*.tests*']),
    entry_points = {
        'trac.plugins': ['TracLogs = TracLogs.TracLogs']
    },
    package_data={'TracLogs': ['templates/*.html', 'htdocs/css/*.css', 'htdocs/js/*.js',
                                 'htdocs/images/*']},
    install_requires = [],
    zip_safe = True
)
