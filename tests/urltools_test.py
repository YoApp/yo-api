# -*- coding: utf-8 -*-

"""Tests the URL helper."""

import requests

from yoapi.urltools import UrlHelper
from . import BaseTestCase


DIRTY_URLS = [
    ['www.justyo.co', 'http://www.justyo.co/'],
    ['www.justyo.co:80/', 'http://www.justyo.co/'],
    ['www.justyo.co?query', 'http://www.justyo.co/?query'],
    ['www.justyo.co?query#fragment', 'http://www.justyo.co/?query#fragment'],
    ['http://www.justyo.co', 'http://www.justyo.co/'],
    ['https://www.justyo.co', 'https://www.justyo.co/'],
    # The urls below are simply to validate they work
    ['tel://+1-867-5309', 'tel://+1-867-5309'],
    ['http://google.com:7070/funfact', 'http://google.com:7070/funfact'],
    ['http://michaelikes.photo/', 'http://michaelikes.photo/']
]

BROKEN_URLS = ['', 'http://', 'http:///', '/yo', '?hello', 'invalid link',
        'http://google .com', 'http://google$.com', 'http://google.com:',
        'http://google.com:80e0',
        'http://toolongbecauseofthelengthoflabelasdefinedperrfc1034foundatwikipedia.com']


class UrlToolsTestCase(BaseTestCase):

    """Tests a bunch of different URLs."""

    def setUp(self):
        super(UrlToolsTestCase, self).setUp()

    def test_parser(self):
        for input_url, expected_url in DIRTY_URLS:
            helper = UrlHelper(input_url)
            self.assertEquals(helper.get_url(), expected_url)

        for input_url in BROKEN_URLS:
            self.assertRaises(ValueError, UrlHelper, input_url)

    def a_test_shortener(self):
        return
        '''
        self.get_request_patcher.stop()
        self.short_url_patcher.stop()
        # After we've stopped the request and url helper mocker we can import
        # them for use.
        with self.app.test_request_context():
            url = 'www.justyo.com?hello=world#fragment'
            helper = UrlHelper(url)
            shortened_url = helper.get_short_url()
            response = requests.get(shortened_url, allow_redirects=False)
            self.assertEquals(response.status_code, 301)
            self.assertEquals(response.headers['location'], helper.get_url())
        '''
