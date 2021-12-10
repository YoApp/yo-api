# -*- coding: utf-8 -*-
"""Tests all authentication related endpoints."""

import mock
import pytz
import time

from datetime import datetime
from flask import json
from twilio import TwilioRestException
from yoapi import jwt

from twilio.rest import Messages

from yoapi.accounts import update_user, get_user
from yoapi.core import redis
from yoapi.models import User
from yoapi.services import low_rq, high_rq

from yoapi.extensions.flask_sendgrid import SendGridClient
from yoapi.services.scheduler import yo_scheduler

from . import BaseTestCase

JOB_TYPE = 'yo'

class AccountTestCase(BaseTestCase):

    def _login(self, account):
        """Shared method for obtaining a new JWT"""
        login_res = self.jsonpost('/rpc/login', auth=False,
                                  data=self._ephemeral_account)
        if login_res.status_code != 200:
            raise Exception('Login failed')
        login_data = json.loads(login_res.data)
        jwt_token = login_data.get('tok')
        user = jwt.get_decoded_token('Bearer ' + jwt_token)
        return jwt_token, user

    def test_01_account(self):
        """Tests creating a new account"""

        self.get_request_mock.return_value.json.return_value = {
                "ip":"74.125.193.106",
				"country_code":"US",
				"country_name":"United States",
				"region_code":"CA",
				"region_name":"California",
				"city":"Mountain View",
				"zipcode":"94043",
				"latitude":37.4192,
				"longitude":-122.0574,
				"metro_code":"807",
				"area_code":"650"}

        # Testing an invalid username.
        res = self.jsonpost('/rpc/sign_up', auth=False, data={'username': '9'})
        self.assertEquals(res.status_code, 400,
                          'Expected bad request response.')

        # Testing a second invalid username.
        res = self.jsonpost('/rpc/sign_up', auth=False,
                            data={'username': 'lowercase'})
        self.assertEquals(
            res.status_code, 400, 'Expected bad request response.')

        # Testing an valid pseudo-username.
        res = self.jsonpost('/rpc/sign_up', auth=False, data={'username': '15102839483'})
        self.assertEquals(res.status_code, 400,
                          'Expected bad request response.')

        # Testing with valid data.
        res = self.jsonpost('/rpc/sign_up', auth=False,
                            data=self._ephemeral_account)
        self.assertEquals(res.status_code, 201, 'Expected 201 Created.')

        self.get_request_mock.return_value.json.return_value = None

        # Update the account created.
        jwt_token, _ = self._login(self._ephemeral_account)

        data = {'name': 'Sucha Poser',
                'email': 'fakemail2@fakedomain.com',
                'photo': self._photo.replace(' ', '').replace('\n', '')}

        res = self.jsonpost('/rpc/set_me', auth=False,
                            data=data, jwt_token=jwt_token)
        self.assertEquals(res.status_code, 200)

        # Create a new API account
        res = self.jsonpost('/rpc/new_api_account', data=self._ephemeral_api)
        self.assertEquals(res.status_code, 201, 'Expected 201 Created.')

        # attempt to create a new API account, username already exist - expect
        # 422 UNPROCESSABLE ENTITY
        res = self.jsonpost('/rpc/new_api_account', data=self._user1)
        self.assertEquals(res.status_code, 422, '422 UNPROCESSABLE ENTITY')

        # attempt to create a new API account with a pseudo-username
        res = self.jsonpost('/rpc/new_api_account', data=self._ephemeral_invalid_api)
        self.assertEquals(res.status_code, 400, 'expected 400 bad request')

        # attempt to create a new API account with an invalid username
        self._ephemeral_invalid_api.update({'username':'3'})
        res = self.jsonpost('/rpc/new_api_account', data=self._ephemeral_invalid_api)
        self.assertEquals(res.status_code, 400, 'expected 400 bad request')

        # attempt to create a new API account with another invalid username
        self._ephemeral_invalid_api.update({'username':'badname'})
        res = self.jsonpost('/rpc/new_api_account', data=self._ephemeral_invalid_api)
        self.assertEquals(res.status_code, 400, 'expected 400 bad request')

        # Tests that api user is a child user
        res = self.jsonpost('/rpc/list_my_api_accounts',
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')
        self.assertEquals(len(res.json.get('accounts', [])), 1,
                          'Expected 1 child accounts.')

        # Attempt to list api account while not logged in
        res = self.jsonpost('/rpc/list_my_api_accounts', auth=False,
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

        # Attempt to delete the account without auth - expecting 401
        # UNAUTHORIZED.
        delete_res = self.jsonpost(
            '/rpc/delete_api_account', auth=False,
            data={'username': self._ephemeral_api['username']})
        self.assertEquals(delete_res.status_code, 401)

        # Attempt to delete the account.
        delete_res = self.jsonpost(
            '/rpc/delete_api_account',
            data={'username': self._ephemeral_api['username']})
        self.assertEquals(delete_res.status_code, 200)

        # Attempt to signup a deleted account.
        new_res = self.jsonpost(
            '/rpc/new_api_account',
            data={'username': self._ephemeral_api['username']})
        self.assertEquals(new_res.status_code, 201)

        # Attempt to delete your own account (the one you've using and not the
        # api) - expecting 401 UNAUTHORIZED
        #delete_res = self.jsonpost(
        #    '/rpc/delete_api_account',
        #    data={'username': self._user1['username']})
        #self.assertEquals(delete_res.status_code, 401)

        # Attempting to delete someone else's account - expecting 401
        # UNAUTHORIZED
        delete_res = self.jsonpost(
            '/rpc/delete_api_account',
            data={'username': self._user2['username']})
        self.assertEquals(delete_res.status_code, 401)

        # Attempting to delete non existent account - expecting 401
        # UNAUTHORIZED
        delete_res = self.jsonpost(
            '/rpc/delete_api_account',
            data={'username': 'NONEXISTENTUSERNAME'})
        self.assertEquals(delete_res.status_code, 404)

        # We can pass the entire account dict to the API since it only looks for
        #username and password.
        data = {'username': self._user1.username,
                'password': 'calcifer'}
        res = self.jsonpost('/rpc/login', auth=False, data=data)
        self.assertEqual(res.status_code, 200, 'Login failed.')

        jwt_token = res.json.get('tok')
        self.assertIsNotNone(jwt_token)

        user = jwt.get_decoded_token('Bearer ' + jwt_token)

        self.assertEquals(user.user_id, str(self._user1.id),
                          'Username mismatch')

        # Attempting to logout
        logout_res = self.jsonpost('/rpc/logout')
        self.assertEquals(logout_res.status_code, 200, 'Expected 200 OK')

        # Attempting to logout while with no auth - expecting 401
        logout_res = self.jsonpost('/rpc/logout', auth=False)
        self.assertEqual(logout_res.status_code, 401, '401 UNAUTHORIZED')

        # Tests that a user exists
        res = self.jsonpost('/rpc/user_exists',
                            data={'username': self._user1.username})
        exists = res.json.get('exists')
        self.assertTrue(exists, 'User should exist.')

        # Tests that a user does not exist
        res = self.jsonpost('/rpc/user_exists',
                            data={'username': 'TESTUSERPYTHONX'})
        exists = res.json.get('exists')
        self.assertFalse(exists, 'User should not exist.')

        # Attempt to set yourself verified
        self._user1.verified = False
        self._user1.save()
        res = self.jsonpost('/rpc/set_me',
                            data={'verified': True})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')
        self.assertFalse(res.json.get('verified'))

        res = self.jsonpost('/rpc/set_api_account',
                            data={'verified': True,
                                  'username': self._user1.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')
        self.assertFalse(res.json.get('verified'))


    def test_03_get_profile(self):
        # Tests the content of get_profile endpoint

        # Testing non-existent user - expecting 404 NOT FOUND
        res = self.jsonpost('/rpc/get_profile',
                            data={'username': 'TESTUSERNOTTHERIGHTUSER'})
        self.assertEquals(res.status_code, 404, '404 NOT FOUND')

        # Testing valid user - expecting 200
        res = self.jsonpost('/rpc/get_profile',
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 200, '200 OK')

    def test_04_get_me(self):
        """ Tests the content of get_me endpoint """

        # Testing none-loggedin user - expecting 401 UNAUTHORIZED
        res = self.jsonpost('/rpc/get_me', auth=False,
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 401,
                          'UNAUTHORIZED.')

        # Testing valid user - expecting 200 OK
        res = self.jsonpost('/rpc/get_me',
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

    def test_05_is_verified(self):
        """ Tests the content of is_verified endpoint """
        # Testing none-verified user - expected 200 OK
        res = self.jsonpost('/rpc/is_verified',
                            data={'username': self._user1.username})
        verified = res.json.get('verified')
        self.assertFalse(verified, 'User should not be verified.')
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Testing logged out user - expected 401 UNAUTHORIZED
        res = self.jsonpost('/rpc/is_verified', auth=False,
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED.')

        # Testing verified user - expected 200 OK
        # Placeholder, currently there's no api to create verified users

    def test_06_confirm_password_reset(self):
        """ Tests the content of confirm_password_reset endpoint """
        # Testing non existent username - expecting 404 ERROR
        res = self.jsonpost(
            '/rpc/confirm_password_reset',
            data={
                'token': 'wrongtoken',
                'username': 'NONEEXSITENTUSERNAME',
                'password': 'newpassword'})
        self.assertEquals(res.status_code, 404, 'Expected 404 ERROR.')

        # Testing existent username - but bad verification code, expecting 400
        # error
        res = self.jsonpost(
            '/rpc/confirm_password_reset',
            data={
                'code': 'wrongtoken',
                'username': self._user1.username,
                'password': 'newpassword'})
        self.assertEquals(res.status_code, 400, 'Expected 400 BAD REQUEST.')

        # Testing existent username with valid code
        # ** how do i pass valid code during the account initiation ? **
        # res = self.jsonpost(
        #    '/rpc/confirm_password_reset',
        #    data={
        #        'code': '0110',
        #        'username': self._user1.username,
        #        'password': 'newpassword'})
        #import pdb; pdb.set_trace()
        #self.assertEquals(res.status_code, 200, 'Expected 200 OK.')

    def test_07_recover(self):
        """ Tests the content of recover endpoint """

        # Become the user so we can set the verified token.
        self.become(self._user1)

        # Update user object to set phone as verified.
        update_user(self._user1, verified=True)
        res = self.jsonpost('/rpc/recover',
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK.')
        #self.assertTrue(self.twilio_send_mock.called)

        # Testing non-existent user with no phone or email - expecting 404
        res = self.jsonpost('/rpc/recover',
                            data={'username': 'RANDOMUSERNOEMAILORPHONE'})
        self.assertEquals(res.status_code, 404, 'Expected 404 Not Found.')

        # Testing recoverable user - expected 200 OK
        # Placeholder, currently there's no api to create email/phone with user

    def test_08_reset_password_via_email_address(self):
        """ Tests the content of reset_password_via_email_address endpoint """
        # Testing non-existent email
        res = self.jsonpost(
            '/rpc/reset_password_via_email_address',
            data={
                'username': self._user1.username,
                'email_address': self._user1.email})
        # Make sure the Sendgrid library send function has been called.
        self.assertTrue(self.send_grid_send_mock.called)

        self.assertEquals(res.status_code, 200, 'Expected 200 OK.')

    def test_09_reset_password_via_phone_number(self):
        """ Tests the content of reset_password_via_phone_number endpoint """

        # Become the user so we can set the verified token.
        self.become(self._user1)

        # Update user object to set phone as verified.
        update_user(self._user1, verified=True)

        res = self.jsonpost(
            '/rpc/reset_password_via_phone_number',
            data={
                'username': self._user1.username,
                'phone_number': '+14153351320'})

        # Make sure the Twilio library create function has been called.
        #self.assertTrue(self.twilio_send_mock.called)
        self.assertEquals(res.status_code, 200, 'Expected 200 OK.')

    def test_10_send_verification_code(self):
        """ Tests the content of send_verification_code endpoint """

        data={'country_code': '1',
              'phone_number': '4158671464',
              'username': self._user1.username}
       	res = self.jsonpost('/rpc/send_verification_code', data=data)

        # Make sure the Twilio library create function has been called.
        #self.assertTrue(self.twilio_send_mock.called)
        self.assertEquals(res.status_code, 200, 'Expected 200 OK.')

    def test_11_unset_my_phone_number(self):
        """ Tests the content of unset_my_phone_number endpoint """
        # None logged in user, expect to get 401 UNAUTHORIZED
        res = self.jsonpost(
            '/rpc/unset_my_phone_number',
            auth=False,
            data={
                'username': 'TEST'})
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

        # Valid user, expecting to get 200 OK
        # ** i think there's a respond or status code missing missing - i would expect SUCCESS/FAILED,
        # it'll get 200 OK no matter what username i'll put it in - see
        # commented code **
        res = self.jsonpost(
            '/rpc/unset_my_phone_number',
            data={
                'username': self._user1['username']})
       #res = self.jsonpost('/rpc/unset_my_phone_number',data={'username': NONEXISTENTUSERNAME})
        self.assertEquals(res.status_code, 200, '200 OK')

    def test_12_verify_code(self):
        """ Tests the content of verify_code endpoint """

        # No code set to user - expecting 400 BAD REQUEST
        res = self.jsonpost('/rpc/verify_code', data={'code': '3993'})
        self.assertEquals(res.status_code, 400, '400 BAD REQUEST')

        # Non logged in user - expect 401 UNAUTHORIZED
        res = self.jsonpost(
            '/rpc/verify_code',
            auth=False,
            data={
                'code': '3993'})
        self.assertEquals(res.status_code, 401, '401 BAD REQUEST')

        # Missing SUCCESSFUL request, need to find an easy way to put in
        # verification code in db

    def test_13_delete_account(self):
        """ Tests the content of delete_account endpoint """
        # placeholder for new method

    def test_14_gen_email_hash(self):
        """ Tests the content of gen_email_hash endpoint """
        # placeholder for new method

    def test_15_gen_sms_hash(self):
        """ Tests the content of gen_sms_hash endpoint """
        # placeholder for new method

    def test_16_find_users(self):
        """ Tests the content of find_users endpoint """
        # Attempt to use find_users without admin permission - expecting 401
        # UNAUTHORIZED
        res = self.jsonpost(
            '/rpc/find_users',
            data={
                'username': 'TESTUSERPYTHON'})
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

    def test_17_create_account_limiters(self):
        """Tests the limiters for creating accounts"""
        for i in range(0, 20):
            username = 'LIMITERTEST%s' % i
            res = self.jsonpost(
                '/rpc/new_api_account',
                jwt_token=self._user2_jwt,
                data={'username':username})
            self.assertEquals(res.status_code, 201,
                'Try %s Expected 201 Created. Got %s' %
                (username, res.status_code))

        # the third should fail
        res = self.jsonpost(
            '/rpc/new_api_account',
            jwt_token=self._user2_jwt,
            data={'username':'TESTUSERPYTHON3'})
        self.assertEquals(res.status_code, 429,
            'Expected 429 Too many requests. Got %s' % res.status_code)


        for i in range(0, 20):
            username = 'ACCOUNTSLIMITERTEST%s' % i
            res = self.jsonpost(
                '/accounts/',
                jwt_token=self._user2_jwt,
                data={'username':username})
            self.assertEquals(res.status_code, 201,
                'Try %s Expected 201 Created. Got %s' %
                (username, res.status_code))

        # the third should fail
        res = self.jsonpost(
            '/accounts/',
            jwt_token=self._user2_jwt,
            data={'username':'ACCOUNTSLIMITERTEST3'})
        self.assertEquals(res.status_code, 429,
            'Expected 429 Too many requests. Got %s' % res.status_code)

    def test_18_login_limiters(self):
        """Tests the limiters for logging in"""

        # Test that logins are rate limited
        # This limiter is unique for the client hash so use a
        # custom useragent
        for i in range(0, 20):
            res = self.jsonpost(
                '/rpc/login',
                useragent='login_test',
                auth=False,
                data={'username':self._user1.username,
                      'password':self._user1.password})
            self.assertEquals(res.status_code, 401,
                'Expected 401 UNAUTHORIZED.')

        # The 21st should fail
        res = self.jsonpost(
            '/rpc/login',
            auth=False,
            useragent='login_test',
            data={'username':self._user1.username,
                  'password':self._user1.password})
        self.assertEquals(res.status_code, 429,
        'Expected 429 Too many requests.')


    def test_19_reclaim_user(self):
        """Tests that deleting a user properly removes them from
           the database as well as parse"""

        res = self.jsonpost('/rpc/sign_up',
                            data={'username': 'USERTODELETE',
                                  'password': '12345'})
        self.assertEquals(res.status_code, 201, 'Expected 201 created')

        admin_user = User(username='ADMINACCOUNT', is_admin=True)
        admin_user.set_password('123456')
        admin_user.save()
        _admin_user_token = jwt.generate_token(admin_user)

        res = self.jsonpost('/rpc/reclaim',
                            jwt_token=_admin_user_token,
                            data={'username': 'USERTODELETE'})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # Run the workers to perform the background deletes.
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        high_rq.create_worker(app=self.worker_app).work(burst=True)

        self.assertEquals(self.parse_query_get_mock.call_count, 1)
        self.assertEquals(self.parse_delete_mock.call_count, 1)


    def test_20_send_verification_code(self):
        """Tests that sending a verification code to an unreachable number
        that passes validation response with a 200

        NOTE: The phone number we are sending to below is a twilio test
        number. Please do not change it."""

        # Stop the patcher to make the test call
        self.twilio_send_patcher.stop()
        res = self.jsonpost('/rpc/send_verification_code',
                            data={'country_code': '+1',
                                  'phone_number': '+15005550002'})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')
        #self.assertIn('error', res.json, 'Expected error message in response')

        # Resume the patcher
        self.twilio_send_patcher.start()

    def test_21_get_profile(self):
        # Tests that retrieving a user profile gets the correct
        # properties depending on the level of permissions.
        # This will also ensure that things that have a value of None
        # don't get returned.

        admin_user = User(username='ADMINACCOUNT', is_admin=True)
        admin_user.set_password('123456')
        admin_user.save()
        _admin_user_token = jwt.generate_token(admin_user)

        res = self.jsonpost('/admin/get_profile',
                            jwt_token=_admin_user_token,
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # check for admin only properties
        self.assertNotIn('last_yo_time', res.json,
                      'Expected admin get_profile to return last_yo_time')
        self.assertNotIn('updated', res.json,
                      'Expected admin get_profile not to return updated')
        self.assertIn('created', res.json,
                      'Expected admin get_profile to return created')
        self.assertNotIn('parse_id', res.json,
                      'Expected admin get_profile to return parse_id')
        self.assertIn('is_yo_team', res.json,
                      'Expected admin get_profile to return is_yo_team')

        # check for account owner and admin
        self.assertIn('email', res.json,
                      'Expected account get_profile to return email')
        self.assertNotIn('bitly', res.json,
                      'Expected account get_profile not to return bitly')
        self.assertIn('api_token', res.json,
                      'Expected account get_profile to return api_token')
        self.assertIn('phone', res.json,
                      'Expected account get_profile to return phone')
        self.assertIn('is_verified', res.json,
                      'Expected account get_profile to return is_verified')

        res = self.jsonpost('/rpc/get_profile',
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # check for admin only properties
        self.assertNotIn('last_yo_time', res.json,
                      'Expected account get_profile not to return last_yo_time')
        self.assertNotIn('updated', res.json,
                      'Expected account get_profile not to return updated')
        self.assertNotIn('created', res.json,
                      'Expected account get_profile not to return created')
        self.assertNotIn('topic_arn', res.json,
                      'Expected account get_profile not to return topic_arn')
        self.assertNotIn('parse_id', res.json,
                      'Expected acoount get_profile not to return parse_id')
        self.assertNotIn('is_yo_team', res.json,
                      'Expected account get_profile not to return is_yo_team')

        # check for account owner and admin
        self.assertNotIn('email', res.json,
                      'Expected account get_profile not to return email')
        self.assertNotIn('bitly', res.json,
                      'Expected account get_profile not to return bitly')
        self.assertNotIn('api_token', res.json,
                      'Expected account get_profile not to return api_token')
        self.assertNotIn('phone', res.json,
                      'Expected account get_profile not to return phone')
        self.assertNotIn('is_verified', res.json,
                      'Expected account get_profile not to return is_verified')

        res = self.jsonpost('/rpc/get_profile',
                            data={'username': self._user2.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # check for admin only properties
        self.assertNotIn('last_yo_time', res.json,
                      'Expected friend get_profile not to return last_yo_time')
        self.assertNotIn('updated', res.json,
                      'Expected friend get_profile not to return updated')
        self.assertNotIn('created', res.json,
                      'Expected friend get_profile not to return created')
        self.assertNotIn('topic_arn', res.json,
                      'Expected friend get_profile not to return topic_arn')
        self.assertNotIn('parse_id', res.json,
                      'Expected friend get_profile not to return parse_id')
        self.assertNotIn('is_yo_team', res.json,
                      'Expected friend get_profile not to return is_yo_team')
        

        # check for account owner and admin
        self.assertNotIn('email', res.json,
                      'Expected friend get_profile not to return email')
        self.assertNotIn('bitly', res.json,
                      'Expected friend get_profile not to return bitly')
        self.assertNotIn('api_token', res.json,
                      'Expected friend get_profile not to return api_token')
        self.assertNotIn('phone', res.json,
                      'Expected friend get_profile not to return phone')
        self.assertNotIn('is_verified', res.json,
                      'Expected friend get_profile not to return is_verified')
        self.assertNotIn('welcome_link', res.json,
                      'Expected friend get_profile not to return welcome_link')
        self.assertNotIn('callback', res.json,
                      'Expected friend get_profile not to return callback')

        # check for public
        self.assertIn('username', res.json,
                      'Expected friend get_profile to return username')
        self.assertIn('name', res.json,
                      'Expected friend get_profile to return name')
        self.assertIn('user_id', res.json,
                      'Expected friend get_profile to return user_id')
        self.assertIn('is_api_user', res.json,
                      'Expected friend get_profile to return is_api_user')
        self.assertIn('is_subscribable', res.json,
                      'Expected friend get_profile to return is_subscribable')
        self.assertNotIn('is_vip', res.json,
                      'Expected friend get_profile not to return is_vip')
        self.assertNotIn('photo', res.json,
                      'Expected friend get_profile not to return photo')
        self.assertNotIn('needs_location', res.json,
                      'Expected friend get_profile not to return needs_location')
        self.assertNotIn('bio', res.json,
                      'Expected friend get_profile not to return bio')



    def test_22_auto_follow_ref(self):
        # test that signing up from a user refferal links
        # automatically adds that user as a contact

        # Make sure the auto follow ref has a broadcast link
        self.short_url_mock.return_value = 'https://bit.ly/autofollow'
        res = self.jsonpost('/rpc/broadcast_from_api_account',
                data={'link':'http://p.justyo.co/info',
                                  'username': self._user1.username})
        self.assertEquals(res.status_code, 200)

        # Construct and save a fingerprint
        res = self.jsonpost('/rpc/get_fingerprint',
                            auth=False,
                            useragent=self.android_111064067_ua,
                            headers={'X-Forwarded-For': '209.49.1.90'})

        self.assertEquals(res.status_code, 200)
        self.assertIn('fingerprint', res.json)
        fingerprint = res.json.get('fingerprint')

        redis.set(fingerprint, self._user1.username)

        # Sign up a user with the same fingerprint data from above
        res = self.jsonpost('/rpc/sign_up', auth=False,
                            data=self._ephemeral_account,
                            useragent=self.android_111064067_ua,
                            headers={'X-Forwarded-For': '209.49.1.90'})
        self.assertEquals(res.status_code, 201, 'Expected 201 Created.')

        # Assert the auto follow ref has a new follower
        res = self.jsonpost('/rpc/get_followers')
        self.assertEquals(res.status_code, 200)
        self.assertIn(self._ephemeral_account['username'],
                      res.json.get('followers'))

        # Wait for jobs to be ready
        # In order to allow auto follow to be turned off the minum time
        # must be greator than 0
        time.sleep(1)
        # Assert there is a auto ref yo created
        next_job_time = yo_scheduler.get_time_until_next_job()
        self.assertEquals(next_job_time[0], JOB_TYPE)
        self.assertEquals(next_job_time[1], 0,
                          'Expected sign_up to have created job')
        jobs = yo_scheduler.get_scheduled_jobs_by_type(JOB_TYPE)
        self.assertEquals(len(jobs), 3, 'Expected 3 job')

        self.assertEquals(jobs[2].sender, self._user1)
        self.assertEquals(jobs[2].recipient.username,
                          self._ephemeral_account['username'])
        self.assertEquals(jobs[2].link, 'https://bit.ly/autofollow')

    def test_23_sign_up_yo_android(self):
        # test that signing up on android creates both the first yo link
        # and the first yo location
        res = self.jsonpost('/rpc/sign_up', auth=False,
                            useragent=self.android_111064067_ua,
                            data=self._ephemeral_account)
        self.assertEquals(res.status_code, 201, 'Expected 201 Created.')

        # Give the sign_up yo's time to propogate
        time.sleep(1)

        next_job_time = yo_scheduler.get_time_until_next_job()
        jobs = yo_scheduler.get_scheduled_jobs_by_type(JOB_TYPE)
        self.assertEquals(len(jobs), 2, 'Expected 2 job')

        yo_scheduler.execute_scheduled_items_now(JOB_TYPE)

    def test_24_sign_up_yo_ios(self):
        # test that signing up on ios doesn't create any sign_up yos
        res = self.jsonpost('/rpc/sign_up', auth=False,
                            useragent=self.ios_146_ua,
                            data=self._ephemeral_account)
        self.assertEquals(res.status_code, 201, 'Expected 201 Created.')

        # Give the sign_up yo's time to propogate
        time.sleep(1)

        jobs = yo_scheduler.get_scheduled_jobs_by_type(JOB_TYPE)
        self.assertEquals(len(jobs), 2, 'Expected 2 jobs')

    def test_25_limited_get_profile(self):
        # Test that get_profile is properly including and omitting keys.

        # test no useragent.
        res = self.jsonpost('/rpc/get_profile',
                            data={'username': self._user2.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        self.assertIn('username', res.json,
                      'Expected get_profile to return username')
        self.assertIn('name', res.json,
                      'Expected get_profile to return name')
        self.assertIn('user_id', res.json,
                      'Expected get_profile to return user_id')
        self.assertIn('is_api_user', res.json,
                         'Expected get_profile not to return is_api_user')
        self.assertIn('is_subscribable', res.json,
                      'Expected get_profile not to return is_subscribable')
        self.assertNotIn('is_vip', res.json,
                      'Expected get_profile not to return is_vip')
        self.assertNotIn('photo', res.json,
                      'Expected get_profile not to return photo')
        self.assertNotIn('needs_location', res.json,
                      'Expected get_profile not to return needs_location')
        self.assertNotIn('bio', res.json,
                      'Expected get_profile not to return bio')

        # test android.
        res = self.jsonpost('/rpc/get_profile',
                            useragent=self.android_111064067_ua,
                            data={'username': self._user2.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        self.assertIn('username', res.json,
                      'Expected get_profile to return username')
        self.assertIn('name', res.json,
                      'Expected get_profile to return name')
        self.assertIn('user_id', res.json,
                      'Expected get_profile to return user_id')
        self.assertIn('is_api_user', res.json,
                      'Expected get_profile to return is_api_user')
        self.assertIn('is_subscribable', res.json,
                      'Expected get_profile to return is_subscribable')
        self.assertNotIn('is_vip', res.json,
                      'Expected get_profile not to return is_vip')
        self.assertNotIn('photo', res.json,
                      'Expected get_profile not to return photo')
        self.assertNotIn('needs_location', res.json,
                      'Expected get_profile not to return needs_location')
        self.assertNotIn('bio', res.json,
                      'Expected get_profile not to return bio')

        # test ios.
        res = self.jsonpost('/rpc/get_profile',
                            useragent=self.ios_146_ua,
                            data={'username': self._user2.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        self.assertIn('username', res.json,
                      'Expected get_profile to return username')
        self.assertIn('name', res.json,
                      'Expected get_profile to return name')
        self.assertIn('user_id', res.json,
                      'Expected get_profile to return user_id')
        self.assertIn('is_api_user', res.json,
                      'Expected get_profile to return is_api_user')
        self.assertIn('is_subscribable', res.json,
                      'Expected get_profile not to return is_subscribable')
        self.assertNotIn('is_vip', res.json,
                      'Expected get_profile not to return is_vip')
        self.assertNotIn('photo', res.json,
                      'Expected get_profile not to return photo')
        self.assertNotIn('needs_location', res.json,
                      'Expected get_profile not to return needs_location')
        self.assertNotIn('bio', res.json,
                      'Expected get_profile not to return bio')

    def test_26_link_facebook_account(self):
        facebook_data = {'id': 'test_facebook_id',
                         'first_name': 'Johnny',
                         'last_name': 'Appleseed',
                         'email': 'test@justyo.co'}
        self.facebook_get_profile_mock.return_value = facebook_data

        res = self.jsonpost('/rpc/link_facebook_account',
                data={'facebook_token': 'test_facebook_token'})
        self.assertEquals(res.status_code, 200)
        user_dict = res.json
        self.assertIsNotNone(user_dict)
        self.assertEquals(user_dict.get('user_id'), self._user1.user_id)
        self.assertEquals(user_dict.get('display_name'), 'Johnny A.')

        # Test that user 1 is returned.
        res = self.jsonpost('/rpc/login_with_facebook_token',
                            auth=False,
                            data={'facebook_token': 'test_facebook_token'})

        profile = res.json
        self.assertEquals(res.status_code, 200, '200 OK')
        self.assertEquals(profile.get('user_id'), self._user1.user_id)

        res = self.jsonpost('/rpc/link_facebook_account',
                            data={'facebook_token': 'test_facebook_token'},
                            jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200)
        user_dict = res.json
        self.assertIsNotNone(user_dict)
        self.assertEquals(user_dict.get('user_id'), self._user2.user_id)
        self.assertEquals(user_dict.get('display_name'), 'Johnny A.')

        # Test that user 2 is returned.
        res = self.jsonpost('/rpc/login_with_facebook_token',
                            auth=False,
                            data={'facebook_token': 'test_facebook_token'})

        profile = res.json
        self.assertEquals(res.status_code, 200, '200 OK')
        self.assertEquals(profile.get('user_id'), self._user2.user_id)

        self.facebook_get_profile_mock.return_value = {}

    def test_27_clear_cache_endpoint(self):
        admin_user = User(username='ADMINACCOUNT', is_admin=True)
        admin_user.set_password('123456')
        admin_user.save()
        _admin_user_token = jwt.generate_token(admin_user)

        first_name = self._user1.first_name
        new_first_name = 'BLAHBLAH User 1 name'
        self.assertNotEquals(first_name, new_first_name)

        res = self.jsonpost('/rpc/get_me')
        self.assertEquals(res.status_code, 200)
        self.assertEquals(res.json.get('first_name'), first_name)

        self._user1.first_name = new_first_name
        self._user1.save()

        # Make sure the first_name doesn't change without
        # clearing the cache.
        res = self.jsonpost('/rpc/get_me')
        self.assertEquals(res.status_code, 200)
        self.assertEquals(res.json.get('first_name'), first_name)

        res = self.jsonpost('/admin/clear_cache', jwt_token=_admin_user_token,
                            data={'username': self._user1.username,
                                  'clear_contacts': True,
                                  'clear_followers': True,
                                  'clear_yo_inbox': True,
                                  'clear_endpoints': True})
        self.assertEquals(res.status_code, 200)
        self.assertEquals(len(res.json.get('failures')), 0)

        res = self.jsonpost('/rpc/get_me')
        self.assertEquals(res.status_code, 200)
        self.assertEquals(res.json.get('first_name'), new_first_name)


    def test_28_calculate_is_person(self):
        user = self._user1
        self.assertIsNone(user._is_person)
        self.assertTrue(user.is_person)

        # Test that _is_person doesn't get set without a useragent.
        res = self.jsonpost('/rpc/get_me')
        self.assertEquals(res.status_code, 200)

        user = self._user1.reload()
        self.assertIsNone(user._is_person)
        self.assertTrue(user.is_person)

        self.assertFalse(user.is_service)

        # Test that _is_person gets set with a useragent.
        res = self.jsonpost('/rpc/get_me',
                            useragent=self.ios_141_ua)
        self.assertEquals(res.status_code, 200)

        user = self._user1.reload()
        self.assertTrue(user._is_person)
        self.assertTrue(user.is_person)

        self.assertFalse(user.is_service)

    def test_29_send_verification_code(self):
        """ Tests the send_verification_code endpoint """

        update_user(self._user1, phone=None, ignore_permission=True)

        # Bad phone number.
        res = self.jsonpost('/rpc/send_verification_code',
                            data={'phone_number': '+11111'})
        self.assertEquals(res.status_code, 400)
        self.assertEquals(res.json.get('error'), 'Invalid phone number')
        user = get_user(self._user1.username, ignore_permission=True)
        self.assertIsNone(user.phone)

        # Good phone number that twilio doesnt like.
        self.twilio_send_mock.side_effect = TwilioRestException(None, None, 'Invalid')
        res = self.jsonpost('/rpc/send_verification_code',
                            data={'phone_number': '+14153351320'})
        self.assertEquals(res.status_code, 200)
        #self.assertEquals(res.json.get('error'), 'Invalid')
        #user = get_user(self._user1.username, ignore_permission=True)
        #self.assertIsNone(user.phone)
        #self.twilio_send_mock.side_effect = None

        # Good phone number.
        res = self.jsonpost('/rpc/send_verification_code',
                            data={'phone_number': '+14153351320'})
        self.assertEquals(res.status_code, 200)
        user = get_user(self._user1.username, ignore_permission=True)
        self.assertEquals(user.phone, '+14153351320')

    def test_30_get_me_location(self):
        '''
        # Test that when no data is returned nothing is changed.
        tzinfo = pytz.timezone('America/Los_Angeles')
        offset_delta = tzinfo.utcoffset(datetime.now())
        offset_hours = offset_delta.total_seconds()/3600
        dst_offset = 1 if offset_hours == -7 else 0

        res = self.jsonpost('/rpc/get_me',
                            headers={'X-Forwarded-For': '127.0.0.1'})
        self.assertEquals(res.status_code, 200)

        user_dict = res.json
        self.assertEquals(user_dict.get('user_id'), self._user1.user_id)
        user1 = get_user(user_id=self._user1.user_id)
        self.assertIsNone(user1.city)
        self.assertIsNone(user1.country_name)
        self.assertIsNone(user1.region_name)
        self.assertIsNone(user1.timezone)
        self.assertIsNone(user1.utc_offset)

        # Test that when data is returned the location is set.
        location_data = {'ip': '127.0.0.1',
                         'country_code': 'US',
                         'country_name': 'United States',
                         'region_code': 'TX',
                         'region_name': 'Texas',
                         'city': 'Dallas',
                         'zip_code': '75201',
                         'time_zone': 'America/Chicago',
                         'latitude':  32.788,
                         'longitude': -96.8,
                         'metro_code': 623}
        self.get_request_mock.return_value.json.return_value = location_data

        res = self.jsonpost('/rpc/get_me',
                            headers={'X-Forwarded-For': '127.0.0.1'})
        self.assertEquals(res.status_code, 200)

        user_dict = res.json
        self.assertEquals(user_dict.get('user_id'), self._user1.user_id)
        user1 = get_user(user_id=self._user1.user_id)
        self.assertEquals(user1.city, 'Dallas')
        self.assertEquals(user1.country_name, 'United States')
        self.assertEquals(user1.region_name, 'Texas')
        self.assertEquals(user1.timezone, 'America/Chicago')
        self.assertEquals(user1.utc_offset, (-6 + dst_offset))

        # Test that when partial data is returned the rest is set.
        location_data = {'ip': '127.0.0.1',
                         'country_code': 'US',
                         'country_name': 'France',
                         'time_zone': 'America/Chicago'}
        self.get_request_mock.return_value.json.return_value = location_data

        res = self.jsonpost('/rpc/get_me',
                            headers={'X-Forwarded-For': '127.0.0.1'})
        self.assertEquals(res.status_code, 200)

        user_dict = res.json
        self.assertEquals(user_dict.get('user_id'), self._user1.user_id)
        user1 = get_user(user_id=self._user1.user_id)
        self.assertIsNone(user1.city)
        self.assertIsNone(user1.region_name)
        self.assertEquals(user1.country_name, 'France')
        self.assertEquals(user1.timezone, 'America/Chicago')
        self.assertEquals(user1.utc_offset, (-6 + dst_offset))

        self.get_request_mock.return_value.json.return_value = None
        '''

    # TODO, create a local admin user to add admin based tests
