# -*- coding: utf-8 -*-

"""A custom logger for the YoAPI.

TODO: This should be moved into its own repository so it can beresued across
different flask apps.
"""

import logging
import hashlib
import requests
import socket
import sys
import traceback


from cStringIO import StringIO
from datetime import datetime
from flask import json, request, current_app, g, _request_ctx_stack
from collections import OrderedDict
from coloredlogs import ColoredStreamHandler
from logging import Formatter, StreamHandler, getLogger
from logging.handlers import BufferingHandler
from werkzeug.local import LocalProxy


EXTENSION_NAME = 'JSONLogger'


class JSONLogger(object):

    """A custom logging class for Flask.

    We are trying to achieve the following things by replacing the default log
    handler in Flask.

        1. Make initialization in yoflask.py as simple as possible.
        2. Log everything as a JSON string.
        3. Include relevant contextual information for all records.
        4. Send admins an email for errors and critical records.

    Even though we initialize this class inside of the Flask subclass, we still
    use the "extension" pattern. This makes future modifications easier.

    Note that __getattr__ forwards attribute lookups first to the logger adapter,
    which is responsible for attaching contextual information, and if no match is
    found there, we then try the same for the actual logging object. This means
    that e.g. `logger.info()` actually calls the `info` method on the adapter
    object.
    """

    SEVERITY_TO_STYLE = {
        'DEBUG': dict(color='yellow'),
        'INFO': dict(color='green'),
        'VERBOSE': dict(color='yellow'),
        'WARNING': dict(color='cyan'),
        'ERROR': dict(color='red'),
        'CRITICAL': dict(color='red', bold=True)}

    def __init__(self, app=None, sendgrid=None, redis=None):
        app.extensions = getattr(app, 'extensions', {})
        if not EXTENSION_NAME in app.extensions:
            app.extensions[EXTENSION_NAME] = {}

        if self in app.extensions[EXTENSION_NAME]:
            # Raise an exception if extension already initialized as
            # potentially new configuration would not be loaded.
            raise Exception('Extension already initialized')

        # Silence a few of the module loggers.
        # TODO: Figure out why these need to be silenced and not other
        # libraries.
        #     It seems that setting an error log level on the root
        # logger by calling getLogger() without arguments doesn't
        # actually mute the libraries below. It should be investigated
        # since it only affects 4 libraries, which is suspicious.
        limiter_logger = getLogger('flask-limiter')
        limiter_logger.setLevel(app.config.get('LOG_LEVEL', logging.DEBUG))
        request_logger = getLogger('requests')
        request_logger.setLevel(app.config.get('LOG_LEVEL', logging.DEBUG))

        getLogger('boto').setLevel(app.config.get('LOG_LEVEL', logging.DEBUG))
        getLogger('rq').setLevel(app.config.get('LOG_LEVEL', logging.DEBUG))

        # Set log level on root logger even though it's not behaving as
        # expected.
        getLogger().setLevel(app.config.get('LOG_LEVEL', logging.DEBUG))

        # Let's not mix up this logger with Flask's own logger. This way
        # we can separate streams, or silence the other Flask log messages.
        logger = getLogger(app.logger_name)
        logger.setLevel(app.config.get('LOG_LEVEL', logging.DEBUG))

        # just in case that was not a new logger, get rid of all the handlers
        # already attached to it.
        del logger.handlers[:]

        # Add a email handler.
        email_handler = self._create_email_handler(app, sendgrid, redis)
        email_handler.setFormatter(JSONFormatter(app=app, pretty=True))
        logger.addHandler(email_handler)

        # Add a new stream handler.
        stream_handler = self._create_stream_handler(app)
        stream_handler.setFormatter(JSONFormatter(app))
        logger.addHandler(stream_handler)

        # After each request we log the response.
        app.after_request(self.log_response)

        # Adding fixed fields to the logger
        args = OrderedDict((('server', socket.gethostname()),
                            ('app', app.name)))

        # Create a logger adapter that can decorate the logged message with
        # standard items like, IP address, current user etc.
        adapter = LoggerAdapter(app, logger, extra=args)

        # Log request details after each request.
        app.extensions[EXTENSION_NAME][self] = (adapter, logger)

    def _create_stream_handler(self, app):
        """Creates a logger for a Flask application"""
        handler = StreamHandler(sys.stdout)
        return handler

    def _create_email_handler(self, app, sendgrid, redis):
        """Creates a logger for a Flask application"""
        handler = EmailHandler(app, sendgrid, redis)
        return handler

    def log_response(self, response=None):
        """Emits a log message (surprise).

        Contents of the request body are filtered by the _filter_content
        function before the it is included in the log message.

        TODO (mattias): Figure out if this should be tied to after_request or
        teardown_request. The big difference would be that teardown_request
        happens regardless of an exception being thrown in the request.

        Args:
            response: A response object.
        """

        if response.direct_passthrough:
            return response

        # The adapter adds contextual information to the record.
        adapter, _ = current_app.extensions[EXTENSION_NAME][self]
        log_entry = OrderedDict()
        if request:
            log_entry['request'] = request.get_loggable_dict()
            if request.log_as_event:
                log_entry['event'] = request.json.copy()
        if hasattr(request, 'job'):
            log_entry['job'] = request.job.get_loggable_dict()
        log_entry['response'] = response.get_loggable_dict()
        adapter.info(log_entry)
        return response

    def __getattr__(self, name):
        """Forward any uncaught attributes to the instance object"""
        adapter, logger = current_app.extensions[EXTENSION_NAME][self]
        if hasattr(adapter, name):
            return getattr(adapter, name)
        elif hasattr(logger, name):
            return getattr(logger, name)
        else:
            raise AttributeError('%s has no attribute "%s"' % (self, name))


