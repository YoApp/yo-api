# -*- coding: utf-8 -*-

"""Factory function for creating API apps."""


from .base import create_app
from ..core import cors, limiter, s3, sns, geocoder, facebook, giphy, imgur, oauth, mixpanel_yostatus, mixpanel_yoapp
from ..services import high_rq, medium_rq, low_rq
from ..services.scheduler import yo_scheduler

# This allows domains specified by Allow-Origin to access all response headers
# of cross-origin XHR requests.
from yoapi.websockets import WebSockets

EXPOSED_HEADERS =['X-Ratelimit-Reset', 'X-Ratelimit-Remaining',
                  'X-Ratelimit-Limit']


def create_api_app(*args, **kwargs):
    """Create a frontend API app"""
    app = create_app(*args, **kwargs)

    # Add CORS headers to all requests.
    cors.init_app(app, expose_headers=EXPOSED_HEADERS)

    # This is the request/route limiter that let's us control how often
    # certain actions can be performed.
    limiter.init_app(app)

    # Initialize AWS S3 for image upload.
    s3.init_app(app)

    # Initialize AWS SNS for mobile push notifications.
    sns.init_app(app)

    # Initialize geocoder.
    geocoder.init_app(app)

    # Initialize facebook.
    facebook.init_app(app)

    # Initialize facebook.
    giphy.init_app(app)

    # Initialize imgur.
    imgur.init_app(app)

    oauth.init_app(app)

    mixpanel_yostatus.init_app(app)
    mixpanel_yoapp.init_app(app)

    # Initialize Redis Queue connections.
    low_rq.init_app(app)
    medium_rq.init_app(app)
    high_rq.init_app(app)

    # Initialize scheduler
    yo_scheduler.init_app(app)

    # Initialize accounts endpoints.
    from ..blueprints import accounts_bp
    app.register_blueprint(accounts_bp)

    # Initialize contacts management endpoints.
    from ..blueprints import contacts_bp
    app.register_blueprint(contacts_bp)

    # Initialize yo endpoints.
    from ..blueprints import yos_bp
    app.register_blueprint(yos_bp)

    # Initialize public api endpoints.
    from ..blueprints import public_api_bp
    app.register_blueprint(public_api_bp)

    # Initialize endpoints endpoints.
    from ..blueprints import notification_endpoints_bp
    app.register_blueprint(notification_endpoints_bp)

    # Initialize admin endpoints.
    from ..blueprints import admin_bp
    app.register_blueprint(admin_bp)

    # Initialize callback endpoints.
    from ..blueprints import callback_bp
    app.register_blueprint(callback_bp)

    # Initialize store endpoints.
    from ..blueprints import store_bp
    app.register_blueprint(store_bp)

    # Initialize yoindex endpoints.
    from ..blueprints import yostore_bp
    app.register_blueprint(yostore_bp)

    # Initialize store category endpoints.
    from ..blueprints import store_category_bp
    app.register_blueprint(store_category_bp)

    # Initialize store category endpoints.
    from ..blueprints import watchpromo_bp
    app.register_blueprint(watchpromo_bp)

    # Initialize group management endpoints.
    from ..blueprints import groups_bp
    app.register_blueprint(groups_bp)

    # Initialize faq management endpoints.
    from ..blueprints import faq_bp
    app.register_blueprint(faq_bp)

    # Initialize ab test management endpoints.
    from ..blueprints import ab_test_bp
    app.register_blueprint(ab_test_bp)

    # Initialize context management endpoints.
    from ..blueprints import contexts_bp
    app.register_blueprint(contexts_bp)

    # Initialize banners endpoints.
    from ..blueprints import banners_bp
    app.register_blueprint(banners_bp)

    # Initialize rest endpoints.
    from yoapi.blueprints.rest import rest_bp
    app.register_blueprint(rest_bp)

    from yoapi.blueprints.polls import polls_bp
    app.register_blueprint(polls_bp)

    from yoapi.blueprints.status import status_bp
    app.register_blueprint(status_bp)

    from yoapi.blueprints.push_apps import push_apps_bp
    app.register_blueprint(push_apps_bp)

    from yoapi.blueprints.subscriptions import subscriptions_bp
    app.register_blueprint(subscriptions_bp)

    WebSockets(app)

    from yoapi.blueprints.websocket import websocket_bp
    app.register_blueprint(websocket_bp)

    from yoapi.blueprints.integrations import integration_bp
    app.register_blueprint(integration_bp)

    from yoapi.blueprints.ifttt import ifttt_bp
    app.register_blueprint(ifttt_bp)

    return app
