# -*- coding: utf-8 -*-

"""Collection of constants related to the client Contexts."""


# Context Ids shared with the client.
AUDIO_CTX = 'audio'
CAMERA_CTX = 'camera'
DEFAULT_CTX = 'just_yo'
EMOJI_CTX = 'emoji'
GIPHY_CTX = 'gif'
LOCATION_CTX = 'location'

# These are not allowed because iOS will put them on its own.
CLIPBOARD_CTX = 'clipboard'
EASTER_EGG_CTX = 'easter_egg'
LAST_PHOTO_CTX = 'last_photo'

# This will probably never be used.
WEB_CTX = 'web'


# Context ids returned when the environment variable
# ENABLE_ALL_CONTEXTS is True.
# NOTE: This list should never contain things iOS will put on its own.
ALL_CONTEXT_IDS = [LOCATION_CTX, DEFAULT_CTX, EMOJI_CTX, GIPHY_CTX,
                   CAMERA_CTX]

# Contexts ids that the api is allowed to control. This list is used for
# ab tests to ensure we are only testing things the api is allowed to control.
ALLOWED_CONTEXT_IDS = [AUDIO_CTX, CAMERA_CTX, DEFAULT_CTX, EMOJI_CTX,
                       GIPHY_CTX, LOCATION_CTX]

# 3 Default context ids that will always be displayed.
# NOTE: Only change this in line with what the clients considers as
# defaults and WONT be A-B tested.
DEFAULT_CONTEXTS = [LOCATION_CTX, DEFAULT_CTX, CAMERA_CTX]

# All of the valid context IDS. If more contexts are created
# they should be added here. This list is used for banners to ensure
# we are creating banners for context ids that exist.
VALID_CONTEXT_IDS = [AUDIO_CTX, CAMERA_CTX, DEFAULT_CTX, EMOJI_CTX, GIPHY_CTX,
                     LOCATION_CTX, CLIPBOARD_CTX, EASTER_EGG_CTX]
