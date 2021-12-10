# -*- coding: utf-8 -*-

"""Flask extension pacakge for Giphy"""

import sys
import random

from flask import current_app
from giphypop import GiphyApiException, Giphy as GiphyBase
from requests.exceptions import RequestException
from . import FlaskExtension
from ..errors import APIError


class Giphy(FlaskExtension):

    """A helper class for managing a the giphy API calls"""

    EXTENSION_NAME = 'giphy'

    def __init__(self, app=None, cache=None):
        self.cache = cache
        super(Giphy, self).__init__(app=app)

    def _create_instance(self, app):
        """Init and store the giphy api object on the stack on
        first use."""
        api_key = app.config.get('GIPHY_API_KEY')
        if api_key:
            return GiphyBase(api_key=api_key)
        else:
            return GiphyBase()

    def get_gifs_by_phrase(self, phrase):
        """Get a gif from a phrase"""
        # Use the injected flask cache to cache the results for a day.
        # NOTE: Raising an error prevents the rv from being cached.
        @self.cache.memoize(timeout=60*24)
        def inner(p, make_name=lambda n: 'inner:get_gifs_by_phrase'):
            gifs = self.instance.search_list(phrase=p, limit=30)
            if not gifs:
                raise ValueError('No gifs')
            return gifs

        try:
            gifs = inner(phrase)
        except (RequestException, GiphyApiException) as err:
            """We probably don't actually care about an error here but
            lets get notified to be safe"""
            current_app.log_exception(sys.exc_info())
            if hasattr(err, 'message'):
                raise APIError(message=err.message)
            else:
                raise APIError('Error with giphy')
        except ValueError as e:
            return []

        gifs_urls = []
        for gif in gifs:
            try:
                gifs_urls.append(gif.fixed_width.url)
            except:
                pass

        sample_size = min(len(gifs_urls), 5)
        return random.sample(gifs_urls, sample_size)
