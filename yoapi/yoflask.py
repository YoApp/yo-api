# -*- coding: utf-8 -*-

"""Module for changing default behavior of Flask"""

import gevent

from io import BytesIO
from bson.objectid import ObjectId
from collections import OrderedDict, namedtuple
from flask import (Flask, Blueprint as BaseBlueprint, Request,
                   request, g, Response, json, current_app)
from gevent.queue import Queue
from threading import Lock
from uuid import uuid4
from werkzeug.exceptions import ClientDisconnected

from .core import sendgrid, redis
from .logger import JSONLogger
from .permissions import login_required, pseudo_forbidden, no_pseudo_login
from .helpers import get_usec_timestamp, get_remote_addr, iso8601_from_usec

user_active_paths = ['/rpc/register_device', '/rpc/yo']

# pylint: disable=star-args

# a lock used for logger initialization
_logger_lock = Lock()


class YoRequest(Request):

    """Subclass of Flask Request to customize behavior."""

    # Timestamp of when request was created.
    created_usec = None
    # Tells the log adapter to copy the json to a event dict.
    log_as_event  = None
    # a unique id created for each request.
    request_id = None

    def __init__(self, *args, **kwargs):
        super(YoRequest, self).__init__(*args, **kwargs)
        self.created_usec = get_usec_timestamp()
        self.request_id = self.environ.get('HTTP_X_REQUEST_ID')
        if not self.request_id:
            self.request_id = uuid4().hex

    def has_auth(self):
        try:
            return bool(g.identity.user.user_id)
        except:
            return False

    def is_user_activity(self):
        if hasattr(request, 'job'):
            return False
        if not (hasattr(g, 'identity') and hasattr(g.identity, 'user')):
            return False
        if not g.identity.user:
            return False
        if request.path in user_active_paths:
            return True
        return False

    @property
    def installation_id(self):
        return self.headers.get('X-RPC-UDID') or \
            self.headers.get('X-Yo-Installation-Id')

    @property
    def json(self):
        """Overrides the deprecated json property.

        The request JSON body is frequently accessed so we bring back this
        deprecated function. To avoid constant error checking, we make the
        default behavior silten.

        Someone might someday forget to use the correct mimetype, so we force
        the conversion.
        """
        json_data = self.get_json(silent=True, force=True) or {}

        # Patch to keep chrome extension working. It's using form data instead
        # of sending a JSON payload.
        if not json_data and self.form:
            try:
                json_data = json.loads(request.form.keys()[0])
            except ValueError:
                # Pass as there's no JSON data.
                pass

        # If regular parsing fails, revert to values dict
        if not json_data:
            json_data = self.values.to_dict()
        return self.map_params(json_data)

    def get_loggable_dict(self, include_headers=False):
        """A dict representation of that is good for loggin"""
        rv = OrderedDict((
            ('method', self.method),
            ('path', self.path),
            ('args', self.args),
            ('ssl', self.is_secure),
            ('ts', iso8601_from_usec(self.created_usec)),
            ('ip', self.remote_addr),
            ('request_id', self.request_id),
            ('install_id', self.installation_id),
            ('length', self.content_length or 0),
            ('form', self.form.items() or None),
            ('args', self.args.items() or None),
            ('useragent', self.user_agent.string),
            ('json', self.json)))
        if include_headers:
            log_headers = {}
            for header in self.headers.items():
                if header[1]:
                    log_headers[header[0]] = header[1]

            rv['headers'] = log_headers
        for key in rv:
            if rv[key] is None:
                del rv[key]

        return rv

    def map_params(self, json_data):
        """Maps legacy parameter names to their canonical counterparts"""

        # TODO: Consider a better implementation for mapping parameters
        # consistently that doesn't do unnecessary work.
        if 'email_address' in json_data:
            json_data['email'] = json_data.pop('email_address')

        if 'callback_url' in json_data:
            json_data['callback'] = json_data.pop('callback_url')

        if 'needs_location' in json_data:
            json_data['request_location'] = json_data.pop('needs_location')

        if 'new_account_username' in json_data:
            json_data['username'] = json_data.pop('new_account_username')

        if 'new_account_passcode' in json_data:
            json_data['password'] = json_data.pop('new_account_passcode')

        if 'bitlyToken' in json_data:
            json_data['bitly_token'] = json_data.pop('bitlyToken')

        return json_data


class YoResponse(Response):

    """Subclass of Flask Response to customize behavior."""

    # Only log the response json if set to true
    log_json_response = True

    def get_loggable_dict(self, include_headers=False):
        """Get a dict representation good for logging"""

        latency = get_usec_timestamp() - request.created_usec
        response_data = self.get_data() if not self.direct_passthrough else None
        response_length = len(response_data) if response_data else None

        rv = OrderedDict((('status', self.status_code),
                          ('length', response_length),
                          ('latency', latency)))

        # Include JSON response depending if content type suggests it's
        # available.
        if self.log_json_response and 'json' in self.content_type:
            try:
                log_dict = json.loads(response_data)
                if log_dict:
                    # Let's not include an empty dictionary.
                    rv['json'] = log_dict
            except (TypeError, ValueError):
                # If response is malformed then display warning in the logs
                # so there is a chance to fix it.
                current_app.logger.warning('Malformed JSON response')
        elif 'json' in self.content_type:
            rv['json'] = {'response': 'REDACTED'}

        if include_headers:
            log_headers = {}
            for header in self.headers.items():
                if header[1]:
                    log_headers[header[0]] = header[1]

            rv['headers'] = log_headers
        return rv


class MongoJSONEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, Exception):
            return str(obj)
        elif hasattr(obj, 'isoformat'):
            return obj.isoformat()
        else:
            return obj


class YoFlask(Flask):

    """Subclass of Flask to customize behavior.

    This class is meant to be used in application factories. It modifies the
    behavior of the following:

        1) Routing.
        2) Exception logging.

    Subclassing Flask becomes necessary when an application grows, so it is
    generally a good idea to do it from the start.
    """

    _is_worker = False
    json_encoder = MongoJSONEncoder
    request_class = YoRequest
    response_class = YoResponse

    def __init__(self, *args, **kwargs):
        self._is_worker = kwargs.pop('is_worker', False)
        return super(YoFlask, self).__init__(*args, **kwargs)

    def route(self, rule, **options):
        """Adds JWT auth option to regular Flask routing.

        To be extra safe, we assume authentication is required unless
        explicitly stated otherwise.

        Because this API deals mostly in POST requests, we also set that as
        the default method.
        """
        options.setdefault('methods', ['POST'])

        def decorator(f):
            endpoint = options.pop('endpoint', None)

            if hasattr(f, 'original_func'):
                func = f.original_func
                require_login = options.pop('login_required', True)
                forbid_pseudo = options.pop('pseudo_forbidden', True)
                if ((f.require_login, f.forbid_pseudo) !=
                    (require_login, forbid_pseudo)):
                    raise AssertionError('Why would you ever have '
                                         'different permissions on the '
                                         'SAME view func!? smh')

                self.add_url_rule(rule, endpoint, func, **options)
                return func

            require_login = options.pop('login_required', True)
            forbid_pseudo = options.pop('pseudo_forbidden', True)
            if require_login and forbid_pseudo:
                func = no_pseudo_login(f)
            elif require_login:
                # Use login_required need.
                func = login_required(f)
            elif forbid_pseudo:
                # Use pseudo_forbidden need.
                func = pseudo_forbidden(f)
            else:
                func = f

            func.require_login = require_login
            func.forbid_pseudo = forbid_pseudo
            func.original_func = func

            self.add_url_rule(rule, endpoint, func, **options)
            return func
        return decorator

    def socket_route(self, command, **options):
        def decorator(f):
            if hasattr(f, 'original_func'):
                func = f.original_func
                require_login = options.pop('login_required', True)
                forbid_pseudo = options.pop('pseudo_forbidden', True)
                if ((f.require_login, f.forbid_pseudo) !=
                    (require_login, forbid_pseudo)):
                    raise AssertionError('Why would you ever have '
                                         'different permissions on the '
                                         'SAME view func!? smh')

                self.websockets.add_command(command, func)
                return func

            require_login = options.pop('login_required', True)
            forbid_pseudo = options.pop('pseudo_forbidden', True)
            if require_login and forbid_pseudo:
                func = no_pseudo_login(f)
            elif require_login:
                # Use login_required need.
                func = login_required(f)
            elif forbid_pseudo:
                # Use pseudo_forbidden need.
                func = pseudo_forbidden(f)
            else:
                func = f

            func.require_login = require_login
            func.forbid_pseudo = forbid_pseudo
            func.original_func = func

            self.websockets.add_command(command, func)
            return func
        return decorator

    def log_analytics(self, data):
        """Logs an analytic event in a format that is already understood
        by the log parser.
        """

        info = OrderedDict()
        request_dict = request.get_loggable_dict(include_headers=False)
        event_data = OrderedDict()
        event_data['request_id'] = request.request_id
        event_data['ts'] = iso8601_from_usec(request.created_usec)
        event_data['useragent'] = request.user_agent.string
        for key, value in data.items():
            if hasattr(value, 'get_loggable_dict'):
                event_data[key] = value.get_loggable_dict()
            elif not callable(value):
                event_data[key] = value

        info['request'] = request_dict.copy()
        info['request']['original_path'] = info['request']['path']
        info['request']['path'] = '/callback/gen_204'
        info['event'] = event_data

        self.logger.info(info)

    def log_error(self, message, **kwargs):
        """Logs an error"""

        info = OrderedDict()

        if message:
            if isinstance(message, dict) and kwargs:
                info.update(message)
            elif isinstance(message, dict):
                kwargs = message
            else:
                info['message'] = message

        if request:
            info['request'] = request.get_loggable_dict(include_headers=True)

        for key, value in kwargs.items():
            if hasattr(value, 'get_loggable_dict'):
                info[key] = value.get_loggable_dict()
            elif isinstance(value, (basestring, int)):
                info[key] = value

        self.logger.error(info)

    def log_warning(self, message, **kwargs):
        """Logs an warning"""

        info = OrderedDict()

        if message:
            if isinstance(message, dict) and kwargs:
                info.update(message)
            elif isinstance(message, dict):
                kwargs = message
            else:
                info['message'] = message

        if request:
            info['request'] = request.get_loggable_dict(include_headers=True)

        for key, value in kwargs.items():
            if hasattr(value, 'get_loggable_dict'):
                info[key] = value.get_loggable_dict()
            elif isinstance(value, (basestring, int)):
                info[key] = value

        self.logger.warning(info)

    def log_exception(self, exc_info, **kwargs):
        """Logs an exception

        The typical stack trace is often insufficient in determing the cause
        of errors so we add more details.
        """
        exc_type, exc_value, _ = exc_info

        # Client disconnected errors must be suppressed here.
        if isinstance(exc_value, ClientDisconnected):
            return

        info = OrderedDict((('exception_type', str(exc_type)),
                           ('exception_message', str(exc_value.message))))

        # If we're handling a client disconnected error then we can't access
        # the requeset payload.
        if request:
            info['request'] = request.get_loggable_dict(include_headers=True)

        for key, value in kwargs.items():
            if hasattr(value, 'get_loggable_dict'):
                info[key] = value.get_loggable_dict()
            elif isinstance(value, (basestring, int)):
                info[key] = value

        self.logger.error(info, exc_info=True)

    def is_worker(self):
        """Returns True if this app is a marked as a Worker app"""
        return self._is_worker

    @property
    def logger(self):
        """Overrides the default logger property in Flask"""
        if self._logger and self._logger.name == self.logger_name:
            return self._logger
        with _logger_lock:
            if self._logger and self._logger.name == self.logger_name:
                return self._logger
            self._logger = rv = JSONLogger(self, sendgrid, redis)
            return rv

    @property
    def client(self):
        """Gets the client model"""
        if hasattr(g.identity, 'client'):
            return g.identity.client
        else:
            return None

    @property
    def user(self):
        """Gets the currently authenticated user"""
        if hasattr(g.identity, 'user'):
            return g.identity.user
        else:
            return None


