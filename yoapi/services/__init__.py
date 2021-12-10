# -*- coding: utf-8 -*-

"""Instantiation of service libraries."""

# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name

from ..extensions.flask_rq import RQ
from ..extensions.pubsub import RedisPubSub

# Redis Queue
high_rq = RQ(name='high')

# Redis Queue
low_rq = RQ(name='low')

# Redis Queue
medium_rq = RQ(name='medium')

# Socket manager
redis_pubsub = RedisPubSub()
