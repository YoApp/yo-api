
# -*- coding: utf-8 -*-

"""Flask extension pacakge for Mixpanel"""

from . import FlaskExtension
from mixpanel import Mixpanel


class MixpanelExtension(FlaskExtension):

    EXTENSION_NAME = 'mixpanel'
    api_key = None
    disabled = False

    def __init__(self, app=None, api_key=None):
        self.api_key = api_key
        super(MixpanelExtension, self).__init__(app=app)

    def _create_instance(self, app):
        api_key = self.api_key or app.config.get('MIXPANEL_API_KEY')
        return Mixpanel(api_key)

    def track(self, user_id, event, properties=None):
        if not self.disabled:
            self.instance.track(user_id, event, properties)


