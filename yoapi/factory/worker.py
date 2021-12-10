# -*- coding: utf-8 -*-

"""Factory function for creating Worker apps."""


from .base import create_app
from ..core import sns, geocoder, s3
from ..services import high_rq, medium_rq, low_rq


def create_worker_app(*args, **kwargs):
    """Create a worker app"""
    app = create_app(*args, is_worker=True, **kwargs)

    # Initialize Redis Queue connections.
    low_rq.init_app(app)
    medium_rq.init_app(app)
    high_rq.init_app(app)

    # Initialize AWS S3 for image upload.
    s3.init_app(app)

    # Initialize AWS SNS for mobile push notifications.
    sns.init_app(app)

    # Initialize geocoder.
    geocoder.init_app(app)

    return app
