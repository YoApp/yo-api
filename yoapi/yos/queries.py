# -*- coding: utf-8 -*-

"""Yo querying package."""

from itertools import takewhile

from mongoengine import Q, DoesNotExist
from ..core import cache
from ..async import async_job
from ..errors import YoTokenInvalidError
from ..helpers import get_usec_timestamp
from ..models import Yo, YoToken, User
from ..permissions import assert_account_permission
from ..services import low_rq
from yoapi.constants.yos import UNREAD_YOS_FETCH_LIMIT


@cache.memoize()
def _get_broadcasts(user_id):
    """Gets the number of Yo's broadcasted by the user.
    This has an arbitrary limit of 100 set so that we don't
    cache too much"""
    query = Q(sender=user_id,
              broadcast=True) & (Q(link__exists=True) | Q(photo__exists=True))
    yos = Yo.objects(query).order_by('-created') \
                                     .only('id').limit(100)
    return list(yos)


@cache.memoize()
def _get_favorite_yos(user_id):
    """Gets the Yo' favorited by the user.
    This has an arbitrary limit of 100 set so that we don't
    cache too much"""
    yos = Yo.objects(recipient=user_id,
                     is_favorite=True).order_by('-created') \
                                   .only('id').limit(100)
    return list(yos)


@cache.memoize()
def _get_unread_yos(user_id, limit, app_id=None):
    """Gets the Yo' favorited by the user.
    This has an arbitrary limit of 100 set so that we don't
    cache too much"""
    if app_id:
        yos = Yo.objects(recipient=user_id,
                         status__in=['sent', 'received'],
                         app_id=app_id,
                         is_push_only__in=[None, False])\
            .order_by('-created').only('id').limit(limit)
    else:
        yos = Yo.objects(recipient=user_id,
                         status__in=['sent', 'received'],
                         app_id__in=['co.justyo.yoapp', None],
                         is_push_only__in=[None, False])\
            .order_by('-created').only('id').limit(limit)
    return list(yos)


def clear_get_favorite_yos_cache(user_id):
    """Clears the _get_favories cache"""
    cache.delete_memoized(_get_favorite_yos, user_id)


def clear_get_unread_yos_cache(user_id, limit, app_id=None):
    """Clears the get_unread_yos results cache"""
    cache.delete_memoized(_get_unread_yos, user_id, limit, app_id)


def clear_get_yo_cache(yo_id):
    """Clears the get_yo_by_id result cache"""
    cache.delete_memoized(get_yo_by_id, yo_id)


def clear_get_yo_count_cache(user):
    """clears the get_yo_count_cache"""
    cache.delete_memoized(get_yo_count, user)


def clear_get_yo_token_cache(token):
    """Clears the get_yo_token_cache"""
    cache.delete_memoized(get_yo_token, token)


def clear_get_yos_received_cache(user):
    """Clears the get_yos_received results cache"""
    cache.delete_memoized(_get_yos_received, user.user_id)


def clear_get_yos_sent_cache(user):
    """Clears the _get_broadcasts and get_yos_sent results cache"""
    cache.delete_memoized(_get_broadcasts, user.user_id)
    cache.delete_memoized(get_yos_sent, user)

def clear_all_yos_caches(user):
    """Clears all the yo caches for this user"""
    clear_get_yos_sent_cache(user)
    clear_get_yos_received_cache(user)
    clear_get_yo_count_cache(user)
    clear_get_unread_yos_cache(user.user_id, UNREAD_YOS_FETCH_LIMIT)
    clear_get_favorite_yos_cache(user.user_id)


@async_job(rq=low_rq)
def delete_user_yos(user_id):
    """Deletes all the yos this user has sent"""
    yos_sent_query = Yo.objects(sender=user_id)
    yos_sent = yos_sent_query.select_related()
    recipients = set()
    user = None
    for yo in yos_sent:
        if not user and isinstance(yo.sender, User):
            user = yo.sender
        if yo.has_children():
            child_yos_query = Yo.objects(parent=yo.yo_id)
            child_yos = child_yos_query.select_related()
            for child_yo in child_yos:
                if not child_yo.has_dbrefs():
                    recipients.add(child_yo.recipient)
            child_yos_query.delete()
        elif yo.recipient and not yo.has_dbrefs():
            recipients.add(yo.recipient)

    yos_sent_query.delete()
    for recipient in recipients:
        clear_get_unread_yos_cache(recipient.user_id, UNREAD_YOS_FETCH_LIMIT)

    if user:
        clear_all_yos_caches(user)


def get_broadcasts(user, limit=20, ignore_permission=False):
    """Gets the number of Yo's broadcasted by the user"""
    if not ignore_permission:
        assert_account_permission(user, 'No permission to see Yo\'s')
    yos = _get_broadcasts(user.user_id)
    yos = [get_yo_by_id(yo.yo_id) for i, yo in enumerate(yos) if i < limit]
    return yos


