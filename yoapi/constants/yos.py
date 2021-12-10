# -*- coding: utf-8 -*-

"""Collection of constants involved in sending Yos."""


QUEUING_WORKERS = 10
PARTITION_SIZE = 2000
UNREAD_YOS_FETCH_LIMIT = 20
LIVE_YO_CHANNEL = 'live-yos'
LIVE_YO_COMMAND = 'live-yo'
WELCOME_MESSAGE_COPY = 'Yo is an app that lets you share the moments that need no words. To stop receiving Yos by SMS reply STOP.'

STATUS_PRIORITY_MAP = {
    None: -1,
    'pending': 0,
    'scheduled': 1,
    'started': 2,
    'sending': 3,
    'sent': 4,
    'received': 5,
    'dismissed': 6,
    'read': 7
}
