# -*- coding: utf-8 -*-
import newrelic.agent
newrelic.agent.initialize('newrelic.ini', 'production')

import argparse
from geventwebsocket import WebSocketServer
from yoapi.factory import create_api_app

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='YoAPI console server.')
    parser.add_argument('--config', dest='config',
                        default='yoapi.config.Default',
                        help='Dotted module path of config class.')
    args = parser.parse_args()
    app = create_api_app(name='local-api', config=args.config)
    try:
        http_server = WebSocketServer(('', 5001), app, log=None)
        http_server.serve_forever()
    except KeyboardInterrupt:
        print 'goodbye'
else:
    app = create_api_app(name='api', config='yoapi.config.Production')
