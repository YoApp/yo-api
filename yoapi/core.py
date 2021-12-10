# -*- coding: utf-8 -*-

"""Instantiation of core libraries.

Some libraries require decorators that depend on the instance so they
are instantiated elsewhere. See security.py as an example.
"""

from .errors import ErrorManager

from flask_cache import Cache
from flask_cors import CORS
from flask_limiter import Limiter
from flask_mongoengine import MongoEngine
from flask_principal import Principal
from flask_redis import Redis
from flask_sslify import SSLify
from flask_wtf.csrf import CsrfProtect

from .extensions.flask_facebook import Facebook
from .extensions.flask_giphy import Giphy
from .extensions.flask_imgur import Imgur
from .extensions.flask_sendgrid import SendGrid
from .extensions.flask_twilio import Twilio
from .extensions.geocoder import Geocoder
from .extensions.s3 import S3
from .extensions.sns import SNS
from .extensions.oauth import YoOAuth2Provider
import grequests
from .parse import Parse


# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name

# Flask-Redis instance
from yoapi.extensions.flask_mixpanel import MixpanelExtension


def log_to_slack(text):
    r = grequests.post('https://hooks.slack.com/services/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',
                       json={"text": text,  "icon_emoji": ":ghost:", "username": "Yo Log"})
    grequests.map([r])


redis = Redis()

# Flask-Cache instance
cache = Cache()

# Csrf Protection provided by Flask WTF
csrf = CsrfProtect()

# Flask-Limiter
limiter = Limiter()

# Parse library
parse = Parse()

# Error manager instance.
errors = ErrorManager()

# Google maps geolocation lookup library.
geocoder = Geocoder()

# Flask-Principals used for authentication.
principals = Principal(use_sessions=False)

# Mongo engine
mongo_engine = MongoEngine()

# AWS Short Notification Service instnace.
sns = SNS()

# AWS S3
s3 = S3()

# Twilio
twilio = Twilio()

# SendGrid
sendgrid = SendGrid()

# Enables CORS headers on all responses.
cors = CORS()

# This extension forces SSL. Version 0.1.4 requires that a value is passed
# for app in the constructor, even if it can be None.
sslify = SSLify()

# This is used to login users with facebook.
facebook = Facebook()

# This is used to get gifs via a phrase.
giphy = Giphy(cache=cache)

# Extension to query imgur.
imgur = Imgur()

oauth = YoOAuth2Provider()

mixpanel_yostatus = MixpanelExtension(api_key='6a870be839944269b2a628c225e32021')

mixpanel_yoapp = MixpanelExtension(api_key='33cac15230c540b752a1a24a91725538')
mixpanel_yoapp.disabled = True