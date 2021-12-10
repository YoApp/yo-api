# -*- coding: utf-8 -*-
"""Tests all registration related endpoints."""

from uuid import uuid4

from yoapi.models import Device, NotificationEndpoint
from yoapi.notification_endpoints import (get_useragent_profile, IOSBETA, IOS,
                                          ANDROID)
from . import BaseTestCase


class NotificationEndpointTestCase(BaseTestCase):
    @staticmethod
    def get_unique_arn(*args, **kwargs):
        return str(uuid4())

    def test_01_test_register_device_forms(self):
        """Tests device registration"""
        res = self.jsonpost('/rpc/register_device',
                            data={'owner': self._user1.username})
        self.assertEquals(res.status_code, 400, 'Expected form failed.')
        self.assertIn('device_type', res.json.get('payload', {}))

        # Unregister has no required parameters.

    def test_02_test_subscribe_forms(self):
        """Tests device registration"""
        res = self.jsonpost('/rpc/subscribe',
                            data={'owner': self._user1.username})
        self.assertEquals(res.status_code, 400, 'Expected form failed.')
        self.assertIn('device_type', res.json.get('payload', {}))

        # Unsubscribe has no required parameters.


    def test_03_reqister_device(self):
        """Tests device registration"""

        # Test that the Device table is being properly populated
        test_install_id = 'installation_id_test'
        test_token1 = 'test_install_token'
        test_token2 = 'test_install_token2'

        res = self.jsonpost('/rpc/register_device',
                            data={'device_type': ANDROID,
                                  'push_token': test_token1},
                            headers={'X-Yo-Installation-Id': test_install_id})
        self.assertEquals(res.status_code, 200)

        # process registration
        self.worker.work(burst=True)

        device = Device.objects(installation_id=test_install_id).first()
        self.assertIsNotNone(device, 'Expected device with installation id')

        # Test that the Device table is being properly populated if no
        # installation_id is provided
        res = self.jsonpost('/rpc/register_device',
                            data={'device_type': ANDROID,
                                  'push_token': test_token2},
                            headers={'X-Yo-Installation-Id': ''})
        self.assertEquals(res.status_code, 200)

        # process registration
        self.worker.work(burst=True)

        device = Device.objects(token=test_token2).first()
        self.assertIsNotNone(device, 'Expected device with token')

        #self.assertIsNone(device.installation_id,
        #                  'Expected device without installation_id')
        self.assertEquals(device.owner, self._user1,
                          'Expected different owner')

        # Test that the Devices table is still properly overriding owners for
        # devices without installation ids
        res = self.jsonpost('/rpc/register_device',
                            jwt_token=self._user2_jwt,
                            data={'device_type': ANDROID,
                                  'push_token': test_token2},
                            headers={'X-Yo-Installation-Id': ''})
        self.assertEquals(res.status_code, 200)

        # process registration
        self.worker.work(burst=True)

        device = Device.objects(token=test_token2).first()
        self.assertIsNotNone(device, 'Expected device with token')
        #self.assertIsNone(device.installation_id,
        #                  'Expected device without installation_id')
        self.assertEquals(device.owner, self._user2,
                          'Expected different owner')

        res = self.jsonpost('/rpc/logout',
                            headers={'X-Yo-Installation-Id': test_install_id})
        self.assertEquals(res.status_code, 200)

        # process de-registration
        self.worker.work(burst=True)

        device = Device.objects(installation_id=test_install_id).first()
        self.assertIsNone(device.owner, 'Expected device owner to be None')


    def test_04_endpoint_subscribe(self):
        """Test that the NotificationEndpoint table is being properly populated"""

        self.sns_create_endpoint_mock.side_effect = self.get_unique_arn

        test_install_id = 'installation_id_test'
        test_install_id2 = 'installation_id_test2'
        test_token1 = 'test_install_token'
        test_token2 = 'test_install_token2'

        res = self.jsonpost('/rpc/register_device',
                            useragent=self.android_111064067_ua,
                            data={'device_type': ANDROID,
                                  'push_token': test_token1},
                            headers={'X-Yo-Installation-Id': test_install_id})
        self.assertEquals(res.status_code, 200)

        # process registration
        self.worker.work(burst=True)
        self.assertEquals(self.sns_create_endpoint_mock.call_count, 1,
                          'Expected 1 calls to sns create endpoint')

        endpoint = NotificationEndpoint.objects(installation_id=test_install_id).first()
        self.assertIsNotNone(endpoint, 'Expected endpoint with installation id')

        # Test that the NotificationEndpoint table is not populated if no
        # installation_id is provided
        '''res = self.jsonpost('/rpc/register_device',
                            useragent=self.android_111064067_ua,
                            data={'device_type': ANDROID,
                                  'push_token': test_token2},
                            headers={'X-Yo-Installation-Id': ''})
        self.assertEquals(res.status_code, 200)

        # process registration
        self.worker.work(burst=True)

        # Assert create endpoint is not called again
        self.assertEquals(self.sns_create_endpoint_mock.call_count, 1,
                          'Expected 1 calls to sns create endpoint')
        device = NotificationEndpoint.objects(token=test_token2).first()
        self.assertIsNone(device, 'Expected no endpoint with token')
        '''

        # Test that the NotificationEndpoint table is properly overriding owners
        res = self.jsonpost('/rpc/register_device',
                            useragent=self.android_111064067_ua,
                            jwt_token=self._user2_jwt,
                            data={'device_type': ANDROID,
                                  'push_token': test_token1},
                            headers={'X-Yo-Installation-Id': test_install_id})
        self.assertEquals(res.status_code, 200)

        # process registration
        self.worker.work(burst=True)

        device = NotificationEndpoint.objects(installation_id=test_install_id).first()
        # tests that existing endpoints are updated in sns and not recreated
        self.assertEquals(self.sns_set_endpoint_mock.call_count, 1)
        self.assertIsNotNone(device, 'Expected device with install id')
        self.assertEquals(device.owner, self._user2,
                          'Expected different owner')

        res = self.jsonpost('/rpc/logout',
                            useragent=self.android_111064067_ua,
                            jwt_token=self._user2_jwt,
                            headers={'X-Yo-Installation-Id': test_install_id})
        self.assertEquals(res.status_code, 200)

        # process de-registration
        self.worker.work(burst=True)

        device = NotificationEndpoint.objects(installation_id=test_install_id).first()
        self.assertIsNone(device.owner, 'Expected device owner to be None')

        # test that overriding a NotificationEndpoint without a installation id
        # using a token works
        NotificationEndpoint(token=test_token2, platform=ANDROID, arn=str(uuid4())).save()
        res = self.jsonpost('/rpc/register_device',
                            useragent=self.android_111064067_ua,
                            data={'device_type': ANDROID,
                                  'push_token': test_token2},
                            headers={'X-Yo-Installation-Id': test_install_id2})
        self.assertEquals(res.status_code, 200)

        # process registration
        self.worker.work(burst=True)

        device = NotificationEndpoint.objects(token=test_token2,
                                              installation_id=test_install_id2) \
            .first()
        self.assertIsNotNone(device, 'Expected device with install id')
        self.assertEquals(device.owner, self._user1,
                          'Expected different owner')

    def test_05_register_pre_sns_ios_device(self):
        # Register an iOS phone without a < 1.4.6 useragent.
        # These devices will now be allowed to organically migrate to sns
        # This means it the below register_device call should register
        # them to sns

        # Add token to device table to test migration
        Device(token=self._user1_push_token, device_type=IOS,
               owner=self._user1).save()

        data = {'owner': self._user1.username,
                'device_type': IOS,
                'push_token': self._user1_push_token}
        res = self.jsonpost('/rpc/register_device', data=data,
                            useragent=self.ios_141_ua)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Process register device background job.
        self.worker.work(burst=True)

        # Assert that the right external calls have been made.
        # By asserting parse.unsubscribe was called we know this
        # device was properly migrated.
        self.assertEquals(self.parse_unsubscribe_mock.call_count, 1,
                          'Expected 1 calls to parse unsubscribe')
        self.assertEquals(self.parse_subscribe_mock.call_count, 0,
                          'Expected 0 calls to parse subscribe')
        self.assertEquals(self.sns_create_endpoint_mock.call_count, 1,
                          'Expected 1 calls to sns create endpoint')

        # Unregister the device.
        data = {'push_token': self._user1_push_token}
        res = self.jsonpost('/rpc/unregister_device', data=data,
                            useragent=self.ios_141_ua)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Process register device background job.
        self.worker.work(burst=True)

        # Assert parse has not been unsubscribed a second time
        self.assertEquals(self.parse_unsubscribe_mock.call_count, 1,
                          'Expected 1 calls to parse unsubscribe')


    def test_06_register_pre_sns_android_device(self):
        # Register an Android without a useragent.
        data = {'device_type': ANDROID,
                'push_token': self._user2_push_token}
        res = self.jsonpost('/rpc/register_device', data=data)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Process register device background job.
        self.worker.work(burst=True)

        # Assert that the right external calls have been made.
        self.assertEquals(self.parse_subscribe_mock.call_count, 0,
                          'Expected 0 calls to parse subscribe')

        # Unregister the device.
        data = {'push_token': self._user2_push_token}
        res = self.jsonpost('/rpc/unregister_device', data=data)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Process register device background job.
        self.worker.work(burst=True)

        # Assert that the right external calls have been made.
        self.assertEquals(self.parse_unsubscribe_mock.call_count, 1,
                          'Expected 1 calls to parse unsubscribe')


    def test_07_register_sns_ios_device(self):
        # Register an iOS phone with a >= 1.4.6 useragent.
        data = {'owner': self._user1.username,
                'device_type': IOS,
                'push_token': self._user1_push_token}
        res = self.jsonpost('/rpc/register_device', data=data,
                            useragent=self.ios_146_ua)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Process register device background job.
        self.worker.work(burst=True)

        # Assert that the right external calls have been made.
        # By asserting against parse.unsubscribe we make sure
        # this device wasn't migrated twice
        self.assertEquals(self.parse_unsubscribe_mock.call_count, 0,
                          'Expected 0 calls to parse unsubscribe')
        self.assertEquals(self.parse_subscribe_mock.call_count, 0,
                          'Expected 0 calls to parse subscribe')
        self.assertEquals(self.sns_create_endpoint_mock.call_count, 1,
                          'Expected 1 calls to sns create endpoint')

        # Unregister the device.
        data = {'push_token': self._user1_push_token}
        res = self.jsonpost('/rpc/unregister_device', data=data,
                            useragent=self.ios_146_ua)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Process register device background job.
        self.worker.work(burst=True)

        # Assert that the right external calls have been made.
        self.assertEquals(self.parse_unsubscribe_mock.call_count, 0,
                          'Expected 0 calls to parse unsubscribe')

    def test_08_register_sns_android_device(self):
        # Register an Android device with a useragent.
        data = {'owner': self._user1.username,
                'device_type': ANDROID,
                'push_token': self._user1_push_token}
        res = self.jsonpost('/rpc/register_device', data=data,
                            useragent=self.android_111064067_ua)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Process register device background job.
        self.worker.work(burst=True)

        # Assert that the right external calls have been made.
        self.assertEquals(self.parse_subscribe_mock.call_count, 0,
                          'Expected 0 calls to parse subscribe')
        self.assertEquals(self.sns_create_endpoint_mock.call_count, 1,
                          'Expected 1 calls to sns create endpoint')

        # Unregister the device.
        data = {'push_token': self._user1_push_token}
        res = self.jsonpost('/rpc/unregister_device', data=data,
                            useragent=self.android_111064067_ua)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Process register device background job.
        self.worker.work(burst=True)

        # Assert that the right external calls have been made.
        self.assertEquals(self.parse_unsubscribe_mock.call_count, 0,
                          'Expected 0 calls to parse unsubscribe')

    def test_09_test_android_patch_20150125(self):
        """Tests that bad request is raised when bad GCM token is provided"""
        res = self.jsonpost('/rpc/register_device',
                            data={'push_token': 'No REG_ID',
                                  'device_type': 'android'})
        self.assertEquals(res.status_code, 400, 'Expected 400 bad request.')

    def test_10_useragent_parser(self):
        # TODO: Refactor the get_useragent_profile function to accept a
        # useragent instead of a request
        class FakeRequest(object): pass

        ios_request = FakeRequest()
        ios_request.user_agent = self.ios_155_ua
        ua_profile = get_useragent_profile(ios_request)
        self.assertFalse(ua_profile.get('is_beta'))
        self.assertEquals(ua_profile.get('app_version'), '1.5.5')
        self.assertEquals(ua_profile.get('os_version'), '8.1.2')
        self.assertEquals(ua_profile.get('platform'), IOS)

        # TODO: Find a better name than 'big'. This is simply to check
        # devices with a scale other than 2.00.
        ios_big_request = FakeRequest()
        ios_big_request.user_agent = self.ios_big_155_ua
        ua_profile = get_useragent_profile(ios_big_request)
        self.assertFalse(ua_profile.get('is_beta'))
        self.assertEquals(ua_profile.get('app_version'), '1.5.5')
        self.assertEquals(ua_profile.get('os_version'), '8.1.2')
        self.assertEquals(ua_profile.get('platform'), IOS)

        iosbeta_request = FakeRequest()
        iosbeta_request.user_agent = self.iosbeta_156_ua
        ua_profile = get_useragent_profile(iosbeta_request)
        self.assertTrue(ua_profile.get('is_beta'))
        self.assertEquals(ua_profile.get('app_version'), '1.5.6')
        self.assertEquals(ua_profile.get('os_version'), '8.1.2')
        self.assertEquals(ua_profile.get('platform'), IOSBETA)

        android_request = FakeRequest()
        android_request.user_agent = self.android_111064067_ua
        ua_profile = get_useragent_profile(android_request)
        self.assertFalse(ua_profile.get('is_beta'))
        self.assertEquals(ua_profile.get('app_version'), '111064067')
        self.assertEquals(ua_profile.get('os_version'), '5.0.1')
        self.assertEquals(ua_profile.get('platform'), ANDROID)

        androidbeta_request = FakeRequest()
        androidbeta_request.user_agent = self.androidbeta_111064077_ua
        ua_profile = get_useragent_profile(androidbeta_request)
        self.assertTrue(ua_profile.get('is_beta'))
        self.assertEquals(ua_profile.get('app_version'), '111064077')
        self.assertEquals(ua_profile.get('os_version'), '5.0.1')
        self.assertEquals(ua_profile.get('platform'), ANDROID)