class JSONFormatter(Formatter):

    """Formatter that dumps the message to JSON"""

    # For the following fields we redact the key value.
    _excluded_fields = ['image_body', 'tok', 'session_token', 'contacts',
                        'password', 'photo', 'phone_numbers', 'parse_payload',
                        'sns_message', 'cover']

    _system_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    def __init__(self, app=None, pretty=False):
        self.app = app
        self.pretty = pretty

    @classmethod
    def _filter_content(cls, data):
        """Filters some content from request/response payload"""
        if isinstance(data, list):
            for item in data:
                item = cls._filter_content(item)
        if isinstance(data, dict):
            for field_name, value in data.items():
                if field_name in cls._excluded_fields:
                    data[field_name] = 'REDACTED'
                else:
                    if isinstance(value, dict) or isinstance(value, list):
                        value = cls._filter_content(value)
        return data

    def format(self, record):
        """Formats a log record as a JSON string"""
        indent = None
        if self.pretty or self.app.config.get('PRETTY_PRINT_LOGS'):
            indent = 4

        if isinstance(record.msg, dict):
            rv = json.dumps(self._filter_content(record.msg),
                            sort_keys=False,
                            indent=indent)
        else:
            # This line merges any user supplied arguments into the string via
            # interpolation.
            record.message = record.getMessage()

            if '%(asctime)' in self._system_fmt:
                record.asctime = self.formatTime(record)
            rv = self._system_fmt % record.__dict__

        # Include the stacktrace if we're in debug mode.
        if self.app.config.get('DEBUG') and record.exc_info:
            rv = rv + '\n\n' + ''.join(traceback.format_tb(record.exc_info[2]))

        return rv


class LoggerAdapter(logging.LoggerAdapter):

    """Logger adapter to pre-process messages into JSON strings

    In addition to ensuring that output messages are JSON formatted we also
    add contextual information like server IP address etc.
    """

    def __init__(self, app, logger, extra=None):
        self.app = app
        super(LoggerAdapter, self).__init__(logger, extra=extra)

    def process(self, message, kwargs):
        """Processes the log record and attaches extra variables"""
        rv = OrderedDict()

        if hasattr(g, 'identity'):
            if (hasattr(g.identity, 'client') and
                hasattr(g.identity.client, 'client_id')):
                rv['client_hash'] = str(g.identity.client.client_id)
            if hasattr(g.identity, 'id') and g.identity.id:
                rv['user_id'] = g.identity.id
            if hasattr(g.identity, 'user') and g.identity.id:
                rv['username'] = g.identity.user.username
            if hasattr(g.identity, 'auth_type'):
                rv['auth'] = g.identity.auth_type

        if self.extra:
            rv.update(self.extra)

        # Dump to JSON if record is a string.
        if not isinstance(message, dict):
            rv['message'] = message
        else:
            request_dict = message.get('request')
            request_id = None
            if request_dict:
                new_request_dict = OrderedDict()
                new_request_dict.update(rv)
                new_request_dict.update(request_dict)
                request_id = request_dict.get('request_id')
                message['request'] = new_request_dict

            event_dict = message.get('event')
            if event_dict:
                new_event_dict = OrderedDict()
                new_event_dict['request_id'] = request_id
                new_event_dict.update(event_dict)
                message['event'] = new_event_dict

            job_dict = message.get('job')
            if job_dict:
                new_job_dict = OrderedDict()
                new_job_dict['request_id'] = request_id
                new_job_dict.update(job_dict)
                message['job'] = new_job_dict

            response_dict = message.get('response')
            if response_dict:
                new_response_dict = OrderedDict()
                new_response_dict['request_id'] = request_id
                new_response_dict.update(response_dict)
                message['response'] = new_response_dict

            rv.update(message)

        return rv, kwargs