def get_child_yos(parent_yo_id):
    """Returns a list of child yos"""
    yos = Yo.objects(parent=parent_yo_id).all().select_related()
    return yos


def get_favorite_yos(user, limit=20, ignore_permission=False):
    """Gets the Yo's favorited by the user"""
    if not ignore_permission:
        assert_account_permission(user, 'No permission to see Yo\'s')
    yos = _get_favorite_yos(user.user_id)
    yos = [get_yo_by_id(yo.yo_id) for i, yo in enumerate(yos) if i < limit]
    return yos


def get_last_broadcast(user, ignore_permission=False):
    """Get the last broadcast sent"""
    yos = get_broadcasts(user, limit=1, ignore_permission=ignore_permission)
    if yos:
        return yos[0]

    return None


def get_unread_yos(user, limit=20, age_limit=None, app_id=None, ignore_permission=False):
    """Gets Yo's not yet read by the user"""
    if not ignore_permission:
        assert_account_permission(user, 'No permission to see Yo\'s')
    yos = _get_unread_yos(user.user_id, limit, app_id)
    fetched = []
    for yo in yos:
        try:
            reloaded = get_yo_by_id(yo.yo_id)
            fetched.append(reloaded)
        except:
            continue
    if age_limit:
        cuttoff_usec = get_usec_timestamp(age_limit)
        cmp_func = lambda yo: yo.created and yo.created - cuttoff_usec >= 0
        fetched = takewhile(cmp_func, fetched)
    yos = [yo for yo in fetched if not yo.has_dbrefs() and not yo.is_poll]
    return yos[:limit]


def get_unread_polls(user, limit=20, age_limit=None, ignore_permission=False):
    """Gets Yo's not yet read by the user"""
    if not ignore_permission:
        assert_account_permission(user, 'No permission to see Yo\'s')
    yos = _get_unread_yos(user.user_id, limit, app_id='co.justyo.yopolls')
    yos = [get_yo_by_id(yo.yo_id) for yo in yos]
    if age_limit:
        cuttoff_usec = get_usec_timestamp(age_limit)
        cmp_func = lambda yo: yo.created and yo.created - cuttoff_usec >= 0
        yos = takewhile(cmp_func, yos)
    yos = [yo for yo in yos if not yo.has_dbrefs()]
    return yos[:limit]


def get_public_dict_for_yo_id(yo_id):
    yo = get_yo_by_id(yo_id)
    dic = {
        'yo_id': yo.yo_id
    }
    if yo.thumbnail_url:
        dic.update({'thumbnail': yo.thumbnail_url})

    if yo.text:
        dic.update({'text': yo.text})

    if yo.left_replies_count:
        dic.update({'left_replies_count': yo.left_replies_count})

    if yo.right_replies_count:
        dic.update({'right_replies_count': yo.right_replies_count})

    if yo.left_reply:
        dic.update({'left_reply': yo.left_reply})

    if yo.right_reply:
        dic.update({'right_reply': yo.right_reply})

    dic.update({'sender_object': {
        'id': yo.sender.user_id,
        'username': yo.sender.username
    }})

    return dic


@cache.memoize()
def get_yo_by_id(yo_id):
    """Returns a Yo model from the database"""
    return Yo.objects(id=yo_id).get()


@cache.memoize()
def get_yo_count(user):
    """Gets the number of Yo's received by the user"""

    user.reload()
    return user.count_in or 0


@cache.memoize()
def get_yo_token(token):
    """Gets a yo token from the database"""
    try:
        return YoToken.objects(auth_token__token=token).get()
    except DoesNotExist:
        raise YoTokenInvalidError


def get_yos_received(user, limit=20, ignore_permission=False):
    """Gets the number of Yo's received by the user"""
    if not ignore_permission:
        assert_account_permission(user, 'No permission to see Yo\'s')

    yos = _get_yos_received(user.user_id)
    return yos[:limit]


@cache.memoize()
def _get_yos_received(user_id):
    yos = Yo.objects(recipient=user_id).order_by('-created').limit(100)
    # Turn the generator into a list so redis can cache it.
    return list(yos)


@cache.memoize()
def get_yos_sent(user):
    """Gets the number of Yo's sent by the user
    This is limited by 20 in order to minimize the ammount of
    data that needs to be stored in redis. At some point this
    should be a paginated list"""

    assert_account_permission(user, 'No permission to see Yo\'s')
    yos = Yo.objects(sender=user).order_by('-created').limit(20)
    # Turn the generator into a list so redis can cache it.
    return list(yos)
