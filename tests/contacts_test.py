# -*- coding: utf-8 -*-

"""Tests all authentication related endpoints."""

from flask import g
from yoapi.accounts import get_user

from . import BaseTestCase


class ContactsTestCase(BaseTestCase):

    def setUp(self, *args, **kwargs):
        """Test adding and removing contacts."""
        super(ContactsTestCase, self).setUp(*args, **kwargs)
        self.owner = self._user1
        self.target = self._user2

    def test_01_contacts(self):
        # This is the longest test ever. Initially this test was split into
        # many smaller tasks, but one subsequent job depended on successful
        # execution of previous jobs. Tests should not influence each others.

        # Testing valid user - expecting 200 ok
        res = self.jsonpost('/rpc/add',
                            data={'username': self.target.username})
        self.assertEquals(res.status_code, 200, '200 OK')

        # Test that endpoint requires authentication.
        res = self.jsonpost('/rpc/add', auth=False,
                            data={'username': self.target.username})
        self.assertEquals(res.status_code, 401, 'Expecting unauthorized')

        # Testing valid but non-logged user - expecting 401
        res = self.jsonpost('/rpc/add',
                            data={'username': 'HOPEFULLYNOTEXISTUSER'})
        self.assertEquals(res.status_code, 404, 'Expecting user not found')

        # By default, the jsonpost request authenticates as self._user1
        res = self.jsonpost('/rpc/get_contacts')
        self.assertIn(self.target.username, res.json['contacts'])

        # Testing that friend not blocked shows up in followers list.
        res = self.jsonpost('/rpc/get_followers', jwt_token=self._user2_jwt)
        self.assertIn(self.owner.username, res.json.get('followers'),
                      'User should be in followers list.')

        # Testing "find_friends" endpoint
        phone_book = {'phone_numbers': ['+972526706103']}
        res = self.jsonpost('/rpc/find_friends', data=phone_book)
        self.assertEquals(res.status_code, 200, '200 OK')

        # Testing no number, expecting 400 BAD REQUEST
        res = self.jsonpost(
            '/rpc/find_friends', data={})
        self.assertEquals(res.status_code, 400, '400 BAD REQUEST')

        # Testing invalid request, expecting 401 OK
        res = self.jsonpost(
            '/rpc/find_friends',
            auth=False,
            data={
                'phone_numbers': ['+972526706103']})
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

        # Test that a unverified friend is not returned
        res = self.jsonpost('/rpc/find_friends',
                       data={'phone_numbers': [self._user1.phone]},
                       jwt_token=self._user2_jwt)

        friends = res.json.get('friends')
        self.assertEquals(len(friends), 0, 'Expected 0 friends')

        friend = get_user(phone=self._user1.phone)
        friend.verified = True
        friend.save()

        # Test that a verified friend is returned
        res = self.jsonpost('/rpc/find_friends',
                       data={'phone_numbers': [self._user1.phone]},
                       jwt_token=self._user2_jwt)

        friends = res.json.get('friends')
        self.assertEquals(len(friends), 1, 'Expected 1 friends')

        # Test that a malformed number works
        res = self.jsonpost('/rpc/find_friends',
                            data={'phone_numbers': ['(415) 335 1320']},
                            jwt_token=self._user2_jwt)
        friends = res.json.get('friends')
        self.assertGreater(len(friends), 0, 'Expected 1 friend')

        # Testing no facebook ids, expecting 400 BAD REQUEST
        res = self.jsonpost(
            '/rpc/find_facebook_friends', data={})
        self.assertEquals(res.status_code, 400, '400 BAD REQUEST')

        # Testing unauthenticated request, expecting 401 UNAUTHORIZED
        res = self.jsonpost(
            '/rpc/find_facebook_friends',
            auth=False,
            data={'facebook_ids': ['testuser1','testuser2']})
        self.assertEquals(res.status_code, 401, '401 UNAUTHORIZED')

        # Test that a friend is returned and self is not
        res = self.jsonpost('/rpc/find_facebook_friends',
                       data={
                'facebook_ids': ['testuser1','testuser2']},
                       jwt_token=self._user2_jwt)

        friends = res.json.get('friends')
        self.assertEquals(res.status_code, 200, '200 OK')
        self.assertEquals(len(friends), 1, 'Expected 1 friends')
        self.assertEquals(friends[0].get('username'), 'TESTUSERPYTHON', 'Found wrong user')

        # Test blocking a user.
        res = self.jsonpost('/rpc/block',
                            data={'username': self.target.username})
        block = res.json.get('blocked')
        self.assertEquals(block, self.target.username)
        self.assertEquals(res.status_code, 200, 'Expecting ok')

        # Test unauthorized calls.
        res = self.jsonpost('/rpc/block', auth=False,
                            data={'username': self.target.username})
        self.assertEquals(res.status_code, 401, 'Expecting unauthorized')

        # Test block user that doesn't exist.
        res = self.jsonpost(
            '/rpc/block',
            data={'username': self._ephemeral_account['username']})
        self.assertEquals(res.status_code, 404, 'Expecting user not found')

        # Test that target user is blocked.
        res = self.jsonpost('/rpc/is_blocked',
                            data={'username': self.target.username})
        blocked = res.json.get('blocked')
        self.assertTrue(blocked, 'User should be blocked')
        self.assertEquals(res.status_code, 200, '200 OK')

        # Testing that blocked friend does not show up in friend list.
        res = self.jsonpost('/rpc/get_contacts')
        contacts = res.json.get('contacts')
        self.assertEquals(res.status_code, 200, '200 OK')
        self.assertNotIn(self.target.username, contacts,
                         'User should not be in friends list.')

        # Testing that blocked friend does not show up in followers list.
        res = self.jsonpost('/rpc/get_followers', jwt_token=self._user2_jwt)
        self.assertNotIn(self.owner.username, res.json.get('followers'),
                         'User should not be in followers list.')

        # Testing that blocked friend shows up in blocked friend list.
        res = self.jsonpost('/rpc/get_blocked_contacts')
        contacts = res.json.get('contacts')
        self.assertEquals(res.status_code, 200, '200 OK')
        self.assertIn(self.target.username, contacts,
                      'User should be in blocked contacts list.')

        # Testing that get_profile is blocked.
        res = self.jsonpost('/rpc/get_profile',
            jwt_token=self._user2_jwt,
            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 403, 'Expected 403 Forbidden')

        # Testing is blocked without authentication.
        res = self.jsonpost('/rpc/is_blocked', auth=False)
        self.assertEquals(res.status_code, 401, 'Expecting unauthorized')

        # Testing is blocked for a user that doesn't exist.
        res = self.jsonpost(
            '/rpc/is_blocked',
            data={'username': self._ephemeral_account['username']})
        self.assertEquals(res.status_code, 404, 'Expecting user not found')

        # Test unblock user.
        res = self.jsonpost('/rpc/unblock',
                            data={'username': self.target.username})
        self.assertEquals(res.status_code, 200, 'Expecting OK')

        # Test unauthorized call.
        res = self.jsonpost('/rpc/unblock', auth=False)
        self.assertEquals(res.status_code, 401, 'Expecting unauthorized')

        # Test unblock user that does not exist.
        res = self.jsonpost(
            '/rpc/unblock',
            data={'username': self._ephemeral_account['username']})
        self.assertEquals(res.status_code, 404, 'Expecting user not found')

        # Test removing a contact.
        res = self.jsonpost('/rpc/delete',
                            data={'username': self.target.username})
        self.assertEquals(res.status_code, 200, '200 OK')

        # Test that contact is gone.
        res = self.jsonpost('/rpc/get_contacts')
        self.assertNotIn(self.target.username, res.json['contacts'])

        # Test the contact can be re-added via sending a yo.
        res = self.jsonpost('/rpc/yo',
                            data={'username': self.target.username})
        self.assertEquals(res.status_code, 200, '200 OK')

        # Test that contact is back.
        res = self.jsonpost('/rpc/get_contacts')
        self.assertIn(self.target.username, res.json['contacts'])

        # Test removing a contact.
        res = self.jsonpost('/rpc/delete',
                            data={'username': self.target.username})
        self.assertEquals(res.status_code, 200, '200 OK')

        # Test that contact is gone.
        res = self.jsonpost('/rpc/get_contacts')
        self.assertNotIn(self.target.username, res.json['contacts'])

        # Test the contact can be re-added via /rpc/add.
        res = self.jsonpost('/rpc/add',
                            data={'username': self.target.username})
        self.assertEquals(res.status_code, 200, '200 OK')

        # Test that contact is back.
        res = self.jsonpost('/rpc/get_contacts')
        self.assertIn(self.target.username, res.json['contacts'])

        # Test unauthenticated call.
        res = self.jsonpost('/rpc/delete', auth=False)
        self.assertEquals(res.status_code, 401, 'Expecting unauthorized')

        # Test removing a user that doesn't exist.
        res = self.jsonpost('/rpc/delete',
                            data={'username': 'HOPEFULLYNOTEXISTUSER'})
        self.assertEquals(res.status_code, 404, 'Expecting user not found')

        # Testing "count_subscribers" endpoint

        # Testing on logged in  username, expecting 200 OK
        res = self.jsonpost('/rpc/count_subscribers')
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # Testing on logged out  username, expecting 401 UNAUTHORIZED
        res = self.jsonpost('/rpc/count_subscribers', auth=False)
        self.assertEquals(res.status_code, 401, 'Expected 401 UNAUTHORIZED')

    def test_02_get_contact_profile(self):
        # Testing "get_profile" endpoint

        # Remove contacts before actual tests
        self.jsonpost('/rpc/delete',
            jwt_token=self._user1_jwt,
            data={'username': self._user2.username})
        self.jsonpost('/rpc/delete',
            jwt_token=self._user2_jwt,
            data={'username': self._user1.username})

        # TODO: In the future this should return 401. For now, leave this type.
        res = self.jsonpost('/rpc/get_profile',
            data={'username': self._user2.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

        # test get profile of contact
        self.jsonpost('/rpc/add',
            data={'username': self._user2.username})
        res = self.jsonpost('/rpc/get_profile',
            data={'username': self._user2.username})
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')

    def test_03_hidden_contacts(self):
        # Testing that when a contact is deleted the still exist
        # as a follower
        # Assert initial state
        res = self.jsonpost('/rpc/get_followers')
        self.assertEquals(res.status_code, 200, '200 OK')
        self.assertNotIn(self._user2.username, res.json['followers'])

        # Become a follower
        res = self.jsonpost('/rpc/add',
                            jwt_token=self._user2_jwt,
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 200, '200 OK')

        # Test that the follower was successfully made.
        res = self.jsonpost('/rpc/get_followers')
        self.assertEquals(res.status_code, 200, '200 OK')
        self.assertIn(self._user2.username, res.json['followers'])

        # hide the contact.
        res = self.jsonpost('/rpc/delete',
                            jwt_token=self._user2_jwt,
                            data={'username': self._user1.username})
        self.assertEquals(res.status_code, 200, '200 OK')

        # Test that the follower still exists.
        res = self.jsonpost('/rpc/get_followers')
        self.assertEquals(res.status_code, 200, '200 OK')
        self.assertIn(self._user2.username, res.json['followers'])


    def test_04_list_contacts(self):
        res = self.jsonpost('/rpc/add',
            data={'username': self._user2.username})
        self.assertEquals(res.status_code, 200)

        res = self.jsonpost('/rpc/list_contacts')
        self.assertEquals(res.status_code, 200)

        contacts = res.json.get('contacts')
        self.assertEquals(len(contacts), 1)

        res = self.jsonpost('/rpc/block',
            data={'username': self._user2.username})
        self.assertEquals(res.status_code, 200)

        res = self.jsonpost('/rpc/list_contacts')
        self.assertEquals(res.status_code, 200)

        contacts = res.json.get('contacts')
        self.assertEquals(len(contacts), 0)
