# -*- coding: utf-8 -*-
"""Tests the contexts endpoints"""

from . import BaseTestCase

class Obj(object):
    """Pseudo object"""

    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)

class ContextsTestCase(BaseTestCase):
    """These tests just ensure that these endpoints work since
    they are client facing"""

    def test_01_test_easter_egg(self):
        res = self.jsonpost('/rpc/get_easter_egg')
        self.assertEquals(res.status_code, 200)
        easter_egg = res.json.get('easter_egg')
        self.assertIn('url', easter_egg)
        self.assertEquals(easter_egg.get('url'), 'https://google.com')

    def test_02_test_meme(self):
        res = self.jsonpost('/rpc/meme')
        self.assertEquals(res.status_code, 200)
        self.assertEquals(res.json.get('payload'), {})

        meme = Obj(link='https://imgur.com/link1')
        self.imgur_search_mock.return_value = [meme]

        res = self.jsonpost('/rpc/meme')
        self.assertEquals(res.status_code, 200)
        payload = res.json.get('payload')
        self.assertIn('title', payload)
        self.assertEquals(payload.get('urls')[0], meme.link)

        self.imgur_search_mock.return_value = []

    def test_03_test_giphy(self):
        res = self.jsonpost('/rpc/giphy')
        self.assertEquals(res.status_code, 200)
        self.assertEquals(res.json.get('payload'), {})

        gif = Obj(fixed_width=Obj(
            url='https://imgur.com/link1',
            downsampled=Obj(
                size=100,
                url='https://imgur.com/link1')))
        self.giphy_search_mock.return_value = [gif]

        res = self.jsonpost('/rpc/giphy')
        self.assertEquals(res.status_code, 200)
        payload = res.json.get('payload')
        self.assertIn('title', payload)
        self.assertEquals(payload.get('urls')[0], gif.fixed_width.url)

        self.giphy_search_mock.return_value = []
