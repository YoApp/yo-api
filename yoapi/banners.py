# -*- coding: utf-8 -*-

"""Banners module"""

from datetime import timedelta
from mongoengine import DoesNotExist

from .contexts import get_gif_phrase
from .core import cache
from .errors import APIError
from .models import Banner
from .permissions import assert_account_permission

from .constants.context import VALID_CONTEXT_IDS, GIPHY_CTX


def acknowledge_banner(banner_id, status):
    try:
        banner = get_banner_by_id(banner_id)
    except DoesNotExist:
        raise APIError('Banner not found')

    assert_account_permission(banner.recipient, 'Unauthorized')

    banner.status = status
    banner.save()
    clear_get_banner_by_id_cache(banner_id)
    clear_get_acknowledged_banners_cache(banner.recipient)


def clear_get_acknowledged_banners_cache(user):
    cache.delete_memoized(get_acknowledged_banners, user.user_id)


def clear_get_banner_by_id_cache(banner_id):
    cache.delete_memoized(get_banner_by_id, banner_id)


def clear_get_banners_cache(contexts):
    for context in contexts:
        cache.delete_memoized(get_banners, context)


@cache.memoize()
def get_banner_by_id(banner_id):
    return Banner.objects(id=banner_id).get()


@cache.memoize()
def get_banners(context):
    if context == 'all':
        banners = Banner.objects(enabled=True)
    else:
        banners = Banner.objects(context=context, enabled=True)
    banners = banners.order_by('priority')
    return list(banners)


@cache.memoize()
def get_acknowledged_banners(user_id):
    banners = Banner.objects(recipient=user_id,
        status__exists=True)
    return list(banners)


@cache.memoize(timeout=int(timedelta(days=1).total_seconds()))
def get_child_banner(user_id, parent_id):
    return Banner.objects(recipient=user_id, parent=parent_id).get()


def get_banner(user, contexts, open_count):

    # Copy the contexts before sorting so we don't change the
    # original input.
    contexts = contexts[:]
    # Always sort the contexts to make sure they hash
    # to the same value.
    contexts.sort()

    parent = None
    banners = []
    gif_phrase = None

    if GIPHY_CTX in contexts:
        gif_phrase = get_gif_phrase(user)

    banners_seen = get_acknowledged_banners(user.user_id)

    banners_seen_ids = []
    for b in banners_seen:
        try:
            banners_seen_ids.append(b.parent.banner_id)
        except Exception as e:
            continue

    banners_seen_ids = set(banners_seen_ids)

    for context in contexts:
        all_context_banners = get_banners(str(context))
        context_banners = []
        for banner in all_context_banners:

            if not banner.enabled:
                continue

            if banner.is_test and not user.is_beta_tester:
                continue

            if banner.open_count > open_count:
                continue

            if banner.banner_id in banners_seen_ids:
                continue

            if banner.context == GIPHY_CTX and banner.content:
                #if gif_phrase and b.content == gif_phrase.keyword:
                banners.append(banner)
            else:
                banners.append(banner)

    if banners:
        parent = max(banners, key=lambda b: b.priority)
        try:
            return get_child_banner(user.user_id, parent.banner_id)
        except DoesNotExist:
            return Banner(recipient=user, parent=parent).save()


def update_banners(payload):
    items = []
    contexts_to_clear = set()
    for item in payload:
        item = item.copy()
        items.append(item)

        item.update({'update_status': 'nochange'})

        banner_id = item.get('id')
        enabled = item.get('enabled')
        context = str(item.get('context').strip())
        content = item.get('content').strip()
        message = item.get('message').strip()
        open_count = item.get('open_count')
        is_test = item.get('is_test')
        link = item.get('link')
        open_count = item.get('open_count')
        priority = item.get('priority')

        if context not in VALID_CONTEXT_IDS:
            raise APIError('%s is not a valid context id' % context)

        is_new = False
        if banner_id:
            try:
                banner = get_banner_by_id(banner_id)
            except DoesNotExist:
                raise APIError('The banner %s does not exist' % banner_id)
        else:
            banner = Banner()
            is_new = True

            if not enabled:
                item.update({'update_status': 'skipped'})
                continue

        if is_new or banner.enabled != enabled:
            banner.enabled = enabled

        if is_new or banner.context != context:
            banner.context = context
            contexts_to_clear.add(context)

        if is_new or banner.content != content:
            banner.content = content or None

        if is_new or banner.message != message:
            banner.message = message

        if is_new or banner.open_count != open_count:
            banner.open_count = open_count

        if is_new or banner.priority != priority:
            banner.priority = priority

        if is_new or banner.is_test != is_test:
            banner.is_test = is_test

        if is_new or banner.link != link:
            banner.link = link

        if is_new:
            item.update({'update_status': 'created'})
        elif banner._changed_fields:
            item.update({'update_status': 'updated'})
            clear_get_banner_by_id_cache(banner_id)

        if is_new or banner._changed_fields:
            banner = banner.save()
            item.update({'id': banner.banner_id})

    contexts_to_clear.add('just_yo')
    clear_get_banners_cache(contexts_to_clear)

    return {'items': items}
