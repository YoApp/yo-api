# -*- coding: utf-8 -*-
"""Code for asyncronous functions"""

from functools import wraps

from .helpers import assert_function_arguments


def async_job(rq=None, custom_queue=None):
    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            return fn(*args, **kwargs)

        @wraps(fn)
        def delay(*args, **kwargs):
            # Before we delay the function we make sure the argument count
            # matches the arguments provided.

            assert_function_arguments(fn, *args, **kwargs)

            # Enqueue the job and relax.
            if custom_queue:
                queue = rq.get_queue(custom_queue)
            else:
                queue = rq.queue

            return queue.enqueue(fn, *args, **kwargs)

        inner.delay = delay
        inner.custom_queue = custom_queue or 'default'
        inner.original_func = fn

        return inner
    return wrapper
