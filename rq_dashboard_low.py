# -*- coding: utf-8 -*-

from gevent import monkey
monkey.patch_all()

import argparse

from gevent.wsgi import WSGIServer
from yoapi.factory import create_rq_dashboard

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='YoAPI console server.')
    parser.add_argument('--config', dest='config',
                        default='yoapi.config.RQDashboardLowDebug',
                        help='Dotted module path of config class.')
    args = parser.parse_args()
    app = create_rq_dashboard(name='rq-local', config=args.config)
    try:
        http_server = WSGIServer(('', 3000), app, log=None)
        http_server.serve_forever()
    except KeyboardInterrupt:
        print 'goodbye'
else:
    app = create_rq_dashboard(name='rq-dash', config='yoapi.config.RQDashboardLow')
