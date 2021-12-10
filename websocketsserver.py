# -*- coding: utf-8 -*-

import os

# Check if this code is running on Heroku. The easiest way is to tell is by
# the existence of an environment variable called `DYNO`.
if os.getenv('DYNO'):
    # Newrelic has to be imported before any flask code is imported.
    import newrelic.agent
    newrelic.agent.initialize('newrelic.ini', 'production')

from geventwebsocket import WebSocketServer
from yoapi.factory import create_api_app

app = create_api_app(name='local-api', config='yoapi.config.Production')
try:
    http_server = WebSocketServer(('', 5001), app, log=None)
    http_server.serve_forever()
except KeyboardInterrupt:
    print 'goodbye'
