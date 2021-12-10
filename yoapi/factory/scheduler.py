# -*- coding: utf-8 -*-

"""Factory function for creating scheduler apps."""


from yoapi.factory.base import create_app
from yoapi.core import cors, limiter, s3, sns
from yoapi.services import high_rq, medium_rq, low_rq
from yoapi.services.scheduler import yo_scheduler


def create_scheduler_app(*args, **kwargs):
    """Create a frontend API app"""
    app = create_app(*args, **kwargs)

    # Initialize AWS SNS for mobile push notifications.
    sns.init_app(app)

    # Initialize Redis Queue connections.
    low_rq.init_app(app)
    medium_rq.init_app(app)

    # Initialize Scheduler
    yo_scheduler.init_app(app)

    return app

