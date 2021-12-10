# -*- coding: utf-8 -*-

"""URL tools module"""

import sys
from collections import OrderedDict
from urllib import urlencode
from urlparse import urlsplit, urlunsplit, parse_qsl

import re
import requests
from flask import current_app
from .errors import APIError


BITLY_ENDPOINT = 'https://api-ssl.bitly.com/v3/shorten'
BLOCKED_HOSTNAMES = ['justyo.co']


class UrlHelper(object):

    """A class to help with common URL related tasks.

    The following steps are automatically performed:

        1) The scheme defaults to http if missing before urlparse, otherwise
           the link will be interpreted as consiting of a path + query without
           a netloc.
        2) Port 80 is removed if specified.
        3) Spaces are truncated in the netloc.
        3) Passed querystring parameters are addded. Order is preserved, even
           when parameters update existing existing ones.
        4) If path is empty then we set it to '/'. This behavior is common,
           seen for example in Google Chrome.

    Args:
        url: A potentially dirty URL.
        params: A dict with extra querystring parameters.
    """

    shortened_link = None
    original_link = None
    parts = None
    bitly = None

    @property
    def netloc(self):
        return self.parts['netloc']

    @property
    def scheme(self):
        return self.parts['scheme']

    @property
    def path(self):
        return self.parts['path']

    @property
    def query(self):
        return self.parts['path']

    @property
    def fragment(self):
        return self.parts['fragment']

    def __init__(self, url, bitly=None, path=None, params=None):
        """Splits the URL and cleans it up.

        We convert the urlsplit return value to an OrderedDict since the
        urlsplit result is a NamedTuple, and hence read-only.
        """

        if not url:
            raise ValueError('Empty URL not allowed.')

        # TODO: This is done to solve an issue #36 with yoall links
        # mystereously adding a new line character at the end
        if url.endswith('\n'):
            url = url[:-1]

        self.original_link = url.strip()

        # Default to http if no scheme present. Valid URI scheme names are
        # defined in http://www.ietf.org/rfc/rfc2396.txt
        if not re.match(r'^[A-Za-z][a-zA-Z0-9+-]+://', url):
            url = 'http://' + url

        self.parts = urlsplit(url)._asdict()

        # Remove default port.
        if self.parts['netloc'].endswith(':80'):
            self.parts['netloc'] = self.parts['netloc'][:-3]

        # Check for spaces in netloc.
        if ' ' in self.parts['netloc']:
            raise ValueError('Invalid hostname')

        # Check if length meets RFC 1034 size rules
        if len(self.parts['netloc']) > 253:
            raise ValueError('Invalid hostname')
        for label in self.parts['netloc'].split('.'):
            if len(label) > 63:
                raise ValueError('Invalid hostname')

        # Check if length meets RFC 4343 size rules
        if not re.match(r'^(\+)?[A-Za-z0-9-.]+(\:([0-9])+)?$', self.parts['netloc']):
            raise ValueError('Invalid hostname')

        # Raise exception if netloc is missing.
        if not self.parts['netloc'] and self.parts['scheme'] in(
                'http', 'https'):
            raise ValueError('Invalid hostname')

        # Add new parameters.
        if params:
            self.add_params(params)

        # Append path
        if path:
            self.append_path(path)

        if bitly:
            self.bitly = bitly
        else:
            self.bitly = current_app.config['BITLY_API_KEY']

        if not self.parts['path'] and self.parts['scheme'].startswith('http'):
            self.parts['path'] = '/'

    def add_params(self, params):
        """Adds querystring parameters.

        The original parameter order is preserved through use of OrderedDict.

        Returns:
            A urlencoded string.
        """
        query = OrderedDict(
            parse_qsl(
                self.parts['query'],
                keep_blank_values=True))
        query.update(params)
        self.parts['query'] = urlencode(query)

    def append_path(self, path):
        """Adds a string to the path."""
        self.parts['path'] += path

    def get_short_url(self):
        """Returns a shortened URL.

        Returns the original link if bit.ly says it's already a shortened
        bit.ly link.

        The primary purpose of shortening URLs is the data they make available
        through an API. The current provider is bit.ly.

        Developer docs can be found at: http://dev.bitly.com/

        Raises:
            APIError when something goes wrong.

        Returns:
            A URL string.
        """
        # If shortened already, return cached value.

        return self.get_url()
        '''
        if self.shortened_link:
            return self.shortened_link
        elif not self.get_url():
            return None

        helper = UrlHelper(BITLY_ENDPOINT)
        helper.add_params({'access_token': self.bitly,
                           'longUrl': self.get_url()})
        try:
            response = requests.get(helper.get_url()).json()
        except Exception as err:
            current_app.log_exception(sys.exc_info())
            raise APIError('Invalid URL', status_code=400)

        if response.get('status_txt') == 'OK':
            return response['data']['url']
        elif response.get('status_txt') == 'ALREADY_A_BITLY_LINK':
            return UrlHelper(self.original_link).get_url()
        elif response.get('status_txt') == 'INVALID_ARG_ACCESS_TOKEN':
            if self.bitly == current_app.config['BITLY_API_KEY']:
                current_app.log_error('Help! Our bitly token is broken!',
                                      **response)
                return UrlHelper(self.original_link).get_url()

            raise APIError('Invalid Bitly Token.', status_code=400)
        elif response.get('status_txt') == 'RATE_LIMIT_EXCEEDED':
            if self.bitly == current_app.config['BITLY_API_KEY']:
                current_app.log_error('Bitly rate limit was exceeded!',
                                      **response)
                return UrlHelper(self.original_link).get_url()

            raise APIError('Bitly Rate Limit Exceeded.', status_code=400)
        elif response.get('status_txt') == 'TEMPORARILY_UNAVAILABLE':
            current_app.log_error('Bitly is down!', **response)
            return UrlHelper(self.original_link).get_url()
        else:
            current_app.log_error(response)
            raise APIError('Invalid URL', status_code=400)
    '''

    def get_url(self):
        # Returning an empty string is frowned upon by parse.
        url = urlunsplit(self.parts.values())
        return url if url else None

    def raise_for_hostname(self):
        """If the hostname is blocked raise an error"""

        hostname = self.parts['netloc']
        if hostname in BLOCKED_HOSTNAMES:
            raise APIError('Sending links with this host is not allowed',
                           status_code=401)
