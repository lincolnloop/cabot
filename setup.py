#!/usr/bin/env python
from setuptools import setup, find_packages

setup(
    name='cabot',
    version='0.0.0-dev',
    description="Self-hosted, easily-deployable monitoring and alerts service"
                " - like a lightweight PagerDuty",
    long_description=open('README.md').read(),
    author="Arachnys",
    author_email='info@arachnys.com',
    url='http://cabotapp.com',
    license='MIT',
    # Not hosted on PyPI
    dependency_links=[
        'https://argparse.googlecode.com/files/argparse-1.2.1.tar.gz',
    ],
    install_requires=[
        'Django==1.6.2',
        'PyJWT==0.1.2',
        'South==0.8.4',
        'amqp==1.3.3',
        'anyjson==0.3.3',
        'billiard==3.3.0.13',
        'celery==3.1.7',
        'certifi==1.0.1',
        'dj-database-url==0.2.2',
        'django-appconf==0.6',
        'django-celery==3.1.1',
        'django-celery-with-redis==3.0',
        'django-compressor==1.3',
        'django-dotenv==1.2',
        'django-jsonify==0.2.1',
        'django-mptt==0.6.0',
        'django-polymorphic==0.5.3',
        'django-redis==1.4.5',
        'django-smtp-ssl==1.0',
        'gunicorn==18.0',
        'hiredis==0.1.1',
        'httplib2==0.7.7',
        'icalendar==3.6.1',
        'irc==8.5.4',
        'kombu==3.0.8',
        'mock==1.0.1',
        'psycopg2==2.5.1',
        'pytz',
        'redis==2.9.0',
        'requests==0.14.2',
        'six==1.5.1',
        'twilio==3.4.1',
        'wsgiref==0.1.2',
        'python-dateutil==2.2',
    ],
    scripts=['manage.py'],
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)
