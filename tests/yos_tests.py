# -*- coding: utf-8 -*-

"""Tests all yo related endpoints."""

import mock
import time

from flask import g, json
from gevent.queue import Queue
from yoapi.accounts import update_user
from yoapi.contacts import add_contact
from yoapi.core import limiter
from yoapi.models import Contact, User
from yoapi.urltools import UrlHelper
from yoapi.services import low_rq, medium_rq, high_rq, redis_pubsub

from yoapi.yos.queries import (get_yos_received, get_yos_sent, get_yo_by_id,
                               get_child_yos)
from yoapi.constants.yos import LIVE_YO_CHANNEL

from . import BaseTestCase


ACCOUNT_COUNT = 50
BIG_ACCOUNT_PREFIX = 'BROADCASTUSER%s'

class YosTestCase(BaseTestCase):

    # Just a holder where the pubsub callback can add received data.
    live_yos_detected = None

    def pubsub_callback(self, data):
        """Callback we can pass to pubsub."""
        self.live_yos_detected.append(data)

    @classmethod
    def setup_class(cls):
        super(YosTestCase, cls).setup_class()

    @classmethod
    def teardown_class(cls):
        pass

    def setUp(self):
        # Spawn lots of followers of user1
        super(YosTestCase, self).setUp()
        followers = []
        for i in xrange(0, ACCOUNT_COUNT):
            username = BIG_ACCOUNT_PREFIX % i
            user = User(username=username, topic_arn='test')
            user.save()
            followers.append(user)

        for follower in followers:
            contact1 = Contact(owner=follower, target=self._user1)
            contact1.save()
            contact2 = Contact(owner=follower, target=self._user2)
            contact2.save()

        # Initialize the live yo's detected array here so it's cleared between
        # tests.
        self.live_yos_detected = []

    def tearDown(self):
        # Unregister from pubsub.
        redis_pubsub.unregister(self.pubsub_callback, LIVE_YO_CHANNEL)

    def test_01_yo(self):

        # Testing Yo delivery with loggedin user - expecting 200 OK
        # Test that a empty link is ignored
        res = self.jsonpost('/rpc/yo',
                            data={
                                'link': '',
                                'to': self._user2['username'],
                                'location': '23.899384;54.589922'})
        status = res.json.get('success')
        self.assertTrue(status, 'output should be true')
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Test that location has been stored.
        yo_id = res.json.get('yo_id')
        yo = get_yo_by_id(yo_id)
        self.assertIsNotNone(yo.location)

        with self.app.test_request_context():
            pass
            # Register with pubsub.
            #redis_pubsub.register(self.pubsub_callback, LIVE_YO_CHANNEL)

            # Start redis pubsub so that we can verify that it's broadcasting
            # sent yo's correctly.
            #redis_pubsub.start()

            # Test that location is removed when yo has been processed and marked
            # as sent.
            low_rq.create_worker(app=self.worker_app).work(burst=True)

            #time.sleep(1)
            # Test that a redis pubsub is working with the help of a moock
            # socket that we've plugged into `redis_pubsub`.
            #self.assertEquals(len(self.live_yos_detected), 1)
            #message = self.live_yos_detected[0]

            #self.assertIn('sender', message)
            #self.assertEquals(message['sender'], self._user1.username)
            #self.assertIn('yo_id', message)
            #self.assertEquals(message['yo_id'], yo_id)

            # This is no longer necessary so let turn it off.
            #redis_pubsub.close()

        # Verify that the Yo has been marked sent.
        yo.reload()
        self.assertEquals(yo.status, 'sent')

        # Testing Yo delivery with logged out user - expecting 401 UNAVAIABLE
        res = self.jsonpost('/rpc/yo', auth=False,
                            data={
                                'to': self._ephemeral_account['username'],
                                'link': 'http://www.google.com',
                                'location': '23.899384;54.589922'})
        self.assertEquals(res.status_code, 401, 'Expected 401 UNAVAIABLE')

        # Testing Yo delivery with non existent user - expecting 404 NOT FOUND
        res = self.jsonpost('/rpc/yo',
                            data={
                                'to': self._ephemeral_account['username'],
                                'link': 'http://www.google.com'})
        self.assertEquals(res.status_code, 404, 'Expected 404 NOT FOUND')

        # Testing Yo delivery with empty link to fix winphone - expected 200
        res = self.jsonpost('/rpc/yo',
                            data={
                                'to': self._user2['username'],
                                'link': ''})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Testing Yo delivery with bad location
        # Location should be probably stripped if it comes to that, for some reason it works just fine.
        # res = self.jsonpost('/rpc/yo',
        #                     data={
        #                         'to': self._user2['username'],
        #                         'location': 'aa.bb,xx.yy'})
        #status = res.json.get('success')
        #self.assertTrue(status, 'output should be true')
        #self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        # Testing Yo delivery with bad link
        # Should we handle non-standard url ? clearly this is not a url.. but it does return 200 OK
        # res = self.jsonpost('/rpc/yo',
        #                    data={
        #                        'to': self._user2['username'],
        #                        'link': 'JUSTNAMEWITHNOEXTENTIONORANYTHINGELSE'})
        #status = res.json.get('success')
        #self.assertTrue(status, 'output should be true')
        #self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

    def test_02_user_yo_count(self):
        # testing user_yo_count endpoint

        # testing valid use - expecting 200 OK
        res = self.jsonpost('/rpc/user_yo_count')
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # testing logged out user - expecting 401 UNAVAIBLE
        res = self.jsonpost('/rpc/user_yo_count', auth=False)
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

    def test_03_test_callback(self):
        # Set callback link.
        self.become(self._user2)
        callback_link = UrlHelper('http://www.justyo.co')
        update_user(self._user2, callback=callback_link.get_url())

        # Send yo to trigger callback link.
        # Spoof an ip for assertion
        user_ip = '192.168.0.1'
        res = self.jsonpost('/rpc/yo',
                            headers={'X-Forwarded-For': user_ip},
                            jwt_token=self._user1_jwt,
                            data={'to': self._user2['username']})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        yo_id = res.json.get('yo_id')
        self.assertIsNotNone(yo_id)

        # Process yo's
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Check that the callback has only been called once.
        self.assertEquals(self.get_request_mock.call_count, 1)

        # Check the url of the callback that was made.
        _, call_kwargs = self.get_request_mock.call_args_list[0]
        called_url = call_kwargs.get('url')
        callback_link.add_params({'username': self._user1['username'],
                                  'user_ip': user_ip})
        self.assertEquals(callback_link.get_url(), called_url,
                          'Expected callback link to be last request:' + callback_link.get_url() + ' ' +
                          called_url)


    def test_04_broadcast_from_api_account(self):
        # testing user_yo_count endpoint

        # testing valid user - expecting 200 OK
        res = self.jsonpost(
            '/rpc/broadcast_from_api_account',
            data={'username': self._user1['username']})
        success = res.json.get('success')
        yo_id = res.json.get('yo_id')
        self.assertTrue(success, 'Expected Successful request')
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # The low rq will run _send_yo which in turn adds _push_to_recipients
        # to the medium rq. The medium rq is now incharge of adding
        # _push_to_recipient and _push_to_recipient_partition to the low rq.
        # Because of this process the low rq nees to be worked twice. Once
        # for _send_yo and once for the many _push_to_recipient calls.
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Load yo after workers have run and verify that braodcast has been
        # sent.
        yo_1 = get_yo_by_id(yo_id)
        yo_1_child_yos = get_child_yos(yo_id)
        self.assertEquals(yo_1.recipient_count, ACCOUNT_COUNT)
        self.assertEquals(len(yo_1_child_yos), ACCOUNT_COUNT)
        for child_yo in yo_1_child_yos:
            self.assertEquals(child_yo.status, 'sent',
                              'Expected all child yos to have status sent')
        queue_names = [queue.name for queue in low_rq.get_all_queues()]
        self.assertIn(yo_1.sender.username, queue_names,
                     'Expected broadcast to have created a new queue.')

        # Broadcast from another account to verify that the queue name from
        # the previous broadcast gets cleared.
        res = self.jsonpost('/rpc/broadcast_from_api_account',
                            data={'username': self._user2.username},
                            jwt_token=self._user2_jwt)
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        yo_2 = get_yo_by_id(res.json.get('yo_id'))
        queue_names = [queue.name for queue in low_rq.get_all_queues()]
        self.assertIn(yo_2.sender.username, queue_names,
                     'Expected broadcast to have created a new queue.')
        self.assertNotIn(yo_1.sender.username, queue_names,
             'Expected previous broadcast queue to have been removed.')

        # testing broadcast with no followers
        res = self.jsonpost(
            '/rpc/broadcast_from_api_account',
            jwt_token=self._user3_jwt)
        success = res.json.get('success')
        yo_id = res.json.get('yo_id')
        self.assertTrue(success, 'Expected Successful request')
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')
        low_rq.create_worker(app=self.worker_app).work(burst=True)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)

        # Load yo after workers have run and verify that braodcast has been
        # sent.
        yo_1 = get_yo_by_id(yo_id)
        yo_1_child_yos = get_child_yos(yo_id)
        self.assertEquals(yo_1.recipient_count, None)
        self.assertEquals(len(yo_1_child_yos), 0)

    def test_05_list_broadcasted_links(self):
        # testing list_broadcasted_links endpoint

        # testing valid user - expecting 200 OK
        res = self.jsonpost(
            '/rpc/list_broadcasted_links',
            data={
                'username': self._user1['username']})
        self.assertEquals(res.status_code, 200, '200 OK')

        # Testing with implied user by passing no data in the body.
        res2 = self.jsonpost(
            '/rpc/list_broadcasted_links',
            data={})
        self.assertEquals(res2.status_code, 200, '200 OK')
        self.assertEquals(res.data, res2.data, 'Expected same return value')

        # testing invalid user - expecting 401 UNAUTHORIZED
        res = self.jsonpost(
            '/rpc/list_broadcasted_links',
            data={
                'username': self._user2['username']})
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

        # testing valid user but not logged in
        res = self.jsonpost(
            '/rpc/list_broadcasted_links', auth=False,
            data={
                'username': self._user1['username']})
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

        # testing valid user - expecting 404 NOT FOUND
        res = self.jsonpost(
            '/rpc/list_broadcasted_links',
            data={
                'username': 'HOPEFULLYNOUSEREXIST'})
        self.assertEquals(res.status_code, 404, '404 NOT FOUND')

    def test_06_yo_from_api_account(self):
        # testing yo_from_api_account

        # testing valid user with valid request - expected 200
        res = self.jsonpost(
            '/rpc/yo_from_api_account',
            data={
                'username': self._user1['username'],
                'to': self._user2['username']})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # testing invalid user (NO API USER)
        res = self.jsonpost(
            '/rpc/yo_from_api_account',
            data={
                'username': self._user1['username'],
                'to': ''})
        self.assertEquals(res.status_code, 400, 'Expected 400')

        # testing valid but logged out user - expected 401
        res = self.jsonpost(
            '/rpc/yo_from_api_account', auth=False,
            data={
                'username': self._user2['username'],
                'to': 'HOPEFULLYNOUSERNAMEEXIST'})
        self.assertEquals(res.status_code, 401, 'Expected 401 UNAUTHORIZED')

        # testing non existent receiver - expected 404
        res = self.jsonpost(
            '/rpc/yo_from_api_account',
            data={
                'username': self._user1['username'],
                'to': 'HOPEFULLYNOUSERNAMEEXIST'})
        self.assertEquals(res.status_code, 404, 'Expected 400 NOT FOUND')

        # testing valid user without assert_account_permission - expected 401
        res = self.jsonpost(
            '/rpc/yo_from_api_account',
            data={
                'username': self._user2['username'],
                'to': self._user1['username']})
        self.assertEquals(res.status_code, 401, 'Expected 401 UNAUTHORIZED')

    def test_07_yo_all(self):
        # testing yo_all

        # testing valid username with yo_all capabilities
        res = self.jsonpost(
            '/rpc/yo_all',
            data={
                'username': self._user1['username']})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # testing implied user by passing no data
        res = self.jsonpost(
            '/rpc/yo_all',
            jwt_token=self._user2_jwt,
            data={})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # testing invalid username with yo_all capabilities
        res = self.jsonpost(
            '/rpc/yo_all',
            jwt_token=self._user3_jwt,
            data={
                'username': self._user4['username']})
        self.assertEquals(res.status_code, 401, 'Expected 401 UNAUTHORIZED')

        # testing valid username with yo_all capabilities but not logged in
        res = self.jsonpost(
            '/rpc/yo_all',
            data={
                'username': self._user1['username']}, auth=False)
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

        # testing non-existent username
        res = self.jsonpost(
            '/rpc/yo_all',
            jwt_token=self._user4_jwt,
            data={
                'username': 'HOPEFULLYNOSUCHUSERNAME'})
        self.assertEquals(res.status_code, 404, '404 NOT FOUND')

    def test_08_yoall(self):
        # testing yoall

        # For legecy reaons i'll leave YO_ALL/YOALL and broadcast_from_api just the same
        # if anything changes in the future we will change it accordingly.

        # testing valid username with yo_all capabilities
        res = self.jsonpost(
            '/rpc/yoall',
            jwt_token=self._user1_jwt,
            data={
                'username': self._user1['username']})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # testing invalid username with yo_all capabilities
        res = self.jsonpost(
            '/rpc/yoall',
            jwt_token=self._user2_jwt,
            data={
                'username': self._user3['username']})
        self.assertEquals(res.status_code, 401, 'Expected 401 UNAUTHORIZED')

        # testing valid username with yo_all capabilities but not logged in
        res = self.jsonpost(
            '/rpc/yoall',
            data={
                'username': self._user1['username']}, auth=False)
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

        # testing non-existent username
        res = self.jsonpost(
            '/rpc/yoall',
            jwt_token=self._user3_jwt,
            data={
                'username': 'HOPEFULLYNOSUCHUSERNAME'})
        self.assertEquals(res.status_code, 404, '404 NOT FOUND')

    def test_09_yo_blocked_user(self):

        # Block user.
        res = self.jsonpost('/rpc/block',
                            data={'username': self._user1['username']},
                            jwt_token=self._user2_jwt)

        # Verify sending a yo returns 403 Forbidden.
        res = self.jsonpost('/rpc/yo',
                            data={'username': self._user2['username']})
        self.assertEquals(res.status_code, 403, 'Expected unauthorized')

        # Unblock user.
        res = self.jsonpost('/rpc/unblock',
                            data={'username': self._user1['username']},
                            jwt_token=self._user2_jwt)

        # Verify sending a yo returns 200 OK.
        res = self.jsonpost('/rpc/yo',
                            data={'username': self._user2['username']})
        self.assertEquals(res.status_code, 200, 'Expected OK')

    def test_10_welcome_link(self):
        """This is now considered a response yo but the
        old terminology is left for completeness since the first
        response can be considered a welcome"""

        self.become(self._user2)

        # Set welcome link.
        welcome_link = UrlHelper('http://www.justyo.co')
        update_user(self._user2, welcome_link=welcome_link.get_url())
        # Send yo to trigger welcome link.
        res = self.jsonpost('/rpc/yo',
                            data={'to': self._user2['username']})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        yo_id = res.json.get('yo_id')
        self.assertIsNotNone(yo_id)

        # Process yo's
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Load yo after workers have run and verify that welcome yo has been
        # sent.
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.status, 'sent')

        # The identity of the last jsonpost remains after, so we need to
        # become user2 again.
        # TODO: Investigate if this is a bug in the test system. The application
        # context should only be kept around when using "with" blocks.
        self.become(self._user2)

        # test that user2 recieved the initial yo
        yos_received = get_yos_received(self._user2)
        self.assertEquals(len(yos_received), 1, 'Expected one yo')
        self.assertIn(yo, yos_received)

        # Assert the welcome yo was created and sent
        child_yos = get_child_yos(yo_id)
        self.assertEquals(len(child_yos), 1, 'Expected one yo')
        self.assertEquals(child_yos[0].sender, self._user2)
        self.assertEquals(child_yos[0].recipient, self._user1)
        self.assertEquals(child_yos[0].link, welcome_link.get_url())
        self.assertEquals(child_yos[0].status, 'sent')

        self.become(self._user1)

        yos_received = get_yos_received(self._user1)
        self.assertEquals(len(yos_received), 1, 'Expected one yo')
        self.assertIn(child_yos[0], yos_received)

        # Test that sending a second yo will not trigger a response
        # since the recipient is not in the store
        # Send yo
        res = self.jsonpost('/rpc/yo',
                            data={'to': self._user2['username']})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        yo_id = res.json.get('yo_id')
        self.assertIsNotNone(yo_id)

        # Process yo's
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Load yo after workers have run and verify that welcome yo has been
        # sent.
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.status, 'sent')

        # The identity of the last jsonpost remains after, so we need to
        # become user2 again.
        # TODO: Investigate if this is a bug in the test system. The application
        # context should only be kept around when using "with" blocks.
        self.become(self._user2)

        # test that user2 recieved the initial yo
        yos_received = get_yos_received(self._user2)
        self.assertEquals(len(yos_received), 2, 'Expected two yos')
        self.assertIn(yo, yos_received)

        # Assert a welcome yo was not created
        child_yos = get_child_yos(yo_id)
        self.assertEquals(len(child_yos), 0, 'Expected no children')

    def test_11_broadcast_as_welcome_link(self):
        """Test that user's without welcome links send their last broadcast
        if they are in the store"""

        self.become(self._user2)

        # Remove welcome link and set user in store
        update_user(self._user2, welcome_link=None, in_store=True)
        # Send broadcast
        link = UrlHelper('http://www.justyo.co/test_response')
        res = self.jsonpost('/rpc/yoall',
                            jwt_token=self._user2_jwt,
                            data={'link': link.get_url()})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        yo_id = res.json.get('yo_id')
        self.assertIsNotNone(yo_id)

        # Process yo's
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Send yo to trigger welcome link.
        res = self.jsonpost('/rpc/yo',
                            data={'to': self._user2['username']})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        yo_id = res.json.get('yo_id')
        self.assertIsNotNone(yo_id)

        # Process yo's
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Load yo after workers have run and verify that welcome yo has been
        # sent.
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.status, 'sent')

        # The identity of the last jsonpost remains after, so we need to
        # become user2 again.
        # TODO: Investigate if this is a bug in the test system. The application
        # context should only be kept around when using "with" blocks.
        self.become(self._user2)

        # test that user2 recieved the initial yo
        yos_received = get_yos_received(self._user2)
        self.assertEquals(len(yos_received), 1, 'Expected one yo')
        self.assertIn(yo, yos_received)

        # Assert the welcome yo was created and sent
        child_yos = get_child_yos(yo_id)
        self.assertEquals(len(child_yos), 1, 'Expected one yo')
        self.assertEquals(child_yos[0].sender, self._user2)
        self.assertEquals(child_yos[0].recipient, self._user1)
        self.assertEquals(child_yos[0].link, link.get_url())
        self.assertEquals(child_yos[0].status, 'sent')

        self.become(self._user1)

        yos_received = get_yos_received(self._user1)
        self.assertIn(child_yos[0], yos_received)
        self.assertEquals(len(yos_received), 1, 'Expected one yo')

        # Test that sending a second yo will trigger the same response
        # since the recipient is in the store
        # Send yo
        res = self.jsonpost('/rpc/yo',
                            data={'to': self._user2['username']})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        yo_id = res.json.get('yo_id')
        self.assertIsNotNone(yo_id)

        # Process yo's
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Load yo after workers have run and verify that welcome yo has been
        # sent.
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.status, 'sent')

        # The identity of the last jsonpost remains after, so we need to
        # become user2 again.
        # TODO: Investigate if this is a bug in the test system. The application
        # context should only be kept around when using "with" blocks.
        self.become(self._user2)

        # test that user2 recieved the initial yo
        yos_received = get_yos_received(self._user2)
        self.assertEquals(len(yos_received), 2, 'Expected one yo')
        self.assertIn(yo, yos_received)

        # Assert the welcome yo was created and sent
        child_yos = get_child_yos(yo_id)
        self.assertEquals(len(child_yos), 1, 'Expected one yo')
        self.assertEquals(child_yos[0].sender, self._user2)
        self.assertEquals(child_yos[0].recipient, self._user1)
        self.assertEquals(child_yos[0].link, link.get_url())
        self.assertEquals(child_yos[0].status, 'sent')

        self.become(self._user1)

        yos_received = get_yos_received(self._user1)
        self.assertEquals(len(yos_received), 2, 'Expected one yo')
        self.assertIn(child_yos[0], yos_received)


    def test_12_rate_limiter(self):

        return

        # Test that limiter is working, but against a user that does not
        # exist.
        for _ in range(0, 30):
            response = self.jsonpost('/rpc/yo',
                data={'to': 'IDONOTEXIST'})
            self.assertEquals(response.status_code, 404,
                              'Expected 404 Not Found')
        # The sixth Yo should fail.
        # TODO: We should get the limit programatically. It is currently
        # hardcoded.
        response = self.jsonpost('/rpc/yo',
            data={'to': 'IDONOTEXIST'})
        self.assertEquals(response.status_code, 429,
                          'Expected 429 Too many requests')

        # Test that limiter is working, but against a user that does not
        # exist.
        for _ in range(0, 30):
            response = self.jsonpost('/yo/',
                data={'to': 'IDONOTEXIST3'})
            self.assertEquals(response.status_code, 404,
                              'Expected 404 Not Found')
        # The sixth Yo should fail.
        # TODO: We should get the limit programatically. It is currently
        # hardcoded.
        response = self.jsonpost('/yo/',
            data={'to': 'IDONOTEXIST3'})
        self.assertEquals(response.status_code, 429,
                          'Expected 429 Too many requests')


        # YOALL
        # Test the yoall limiter is working
        # This uses its own user because the limiter for yo all keys on
        # the sending username

        for _ in xrange(4):
            response = self.jsonpost('/rpc/broadcast_from_api_account',
                jwt_token=self._yoalluser_jwt)
            self.assertEquals(response.status_code, 200,
                              'Expected 200 Success')
        # The 5th Yoall should fail.
        # TODO: We should get the limit programatically. It is currently
        # hardcoded.
        response = self.jsonpost('/rpc/broadcast_from_api_account',
                jwt_token=self._yoalluser_jwt)
        self.assertEquals(response.status_code, 429,
                          'Expected 429 Too many requests')

        # Give the user a custom yoall limit and test that it works.
        update_user(self._yoalluser, yoall_limits='30/10 minutes')

        for _ in xrange(30):
            # Test that limiter is working
            response = self.jsonpost('/yoall/',
                jwt_token=self._yoalluser_jwt)
            self.assertEquals(response.status_code, 200,
                              'Expected 200 Success')
        # The 31st Yo should fail.
        response = self.jsonpost('/yoall/',
                jwt_token=self._yoalluser_jwt)
        self.assertEquals(response.status_code, 429,
                          'Expected 429 Too many requests')

        update_user(self._yoalluser, yoall_limits=None)



    def test_13_iphone_patch(self):
        """Tests that iPhone client 1.4.1 have custom error codes

        APIErrors raised on /rpc/yo, /rpc/yoall and /rpc/yo_all should return
        a 200 OK with {"message": "[MESSAGE]"} as payload.

        https://github.com/YoApp/api/issues/91
        """

        # Send a yo without specifying the username. It should fail.
        response = self.jsonpost('/rpc/yo')
        self.assertEquals(response.status_code, 400,
                          'Expected 400 Bad Request')

        # Send a the same Yo, but observe a 200 OK since the user agent
        # indicates this is an iPhone 1.4.1 client.
        useragent = 'Yo/1.4.1 (iPhone; iOS 7.0.6; Scale/2.00)'
        response = self.jsonpost('/rpc/yo', useragent=useragent)
        self.assertEquals(response.status_code, 200, 'Expected 200 OK')
        self.assertIsNotNone(response.json.get('message'), 'Message malformed')
        self.assertIsNone(response.json.get('error'), 'Message malformed')


        # Test that limiter is working, but against a user that does not
        # exist. We use a different username from test_08_rate_limiter
        # since that would otherwise interfere with this rate_limiter test.
        '''for i in range(0, 30):
            response = self.jsonpost('/rpc/yo',
                                     useragent=useragent,
                                     data={'to': 'IDONOTEXIST2'})
            self.assertEquals(response.status_code, 404,
                              'Expected 404 Not Found')

        # The 30th Yo should not fail since we are using an iPhone 1.4.1
        # useragent string.
        # TODO: We should get the limit programatically. It is currently
        # hardcoded.
        response = self.jsonpost('/rpc/yo', useragent=useragent,
                                 data={'to': 'IDONOTEXIST2'})
        self.assertEquals(response.status_code, 200,
                          'Expected 200 OK')'''

        # Send a the same Yo, but observe a 429 since the user agent
        # indicates this is an iPhone 1.4.2 client.
        '''useragent = 'Yo/1.4.2 (iPhone; iOS 7.0.6; Scale/2.00)'
        response = self.jsonpost('/rpc/yo', useragent=useragent,
                                 data={'to': 'IDONOTEXIST2'})
        self.assertEquals(response.status_code, 429,
                          'Expected 429 Too many requests')
        self.assertIsNone(response.json.get('message'), 'Message malformed')
        self.assertIsNotNone(response.json.get('error'), 'Message malformed')'''


    def test_15_location_format(self):

        # Test valid location seperated by comma
        res = self.jsonpost('/rpc/yo', data={'location':'90.0,-127.554334',
                                             'to': self._user2['username']})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # Test valid location seperated by semi-colon
        res = self.jsonpost('/rpc/yo', data={'location':'90.0;-127.554334',
                                             'to': self._user2['username']})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # Test invalid location
        res = self.jsonpost('/rpc/yo', data={'location':'90',
                                             'to': self._user2['username']})
        self.assertEquals(res.status_code, 400, 'Expected 400 Form validation error')

        # Test invalid location
        res = self.jsonpost('/rpc/yo', data={'location':'-290,80',
                                             'to': self._user2['username']})
        self.assertEquals(res.status_code, 400, 'Expected 200 OK')

    def test_16_blocked_link_hostname(self):

        # Test that you cannot send a link to a justyo.co hostname to
        # prevent forced subscription
        res = self.jsonpost('/rpc/yo', data={'to': self._user2['username'],
                                             'link': 'http://justyo.co/USER'})
        self.assertEquals(res.status_code, 401, 'Expected 401 link forbidden')

    def test_17_yo_acknowledgments(self):

        res = self.jsonpost('/rpc/yo',
                                 data={'to': self._user2['username']})
        self.assertEquals(res.status_code, 200,
                          'Expected 200 OK')
        yo_id = res.json.get('yo_id')

        # Process yo's
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.status, 'sent')

        res = self.jsonpost('/rpc/yo_ack',
                           jwt_token=self._user2_jwt,
                           data={'yo_id': yo_id})
        self.assertEquals(res.status_code, 200,
                          'Expected 200 OK')
        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.status, 'received')

    def test_20_broadcast_security(self):
        # Testing with implied user by passing no data in the body.
        res = self.jsonpost(
            '/rpc/broadcast_from_api_account',
            jwt_token=self._user1_jwt,
            data={})
        success = res.json.get('success')
        self.assertTrue(success, 'Expected Successful request')
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # testing invalid user - expecting 401 OK
        res = self.jsonpost(
            '/rpc/broadcast_from_api_account',
            jwt_token=self._user1_jwt,
            data={
                'username': self._user2['username']})
        self.assertEquals(res.status_code, 401, 'Expected 401 Unauthorized')

        # testing valid username with yo_all capabilities but not logged in
        res = self.jsonpost(
            '/rpc/broadcast_from_api_account',
            data={
                'username': self._user1['username']}, auth=False)
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

        # testing non-existent username
        res = self.jsonpost(
            '/rpc/broadcast_from_api_account',
            jwt_token=self._user3_jwt,
            data={
                'username': 'HOPEFULLYNOSUCHUSERNAME'})
        self.assertEquals(res.status_code, 404, '404 NOT FOUND')

    def test_21_get_unread_yos(self):
        res = self.jsonpost('/rpc/yo',
                            data={'to': self._user2.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')
        yo_id = res.json.get('yo_id')
        self.assertIsNotNone(yo_id)

        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yo = get_yo_by_id(yo_id)
        self.assertEquals(yo.status, 'sent')

        res = self.jsonpost('/rpc/get_unread_yos',
                            jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')
        unread_yos = res.json.get('unread_yos')
        self.assertEquals(len(unread_yos), 1)

        unread_yo = unread_yos[0]
        self.assertEquals(unread_yo.get('yo_id'), yo_id)
        self.assertEquals(unread_yo.get('sender'), self._user1.username)
        self.assertEquals(unread_yo.get('body'), self._user1.display_name)

        # Test acknowledge.
        res = self.jsonpost('/rpc/yo_ack',
                            data={'yo_id': yo_id, 'status': 'read'},
                            jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')

        res = self.jsonpost('/rpc/get_unread_yos',
                            jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200, 'Expected 200 Ok.')
        unread_yos = res.json.get('unread_yos')
        self.assertEquals(len(unread_yos), 0)
