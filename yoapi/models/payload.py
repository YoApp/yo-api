# -*- coding: utf-8 -*-

"""Helper class for constructing push notification payloads"""

import sys

import semver
from flask import json, current_app
from mongoengine.errors import (DoesNotExist,
                                MultipleObjectsReturned)
from ..constants.context import GIPHY_CTX
from ..constants.emojis import text_has_emojis
from ..constants.payload import *
from ..constants.regex import DOUBLE_PERIOD_RE
from ..categories import get_category
from ..contacts import get_contact_pair
from ..contexts import get_gif_phrase
from ..errors import APIError
from ..headers import get_header, build_sms_from_header, build_sms_from_parts
from .notification_endpoint import ANDROID, IOS, IOSDEV
from .yo import Yo
from yoapi.notification_endpoints import IOSBETA


class Payload(object):
    """A payload represents an instance of everything needed to
    construct a payload to send to sns or parse, or twilio/sms.
    """

    category = None
    sound = None

    legacy_enabled = None
    must_handle_any_text = None
    must_handle_invisible_push = False
    must_handle_real_names = False
    should_send_add_response = False
    parse_enabled = None
    sns_enabled = None
    supported_platforms = None

    _extras = None
    _text = None
    _type = None

    DEFAULT = 'notification'

    def __init__(self, text, sound, header=None, **kwargs):
        # Set base endpoint requirements.
        self.legacy_enabled = True
        self.must_handle_any_text = False
        self.must_handle_invisible_push = False
        self.must_handle_real_names = False
        self.parse_enabled = True
        self.sns_enabled = True
        self.version_support = None
        self.should_send_add_response = False

        self._badge = None

        self._extras = {}
        self._text = text
        if header:
            self._text = header.push

        self.category = 'Response_Category'
        if 'category' in kwargs:
            self.category = kwargs.pop('category')
        self.sound = sound

        if kwargs:
            self.set_extras(**kwargs)

        self._type = self.DEFAULT

    def get_extras(self, key=None):
        if not self._extras:
            self._extras = {}

        if key:
            return self._extras.get(key)
        return self._extras

    def get_push_text(self):
        return self._text or ''

    @property
    def payload_type(self):
        return self._type

    def requires_invisible_push(self):
        return self.must_handle_invisible_push

    def requires_any_text(self):
        return self.must_handle_any_text

    def requires_add_response_push(self):
        return self.should_send_add_response

    def set_extras(self, **kwargs):
        if not self._extras:
            self._extras = {}

        for key, val in kwargs.items():
            if val is not None:
                self._extras.update({key: val})

    def should_send_to_parse(self):
        return self.parse_enabled

    def should_send_to_sns(self):
        return self.sns_enabled

    def should_send_to_legacy(self):
        return self.legacy_enabled

    def supports_platform(self, platform):
        if self.supported_platforms is None:
            return True
        if platform in self.supported_platforms:
            return True

        return False

    def supports_version(self, version):
        if self.version_support is None:
            return True

        if not version:
            return False

        try:
            return semver.match(version, self.version_support)
        except ValueError:
            current_app.log_exception(sys.exc_info())

        return False


    def to_parse(self):
        ios_payload = {'alert': self.get_push_text(),
                       'content-available': '1',
                       'category': 'Response_Category',
                       'sound': self.sound}
        payload = {'action': 'com.example.yo.UPDATE_STATUS',
                   'sound': self.sound,
                   'header': self.get_push_text(),
                   'aps': ios_payload}

        return payload

    def get_apns_payload(self):
        payload = {
            'aps': {
                'content-available': '1',
                'category': self.category
            }
        }

        if self.sound:
            payload['aps'].update({'sound': self.sound})
            payload.update({'sound': self.sound})

        push_text = self.get_push_text()
        if push_text:
            # @or: alert can be string or dict
            # https://developer.apple.com/library/mac/documentation/NetworkingInternet/Conceptual/RemoteNotificationsPG/Chapters/TheNotificationPayload.html#//apple_ref/doc/uid/TP40008194-CH107-SW1
            alert = push_text

            # @or: client needs fixing before using this
            #if self.get_extras('sender_object') and self.get_extras('sender_object').get('display_name'):
            #    alert = {
            #        'title': self.get_extras('sender_object').get('display_name'),
            #        'body': push_text
            #    }

            payload['aps'].update({'alert': alert})
            payload.update({'header': push_text})

            if self._badge is not None:
                payload['aps'].update({'badge': self._badge})

        payload.update(self.get_extras())

        return payload

    def get_win_payload(self):
        payload = {'alert': 'Yo %s' % self.get_push_text()}

        if self.sound:
            payload.update({'sound': self.sound})

        payload.update(self.get_extras())

        return payload

    def get_mpns_payload(self):
        try:
            json_extras = json.dumps(self.get_win_payload())
            payload_xml = u'<?xml version="1.0" encoding="utf-8"?>' + \
                          u'<wp:Notification xmlns:wp="WPNotification">' + \
                          u'<wp:Toast>' + \
                          u'<wp:Text1>Yo</wp:Text1>' + \
                          u'<wp:Text2>' + self.get_push_text() + u'</wp:Text2>'
            if self.sound:
                payload_xml += u'<wp:Sound>/Assets/' + self.sound + u'</wp:Sound>'

            payload_xml += u'<wp:Param>?pushJson=' + json_extras + u'</wp:Param>' + \
                           u'</wp:Toast>' + \
                           u'</wp:Notification>'
        except:
            current_app.log_exception(sys.exc_info())
            return ''
        return payload_xml

    def get_gcm_payload(self):
        payload = {
            'action': 'com.example.yo.UPDATE_STATUS',
            'header': self.get_push_text()
        }

        if self.sound:
            payload.update({'sound': self.sound})
        else:
            payload.update({'sound': 'silent.mp3'})

        payload.update(self.get_extras())

        if self.category and '.' in self.category:
            try:

                splitted = self.category.split('.')
                left_button_title = splitted[0]
                right_button_title = splitted[1]

                left_button = {
                    'title': left_button_title,
                    'identifier': left_button_title
                }

                right_button = {
                    'title': right_button_title,
                    'identifier': right_button_title
                }

                if self.get_extras('left_deep_link'):
                    left_button['link'] = self.get_extras('left_deep_link')

                if self.get_extras('right_deep_link'):
                    left_button['link'] = self.get_extras('right_deep_link')

                payload.update({'buttons': [
                    left_button,
                    right_button
                ]})
            except:
                current_app.log_exception(sys.exc_info())

        payload = {'data': {'message': payload}}

        return payload

    def to_sns(self, endpoint=None):

        payload = {
            'default': self.get_push_text(),
            'gcm': json.dumps(self.get_gcm_payload()),
            'mpns': self.get_mpns_payload(),
            'wns': json.dumps(self.get_win_payload()),
            'apns': json.dumps(self.get_apns_payload()),
            'apns_sandbox': json.dumps(self.get_apns_payload())
        }

        return json.dumps(payload)

    def payload_too_large(self):
        """The APNS limit for push notifications is 2KB"""
        return len(json.dumps(self.get_apns_payload())) > 2024

    def __str__(self):
        return "%s" % self.payload_type


