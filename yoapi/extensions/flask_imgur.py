# -*- coding: utf-8 -*-

"""Flask extension pacakge for Imgur"""

from imgurpython import ImgurClient
from imgurpython.helpers.error import (ImgurClientError,
                                       ImgurClientRateLimitError)
from . import FlaskExtension

client_id = '74b67d91988d9e2'
client_secret = '10c15fa5b23931b5bbacad4787fce5f147956051'


class Imgur(FlaskExtension):

    """A helper class for managing a the Imgur API calls"""

    EXTENSION_NAME = 'imgur'

    def __init__(self, app=None):
        super(Imgur, self).__init__(app=app)

    def _create_instance(self, app):
        """Init and store the Imgur object on the stack on
        first use."""
        client = ImgurClient(client_id, client_secret)
        return client

    def get_meme_urls(self, query):
        memes = None
        try:
            memes = self.instance.gallery_search(query, sort='viral')
            memes = [meme.link for meme in memes]
        except (ImgurClientError, ImgurClientRateLimitError) as err:
            """We probably don't actually care about an error here but
            lets get notified to be safe"""
            current_app.log_exception(sys.exc_info())
            if hasattr(err, 'error_message'):
                raise APIError(message=err.error_message)
            else:
                raise APIError(message='Error retreiving imgur memes')

        return memes
