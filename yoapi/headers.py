# -*- coding: utf-8 -*-

"""Yo A-B copy test operations package."""
import sys

import re

from flask import current_app
from mongoengine import MultipleObjectsReturned, DoesNotExist
from mongoengine.errors import ValidationError

from .ab_test import get_enrolled_experiments
from .core import cache
from .errors import APIError
from .models import Header
from .constants.regex import DOUBLE_PERIOD_RE
from .constants.payload import PAYLOAD_TYPE_MAP


def get_header_map(headers):
    header_map = {}
    for header in headers:
        if header in header_map:
            continue

        try:
            header_map[header] = get_header_by_id(header)
        except (DoesNotExist, ValidationError):
            raise APIError('header %s does not exist' % header)

    return header_map


def validate_sms_copy(payload):
    formatting_dict = {'city': 'San Francisco',
                       'text': u'\U0001f3bb',
                       'emoji': '',
                       'forwarded_from': 'FWDUSERNAME',
                       'from': 'from',
                       'group_name': 'Beer Group',
                       'pseudo_user_name': 'My Real Name',
                       'sender_display_name': 'Sender N.',
                       'recipient_display_name': 'Recipient N.',
                       'sender_username': 'SENDERUSERNAME',
                       'social_text': 'with Friend N., Other and 3 others.',
                       'webclient_url': 'https://app.justyo.co/t8F93'}

    examples = []

    for item in payload:
        sms = item.get('sms')
        push = u'%s' % item.get('push')
        ending = item.get('ending')
        yo_type = item.get('yo_type')
        group_yo = item.get('group_yo')
        is_default = item.get('default')

        header = Header()

        header.sms = sms
        header.push = push
        header.ending = ending
        header.yo_type = yo_type
        header.group_yo = group_yo
        header.is_default = is_default

        try:
            header.validate()
        except ValidationError:
            message = 'VALIDATION FAILED!!!'
            examples.append({'sms': message, 'push': message})
            continue

        emoji = PAYLOAD_TYPE_MAP.get(yo_type, {}).get('emoji', '')
        formatting_dict.update({'emoji': emoji})

        message = build_sms_from_header(header, 160, formatting_dict)
        push_text = header.push % formatting_dict
        push_text = push_text.strip()
        push_text = DOUBLE_PERIOD_RE.sub('.', push_text)
        examples.append({'sms': message, 'push': push_text})

    return examples


def update_header_copy(payload):
    items = []
    _defaults = {}
    for item in payload:
        item = item.copy()
        items.append(item)

        header_id = item.get('id')
        sms = item.get('sms')
        push = item.get('push')
        ending = item.get('ending')
        yo_type = item.get('yo_type')
        group_yo = bool(item.get('group_yo'))
        is_default = item.get('default')
        item.update({'update_result': 'no change'})

        if header_id:
            header = get_header_by_id(header_id)
        else:
            header = Header()

        if is_default:
            default = _defaults.get((yo_type, group_yo))
            if not default:
                _defaults[(yo_type, group_yo)] = item
            else:
                is_default = False

        if header.sms != sms:
            header.sms = sms
        if header.push != push:
            header.push = push
        if header.ending != ending:
            header.ending = ending
        if header.yo_type != yo_type:
            header.yo_type = yo_type
        if header.group_yo != group_yo:
            header.group_yo = group_yo
        if header.is_default != is_default:
            header.is_default = is_default or None

        if not header.header_id or header._changed_fields:
            item.update({'update_result': 'upserted'})
            try:
                header.save()
            except ValidationError:
                item.update({'update_result': 'discarded'})
                message = 'Tried to update ab test with invalid information.'
                current_app.log_error({'message': message, 'payload': payload,
                                       'item': item})
                continue

            if header.is_default:
                clear_get_header_cache(header.yo_type, header.group_yo)

        item.update({'id': header.header_id})

    return {'items': items}


def build_sms_from_parts(sms, ending, max_length):
    if len(sms) + len(ending) > max_length:
        sms = sms[:max_length - len(ending) - 3]
        sms = '%s...' % sms

    message = '%s%s' % (sms, ending)
    # fix bad punctuation caused by empty strings during substitution
    message = re.sub('  ',' ', message)
    message = re.sub(' \.','.', message)
    # unescape \\n so that it properly renders as newline
    message = re.sub(r'\\n','\n', message)
    # remove double periods caused by display names ending with .
    message = DOUBLE_PERIOD_RE.sub('.', message)
    return message


def build_sms_from_header(header, max_length, formatting_dict=None):
    """Proxy to unified sms copy formatting"""
    sms = header.sms
    ending = header.ending
    if formatting_dict:
        sms = sms % formatting_dict
        ending = ending % formatting_dict
    return build_sms_from_parts(sms, ending, max_length)


def clear_get_header_cache(yo_type, group_yo):
    cache.delete_memoized(_get_header, yo_type, group_yo)


@cache.memoize()
def get_header_by_id(header_id):
    return Header.objects(id=header_id).get()


def get_header(user, yo_type, group_yo, log_enrolled=False):
    if user:
        experiments = get_enrolled_experiments(user, dimension='notification')
        for experiment in experiments:
            header = experiment.get('header')
            if (header.yo_type == yo_type and header.group_yo == group_yo):
                if log_enrolled and not experiment.ab_test.debug:
                    experiment.log_event('notification_ab_test_enrolled',
                                         extras={'dimension': 'notification'})
                return header

        try:
            return _get_header(yo_type, group_yo)
        except DoesNotExist:
            pass
    else:
        _get_header(yo_type, group_yo)


@cache.memoize()
def _get_header(yo_type, group_yo):
    return Header.objects(yo_type=yo_type, group_yo=group_yo,
                          is_default=True).get()
