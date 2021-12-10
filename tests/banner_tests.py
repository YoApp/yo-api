# -*- coding: utf-8 -*-
"""Tests the banners endpoints"""
'''
from . import BaseTestCase
from yoapi.banners import get_child_banner, clear_get_banners_cache
from yoapi.models import Banner
from yoapi.constants.context import EMOJI_CTX, GIPHY_CTX, CLIPBOARD_CTX

class BannersTestCase(BaseTestCase):
    def setUp(self):
        super(BannersTestCase, self).setUp()

        Banner.drop_collection()

        # Create some banners.
        self.giphy_banner = Banner(message='Click to do other stuff',
                                   context=GIPHY_CTX, priority=5,
                                   open_count=10, enabled=True).save()
        self.emoji_banner = Banner(message='Click to do stuff',
                                   context=EMOJI_CTX, priority=2,
                                   open_count=5, enabled=True).save()
        self.clipboard_banner = Banner(message='Click to do important stuff',
                                       context=CLIPBOARD_CTX, priority=5,
                                       open_count=0, enabled=True).save()


    def test_01_test_priority(self):
        # test that the clipboard banner takes priority
        # over the emoji banner
        banner_data = {'contexts': [CLIPBOARD_CTX, EMOJI_CTX],
                       'open_count': 10}
        res = self.jsonpost('/rpc/get_banner',
                            data=banner_data)
        self.assertEquals(res.status_code, 200)
        banner = res.json
        self.assertIn('message', banner)
        self.assertIn('context', banner)
        self.assertIn('id', banner)
        self.assertEquals(banner.get('message'), self.clipboard_banner.message)
        self.assertEquals(banner.get('context'), CLIPBOARD_CTX)

        child_banner = get_child_banner(self._user1.user_id,
                                        self.clipboard_banner.banner_id)
        self.assertEquals(banner.get('id'), child_banner.banner_id)
        self.assertEquals(child_banner.parent, self.clipboard_banner)

    def test_02_test_open_count(self):
        banner_data = {'contexts': [GIPHY_CTX, EMOJI_CTX],
                       'open_count': 4}
        res = self.jsonpost('/rpc/get_banner',
                            data=banner_data)
        self.assertEquals(res.status_code, 400)
        self.assertEquals(res.json.get('error'), 'No banner')

        banner_data = {'contexts': [GIPHY_CTX, EMOJI_CTX],
                       'open_count': 8}
        res = self.jsonpost('/rpc/get_banner',
                            data=banner_data)
        self.assertEquals(res.status_code, 200)
        banner = res.json
        self.assertIn('message', banner)
        self.assertIn('context', banner)
        self.assertIn('id', banner)
        child_banner = get_child_banner(self._user1.user_id,
                                        self.emoji_banner.banner_id)
        self.assertEquals(banner.get('id'), child_banner.banner_id)
        self.assertEquals(banner.get('message'), self.emoji_banner.message)
        self.assertEquals(banner.get('context'), EMOJI_CTX)
        self.assertEquals(child_banner.parent, self.emoji_banner)

    def test_03_banner_idempotency(self):
        banner_data = {'contexts': [EMOJI_CTX],
                       'open_count': 5}
        res = self.jsonpost('/rpc/get_banner',
                            data=banner_data)
        self.assertEquals(res.status_code, 200)
        banner = res.json
        self.assertIn('message', banner)
        self.assertIn('context', banner)
        self.assertIn('id', banner)
        banner_id = banner.get('id')

        res = self.jsonpost('/rpc/get_banner',
                            data=banner_data)
        self.assertEquals(res.status_code, 200)
        banner = res.json
        self.assertEquals(banner.get('id'), banner_id)

    def test_04_test_acknowledge(self):
        banner_data = {'contexts': [EMOJI_CTX],
                       'open_count': 10}
        res = self.jsonpost('/rpc/get_banner',
                            data=banner_data)
        self.assertEquals(res.status_code, 200)
        banner = res.json

        self.assertIn('message', banner)
        self.assertIn('context', banner)
        self.assertIn('id', banner)
        banner_id = banner.get('id')

        res = self.jsonpost('/rpc/banner_ack',
                            data={'banner_id': banner_id,
                                  'result': 'opened'})
        self.assertEquals(res.status_code, 200)

        res = self.jsonpost('/rpc/get_banner',
                            data=banner_data)
        self.assertEquals(res.status_code, 400)
        self.assertEquals(res.json.get('error'), 'No banner')

    def test_05_test_gif_content(self):
        # test that the giphy content banner takes priority
        # over the default giphy banner.
        banner_data = {'contexts': [GIPHY_CTX],
                       'open_count': 20}
        res = self.jsonpost('/rpc/get_banner',
                            data=banner_data)
        self.assertEquals(res.status_code, 200)
        banner = res.json
        self.assertIn('message', banner)
        self.assertIn('context', banner)
        self.assertIn('id', banner)
        self.assertEquals(banner.get('message'), self.giphy_banner.message)
        self.assertEquals(banner.get('context'), GIPHY_CTX)

        child_banner = get_child_banner(self._user1.user_id,
                                        self.giphy_banner.banner_id)
        self.assertEquals(banner.get('id'), child_banner.banner_id)
        self.assertEquals(child_banner.parent, self.giphy_banner)

        # create a giphy content banner.
        self.giphy_content_banner = Banner(message='Click for good morning',
                                           context=GIPHY_CTX, priority=6,
                                           content='good morning',
                                           open_count=10, enabled=True).save()
        clear_get_banners_cache([GIPHY_CTX])

        banner_data = {'contexts': [GIPHY_CTX],
                       'open_count': 20}
        res = self.jsonpost('/rpc/get_banner',
                            data=banner_data)
        self.assertEquals(res.status_code, 200)
        banner = res.json
        self.assertIn('message', banner)
        self.assertIn('context', banner)
        self.assertIn('id', banner)
        self.assertEquals(banner.get('message'), self.giphy_content_banner.message)
        self.assertEquals(banner.get('context'), GIPHY_CTX)

        child_banner = get_child_banner(self._user1.user_id,
                                        self.giphy_content_banner.banner_id)
        self.assertEquals(banner.get('id'), child_banner.banner_id)
        self.assertEquals(child_banner.parent, self.giphy_content_banner)
'''