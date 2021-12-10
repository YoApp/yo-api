from yoapi.accounts import get_user
from yoapi.constants.yos import UNREAD_YOS_FETCH_LIMIT
from yoapi.contacts import upsert_contact
from yoapi.core import cache
from yoapi.models import Yo
from yoapi.models.push_app import PushApp, EnabledPushApp
from yoapi.yos.queries import clear_get_unread_yos_cache


def get_app_by_id(app_id):
    item = PushApp.objects.get(id=app_id)
    return item


@cache.memoize()
def get_push_apps():
    items = PushApp.objects.filter(is_featured=True)
    return items


@cache.memoize()
def get_enabled_push_apps(user=None):
    items = EnabledPushApp.objects(user=user)
    valid_items = []
    for item in items:
        if not item.has_dbrefs():
            valid_items.append(item)
    return valid_items


def enable_push_app(user, app):
    cache.delete_memoized(get_enabled_push_apps, user)

    app_user = get_user(username=app.username)
    upsert_contact(user, app_user, ignore_permission=True)

    entry = EnabledPushApp(user=user,
                           app=app,
                           is_active=True)
    entry.save()


def enable_all_polls_for_user(user):
    apps = get_push_apps()
    for app in apps:
        enable_push_app(user, app)


def create_first_polls_for_user(user):

    children = []

    polls = Yo.objects.filter(recipient_count__gt=20,
                              app_id='co.justyo.yopolls',
                              broadcast=True,
                              is_poll=True).order_by('-created').limit(10)

    for yo in polls:

        child_yo = Yo(parent=yo,
                      recipient=user,
                      status='sent',
                      app_id='co.justyo.yopolls',
                      created=yo.created)
        children.append(child_yo)

    if children:
        Yo.objects.insert(reversed(children), load_bulk=False)

    clear_get_unread_yos_cache(user.user_id, UNREAD_YOS_FETCH_LIMIT, app_id='co.justyo.yopolls')
