# -*- coding: utf-8 -*-
"""Tests that pseudo users function properly"""

from . import BaseTestCase
from flask import request

from yoapi.accounts import get_user
from yoapi.helpers import random_string
from yoapi.models import User, Contact
from yoapi.services import low_rq, high_rq


class PseudoAccountTestCase(BaseTestCase):
    def setUp(self):
        super(PseudoAccountTestCase, self).setUp()


        token = random_string(length=5)
        pseudo_user = User(username='12322222222', phone='+12322222222',
                           is_pseudo=True, verified=True, api_token=token)
        self.pseudo_user = pseudo_user.save()

    def test_01_account_creation(self):
        # Test that creating a pseudo user by yo'ing them works.
        json_data = {'phone_number': '+11234567890',
                     'name': 'Test User'}
        res = self.jsonpost('/rpc/yo', data=json_data)
        self.assertEquals(res.status_code, 200)

        low_rq.create_worker(app=self.worker_app).work(burst=True)

        pseudo_user = res.json.get('recipient')
        self.assertIsNotNone(pseudo_user)
        self.assertTrue(pseudo_user.get('is_pseudo'))
        self.assertEqual(pseudo_user.get('type'), 'pseudo_user')

        # Test that upserting returns the same user.
        json_data = {'phone_number': '+11234567890',
                     'name': 'Test User'}
        res = self.jsonpost('/rpc/yo', data=json_data)
        self.assertEquals(res.status_code, 200)

        pseudo_user2 = res.json.get('recipient')
        self.assertIsNotNone(pseudo_user2)
        self.assertTrue(pseudo_user.get('is_pseudo'))
        self.assertEqual(pseudo_user.get('type'), 'pseudo_user')
        self.assertEqual(pseudo_user.get('user_id'),
                         pseudo_user2.get('user_id'))

        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # test that the user received the welcome text and the first
        # text. The second text should have gotten muted.

        #self.assertEquals(self.twilio_send_mock.call_count, 1)

    def test_03_contacts(self):
        # Create user.
        json_data = {'phone_number': '+11234567890',
                     'name': 'Test User'}
        res = self.jsonpost('/rpc/yo', data=json_data)
        self.assertEquals(res.status_code, 200)

        pseudo_user = res.json.get('recipient')
        self.assertIsNotNone(pseudo_user)
        self.assertTrue(pseudo_user.get('is_pseudo'))
        self.assertEqual(pseudo_user.get('type'), 'pseudo_user')

        pseudo_user = get_user(user_id=pseudo_user.get('user_id'))

        # Test that the creator appears on the contact list.
        res = self.jsonpost('/rpc/get_contacts',
                            auth=False,
                            data={'api_token': pseudo_user.api_token})
        self.assertEquals(res.status_code, 200)
        self.assertIn(self._user1.username, res.json.get('contacts'))

    def test_04_contacts_existing_user(self):
        # Test an existing pseudo user can get a new contact.
        json_data = {'phone_number': self.pseudo_user.phone,
                     'name': 'Test User'}
        res = self.jsonpost('/rpc/yo', data=json_data)
        self.assertEquals(res.status_code, 200)

        pseudo_user = res.json.get('recipient')
        self.assertIsNotNone(pseudo_user)
        self.assertTrue(pseudo_user.get('is_pseudo'))
        self.assertEqual(pseudo_user.get('type'), 'pseudo_user')
        self.assertEqual(pseudo_user.get('user_id'), self.pseudo_user.user_id)

        res = self.jsonpost('/rpc/yo', data=json_data,
                            jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200)

        pseudo_user = res.json.get('recipient')
        self.assertIsNotNone(pseudo_user)
        self.assertTrue(pseudo_user.get('is_pseudo'))
        self.assertEqual(pseudo_user.get('type'), 'pseudo_user')
        self.assertEqual(pseudo_user.get('user_id'), self.pseudo_user.user_id)

        res = self.jsonpost('/rpc/get_contacts',
                            auth=False,
                            data={'api_token': self.pseudo_user.api_token})
        self.assertEquals(res.status_code, 200)
        self.assertIn(self._user1.username, res.json.get('contacts'))
        self.assertIn(self._user2.username, res.json.get('contacts'))

        res = self.jsonpost('/rpc/get_contacts')
        self.assertEquals(res.status_code, 200)
        self.assertIn(self.pseudo_user.username, res.json.get('contacts'))

        res = self.jsonpost('/rpc/get_contacts',
                            jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200)
        self.assertIn(self.pseudo_user.username, res.json.get('contacts'))

    def test_05_forbidden_routes(self):
        # Test that pseudo users can only access /rpc/yo,
        # /rpc/list_contacts, and /rpc/get_contacts.

        res = self.jsonpost('/rpc/get_profile',
                            auth=False,
                            data={'username': self._user1.username,
                                  'api_token': self.pseudo_user.api_token})
        self.assertEquals(res.status_code, 401)

        res = self.jsonpost('/rpc/list_contacts',
                            auth=False,
                            data={'api_token': self.pseudo_user.api_token})
        self.assertEquals(res.status_code, 200)

    def test_06_account_migrate(self):
        # test that a pseudo account can succesfully migrate to a
        # regular account.

        # Reuse an existing function to setup some contacts.
        self.test_04_contacts_existing_user()
        res = self.jsonpost('/rpc/sign_up',
                            data={'username': 'TESTPSEUDOCONVERT',
                                  'password': '1234'},
                            auth=False)

        self.assertEquals(res.status_code, 201)
        jwt_tok = res.json.get('tok')
        user_id = res.json.get('user_id')
        new_user = User.objects(id=user_id).get()

        # Add some contact relationships for debugging purposes.
        Contact(owner=new_user, target=new_user).save()
        Contact(owner=self.pseudo_user, target=new_user).save()
        Contact(owner=new_user, target=self.pseudo_user).save()

        res = self.jsonpost('/rpc/send_verification_code',
                            jwt_token=jwt_tok,
                            data={'phone_number': self.pseudo_user.phone})

        self.assertEquals(res.status_code, 200)
        new_user = User.objects(id=user_id).get()
        code = new_user.temp_token.token

        res = self.jsonpost('/rpc/verify_code',
                            data={'code': code}, jwt_token=jwt_tok)
        self.assertEquals(res.status_code, 200)

        low_rq.create_worker(app=self.worker_app).work(burst=True)

        res = self.jsonpost('/rpc/get_contacts', jwt_token=jwt_tok)
        self.assertEquals(res.status_code, 200)
        self.assertIn(self._user1.username, res.json.get('contacts'))
        self.assertIn(self._user2.username, res.json.get('contacts'))

        res = self.jsonpost('/rpc/get_contacts', jwt_token=self._user1_jwt)
        self.assertEquals(res.status_code, 200)
        self.assertIn('TESTPSEUDOCONVERT', res.json.get('contacts'))

        res = self.jsonpost('/rpc/get_contacts', jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200)
        self.assertIn('TESTPSEUDOCONVERT', res.json.get('contacts'))