class YoPayload(Payload):
    """A payload represents an instance of everything needed to
    construct a payload to send to sns or parse
    """

    _base_yo_text = None
    _extras = None
    yo = None

    def __new__(cls, yo, *args, **kwargs):
        """Return the proper Payload class based on the yo"""
        flattened_yo = yo.get_flattened_yo()
        if flattened_yo.is_group_yo:
            return object.__new__(YoGroupPayload, yo, *args, **kwargs)

        return object.__new__(YoPayload, yo, *args, **kwargs)

    def __init__(self, yo, support_dict, log_enrolled=False):
        self.yo = yo
        self._badge = 1
        self._social_text = ''
        # Log an analytic event when retreiving a header?
        self.log_enrolled = log_enrolled

        flattened_yo = yo.get_flattened_yo()

        if not flattened_yo.sender:
            raise APIError('Yo is missing sender')

        self.sound = flattened_yo.sound

        sender_username = flattened_yo.sender.username
        sender_display_name = flattened_yo.sender.display_name
        sender_user_id = flattened_yo.sender.user_id
        sender_user_type = flattened_yo.sender.user_type

        contact = None
        if (self.is_group_payload() and
                    self.payload_type != LEGACY_GROUP_YO):
            contact = get_contact_pair(flattened_yo.group,
                                       flattened_yo.sender)
        else:
            contact = get_contact_pair(flattened_yo.recipient,
                                       flattened_yo.sender)
        if contact:
            sender_display_name = contact.get_name()

        sender_object = {'display_name': sender_display_name,
                         'user_id': sender_user_id,
                         'user_type': sender_user_type,
                         'username': sender_username}

        origin_sender_username = None
        if flattened_yo.origin_sender:
            origin_sender_username = flattened_yo.origin_sender.username

        # Some of these extras are used in other functions and should
        # not be modified without ensuring nothing is using them.
        # TODO: Write tests that verify all of this information is provided.
        self.set_extras(created_at=flattened_yo.created,
                        link=flattened_yo.short_link or flattened_yo.link,
                        location=flattened_yo.location_str,
                        origin_sender=origin_sender_username,
                        origin_yo_id=flattened_yo.origin_yo_id,
                        sender=sender_username,
                        sender_object=sender_object,
                        user_id=sender_user_id,
                        user_type=sender_user_type,
                        yo_id=flattened_yo.yo_id,
                        content=flattened_yo.text)

        if flattened_yo.cover:
            self.set_extras(cover=flattened_yo.cover.make_full_url())

        if flattened_yo.thumbnail_url:
            self.set_extras(thumbnail_url=flattened_yo.thumbnail_url)

        # Find the type first so that everything else can make decisions
        # from it.
        self.set_yo_payload_type(flattened_yo, support_dict)

        self.set_extras(body=self.get_yo_inbox_text(flattened_yo))

        self.formatting_dict = self.build_formatting_dict(flattened_yo,
                                                          support_dict)

        # set_yo_push_text after set_extras so that LEGACY_GROUP_YO can override
        # the sender.
        self.set_base_yo_text(support_dict)
        self.set_yo_push_text(flattened_yo, support_dict)
        self.set_yo_category(flattened_yo, support_dict)
        self._action_text = ACTION_TEXT_DICT.get(self.payload_type, '')

        if yo.response_pair is not None:
            self.should_send_add_response = True

        if self.category == CALL_TEXT_CATEGORY:
            phone = flattened_yo.sender.phone
            self.set_extras(left_deep_link='tel:%s' % phone,
                            right_deep_link='sms:%s' % phone)

        if flattened_yo.left_link:
            self.set_extras(left_deep_link=flattened_yo.left_link)

        if flattened_yo.right_link:
            self.set_extras(right_deep_link=flattened_yo.right_link)

    def to_sns(self, endpoint=None):

        apns = self.get_apns_payload()
        if self.yo.is_push_only:
            apns.pop('yo_id')
            del apns['aps']['badge']

        payload = {
            'default': self.get_push_text(),
            'gcm': json.dumps(self.get_gcm_payload()),
            'mpns': self.get_mpns_payload(),
            'wns': json.dumps(self.get_win_payload()),
            'apns': json.dumps(apns),
            'apns_sandbox': json.dumps(self.get_apns_payload())
        }

        return json.dumps(payload)

    def get_base_yo_text(self):
        return self._base_yo_text

    def get_legacy_push_text(self):
        if self.is_link_payload():
            return LEGACY_LINK_YO_TEXT % self.get_base_yo_text()

        if self.is_location_payload():
            return LEGACY_LOCATION_YO_TEXT % self.get_base_yo_text()

        # Return the default text if there is no type
        return self.get_base_yo_text()

    def is_forwarded_payload(self):
        return self.payload_type in FORWARDED_YO_TYPES

    def is_group_payload(self):
        return isinstance(self, YoGroupPayload)

    def is_link_payload(self):
        return self.payload_type in LINK_YO_TYPES

    def is_location_payload(self):
        return self.payload_type in LOCATION_YO_TYPES

    def build_formatting_dict(self, flattened_yo, support_dict):
        use_display_names = support_dict.get('handles_display_names')
        use_unicode = support_dict.get('handles_unicode', True)
        handles_any_text = support_dict.get('handles_any_text')
        platform = support_dict.get('platform')

        # These should never end up being None.
        group_name = ''
        social_text = ''
        pseudo_user_name = ''
        forwarded_from = ''
        city = ''
        context = ''
        text = ''
        emoji = ''
        token = ''

        recipient = flattened_yo.recipient
        if recipient:
            token = recipient.api_token
        webclient_url = WEBCLIENT_URL % token
        origin_sender = flattened_yo.origin_sender
        sender = flattened_yo.sender
        sender_username = sender.username
        sender_display_name = sender_username
        sender_object = self.get_extras('sender_object')
        if flattened_yo.recipient:
            recipient_display_name = flattened_yo.recipient.first_name or flattened_yo.recipient.username
        else:
            recipient_display_name = None
        group = flattened_yo.group

        if self.is_forwarded_payload():
            emoji = origin_sender.emoji
        else:
            emoji = sender.emoji

        if not emoji:
            emoji = PAYLOAD_TYPE_MAP.get(self.payload_type,
                {}).get('emoji', '')

        if use_display_names:
            if sender.is_service and sender.app_name:
                sender_display_name = '' #sender.app_name
                sender_username = sender.app_name
            else:
                sender_display_name = sender_object.get('display_name') or sender_object.get('display_name')
        if not use_unicode:
            sender_display_name = sender_display_name.encode('ascii', 'ignore')
            sender_display_name = sender_display_name.strip()

        if flattened_yo.location_city:
            city = flattened_yo.location_city.strip()
        if city and not use_unicode:
            city = city.encode('ascii', 'ignore').strip()

        if flattened_yo.text:
            text = flattened_yo.text
            city = flattened_yo.text

        if self.is_group_payload() and group:
            group_name = group.username
            if use_display_names:
                group_name = group.name.strip()
            if not use_unicode:
                group_name = group_name.encode('ascii', 'ignore').strip()
            if not group_name:
                group_name = group.username

            pseudo_contact = get_contact_pair(group, recipient)
        else:
            pseudo_contact = get_contact_pair(sender, recipient)

        if pseudo_contact:
            pseudo_user_name = pseudo_contact.get_name().strip()
            if not use_unicode:
                pseudo_user_name = pseudo_user_name.encode('ascii', 'ignore')

        if self.is_forwarded_payload():
            forwarded_from = self.get_extras('origin_sender')

        if handles_any_text and platform != ANDROID:
            from_text = 'from'
        else:
            from_text = 'From'

        return {'city': city,
                'context': context,
                'text': text,
                'emoji': emoji,
                'forwarded_from': forwarded_from,
                'from': from_text,
                'group_name': group_name,
                'pseudo_user_name': pseudo_user_name,
                'sender_display_name': sender_display_name,
                'sender_username': sender_username,
                'recipient_display_name': recipient_display_name,
                'social_text': social_text,
                'webclient_url': webclient_url}

    def get_yo_inbox_text(self, flattened_yo):
        sender_object = self.get_extras('sender_object')
        sender_display_name = sender_object.get('display_name')
        context = self.get_extras('content')

        if self.payload_type == LOCATION_CITY_YO:
            if flattened_yo.text:
                params = (sender_display_name, flattened_yo.text)
            else:
                params = (sender_display_name, flattened_yo.location_city)
            text = '%s @ %s' % params

        elif self.payload_type == CONTEXT_YO:
            text = '%s: %s' % (sender_display_name, context)

        else:
            text = sender_display_name

        return text

    def get_yo_sms_text(self, flattened_yo, max_length=160):
        '''Assemble all the parts of the sms text.

        push_text + social_text + action_prompt + url + api_token
        social_text is only present in group yos.
        '''
        header = get_header(flattened_yo.recipient, self.payload_type,
                            self.is_group_payload(), self.log_enrolled)

        if header:
            message = build_sms_from_header(header, max_length,
                                            self.formatting_dict)
        else:
            token = flattened_yo.recipient.api_token
            ending = '\n\n%s %s' % (self._action_text, WEBCLIENT_URL % token)
            ending = ending.strip()
            ending = ending.encode('ascii', 'ignore')

            push_text = self.get_push_text().encode('ascii', 'ignore')

            social_text = ''
            if self.is_group_payload():
                social_text = self._social_text.encode('ascii', 'ignore')

            sms = '%s %s' % (push_text, social_text)
            sms = sms.strip()

            message = build_sms_from_parts(sms, ending, max_length)

        return message

    def set_base_yo_text(self, support_dict):
        handles_any_text = support_dict.get('handles_any_text')
        platform = support_dict.get('platform')
        use_display_names = support_dict.get('handles_display_names')
        is_legacy = support_dict.get('is_legacy')

        # The latest version of Android only adds friends to the contact
        # list if it contains "From" (capitalized).
        if handles_any_text and platform != ANDROID:
            text = BASE_YO_TEXT
        else:
            text = LEGACY_BASE_YO_TEXT

        sender_object = self.get_extras('sender_object')
        group_object = self.get_extras('group_object')
        if (is_legacy and self.is_group_payload() and
                    self.payload_type != LEGACY_GROUP_YO):
            sender_name = group_object.get('username')
        elif use_display_names:
            sender_name = sender_object.get('display_name')
        else:
            sender_name = sender_object.get('username')

        self._base_yo_text = text % sender_name

    def set_yo_category(self, flattened_yo, support_dict):
        if not support_dict.get('handles_response_category'):
            self.category = 'Response_Category'
            return

        category = None
        override_service = False
        content = self.get_extras('content')
        if support_dict.get('handles_emoji_categories'):
            if flattened_yo.response_pair:
                category = flattened_yo.response_pair
            else:
                try:
                    if self.payload_type == LOCATION_CITY_YO or self.payload_type == LOCATION_YO:
                        category = LOCATION_YO
                    else:
                        category = get_category(self.payload_type, content=content)
                except (MultipleObjectsReturned, DoesNotExist):
                    pass

            if (not category and self.payload_type == CONTEXT_YO and
                    text_has_emojis(content)):
                category = EMOJI_CATEGORY_MAP.get(content,
                                                  THUMBS_UP_DOWN_CATEGORY)

            # This ensures the '_service' doesn't get appended.
            if category:
                override_service = True

        if not category:
            category = CATEGORY_MAP.get(self.payload_type, self.payload_type)

        if category in [CUSTOM_YO, LEGACY_GROUP_YO, CONTEXT_YO]:
            link = self.get_extras('link')
            location = self.get_extras('location')
            if link:
                category = LINK_YO
            elif location:
                category = LOCATION_YO
            else:
                category = DEFAULT_YO

        self.category = category

        if override_service:
            return

        sender = flattened_yo.sender
        broadcast = flattened_yo.broadcast
        is_service = sender.is_service
        is_person = sender.is_person
        use_service_category = is_service and (broadcast or not is_person)
        if use_service_category:
            self.category = '%s_service' % self.category

    def set_yo_payload_type(self, flattened_yo, support_dict):
        self._type = YoPayload.get_yo_payload_type(flattened_yo,
                                                   support_dict=support_dict)
        return self._type

    @staticmethod
    def get_yo_payload_type(flattened_yo, support_dict=None,
                            use_full_support=False):
        """Calculates the type of Yo based on the attributes.
        flattened_yo: Either a Yo or a FlattenedYo object.
        support_dict: A NotificationEndpoint's support dict.
        use_full_support: Assume all features are supported.
            (Ignores the support_dict)
        """

        if use_full_support:
            is_legacy = False
            handles_any_text = True
        elif support_dict:
            is_legacy = support_dict.get('is_legacy')
            handles_any_text = support_dict.get('handles_any_text')
        else:
            # This is useful if you just want "base" types:
            #    LINK_YO, LOCATION_YO, DEFAULT_YO
            is_legacy = True
            handles_any_text = False

        if isinstance(flattened_yo, Yo):
            flattened_yo = flattened_yo.get_flattened_yo()

        payload_type = DEFAULT_YO

        if flattened_yo.link:
            payload_type = LINK_YO

        if flattened_yo.location:
            payload_type = LOCATION_YO

        # Check if it is a photo first so that custom, group,
        # and legacy can override it.
        if (flattened_yo.link_content_type and
                flattened_yo.link_content_type.startswith('audio')):
            payload_type = AUDIO_YO

        if (flattened_yo.link_content_type and
                flattened_yo.link_content_type.startswith('video')):
            payload_type = VIDEO_YO

        if (flattened_yo.link_content_type and
                flattened_yo.link_content_type.startswith('image')):

            if flattened_yo.link_content_type == 'image/gif':
                payload_type = GIF_YO
            else:
                payload_type = PHOTO_YO

        # Check if this is custom or forwarded yo.
        # NOTE: A endpoint should never be legacy and be able to handle
        # any text. However, lets not take chances.
        if handles_any_text and not is_legacy:
            if flattened_yo.location_city:
                payload_type = LOCATION_CITY_YO

            if flattened_yo.origin_sender:
                if payload_type in [PHOTO_YO, GIF_YO]:
                    payload_type = FORWARDED_PHOTO_YO
                else:
                    payload_type = FORWARDED_YO

            # Only mark it a context yo if its not something else.
            # NOTE: This was done to prevent "named" location yos from
            # being marked as context yos.
            if (payload_type in (DEFAULT_YO, LINK_YO) and
                    flattened_yo.text):
                payload_type = CONTEXT_YO

        if not payload_type and flattened_yo.header and not is_legacy:
            payload_type = CUSTOM_YO

        # This limit is to prevent mass yo's constructed manually
        # from composing group yo's to thousands of users.
        # The same limit is applied on the front end when receiving a
        # legacy group yo.
        recipient_count = flattened_yo.recipient_count

        if flattened_yo.is_group_yo and not flattened_yo.group:
            payload_type = LEGACY_GROUP_YO

        return payload_type

    def set_yo_push_text(self, flattened_yo, support_dict,
                         sender_username=None):

        use_display_names = support_dict.get('handles_display_names')
        if support_dict.get('is_legacy'):
            self._text = self.get_legacy_push_text()
            return

        base_text = self.get_base_yo_text()
        recipient = flattened_yo.recipient
        sender = flattened_yo.sender

        if self.payload_type == CUSTOM_YO or flattened_yo.header is not None:
            template = flattened_yo.header.push
            if not self.formatting_dict.get('sender_display_name'):
                template = u'%(text)s'
            self._text = template % self.formatting_dict
            self._text = self._text.strip()
            self._text = DOUBLE_PERIOD_RE.sub('.', self._text)
            return

        else:
            log_enrolled = self.log_enrolled and not self.is_group_payload()
            header = get_header(recipient, self.payload_type, False,
                                log_enrolled)
            if header:
                template = header.push
                if not self.formatting_dict.get('sender_display_name'):
                    template = u'%(text)s'

                self._text = template % self.formatting_dict
                self._text = self._text.strip()
                self._text = DOUBLE_PERIOD_RE.sub('.', self._text)
                return

        if self.is_forwarded_payload():
            display_name = sender.display_name
            if not use_display_names:
                display_name = sender.username
            origin_sender = flattened_yo.origin_sender
            origin_sender_name = origin_sender.display_name
            origin_sender_emoji = origin_sender.emoji
            if not use_display_names:
                origin_sender_name = origin_sender.username

            payload_params = PAYLOAD_TYPE_MAP.get(self.payload_type)
            forward_params = (origin_sender_name, display_name)
            forward_text = FORWARD_YO_TEXT % forward_params
            emoji = origin_sender_emoji or payload_params.get('emoji', '')
            text_params = (emoji, forward_text)
            push_text = payload_params.get('text') % text_params

        elif self.payload_type == LOCATION_CITY_YO:
            emoji = sender.emoji or ROUND_PIN
            if flattened_yo.text:
                params = (emoji, base_text, flattened_yo.text)
            else:
                params = (emoji, base_text, flattened_yo.location_city)
            push_text = LOCATION_CITY_YO_TEXT % params

        elif self.payload_type == CONTEXT_YO:
            params = (flattened_yo.text, base_text)
            push_text = CONTEXT_YO_TEXT % params

        elif self.payload_type == GIF_YO:
            payload_params = PAYLOAD_TYPE_MAP.get(self.payload_type)
            emoji = sender.emoji or payload_params.get('emoji')
            if flattened_yo.context_id == GIPHY_CTX:
                phrase = get_gif_phrase(flattened_yo.sender).header
                params = (emoji, phrase, base_text)
                push_text = GIPHY_YO_TEXT % params
            else:
                text_params = (emoji, base_text)
                push_text = payload_params.get('text') % text_params

        else:
            payload_params = PAYLOAD_TYPE_MAP.get(self.payload_type)
            emoji = sender.emoji or payload_params.get('emoji')
            text_params = (emoji, base_text)
            push_text = payload_params.get('text') % text_params

        self._text = push_text.strip()


