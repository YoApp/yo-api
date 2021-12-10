# -*- coding: utf-8 -*-

"""Default configuration for YoAPI"""

import os
import logging


# These classes do not need public methods.
# pylint: disable=too-few-public-methods


# Helper to distinctly identify undefined values
ENV_NOT_FOUND = '__NONE__'

# Helper for loading dynamic env
_dynamic_config = {}

def env(key, default=ENV_NOT_FOUND, cast=None, optional=False):
    """Convenience function load environment variables"""

    global _dynamic_config
    # This key is no longer dynamic so don't resolve it later
    if key in _dynamic_config:
        _dynamic_config.pop(key, None)

    rv = os.getenv(key, ENV_NOT_FOUND)
    if cast and rv != ENV_NOT_FOUND:
        try:
            if cast == list:
                rv = rv.split(',')
                rv = [v.strip() for v in rv]
            elif cast == tuple:
                rv = rv.split(',')
                rv = [v.strip() for v in rv]
                rv = tuple(rv)
            elif cast == bool:
                rv = True if rv.lower() in ['true', 1, '1', 'yes'] else False
            else:
                rv = cast(rv)
        except Exception as err:
            message = 'WARNING: Environment variable "%s" could not be cast ' + \
                      'by %s'
            print message % (key, cast)

    if rv != ENV_NOT_FOUND:
        return rv

    if default != ENV_NOT_FOUND:
        return default

    if not optional:
        message = 'WARNING: Environment variable "%s" not set and has ' + \
                  'no default value.'
        print message % key
        return ENV_NOT_FOUND


def dynamic_env(target_key, dynamic_key, builder_key):
    """Used to build environment keys dynamically based on another key.

    Args:
        target_key: The target key name to be set on the config object once
                    resolved.
        dynamic_key: The dynamic key that will be built using modulous
                     operator.
        builder_key: A properly defined config key whose value will be used
                     to build the dynamic key.
    """
    global _dynamic_config

    target_key = target_key.upper()
    builder_key = builder_key.upper()

    _dynamic_config[target_key] = {'dynamic_key': dynamic_key,
                                   'builder_key': builder_key}

def resolve_dynamic_env(cls, key):
    global _dynamic_config
    super_cls = super(cls.__class__, cls)

    constructs = _dynamic_config.pop(key)
    builder_key = constructs['builder_key']
    dynamic_key = constructs['dynamic_key']

    builder_value = super_cls.__getattribute__(builder_key)

    source_key = dynamic_key % builder_value.upper()
    dynamic_value = super_cls.__getattribute__(source_key)

    super_cls.__setattr__(key, dynamic_value)


class Config(type):

    """Metaclass to issue warning when loading empty config variables"""

    def __new__(cls, name, bases, attrs):
        """Wrapper to create a iterator over the config variables"""

        config_values = {}
        for attr_name, attr_value in attrs.iteritems():
            if not callable(attr_value):
                config_values[attr_name] = attr_value

        attrs['_config_values'] = config_values

        return super(Config, cls).__new__(cls, name, bases, attrs)

    def __getattribute__(cls, key):
        if key in _dynamic_config:
            resolve_dynamic_env(cls, key)

        try:
            value = super(Config, cls).__getattribute__(key)
            if value != ENV_NOT_FOUND:
                return value
            else:
                print "WARNING: Config value not defined: %s" % key
        except AttributeError:
            raise


