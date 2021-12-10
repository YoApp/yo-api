# -*- coding: utf-8 -*-
"""Tests the callback mechinism."""

from . import BaseTestCase

from yoapi.models import NotificationEndpoint
from yoapi.notification_endpoints import IOS
from yoapi.services import high_rq, low_rq


class CallbacksTestCase(BaseTestCase):

    def test_01_sns_delivery_failure(self):
        # Test that a delivery failure will remove an endpoint
        test_token = 'test_install_token'
        test_endpoint_arn = 'arn:aws:sns:us-east-1:131325091098:endpoint/APNS/iOS/cc9a9af5-59a6-3593-9305-834ccb9ca9f7'

        self.sns_create_endpoint_mock.return_value = test_endpoint_arn

        res = self.jsonpost('/rpc/register_device',
                            useragent=self.ios_146_ua,
                            data={'device_type': IOS,
                                  'push_token': test_token})
        self.assertEquals(res.status_code, 200)

        # process registration
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        self.assertEquals(self.sns_create_endpoint_mock.call_count, 1)

        endpoint = NotificationEndpoint.objects(
            installation_id=self.installation_id).first()
        self.assertIsNotNone(endpoint, 'Expected endpoint with installation id')
        self.assertEquals(endpoint.arn, test_endpoint_arn, 'Expected proper arn')

        # Test auto removal of disabled endpoints
        res = self.jsonpost('/callback/sns',
                            data=self._sns_delivery_failure_json)
        self.assertEquals(res.status_code, 200)
        self.assertEquals(self.sns_delete_endpoint_mock.call_count, 1)

    def test_02_twilio_reverse_sms_account_verify(self):
        # test that a phone number can be verified by sending twilio a
        # a text message with a code generated from gen_sms_hash
        # The To field MUST use the twilio test number so as not to
        # cause issues when testing the twilio error response
        twilio_json = {
            'FromZip': '74105',
            'AccountSid': 'AC0b995abe9156d46f67c6901c84ee226e',
            'SmsSid': 'SM5b6209e024861e08c09efcaa5d237f71',
            'FromCity': 'TULSA',
            'NumMedia': '0',
            'ApiVersion': '2010-04-01',
            'ToCountry': 'US',
            'SmsMessageSid': 'SM5b6209e024861e08c09efcaa5d237f71',
            'FromCountry': 'US',
            'ToCity': '',
            'To': '+15005550006',
            'Body': '',
            'ToZip': '',
            'MessageSid': 'SM5b6209e024861e08c09efcaa5d237f71',
            'FromState': 'OK',
            'ToState': '',
            'SmsStatus': 'received',
            'From': '+2405435792'
        }
        sms_message = """To verify your number tap Send
                         Code: %s
                         * Carrier charges may apply"""

        res = self.jsonpost('/rpc/gen_sms_hash')
        self.assertEquals(res.status_code, 200)
        self.assertIn('hash', res.json, 'Expected a hash to be returned')

        sms_hash = res.json.get('hash')
        twilio_json.update({'Body': sms_message % sms_hash})

        res = self.jsonpost('/callback/sms', data=twilio_json, auth=False)
        self.assertEquals(res.status_code, 200)

        res = self.jsonpost('/rpc/get_me')
        self.assertEquals(res.status_code, 200)
        self.assertTrue(res.json.get('is_verified'),
                        'Expected user to be verified')