class Blueprint(BaseBlueprint):

    """Subclass of Blueprint to customize behavior."""

    socket_commands = None

    def __init__(self, *args, **kwargs):
        self.socket_commands = {}
        super(Blueprint, self).__init__(*args, **kwargs)

    def route(self, rule, **options):
        """Adds JWT auth option to regular Blueprint routing.

        To be extra safe, we assume authentication is required unless
        explicitly stated otherwise.

        Because this API deals mostly in POST requests, we also set that as
        the default method.
        """
        options.setdefault('methods', ['POST'])

        def decorator(f):
            endpoint = options.pop('endpoint', f.__name__)

            if hasattr(f, 'original_func'):
                func = f.original_func
                require_login = options.pop('login_required', True)
                forbid_pseudo = options.pop('pseudo_forbidden', True)
                if ((f.require_login, f.forbid_pseudo) !=
                    (require_login, forbid_pseudo)):
                    raise AssertionError('Why would you ever have '
                                         'different permissions on the '
                                         'SAME view func!? smh')

                self.add_url_rule(rule, endpoint, func, **options)
                return func

            require_login = options.pop('login_required', True)
            forbid_pseudo = options.pop('pseudo_forbidden', True)
            if require_login and forbid_pseudo:
                func = no_pseudo_login(f)
            elif require_login:
                # Use login_required need.
                func = login_required(f)
            elif forbid_pseudo:
                # Use pseudo_forbidden need.
                func = pseudo_forbidden(f)
            else:
                func = f

            func.require_login = require_login
            func.forbid_pseudo = forbid_pseudo
            func.original_func = func

            self.add_url_rule(rule, endpoint, func, **options)
            return func
        return decorator

    def socket_route(self, command, **options):
        def decorator(f):
            if hasattr(f, 'original_func'):
                func = f.original_func
                require_login = options.pop('login_required', True)
                forbid_pseudo = options.pop('pseudo_forbidden', True)
                if ((f.require_login, f.forbid_pseudo) !=
                    (require_login, forbid_pseudo)):
                    raise AssertionError('Why would you ever have '
                                         'different permissions on the '
                                         'SAME view func!? smh')

                self.socket_commands[command] = func
                return func

            require_login = options.pop('login_required', True)
            forbid_pseudo = options.pop('pseudo_forbidden', True)
            if require_login and forbid_pseudo:
                func = no_pseudo_login(f)
            elif require_login:
                # Use login_required need.
                func = login_required(f)
            elif forbid_pseudo:
                # Use pseudo_forbidden need.
                func = pseudo_forbidden(f)
            else:
                func = f

            func.require_login = require_login
            func.forbid_pseudo = forbid_pseudo
            func.original_func = func

            self.socket_commands[command] = func
            return func
        return decorator

    def register(self, app, *args, **kwargs):
        """When blueprints are registered we also register socket commands"""
        super(Blueprint, self).register(app, *args, **kwargs)
        for command, handler in self.socket_commands.items():
            app.websockets.add_command(command, handler)

