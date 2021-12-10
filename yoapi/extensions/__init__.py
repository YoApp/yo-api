# -*- coding: utf-8 -*-

"""Extensions for flask.

We collect all the extensions to increase visibility into extension
development.

How do you know if a third-party library needs to be written as a flask
extension? The common theme it becomes a requirement when said library
requires configuration, such as an API key or an API url. Such
configurations in Flask are app dependent, and require that you follow
the `init_app pattern`.
"""

from flask import current_app


class FlaskExtension(object):

    """A helper class for managing a the twilio API calls"""

    EXTENSION_NAME = None

    def __init__(self, app=None):
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initializes extension for a particular app"""
        app.extensions = getattr(app, 'extensions', {})
        if not self.EXTENSION_NAME in app.extensions:
            app.extensions[self.EXTENSION_NAME] = {}

        if self in app.extensions[self.EXTENSION_NAME]:
            # Raise an exception if extension already initialized as
            # potentially new configuration would not be loaded.
            raise Exception('Extension already initialized')

        app.extensions[self.EXTENSION_NAME][self] = self._create_instance(app)

    def __getattr__(self, name):
        """Forward any uncaught attributes to the instance object"""
        return getattr(self.instance, name)

    def _create_instance(self, app):
        """This needs to be overridden in subclasses"""
        raise NotImplementedError

    @property
    def instance(self):
        """Returns the extension instance for the current app"""
        return current_app.extensions[self.EXTENSION_NAME][self]