class YoGroupPayload(YoPayload):
    def __init__(self, yo, *args, **kwargs):

        flattened_yo = yo.get_flattened_yo()
        group = flattened_yo.group

        if not flattened_yo.is_group_yo:
            raise ValueError('This payload only expects group yo\'s')

        # Legacy group yos do not have an actual group.
        if group:
            group_object = {'display_name': group.name,
                            'user_id': group.user_id,
                            'user_type': group.user_type,
                            'username': group.username}
            self.set_extras(group_object=group_object)

        super(YoGroupPayload, self).__init__(yo, *args, **kwargs)

        if group:
            # Overwrite the sender with the group's username.
            self.set_extras(sender=flattened_yo.group.username)

    def get_yo_inbox_text(self, flattened_yo):
        text = super(YoGroupPayload, self).get_yo_inbox_text(flattened_yo)

        # Legacy group yos do not have an actual group.
        if self.payload_type == LEGACY_GROUP_YO:
            return text

        name = self.get_extras('group_object').get('display_name')
        return GROUP_YO_TEXT % (text, name)

    def set_yo_push_text(self, flattened_yo, support_dict):
        is_legacy = support_dict.get('is_legacy')
        if is_legacy and self.payload_type != LEGACY_GROUP_YO:
            self._text = self.get_legacy_push_text()
            return

        if self.payload_type != LEGACY_GROUP_YO:
            header = get_header(flattened_yo.recipient, self.payload_type,
                                True, self.log_enrolled)
            if header:
                self._text = header.push % self.formatting_dict
                self._text = self._text.strip()
                self._text = DOUBLE_PERIOD_RE.sub('.', self._text)
                return

            super_self = super(YoGroupPayload, self)
            super_self.set_yo_push_text(flattened_yo, support_dict)

        use_display_names = support_dict.get('handles_display_names')


        # When testing for payload size the yo provided is not a child.
        parent = flattened_yo.parent if flattened_yo.parent else flattened_yo

        base_text = self.get_base_yo_text()

        if self.payload_type == LEGACY_GROUP_YO:
            child_yos = Yo.objects(parent=parent.yo_id)
            sender_username = [child_yo.recipient.username
                               for child_yo in child_yos]
            sender_username = ('+').join(sender_username)

            push_text = '%s %s' % (sender_username, base_text)

            # This is a bit out of place but doing this here prevents having
            # to pull the usernames twice.
            self.set_extras(sender=sender_username)

        elif self.payload_type == CUSTOM_YO:
            # Super takes care of this
            pass
        else:
            push_text = self.get_push_text()
            display_name = flattened_yo.group.name

            if not use_display_names:
                display_name = flattened_yo.group.username

            push_text = GROUP_YO_TEXT % (push_text, display_name)

        self._text = push_text.strip()

    def set_yo_social_text(self, flattened_yo, group_contacts,
                           chars_remaining=160):
        if self.payload_type == CUSTOM_YO:
            return

        num_members = 0
        others = 0
        real_members = []
        social_format_dict = {'num_others': 0, 'other': 'other'}
        for contact in group_contacts:
            member = contact.target
            if (member == flattened_yo.sender or
                        member == flattened_yo.recipient):
                continue

            if contact.contact_name:
                display_name = contact.contact_name
                good_name = True
            else:
                display_name = contact.target.display_name
                good_name = contact.target.has_good_name

            if (len(display_name.encode('ascii', 'ignore')) < 2 or
                    not good_name):
                others += 1
            else:
                if num_members < 2:
                    num_members += 1
                    social_format_dict['member%s' % num_members] = display_name
                else:
                    others += 1

        if others:
            social_format_dict.update({'num_others': others,
                                       'other': 'others'})
        social_dict_key = (num_members, bool(others))
        social_text = SOCIAL_DICT[social_dict_key] % social_format_dict

        # currently this function isn't being called from a context
        # where chars_remaining is known. If that changes, the following
        # may become useful
        #if chars_remaining < len(self._social_text) and name_count == 2:
        #    self._social_text = SOCIAL_TEXT_OTHERS_DICT.get(
        #            1)(real_members, others + 1)

        self.formatting_dict.update({'social_text': social_text})

        self._social_text = social_text
