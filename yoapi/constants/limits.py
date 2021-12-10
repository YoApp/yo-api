# -*- coding: utf-8 -*-

"""Collection of constants for rate limiting"""


YO_LIMITS = '30 per minute, 180 per hour'
YOALL_LIMITS = '4 per minute, 180 per hour'
YOALL_LINK_LIMITS = '1 per hour'

YO_LIMIT_ERROR_MSG = 'Too many Yo\'s'
YO_LINK_ERROR_MSG = 'Too many Yo\'s of the same link'

LOGIN_LIMIT = '20 per minute'
LOGIN_LIMIT_MSG = 'Too many login attempts'
SIGNUP_LIMIT = '20 per minute'
SIGNUP_LIMIT_MSG = 'Too many accounts'

VERIFY_CODE_LIMITS = '5 per minute, 10 per hour'
VERIFY_CODE_LIMIT_ERROR_MSG = 'Too many attempts'

GET_ME_LIMIT = '5 per minute'