# -*- coding: utf-8 -*-

"""Factory for creating Flask applications"""

import time
from datetime import datetime

import requests
import newrelic.agent
from flask import g, make_response, request
from werkzeug.contrib.fixers import ProxyFix
from ..callbacks import process_user_activity
from ..core import (cache, redis, parse, errors, mongo_engine,
                    twilio, sendgrid, cors, csrf, sslify)
from ..helpers import make_json_response
from ..permissions import assert_admin_permission
from ..services import redis_pubsub
from ..security import principals
from ..yoflask import YoFlask


def create_web_app(*args, **kwargs):
    """Create a web app"""
    app = create_app(*args, **kwargs)

    # Force SSL if not already on it.
    sslify.init_app(app)

    # Add CORS headers to all requests.
    cors.init_app(app)

    # On the web we want CSRF protection enabled.
    csrf.init_app(app)

    # Initialize auth blueprint.
    from ..blueprints.auth import auth_bp
    app.register_blueprint(auth_bp)

    # TODO: Figure out a better home for this context processor.
    @app.context_processor
    def inject_identity():
        return dict(user=g.identity.user)

    return app


def create_app(name=None, override_settings=None, config=None, is_worker=False,
               template_folder=None, **kwargs):
    """Creates a configured Flask instance.

    Args:
        name: Flask app instance name.
        override_settings: A dict used to override settings loaded from object.

    Returns:
        A Flask application instance.
    """
    app = YoFlask(name or __name__, is_worker=is_worker, static_folder=None,
                  template_folder=template_folder)

    # ProxyFix: http://goo.gl/CkGR0e
    app.wsgi_app = ProxyFix(app.wsgi_app)

    app.config.from_object(config)
    if override_settings:
        app.config.update(**override_settings)

    # TODO: refactor the yoflask.YoFlask logger property so that it is
    # initialized on startup. If nothing accesses the logger object, then
    # the after_request hook is never registered.
    #   On the other hand, if it's loaded before the config then it won't
    # be initialized properly.
    app.logger  # pylint: disable=pointless-statement

    cache.init_app(app)
    errors.init_app(app)
    parse.init_app(app)
    principals.init_app(app)
    redis.init_app(app)
    redis_pubsub.init_app(app)
    sendgrid.init_app(app)
    twilio.init_app(app)

    conn_opts = {}
    conn_opts['host'] = app.config.get('MONGODB_HOST')
    conn_opts['max_pool_size'] = 1000
    conn_opts['use_greenlets'] = True
    conn_opts['auto_start_request'] = True
    conn_opts['safe'] = True
    conn_opts['alias'] = 'default'
    conn_opts['w'] = 1
    conn_opts = {'MONGODB_SETTINGS': conn_opts}
    lazy_connect = app.config.get('MONGODB_LAZY_CONNECTION', False)
    conn_opts['MONGODB_LAZY_CONNECTION'] = lazy_connect
    mongo_engine.init_app(app, config=conn_opts)

    @app.route('/clear', methods=['GET'], login_required=True)
    def route_clear_cache():  # pylint: disable=unused-variable
        """Route for clearing Flask-Cache"""
        assert_admin_permission('Unauthorized')
        cache.clear()
        return make_response('Cache cleared at: %s' % datetime.now())

    @app.route('/crash', methods=['GET'], login_required=True)
    def route_crash():  # pylint: disable=unused-variable
        """Route for manually raising an exception"""
        assert_admin_permission('Unauthorized')
        raise Exception('This exception was caused by a test. Don\'t worry.')

    @app.route('/env', methods=['GET'], login_required=True)
    def route_env():  # pylint: disable=unused-variable
        """Temporary route for manually raising an exception"""
        environ = dict([(key, str(value))
                        for key, value in request.environ.items()])
        assert_admin_permission('Unauthorized')
        return make_json_response(username=g.identity.user.username,
                                  auth_type=g.identity.auth_type,
                                  environ=environ)

    @app.route('/sleep', methods=['GET'], login_required=True)
    def route_sleep():
        """Sleeps for 30 seconds in order to test gunicorn's --timeout"""
        assert_admin_permission('Unauthorized')
        time.sleep(30)
        return make_json_response()

    @app.route('/twemproxy_stats', methods=['GET'], login_required=True)
    def route_twemproxy_stats():
        """Proxy to retreive the twemproxy stats"""
        assert_admin_permission('Unauthorized')
        req = requests.get('http://localhost:22222', stream=True)

        response_json = req.json()
        return make_json_response(**response_json)

    @app.route('/up/', login_required=False, methods=['GET'])
    def route_up():
        """Endpoint for Pingdom verifying the server is up"""
        return make_json_response()

    # Variable to ease setup of Flask-Script. It has its own argument parser,
    # and overriding it is complicated. Therefore, we declare the impersonate
    # variable here. This is also the reason we accept **kwargs for this
    # function.
    app.impersonate = kwargs.pop('impersonate', None)

    @app.after_request
    def after_request(response):
        if (request.has_auth() and response.status_code >= 200 and
            response.status_code < 300):
            try:
                process_user_activity()
            except:
                pass

        if request.has_auth():
            user = g.identity.user
            # Let's add user and request info to the new relic traces.
            newrelic.agent.add_custom_parameter('user_id', user.user_id)
            newrelic.agent.add_custom_parameter('username', str(user.username))

        newrelic.agent.add_custom_parameter('request_id',
                                            request.headers.get('X-Request-Id'))
        response.headers.extend({
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        })

        return response

    return app
