# -*- coding: utf-8 -*-
"""Script module for the YoAPI Flask server.

Examples:

    manage.py resetdb --config yoapi.config.Default --model_names User
    manage.py yo --to USERNAME --link www.google.com
    manage.py login --username USERNAME --password PASSWORD
"""

# Monkey patch using gevent. This has to be done first, _always_.
from gevent import monkey
monkey.patch_all()

import inspect
import yoapi.manage

from flask_script import Command
from functools import partial
from yoapi.factory import create_api_app
from yoapi.manage import Manager

if __name__ == "__main__":

    # The manager option is passed to the factory function. This allows us to
    # specify which config we use from the command line.
    manager = Manager(partial(create_api_app, name='prod-api'))
    manager.add_option("--config", dest="config",
                       default='yoapi.config.Default')
    manager.add_option("--impersonate", dest="impersonate")

    # Iterate over manage module to get all commands.
    for name in dir(yoapi.manage):
        attr = getattr(yoapi.manage, name)
        # Check if strict subclass of flask_script.Command
        if inspect.isclass(attr) and issubclass(attr, Command) and \
                attr != Command:
            # Add the command to the manager.
            manager.add_command(name.lower(), attr)

    manager.run()
