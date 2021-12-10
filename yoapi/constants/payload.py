# -*- coding: utf-8 -*-

"""Collection of constants used in yoapi.models.Payload"""


CAMERA = u'\U0001F4F7'
LINK_SYMBOL = u'\U0001F517'
MICROPHONE = u'\U0001f3a4'
PAPER_CLIP = u'\U0001F4CE'
POINT_RIGHT = u'\U0001F449'
ROUND_PIN = u'\U0001F4CD'
TWO_FINGERS = u'\U0000270C'
VIDEO_CAMERA = u'\U0001F4F9'

CONTEXT_YO = 'context_yo'
CUSTOM_YO = 'custom_yo'
DEFAULT_YO = 'default_yo'
FORWARDED_PHOTO_YO = 'forwarded_photo_yo'
FORWARDED_YO = 'forwarded_yo'
LEGACY_GROUP_YO = 'legacy_group_yo'
LINK_YO = 'link_yo'
LOCATION_CITY_YO = 'location_city_yo'
LOCATION_YO = 'location_yo'
PHOTO_YO = 'photo_yo'
AUDIO_YO = 'audio_yo'
VIDEO_YO = 'video_yo'
GIF_YO = 'gif_yo'

VALID_PAYLOAD_TYPES = [CONTEXT_YO, CUSTOM_YO, DEFAULT_YO, FORWARDED_PHOTO_YO,
                       FORWARDED_YO, LEGACY_GROUP_YO, LINK_YO,
                       LOCATION_CITY_YO, LOCATION_YO, PHOTO_YO, AUDIO_YO,
                       VIDEO_YO, GIF_YO]

# Maps special payload types to ios response categories.
CATEGORY_MAP = {FORWARDED_YO: LINK_YO,
                FORWARDED_PHOTO_YO: PHOTO_YO,
                GIF_YO: PHOTO_YO,
                LOCATION_CITY_YO: LOCATION_YO}

CALL_TEXT_CATEGORY = u'Call 📞.Text 💬'
THUMBS_UP_DOWN_CATEGORY = u'\U0001f44e.\U0001f44d'
EMOJI_CATEGORY_MAP = {u'\U0001f4de': CALL_TEXT_CATEGORY,
                      u'\U0001f618': u'\U0001f60d.\U0001f61a'}

FORWARDED_YO_TYPES = [FORWARDED_YO, FORWARDED_PHOTO_YO]
LINK_YO_TYPES = [AUDIO_YO, PHOTO_YO, LINK_YO, FORWARDED_YO,
                 FORWARDED_PHOTO_YO, VIDEO_YO, GIF_YO]
LOCATION_YO_TYPES = [LOCATION_YO, LOCATION_CITY_YO]

# Legacy devices need 'From' capitalized.
# Base can be changed however desired.
BASE_YO_TEXT = u'from %s'
LEGACY_BASE_YO_TEXT = u'From %s'

# Legacy devices only support '*' and '@'.
LEGACY_LOCATION_YO_TEXT = u'@ %s'
LEGACY_LINK_YO_TEXT = u'* %s'

# Group yos simply take the regular yo text and append 'to GROUPNAME'
# at the end.
GROUP_YO_TEXT = u'%s to %s'

AUDIO_YO_TEXT = u'%s Yo %s'
CONTEXT_YO_TEXT = u'%s %s'
DEFAULT_YO_TEXT = u'%s Yo %s'
FORWARD_YO_TEXT = u'From %s via %s'
LINK_YO_TEXT = u'%s Yo Link %s'
LOCATION_CITY_YO_TEXT = u'%s Yo %s @ %s'
LOCATION_YO_TEXT = u'%s Yo Location %s'
PHOTO_YO_TEXT = u'%s Yo Photo %s'
VIDEO_YO_TEXT = u'%s Yo Video %s'
GIF_YO_TEXT = u'%s Yo GIF %s'
GIPHY_YO_TEXT = u'%s Yo GIF \'%s\' %s'

PAYLOAD_TYPE_MAP = {
    AUDIO_YO: {'emoji': MICROPHONE, 'text': AUDIO_YO_TEXT},
    CONTEXT_YO: {'emoji': '', 'text': CONTEXT_YO_TEXT},
    DEFAULT_YO: {'emoji': '', 'text': DEFAULT_YO_TEXT},
    FORWARDED_PHOTO_YO: {'emoji': CAMERA, 'text': PHOTO_YO_TEXT},
    FORWARDED_YO: {'emoji': LINK_SYMBOL, 'text': LINK_YO_TEXT},
    LINK_YO: {'emoji': LINK_SYMBOL, 'text': LINK_YO_TEXT},
    LOCATION_CITY_YO: {'emoji': ROUND_PIN, 'text': LOCATION_CITY_YO_TEXT},
    LOCATION_YO: {'emoji': ROUND_PIN, 'text': LOCATION_YO_TEXT},
    PHOTO_YO: {'emoji': CAMERA, 'text': PHOTO_YO_TEXT},
    VIDEO_YO: {'emoji': VIDEO_CAMERA, 'text': VIDEO_YO_TEXT},
    GIF_YO: {'emoji': CAMERA, 'text': GIF_YO_TEXT}}

ACTION_TEXT_DICT = {
    AUDIO_YO:           'Tap to view:',
    CONTEXT_YO:         'Tap to view:',
    DEFAULT_YO:         'Tap to Yo back:',
    FORWARDED_PHOTO_YO: 'Tap to view:',
    FORWARDED_YO:       'Tap to view:',
    LINK_YO:            'Tap to view:',
    LOCATION_CITY_YO:   'Tap to see where they are:',
    LOCATION_YO:        'Tap to see where they are:',
    PHOTO_YO:           'Tap to view:',
    VIDEO_YO:           'Tap to view:',
    GIF_YO:             'Tap to view:'}

# key: (Number of names to show, has others)
SOCIAL_DICT = {
    (0, False): '',
    (0, True):  'with %(num_others)s %(other)s',
    (1, False): 'with %(member1)s',
    (2, False): 'with %(member1)s and %(member2)s',
    (1, True):  'with %(member1)s and %(num_others)s %(other)s',
    (2, True): ('with %(member1)s, %(member2)s and %(num_others)s %(other)s')}

WEBCLIENT_URL = 'https://app.justyo.co/%s'