class EmailHandler(StreamHandler):

    """A class that sends an email on application errors"""
    CHANNEL_MAP = {'ERROR': '#api-errors', 'WARNING': '#api-warnings'}
    COLOR_MAP = {'ERROR': '#FF0000', 'WARNING': '#FFFF00'}

    def __init__(self, app=None, sendgrid=None, redis=None):
        StreamHandler.__init__(self, app)
        self.app = app
        self.sendgrid = sendgrid
        self.redis = redis
        self.setLevel(logging.WARNING)
        self.redis_key_prefix = 'redis:emails:'

    def _check_email_limit(self, exc_type, exc_message):
        """ Checks that the same email wasn't already sent within 1 minute"""
        if not self.redis:
            return True

        exc_hash = hashlib.sha1('%s%s' % (exc_type, exc_message)).hexdigest()
        redis_key = '%s%s' % (self.redis_key_prefix, exc_hash)
        hits = self.redis.incr(redis_key)

        errors_allowed = self.app.config.get('ERROR_ALERTS_ALLOWED', 1)
        error_timeout = self.app.config.get('ERROR_ALERT_TIMEDELTA', 60)
        if hits <= errors_allowed:
            self.redis.expire(redis_key, error_timeout)
            return True
        else:
            return False

    def emit(self, record, pretty=True):
        """We override the default emit method to send an email instead"""

        if not (self.app.config.get('ERROR_MAILER_ENABLED') or
                self.app.config.get('ERROR_WEBHOOK_ENABLED')):
            return

        channel = self.CHANNEL_MAP.get(record.levelname)
        color = self.COLOR_MAP.get(record.levelname, '#FF0000')

        formatted_record = self.formatter.format(record)

        body = StringIO()
        body.write(formatted_record)
        fallback_text = formatted_record.encode('ascii', 'ignore')
        subject = 'Yo Error Handler'

        if record.exc_info:

            exc_type, exc_value, exc_trace = record.exc_info
            exc_type, exc_message = (str(exc_type), str(exc_value.message))
            fallback_text = '%s | %s' % (exc_type, exc_message)
            subject = 'Yo Error Handler %s' % exc_message

            if not self._check_email_limit(exc_type, exc_message):
                return

            body.write(2 * '\r\n')
            body.write(exc_type + '\n')
            body.write(exc_message + '\n')
            stacktrace = ''.join(traceback.format_tb(exc_trace))
            body.write(stacktrace)

        # Keeping the subject unique by the message helps stack errors into
        # convenient threads in gmail.

        if (self.app.config.get('ERROR_WEBHOOK_ENABLED') and
            self.app.config.get('ERROR_WEBHOOK_URL')):
            icon = self.app.config.get('ERROR_WEBHOOK_FROM')
            params = {'username': 'Yo Error Handler',
                      'icon_emoji': icon,
                      'attachments': [
                          {'fallback': fallback_text,
                           'title': subject,
                           'color': color,
                           'text': '```%s```' % body.getvalue(),
                           'mrkdwn_in': ['text', 'pretext']
                          }
                      ]}
            if channel:
                params.update({'channel': channel})

            requests.post(self.app.config.get('ERROR_WEBHOOK_URL'),
                          json=params)
        if (self.app.config.get('ERROR_MAILER_ENABLED') and
            self.app.config.get('ERROR_MAILER_TO') and
            record.levelname == 'ERROR'):
            # Assemble the email body.
            self.sendgrid.send_mail(
                recipient=self.app.config.get('ERROR_MAILER_TO'),
                sender=self.app.config.get('ERROR_MAILER_FROM'),
                subject=subject,
                body=body.getvalue())
