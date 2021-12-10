# -*- coding: utf-8 -*-

from gevent import monkey
monkey.patch_all()

import os

# Check if this code is running on Heroku. The easiest way is to tell is by
# the existence of an environment variable called `DYNO`.
if os.getenv('DYNO'):
    # Newrelic has to be imported before any flask code is imported.
    import newrelic.agent
    newrelic.agent.initialize('newrelic.ini', 'scheduler')

import argparse
from yoapi.factory.scheduler import create_scheduler_app

from yoapi.services.scheduler import yo_scheduler

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='YoAPI console server.')
    parser.add_argument('--config', dest='config',
                        default='yoapi.config.Default',
                        help='Dotted module path of config class.')
    args = parser.parse_args()
    app = create_scheduler_app(name='scheduler', config=args.config)
    with app.app_context():
        yo_scheduler.start()
