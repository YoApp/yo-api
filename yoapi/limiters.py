# -*- coding: utf-8 -*-

"""Limiters for YoAPI"""

from flask import g, request, _app_ctx_stack
from functools import wraps

from .core import limiter


def limit_requests_by_user(limit_str, error_message=None):

    def key_func(func_name):
        def _inner():
            # TODO: refactor to find a better way to handle this
            if g.identity.user:
                return 'rate-limiter:%s:%s' % (func_name,
                                               str(g.identity.user.id))
            else:
                return 'rate-limiter:%s:%s' % (
                    func_name, g.identity.client.client_id)
        return _inner

    def wrapper(fn):
        limiter.limit(limit_str, key_func=key_func(fn.__name__),
                       error_message=error_message)(fn)

        @wraps(fn)
        def inner(*args, **kwargs):
            return fn(*args, **kwargs)
        return inner
    return wrapper


@limiter.request_filter
def whitelisted_usernames():
    """Whitelists accounts from rate limiting

    We ultimately want the whitelist to consist of user id's stored in the
    database, but we can't manage such a list without a web based UI. This
    will have to do for now.
    """
    ctx = _app_ctx_stack.top

    # Split out whitelisted usernames from the current app configuration
    # if such a list is defined.
    if not hasattr(ctx, 'username_whitelist'):
        whitelist = ctx.app.config.get('WHITELISTED_USERNAMES')
        if isinstance(whitelist, basestring):
            ctx.username_whitelist = whitelist.split(',')
        else:
            ctx.username_whitelist = []

    # Check if have a current identity and if so, if we have a user
    # object. This will be matched against the whitelist locally
    # cached on the application context.
    if hasattr(g, 'identity') and g.identity.user:
        username = g.identity.user.username
        if username in ctx.username_whitelist:
            return True
