# -*- coding: utf-8 -*-

"""Default configuration for YoAPI tests"""


import logging

from yoapi.config import Default


class Testing(Default):

    """Teseting configuration object"""

    DEBUG = True
    TESTING = True
    LOG_LEVEL = logging.DEBUG
    ERROR_MAILER_ENABLED = False
    ASYNC_WORKER_ENABLED = True
    SEPARATE_QUEUE_LBOUND = 25
    # This MUST use the twilio test number so as not to
    # cause issues when testing the twilio error response
    TWILIO_NUMBERS = ['+15005550006']
    MONGODB_LAZY_CONNECTION = False

    AUTO_FOLLOW_DELAY = 1

    FIRST_YO_FROM = 'TESTUSERPYTHON'
    FIRST_YO_DELAY = '1,1'
    FIRST_YO_LINK = 'http://google.com'
    FIRST_YO_LOCATION = '0,0'

    RATELIMIT_STORAGE_URL = 'redis://localhost:6379/4'

    EASTER_EGG_TEXT = 'Test easter send'
    EASTER_EGG_URL = 'https://google.com'

    MEME_PHRASE = 'good morning'

    GIPHY_PHRASE = 'good morning'
    GIPHY_TEXT = 'Sent Yo Giphy'