class Default(object):

    """Default configuration object"""

    __metaclass__ = Config

    EXPLAIN_TEMPLATE_LOADING = True

    # Allow AB tests to be globally disabled.
    AB_TESTS_ENABLED = env('AB_TESTS_ENABLED', default=True, optional=True, cast=bool)

    AWS_ACCESS_KEY_ID = env('YO_AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = env('YO_AWS_SECRET_ACCESS_KEY')

    BITLY_API_KEY = env('BITLY_API_KEY')

    MIXPANEL_API_KEY = env('MIXPANEL_API_KEY')

    CACHE_REDIS_URL = 'redis://localhost:6379/1'
    CACHE_KEY_PREFIX = 'YOAPI'

    CACHE_ENABLED = True
    CACHE_TYPE = env('CACHE_TYPE', default='redis')

    # See Flask-Cors documentation for more information.
    # http://flask-cors.readthedocs.org/
    CORS_HEADERS = 'Content-Type'
    CORS_SEND_WILDCARD = False
    CORS_HEADERS = 'Authorization,Content-Type,X-CSRF-Token'
    CORS_SUPPORTS_CREDENTIALS = True
    CORS_AUTOMATIC_OPTIONS = True
    CORS_MAX_AGE = 31 * 86400

    # Debug mode the debugger will kick in when an unhandled exception occurs
    # and the integrated server will automatically reload the application if
    # changes in the code are detected.
    DEBUG = True

    # The defualt context shown in the app.
    DEFAULT_CONTEXT = env('DEFAULT_CONTEXT', default='just_yo',
                          optional=True)
    # Controls displaying all the contexts instead of just the defaults.
    ENABLE_ALL_CONTEXTS = env('ENABLE_ALL_CONTEXTS', default=False, optional=True)

    ERROR_MAILER_ENABLED = False
    ERROR_WEBHOOK_ENABLED = False

    # GeoIP Lookup server.
    GEOIP_SERVER = env('GEOIP_SERVER')

    # Used with the giphy library.
    GIPHY_API_KEY = env('GIPHY_API_KEY', optional=True)

    IMAGE_WRAPPER_PREFIX = 'http://i.justyo.co/?link='

    # Secret key, used for signing secure cookies.
    SECRET_KEY = 'pZ3uXRncvfL2P4cP9RM3wTyBQqmJjYMKyP6PFzO1H54VHQtMy7RDlI8Gp4w8RsCo'
    JWT_SECRET_KEY = SECRET_KEY
    JWT_OLD_SECRET_KEY = 'secret'
    JWT_AUTH_HEADER_PREFIX = 'Bearer'
    JWT_ALGORITHM = 'HS256'

    # Server url for inviting users.
    INVITE_SERVER = 'https://www.justyo.co/invite'
    SEND_YO_SERVER = 'https://www.justyo.co/yo'

    LIVE_COUNTER_URL = env('LIVE_COUNTER_URL')
    LIVE_COUNTER_AUTH_TOKEN = env('LIVE_COUNTER_TOKEN')

    LOG_LEVEL = logging.DEBUG

    MAILCHIMP_API_KEY = env('MAILCHIMP_API_KEY')
    MAILCHIMP_LIST_ID = env('MAILCHIMP_LIST_ID')
    MAILCHIMP_SERVER = env('MAILCHIMP_SERVER')

    MONGODB_HOST = 'mongodb://localhost:27017/yo'
    MONGODB_LAZY_CONNECTION = True

    PARSE_APPLICATION_ID = env('PARSE_APPLICATION_ID')
    PARSE_MASTER_KEY = env('PARSE_MASTER_KEY')
    PARSE_REST_API_KEY = env('PARSE_REST_API_KEY')

    # Pretty prints JSON for logging.
    PRETTY_PRINT_LOGS = True

    # Propagate exceptions or let YoFlask.log_exception handle them.
    PROPAGATE_EXCEPTIONS = False

    # Rate limiter
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_STRATEGY = 'fixed-window'
    RATELIMIT_GLOBAL = ''

    RATELIMIT_STORAGE_TYPE = env('RATELIMIT_STORAGE_TYPE', default='redis')
    RATELIMIT_STORAGE_OPTIONS = {'max_connections': 20}
    RATELIMIT_REDIS_URL = 'redis://localhost:6379/4'
    RATELIMIT_MEMORY_URL = 'memory://'
    # The return value here is always None however it is important to define
    # the key so that it is added to the iterator via __new__.
    # The env variable name must be passed as the first arg so that
    # setattr(name, value) can be used to populate it when accessed.
    RATELIMIT_STORAGE_URL = dynamic_env('RATELIMIT_STORAGE_URL',
                                        'RATELIMIT_%s_URL',
                                        'RATELIMIT_STORAGE_TYPE')
    # Used as the from field in password recovery emails.
    RECOVERY_EMAIL_FROM = 'contact@justyo.co'

    # Access API at [hostname]/[RQ_DASHBOARD_ID]/rg
    RQ_DASHBOARD_ID = 'MQOA9BF9YPLUSZN0I2VL6FXZ148E9D9O'

    # This is where we store profile pictures going forward.
    S3_IMAGE_BUCKET = 'yoapp-images'

    # Static files like .js and .css have relative paths by defaul. Modify
    # this to add an absolute prefix.
    STATIC_FILE_PREFIX = ''

    # Tell the scheduler what to listen for and what to schedule
    SCHEDULE_NAME = env('SCHEDULE_NAME', default='default')

    SENDGRID_PASSWORD = env('SENDGRID_PASSWORD')
    SENDGRID_USERNAME = env('SENDGRID_USERNAME')

    TWILIO_ACCOUNT_SID = env('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = env('TWILIO_AUTH_TOKEN')

    TWILIO_NUMBERS = ['+18554650994']

    # Disable automatic CSRF protection on forms.
    WTF_CSRF_ENABLED = False

    # This is used by Flask-Redis
    REDIS_URL = 'redis://localhost:6379/0'

    RQ_PAUSED_QUEUES = env('RQ_PAUSED_QUEUES', cast=list, default=[])
    RQ_HIGH_URL = 'redis://localhost:6379/2'
    RQ_HIGH_TIMEOUT = 180
    RQ_HIGH_MAX_ATTEMPTS = 3

    RQ_LOW_URL = 'redis://localhost:6379/3'
    RQ_LOW_TIMEOUT = 600
    RQ_LOW_MAX_ATTEMPTS = 3

    RQ_MEDIUM_URL = 'redis://localhost:6379/4'
    RQ_MEDIUM_TIMEOUT = 600
    RQ_MEDIUM_MAX_ATTEMPTS = 3

    RQ_REDIS_URL = REDIS_URL

    AUTO_FOLLOW_DELAY = env('AUTO_FOLLOW_DELAY', cast=int, default=10)

    FIRST_YO_DELAY = None
    FIRST_YO_LINK = None
    FIRST_YO_LOCATION = None
    FIRST_YO_FROM = None

    SESSION_COOKIE_DOMAIN = 'justyo.co'

    YO_PHOTO_BUCKET = 'yoapp-userfiles'

    def __iter__(self):
        return self._config_values.items()


class Production(Default):

    """Production configuration object"""

    __metaclass__ = Config

    CACHE_DEFAULT_TIMEOUT = 30 * 24 * 3600
    CACHE_ENABLED = True
    CACHE_REDIS_URL = env('CACHE_REDIS_URL')

    # Debug mode the debugger will kick in when an unhandled exception occurs
    # and the integrated server will automatically reload the application if
    # changes in the code are detected.
    DEBUG = False

    EASTER_EGG_TEXT = env('EASTER_EGG_TEXT', optional=True)
    EASTER_EGG_URL = env('EASTER_EGG_URL', optional=True)

    ERROR_ALERTS_ALLOWED = env('ERROR_ALERTS_ALLOWED', cast=int, default=1)
    ERROR_ALERT_TIMEDELTA = env('ERROR_ALERT_TIMEDELTA', cast=int,
                                default=60)
    ERROR_MAILER_ENABLED = env('ERROR_MAILER_ENABLED', cast=bool,
                               default=True)
    ERROR_MAILER_FROM = env('ERROR_MAILER_FROM')
    ERROR_MAILER_TO = env('ERROR_MAILER_TO')

    # Sends errors directly to slack.
    ERROR_WEBHOOK_ENABLED = env('ERROR_WEBHOOK_ENABLED', cast=bool)
    ERROR_WEBHOOK_FROM = env('ERROR_WEBHOOK_FROM', default=':squirrel:')
    ERROR_WEBHOOK_URL = env('ERROR_WEBHOOK_URL')

    FIRST_YO_DELAY = env('FIRST_YO_DELAY', default='180,300')
    FIRST_YO_LINK = env('FIRST_YO_LINK')
    FIRST_YO_LOCATION = env('FIRST_YO_LOCATION')
    FIRST_YO_FROM = env('FIRST_YO_FROM', default=False)

    # Used with the giphy context in the app.
    GIPHY_PHRASE = env('GIPHY_PHRASE', optional=True, default='good morning')
    GIPHY_TEXT = env('GIPHY_TEXT', optional=True, default='Sent Yo Giphy')

    LOG_LEVEL = logging.INFO

    # Used with the imgur context in the app.
    MEME_PHRASE = env('MEME_PHRASE', optional=True, default='good morning')

    MONGODB_HOST = env('MONGO_HOST')
    MONGODB_LAZY_CONNECTION = True

    # Propagate exceptions or let YoFlask.log_exception handle them.
    PROPAGATE_EXCEPTIONS = False

    # Elastic mapreduce can't parse logs unless the JSON data is written
    # as a single string.
    PRETTY_PRINT_LOGS = False

    RATELIMIT_GLOBAL = env('RATELIMIT_GLOBAL')

    RATELIMIT_REDIS_URL = env('RATELIMIT_REDIS_URL', optional=True)

    REDIS_URL = env('REDIS_URL')

    RQ_LOW_URL = env('RQ_LOW_URL')
    RQ_LOW_TIMEOUT = env('RQ_LOW_TIMEOUT')
    RQ_LOW_MAX_ATTEMPTS = env('RQ_LOW_MAX_ATTEMPTS', cast=int, default=3)

    RQ_HIGH_URL = env('RQ_HIGH_URL')
    RQ_HIGH_TIMEOUT = env('RQ_HIGH_TIMEOUT')
    RQ_HIGH_MAX_ATTEMPTS = env('RQ_HIGH_MAX_ATTEMPTS', cast=int, default=3)

    RQ_MEDIUM_URL = env('RQ_MEDIUM_URL')
    RQ_MEDIUM_TIMEOUT = env('RQ_MEDIUM_TIMEOUT')
    RQ_MEDIUM_MAX_ATTEMPTS = env('RQ_MEDIUM_MAX_ATTEMPTS', cast=int, default=3)

    RQ_REDIS_URL = REDIS_URL

    # This variable is used as a threshold when deciding if a braodcast
    # should create a separate queue to not block the defualt queue. If
    # the recipient count is lower than this value then the default one
    # is used.
    SEPARATE_QUEUE_LBOUND = env('SEPARATE_QUEUE_LBOUND', cast=int, default=25)

    # These users are not subject to rate limiting. See limiter.py for more
    # information.
    WHITELISTED_USERNAMES = env('WHITELISTED_USERNAMES')


class ProductionWeb(Production):

    """Production configuration object"""

    STATIC_FILE_PREFIX = 'https://justyo-co.s3.amazonaws.com'


class ProductionWithPrettyJSON(Production):

    """Production config but pretty print JSON log entries"""

    PRETTY_PRINT_LOGS = True


class LocalRedis(ProductionWithPrettyJSON):
    CACHE_REDIS_URL = 'redis://localhost:6379/1'

    RATELIMIT_STORAGE_TYPE = env('RATELIMIT_STORAGE_TYPE', default='memory')
    RATELIMIT_REDIS_URL = 'redis://localhost:6379/1'
    RATELIMIT_MEMORY_URL = 'memory://'

    REDIS_URL = 'redis://localhost:6379/0'
    RQ_HIGH_URL = 'redis://localhost:6379/2'
    RQ_LOW_URL = 'redis://localhost:6379/0'
    RQ_MEDIUM_URL = 'redis://localhost:6379/4'

    MONGODB_LAZY_CONNECTION = False


class ProductionDebug(LocalRedis):

    """Production config but pretty print JSON log entries"""

    DEBUG = True
    ERROR_MAILER_ENABLED = False
    PRETTY_PRINT_LOGS = True
    PROPAGATE_EXCEPTIONS = False
