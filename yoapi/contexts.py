# -*- coding: utf-8 -*-

"""Client context module."""

import pytz
import time

from flask import current_app
from datetime import datetime, timedelta
from mongoengine import DoesNotExist

from .ab_test import get_enrolled_experiments
from .core import cache
from .errors import APIError
from .helpers import assert_valid_time
from .models import GifPhrase

from .constants.context import DEFAULT_CONTEXTS, ALL_CONTEXT_IDS, LOCATION_CTX, DEFAULT_CTX, AUDIO_CTX, CAMERA_CTX
import semver
from yoapi.models import Yo
from yoapi.notification_endpoints import get_useragent_profile


def get_contexts(user, request=None):
    """Gets the contexts associated with the supplied user"""

    default_context = current_app.config.get('DEFAULT_CONTEXT')
    if user is None:
        return [LOCATION_CTX, DEFAULT_CTX, CAMERA_CTX, AUDIO_CTX], default_context

    week_ago = datetime.now() - timedelta(days=27)
    week_ago_unix = int(time.mktime(week_ago.timetuple()) * 1e6)

    if Yo.objects.filter(sender=user, created__gt=week_ago_unix, context_id='gif').count() > 0:
        return ALL_CONTEXT_IDS, default_context

    if Yo.objects.filter(sender=user, created__gt=week_ago_unix, context_id='emoji').count() > 0:
        return ALL_CONTEXT_IDS, default_context

    try:
        if request and semver.match(get_useragent_profile(request).get('app_version'), '>=2.5.0'):
            return [LOCATION_CTX, DEFAULT_CTX, CAMERA_CTX, AUDIO_CTX], default_context
    except:
        pass

    experiments = get_enrolled_experiments(user, dimension='context')
    if experiments:
        experiment = experiments[0]
        contexts = DEFAULT_CONTEXTS[:]

        assignments = experiment.get_params()
        exp_context = assignments.get('context')
        exp_context_position = assignments.get('context_position')
        exp_default_context = assignments.get('default_context')

        if exp_context:
            if (exp_context_position is not None and
                exp_context_position < len(DEFAULT_CONTEXTS) and
                exp_context_position >= 0):
                contexts.insert(exp_context_position, exp_context)
            else:
                contexts.append(exp_context)

        if exp_default_context:
            default_context = exp_default_context

        if not experiment.ab_test.debug:
            experiment.log_event('context_ab_test_enrolled',
                                 extras={'dimension': 'context'})
        return contexts, default_context

    if current_app.config.get('ENABLE_ALL_CONTEXTS'):
        return ALL_CONTEXT_IDS, default_context

    return DEFAULT_CONTEXTS, default_context


def update_gif_phrases(payload):
    items = []
    for item in payload:
        item = item.copy()
        items.append(item)

        phrase_id = item.get('id')
        is_new = False

        if phrase_id:
            try:
                phrase = get_gif_phrase_by_id(phrase_id)
            except DoesNotExist:
                item.update({'update_result': 'discarded'})
                continue

            if item.get('delete'):
                phrase.delete()
                item.update({'update_result': 'deleted'})
                continue
        else:
            phrase = GifPhrase()
            is_new = True
            if item.get('delete'):
                item.update({'update_result': 'skipped'})
                continue

        end_time = item.get('end_time')
        start_time = item.get('start_time')
        keyword = item.get('keyword')
        header = item.get('header')
        day = item.get('day')
        date = item.get('date')
        default = item.get('is_default')
        default = bool(default)

        # Parse the iso8601 dates that google spreadsheets provide.
        if date:
            try:
                date = datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%fZ')
                date = date.strftime('%-m/%-d/%y')
            except:
                raise APIError('Invalid date format')
        else:
            date = None

        try:
            start_time = datetime.strptime(start_time, '%H:%M')
            start_time = start_time.strftime('%H:%M')
        except:
            raise APIError('Invalid start_time format')

        try:
            end_time = datetime.strptime(end_time, '%H:%M')
            end_time = end_time.strftime('%H:%M')
        except:
            raise APIError('Invalid end_time format')

        if default and date:
            raise APIError('defaults cannot have a date')
        if default and not day:
            raise APIError('defaults must have a day')

        if default != phrase.is_default:
            phrase.is_default = default
        if start_time != phrase.start_time:
            phrase.start_time = start_time
        if end_time != phrase.end_time:
            phrase.end_time = end_time
        if keyword != phrase.keyword:
            phrase.keyword = keyword
        if header != phrase.header:
            phrase.header = header
        if day != phrase.day:
            if day:
                day = day.lower()
                try:
                    assert_valid_time(day, time_format='%A')
                except ValueError:
                    raise APIError('invalid day of the week')
            else:
                day = None
            phrase.day = day

        if date != phrase.date:
            phrase.date = date

        if is_new:
            item.update({'update_result': 'created'})
        elif phrase._changed_fields:
            item.update({'update_result': 'updated'})
        else:
            item.update({'update_result': 'nochange'})
            continue

        try:
            phrase.save()
        except ValidationError:
            item.update({'update_result': 'discarded'})
            message = 'Tried to update gif phrase with invalid information.'
            current_app.log_error({'message': message, 'item': item})
            continue

        item.update({'id': phrase.phrase_id})

        if phrase.is_default:
            clear_get_default_phrase_cache(phrase.day)

    clear_get_phrases_cache()

    return {'items': items}

def clear_get_phrases_cache(date=None):
    if date:
        # This is a hack to make sure dates are NEVER 0 padded
        # when dealing with them in cache.
        ts = time.strptime(date, '%m/%d/%y')
        date = datetime(*ts[:6]).strftime('%-m/%-d/%y')
        cache.delete_memoized(_get_all_phrases, date)
    else:
        cache.delete_memoized(_get_all_phrases)

def clear_get_default_phrase_cache(day):
    day = str(day).lower()
    cache.delete_memoized(_get_default_phrases, day)


def get_gif_phrase_by_id(phrase_id):
    return GifPhrase.objects(id=phrase_id).get()

@cache.memoize()
def _get_default_phrases(day):
    phrases = GifPhrase.objects(day=day, is_default=True).all()
    return list(phrases)

# Timeout after 2 days.
@cache.memoize(timeout=60*60*24*2)
def _get_all_phrases(date):
    phrases = GifPhrase.objects(date=date).all()
    return list(phrases)

def get_gif_phrase(user):
    if user.timezone:
        zone = pytz.timezone(user.timezone)
        current_datetime = datetime.now(zone)
    else:
        zone = pytz.utc
        current_datetime = datetime.now(zone)

    current_time = current_datetime.strftime('%H:%M')
    current_date = current_datetime.strftime('%-m/%-d/%y')
    current_day = current_datetime.strftime('%A').lower()

    phrases = _get_all_phrases(current_date)
    for phrase in phrases:
        if (current_time >= phrase.start_time and
            current_time <= phrase.end_time):
            return phrase

    phrases = _get_default_phrases(current_day)
    for phrase in phrases:
        if (current_time >= phrase.start_time and
            current_time <= phrase.end_time):
            return phrase

    return GifPhrase(keyword=current_app.config.get('GIPHY_PHRASE'),
                     header=current_app.config.get('GIPHY_TEXT'))
