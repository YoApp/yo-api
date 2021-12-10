# -*- coding: utf-8 -*-

"""YoStore operations package."""

from flask import current_app
from mongoengine import MultipleObjectsReturned, DoesNotExist

from .accounts import get_user, update_user
from .core import cache
from .errors import APIError
from .helpers import iso8601_to_usec
from .models import YoStore, StoreCategory, WatchPromo

def update_yo_store(store_json):

    discarded = []
    upserted = []
    for i, item in enumerate(store_json):
        name = item.get('name')
        region = item.get('region')
        
        if not (item.get('name') and item.get('region')):
            message = 'Tried to update with incomplete information: %s %s.'
            message = message % (name, region)
            current_app.log_error(message)
            discarded.append(item)
            continue
        store_item = _get_store_item(name, region)
        if not store_item:
            message = 'Tried to update %s %s but multiple objects were returned'
            message = message % (name, region)
            current_app.log_error(message)
            discarded.append(item)
            continue

        is_official = item.get('isofficial')
        is_official = bool(is_official) or False
        in_carousel = bool(item.get('isfeatured')) or False
        needs_location = bool(item.get('needslocation')) or False
        added_at = item.get('datecreated') or None
        try:
            added_at = iso8601_to_usec(added_at)
        except Exception as err:
            message = 'Error converting datecreated for %s %s'
            message = message % (name, region)
            current_app.log_error(message)
        username = item.get('username') or None
        if username:
            yoall_limit = item.get('yoall_limit')
            _update_user_in_store(username, True, yoall_limit)
        screenshots = item.get('screenshots', '').split(',')
        screenshots = [s.strip() for s in screenshots if s.strip()]
        categories = item.get('category', '').split(',')
        categories = [c.strip() for c in categories if c.strip()]

        store_item.rank = i
        store_item.description = item.get('sendsyowhen')
        store_item.category = categories or None
        store_item.username = username
        store_item.url = item.get('url') or None
        store_item.is_official = is_official
        store_item.added_at = added_at
        store_item.carousel_picture = item.get('carouselpicture') or None
        store_item.in_carousel = in_carousel
        store_item.needs_location = needs_location
        store_item.profile_picture = item.get('profilepicture') or None
        store_item.featured_screenshots = screenshots or None
        store_item.name = name
        store_item.region = region
        store_item.save()

        upserted.append(store_item)

    deleted = YoStore.objects(id__nin=[str(u.id) for u in upserted])
    for store_item in deleted:
        if store_item.username:
            _update_user_in_store(store_item.username, None)
    deleted_items = [(str(i.id), i.name, i.region) for i in deleted]
    upserted = [(str(i.id), i.name, i.region) for i in upserted]
    deleted.delete()
    clear_get_store_items_cache()

    return {'discarded': discarded,
            'deleted': deleted_items, 
            'upserted': upserted}


def clear_get_store_items_cache():
    cache.delete_memoized(_get_store_items)
    cache.delete_memoized(_get_store_item)


def get_store_items(regions=None):
    store_items = _get_store_items()
    if regions:
        filtered_store_items = []
        for i in store_items:
            if i.region in regions or i.region == 'World':
                filtered_store_items.append(i)

        return filtered_store_items
    else:
        return store_items


def _update_user_in_store(username, in_store, yoall_limit=None):
    yoall_limits = str(yoall_limit) + ' per hour' if yoall_limit else None
    try:
        user = get_user(username=username)
        update_user(user, in_store=in_store, yoall_limits=yoall_limits)
    except APIError:
        message = 'Unable to update %s in_store to %s'
        message = message % (username, in_store)
        current_app.logger.warning(message)


@cache.memoize()
def _get_store_items():
    return list(YoStore.objects.all().order_by('rank'))


@cache.memoize()
def _get_store_item(name, region):
    try:
        item = YoStore.objects(name=name, region=region).get()
        return item
    except DoesNotExist:
        return YoStore()
    except MultipleObjectsReturned:
        return None


def update_store_categories(category_json):

    discarded = []
    upserted = []
    for i, item in enumerate(category_json):
        category = item.get('category')
        region = item.get('region')
        
        if not (category and region):
            message = 'Tried to update with incomplete information: %s %s.'
            message = message % (category, region)
            current_app.log_error(message)
            discarded.append(item)
            continue
        store_category = _get_store_category(category, region)
        if not store_category:
            message = 'Tried to update %s %s but multiple objects were returned'
            message = message % (category, region)
            current_app.log_error(message)
            discarded.append(item)
            continue

        store_category.category = category
        store_category.rank = i
        store_category.region = region
        store_category.save()

        upserted.append(store_category)

    deleted = StoreCategory.objects(id__nin=[str(u.id) for u in upserted])
    deleted_items = [(str(i.id), i.category, i.region) for i in deleted]
    upserted = [(str(i.id), i.category, i.region) for i in upserted]
    deleted.delete()
    clear_get_store_categories_cache()

    return {'discarded': discarded,
            'deleted': deleted_items, 
            'upserted': upserted}


def clear_get_store_categories_cache():
    cache.delete_memoized(_get_store_categories)
    cache.delete_memoized(_get_store_category)


def get_store_categories(regions=None):
    store_categories = _get_store_categories()
    if regions:
        store_categories = [i for i in store_categories if i.region in regions]

    return store_categories


@cache.memoize()
def _get_store_categories():
    return list(StoreCategory.objects.all().order_by('rank'))


@cache.memoize()
def _get_store_category(category, region):
    try:
        item = StoreCategory.objects(category=category, region=region).get()
        return item
    except DoesNotExist:
        return StoreCategory()
    except MultipleObjectsReturned:
        return None

def update_watch_promo_items(promo_json):

    discarded = []
    upserted = []
    for i, item in enumerate(promo_json):
        username = item.get('username')

        if not username:
            message = 'Tried to update with incomplete information: %s.'
            message = message % username
            current_app.log_error(message)
            discarded.append(item)
            continue
        promo_item = _get_watch_promo_item(username)

        promo_item.rank = i
        promo_item.username = username
        promo_item.description = item.get('description') or None
        promo_item.url = item.get('link') or None
        promo_item.profile_picture = item.get('profilepicture') or None
        promo_item.preview_picture = item.get('previewpicture') or None
        promo_item.save()

        upserted.append(promo_item)

    deleted = WatchPromo.objects(id__nin=[str(u.id) for u in upserted])
    deleted_items = [(str(i.id), i.username) for i in deleted]
    upserted = [(str(i.id), i.username) for i in upserted]
    deleted.delete()
    clear_get_watch_promo_cache()

    return {'discarded': discarded,
            'deleted': deleted_items,
            'upserted': upserted}


def clear_get_watch_promo_cache():
    cache.delete_memoized(_get_watch_promo_item)
    cache.delete_memoized(get_watch_promo_items)


@cache.memoize()
def get_watch_promo_items():
    return list(WatchPromo.objects.all().order_by('rank'))


@cache.memoize()
def _get_watch_promo_item(username):
    try:
        item = WatchPromo.objects(username=username).get()
        return item
    except DoesNotExist:
        return WatchPromo()
