# -*- coding: utf-8 -*-

"""Socket module"""

import sys

import gevent
from flask import json, g, copy_current_request_context, current_app
from gevent.queue import Queue
from .services import redis_pubsub


class SocketMiddleware(object):
    """Middleware for routing websocket connections"""

    def __init__(self, app, socket):
        self.ws = socket
        self.wsgi_app = app.wsgi_app
        self.app = app

    def __call__(self, environ, start_response):
        """Route to socket handler if socket connection"""
        path = environ['PATH_INFO']
        if path == '/socket':
            handler = self.ws.handle_socket
            environment = environ['wsgi.websocket']
            with self.app.request_context(environ):
                self.app.preprocess_request()
                handler(environment)
            return []
        else:
            return self.wsgi_app(environ, start_response)


class WebSockets(object):
    """Websocket support for Flask"""

    # A map from commands to handlers
    socket_commands = None

    # Public redis channels to subscribe websockets to.
    public_channels = None

    def __init__(self, app=None, public_channels=None):
        self.socket_commands = {}
        self.public_channels = public_channels or []
        if app:
            self.init_app(app)

    def init_app(self, app):
        # Only allow once registration per app.
        if hasattr(app, 'websockets'):
            raise Exception('Sockets already initialized')

        self.app = app
        app.wsgi_app = SocketMiddleware(app, self)

        # Set this instance as a property on the app so it can be accessed
        # from blueprints. See `yoflask.py` for blueprint support
        # functions.
        app.websockets = self

    def handle_socket(self, websocket):
        """Socket handler with duplex support"""

        queue = Queue()
        channels = self.public_channels[:]

        def _pubsub_callback(data):
            """Inline function to get unique instances per request"""
            command = data.pop('cmd', None)
            if not command:
                return
            handler = self.socket_commands.get(command, None)
            if not handler:
                return
            try:
                rv = handler(queue, data)
                queue.put_nowait(rv)
            except:
                current_app.log_exception(sys.exc_info())

        if g.identity.user and g.identity.user.user_id:
            channels.append(g.identity.user.user_id)

        if len(channels):
            redis_pubsub.register(_pubsub_callback, channels)

        @copy_current_request_context
        def _process_queue(_queue):
            """Inline function to allow request context copy"""
            while not websocket.closed:
                message = _queue.get()
                try:
                    websocket.send(json.dumps(message))
                except Exception as e:
                    current_app.log_exception(sys.exc_info())
                    redis_pubsub.unregister(_pubsub_callback, channels)
                    # If this happens, then we return to terminate the
                    # function.
                    return

        # Spawn a worker to monitor the queue for new messages.
        gevent.spawn(_process_queue, queue)

        # Read from the socket and execute handlers.
        while not websocket.closed:
            try:
                message = websocket.receive()
                 # Null test fixes testcase because the mock socket leaves the
                 # AsyncResult unset when they exit. When that happens, the
                 # async_result.get() function returns `null`.
                if not message or message == 'null':
                    break
                data = json.loads(message)
                self.app.logger.info(data)
                try:
                    command = data.pop('cmd')
                    handler = self.socket_commands.get(command, None)
                except:
                    current_app.log_warning(sys.exc_info())
                    continue

                # If the command we received hasn't been registered through
                # a blueprint then we ignore the message.
                if not handler:
                    continue

                try:
                    rv = handler(queue, message)
                    queue.put_no_wait(rv)
                except:
                    current_app.log_warning(sys.exc_info())
            except Exception as e:
                current_app.log_warning(sys.exc_info())


    def add_command(self, command, handler):
        """Registers a handler to a command"""
        self.socket_commands[command] = handler
