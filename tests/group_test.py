# -*- coding: utf-8 -*-
"""Tests for various group actions"""

from . import BaseTestCase

from yoapi.accounts import update_user, get_user
from yoapi.contacts import get_contact_pair
from yoapi.helpers import get_usec_timestamp
from yoapi.models import Yo, Contact, User, NotificationEndpoint
from yoapi.services import low_rq, medium_rq
from yoapi.urltools import UrlHelper

from yoapi.models.payload import YoPayload
from yoapi.yos.queries import get_yo_by_id, get_child_yos


class GroupTestCase(BaseTestCase):

    def setUp(self):
        super(GroupTestCase, self).setUp()

        # Create group
        _group1 = User(username='GROUP1', name='Group 1', parent=self._user1,
                       is_group=True).save()
        Contact(target=self._user1, owner=_group1, is_group_admin=True).save()
        Contact(target=self._user2, owner=_group1).save()
        Contact(target=self._user3, owner=_group1).save()

        Contact(owner=self._user1, target=_group1).save()
        Contact(owner=self._user2, target=_group1).save()
        Contact(owner=self._user3, target=_group1).save()

        self._group1 = _group1

    def test_01_groups(self):
        # Test that creatung a group with improper information throws an error.
        group_data = {'name': 'test group', 'members': [{'username': 'test'}]}
        res = self.jsonpost('/rpc/add_group', data=group_data)
        self.assertEquals(res.status_code, 400)
        self.assertEquals(res.json.get('error'), 'Received invalid data')

        # Test that creating a group with proper information works.
        group_name = 'Group 2'
        group_data = {'name': group_name,
                      'members': [{'username': self._user1.username,
                                   'user_type': 'user'},
                                   {'username': self._user2.username,
                                   'user_type': 'user'}]}
        proper_group_username = ''.join([c.upper() for c in group_name
                                        if c.isalnum()])
        res = self.jsonpost('/rpc/add_group', data=group_data)
        self.assertEquals(res.status_code, 201)
        group_dict = res.json.get('group')
        self.assertIsNotNone(group_dict)

        self.assertEquals(group_dict.get('username'), proper_group_username)
        self.assertEquals(group_dict.get('type'), 'group')

        group_id = group_dict.get('user_id')
        self.assertIsNotNone(group_id)

        # Test the response of a getting a group by username.
        res = self.jsonpost('/rpc/get_group',
                            data={'username': proper_group_username})
        self.assertEquals(res.status_code, 200)

        group_dict = res.json
        self.assertIsNotNone(group_dict)
        self.assertEquals(group_dict.get('username'), proper_group_username)
        self.assertEquals(group_dict.get('type'), 'group')
        self.assertEquals(group_dict.get('user_id'), group_id)
        self.assertEquals(len(group_dict.get('admins')), 1)
        self.assertEquals(len(group_dict.get('members')), 1)
        self.assertEquals(group_dict.get('admins')[0].get('user_id'),
                          self._user1.user_id)
        self.assertEquals(group_dict.get('members')[0].get('user_id'),
                          self._user2.user_id)

        # Test that users not in the group cannot request it.
        res = self.jsonpost('/rpc/get_group',
                            jwt_token=self._user3_jwt,
                            data={'username': proper_group_username})
        self.assertEquals(res.status_code, 401)

        # Test that User objects that are not groups throw an error.
        res = self.jsonpost('/rpc/get_group',
                            jwt_token=self._user1_jwt,
                            data={'username': self._user3.username})
        self.assertEquals(res.status_code, 400)

        # test that adding a user to a group works as expected.
        res = self.jsonpost('/rpc/add_group_members',
                            data={'username': proper_group_username,
                                'members': [{'username': self._user3.username}]})
        self.assertEquals(res.status_code, 200)

        members = res.json.get('added')
        self.assertIsNotNone(members)
        self.assertEquals(self._user3.user_id, members[0].get('user_id'))

        # Test the response of getting a group now that there is a
        # new member.
        res = self.jsonpost('/rpc/get_group',
                            data={'username': proper_group_username})
        self.assertEquals(res.status_code, 200)

        group_dict = res.json
        self.assertIsNotNone(group_dict)
        self.assertEquals(group_dict.get('username'), proper_group_username)
        self.assertEquals(group_dict.get('type'), 'group')
        self.assertEquals(group_dict.get('user_id'), group_id)
        self.assertEquals(len(group_dict.get('admins')), 1)
        self.assertEquals(len(group_dict.get('members')), 2)
        self.assertEquals(group_dict.get('admins')[0].get('user_id'),
                          self._user1.user_id)
        self.assertEquals(group_dict.get('members')[0].get('user_id'),
                          self._user3.user_id)
        self.assertEquals(group_dict.get('members')[1].get('user_id'),
                          self._user2.user_id)

        # test that removing a user from a group works as expected.
        res = self.jsonpost('/rpc/remove_group_member',
                            data={'username': proper_group_username,
                                  'member': self._user2.username})
        self.assertEquals(res.status_code, 200)

        member = res.json.get('removed')
        self.assertIsNotNone(member)
        self.assertEquals(self._user2.user_id, member.get('user_id'))

        # Test the response of getting a group now that there is a
        # new member.
        res = self.jsonpost('/rpc/get_group',
                            data={'username': proper_group_username})
        self.assertEquals(res.status_code, 200)

        group_dict = res.json
        self.assertIsNotNone(group_dict)
        self.assertEquals(group_dict.get('username'), proper_group_username)
        self.assertEquals(group_dict.get('type'), 'group')
        self.assertEquals(group_dict.get('user_id'), group_id)
        self.assertEquals(len(group_dict.get('admins')), 1)
        self.assertEquals(len(group_dict.get('members')), 1)
        self.assertEquals(group_dict.get('admins')[0].get('user_id'),
                          self._user1.user_id)
        self.assertEquals(group_dict.get('members')[0].get('user_id'),
                          self._user3.user_id)

        # Test that users not in the group cannot request it.
        res = self.jsonpost('/rpc/get_group',
                            jwt_token=self._user2_jwt,
                            data={'username': proper_group_username})
        self.assertEquals(res.status_code, 401)

        # test that blocking a group works as expected.
        res = self.jsonpost('/rpc/block_group',
                            jwt_token=self._user3_jwt,
                            data={'username': proper_group_username})
        self.assertEquals(res.status_code, 200)

        group = res.json.get('blocked')
        self.assertIsNotNone(group)
        self.assertEquals(group_dict.get('user_id'), group.get('user_id'))
        # Test the response of getting a group now that a member is gone
        # new member.
        res = self.jsonpost('/rpc/get_group',
                            jwt_token=self._user1_jwt,
                            data={'username': proper_group_username})
        self.assertEquals(res.status_code, 200)

        group_dict = res.json
        self.assertIsNotNone(group_dict)
        self.assertEquals(group_dict.get('username'), proper_group_username)
        self.assertEquals(group_dict.get('type'), 'group')
        self.assertEquals(group_dict.get('user_id'), group_id)
        self.assertEquals(len(group_dict.get('admins')), 1)
        self.assertEquals(len(group_dict.get('members')), 0)
        self.assertEquals(group_dict.get('admins')[0].get('user_id'),
                          self._user1.user_id)

        # Test that users not in the group cannot request it.
        res = self.jsonpost('/rpc/get_group',
                            jwt_token=self._user3_jwt,
                            data={'username': proper_group_username})
        self.assertEquals(res.status_code, 401)

        # test that adding a user that has blocked the group fails.
        res = self.jsonpost('/rpc/add_group_members',
                            data={'username': proper_group_username,
                                'members': [{'username': self._user3.username}]})
        self.assertEquals(res.status_code, 403)
        self.assertEquals(res.json.get('error'),
                          'Member has blocked group.')

    def test_02_add_group(self):
        # Test that when adding a group via /rpc/add you get a 200 if
        # your in the group.

        res = self.jsonpost('/rpc/add',
                            jwt_token=self._user2_jwt,
                            data={'username': self._group1.username})
        self.assertEquals(res.status_code, 200)
        self.assertIsNotNone(res.json.get('added'))
        added = res.json.get('added')
        self.assertEquals(added.get('user_id'), self._group1.user_id)

        # Test that when adding a group via /rpc/add you get a 403 if
        # your not in the group.

        res = self.jsonpost('/rpc/leave_group',
                            jwt_token=self._user2_jwt,
                            data={'username': self._group1.username})
        self.assertEquals(res.status_code, 200)

        res = self.jsonpost('/rpc/add',
                            jwt_token=self._user2_jwt,
                            data={'username': self._group1.username})
        self.assertEquals(res.status_code, 403)

    def test_03_mute_group(self):
        # Test that muting a group prevents a yo from being sent.

        res = self.jsonpost('/rpc/mute',
                            data={'username': self._group1.username})
        self.assertEquals(res.status_code, 200)
        self.assertGreater(res.json.get('mute_until'), get_usec_timestamp())

        res = self.jsonpost('/rpc/get_group',
                            data={'username': self._group1.username})
        self.assertEquals(res.status_code, 200)
        group_details = res.json
        self.assertEquals(group_details.get('user_id'), self._group1.user_id)
        self.assertTrue(group_details.get('is_muted'))

        group_admins = group_details.get('admins')
        self.assertEquals(len(group_admins), 1)

        res = self.jsonpost('/rpc/yo',
                            data={'username': self._group1.username},
                            jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200)
        yo_id = res.json.get('yo_id')

        # Process yo's
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Ensure the muted yo is marked as sent prior to hitting
        # _push_to_recipient.
        yo = get_yo_by_id(yo_id)
        self.assertTrue(yo.is_group_yo)
        self.assertEquals(yo.recipient_count, 3)
        yos = get_child_yos(yo)
        for child_yo in yos:
            self.assertIn(child_yo.status, ['sent', 'pending'])
            #self.assertTrue(child_yo.recipient == self._user1 \
            #                or child_yo.status == 'pending', child_yo.status)

        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yos = get_child_yos(yo)
        for child_yo in yos:
            self.assertIn(child_yo.status, ['sent', 'pending'])
            self.assertTrue(child_yo.recipient == self._user2 \
                            or child_yo.status == 'sent')

        res = self.jsonpost('/rpc/unmute',
                            data={'username': self._group1.username})
        self.assertEquals(res.status_code, 200)

        res = self.jsonpost('/rpc/get_group',
                            data={'username': self._group1.username})
        self.assertEquals(res.status_code, 200)
        group_details = res.json
        self.assertEquals(group_details.get('user_id'), self._group1.user_id)
        self.assertFalse(group_details.get('is_muted'))

        group_admins = group_details.get('admins')
        self.assertEquals(len(group_admins), 1)

        res = self.jsonpost('/rpc/yo',
                            data={'username': self._group1.username},
                            jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200)
        yo_id = res.json.get('yo_id')

        # Process yo's
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Ensure no yo is marked as sent prior to hitting
        # _push_to_recipient.
        yo = get_yo_by_id(yo_id)
        self.assertTrue(yo.is_group_yo)
        self.assertEquals(yo.recipient_count, 3)
        yos = get_child_yos(yo)
        #for child_yo in yos:
        #   self.assertEquals(child_yo.status, 'pending')

        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yos = get_child_yos(yo)
        for child_yo in yos:
            self.assertIn(child_yo.status, ['sent', 'pending'])
            self.assertTrue(child_yo.recipient == self._user2 \
                            or child_yo.status == 'sent')

    def test_04_pseudo_user(self):
        phone = '14411231234'
        res = self.jsonpost('/rpc/add_group_members',
                data={'members': [{'name': 'John Doe',
                                   'display_name': 'John D.',
                                   'phone_number': '+%s' % phone}],
                      'username': self._group1.username})
        self.assertEquals(res.status_code, 200)
        added = res.json.get('added')
        self.assertEquals(len(added), 1)
        self.assertEquals(added[0].get('username'), phone)
        self.assertEquals(added[0].get('display_name'), 'John Doe')


        res = self.jsonpost('/rpc/get_group',
                            data={'username': self._group1.username})
        self.assertEquals(res.status_code, 200)
        group_details = res.json
        self.assertEquals(group_details.get('user_id'), self._group1.user_id)

        admins = group_details.get('admins')
        members = group_details.get('members')
        self.assertEquals(len(admins), 1)
        self.assertEquals(len(members), 3)
        self.assertEquals(members[0].get('username'), phone)
        self.assertEquals(members[0].get('display_name'), 'John Doe')


        pseudo_user = get_user(username=phone)
        res = self.jsonpost('/rpc/yo',
                            data={'username': self._group1.username,
                                  'api_token': pseudo_user.api_token},
                            auth=False)
        self.assertEquals(res.status_code, 200)
        yo_id = res.json.get('yo_id')

        low_rq.create_worker(app=self.worker_app).work(burst=True)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yos = get_child_yos(yo_id)
        support_dict = NotificationEndpoint.perfect_payload_support_dict()
        payload = YoPayload(yos[0], support_dict)
        self.assertEquals(payload.get_base_yo_text(), 'from John Doe')

    def test_05_fix_old_group(self):
        # TODO: Mock the fix group function to make sure it was only called once.
        group = User(username='OLDGROUP', name='Old Group', parent=self._user1,
                       is_group=True, created=1434350930750435).save()
        Contact(owner=self._user1, target=group, is_group_admin=True).save()
        Contact(owner=self._user2, target=group).save()

        # Make the call twice to ensure upsert it isn't fixed twice.
        res = self.jsonpost('/rpc/get_group', data={'username': group.username})
        self.assertEquals(res.status_code, 200)
        res = self.jsonpost('/rpc/get_group', data={'username': group.username})
        self.assertEquals(res.status_code, 200)
        group_dict = res.json
        self.assertIsNotNone(group_dict)
        self.assertEquals(group_dict.get('username'), group.username)
        self.assertEquals(group_dict.get('type'), 'group')
        self.assertEquals(group_dict.get('user_id'), group.user_id)
        self.assertEquals(len(group_dict.get('admins')), 1)
        self.assertEquals(len(group_dict.get('members')), 1)
        self.assertEquals(group_dict.get('admins')[0].get('user_id'),
                          self._user1.user_id)
        self.assertEquals(group_dict.get('members')[0].get('user_id'),
                          self._user2.user_id)

        contact = get_contact_pair(group, self._user1)
        self.assertIsNotNone(contact)
        self.assertTrue(contact.is_group_admin)

        contact = get_contact_pair(self._user1, group)
        self.assertIsNotNone(contact)
        self.assertIsNone(contact.is_group_admin)

        contact = get_contact_pair(group, self._user2)
        self.assertIsNotNone(contact)
        self.assertIsNone(contact.is_group_admin)

        contact = get_contact_pair(self._user2, group)
        self.assertIsNotNone(contact)
        self.assertIsNone(contact.is_group_admin)

    def test_06_fix_old_group_yo(self):
        group = User(username='OLDGROUP', name='Old Group', parent=self._user1,
                     is_group=True, created=1434350930750435).save()
        Contact(owner=self._user1, target=group, is_group_admin=True).save()
        Contact(owner=self._user2, target=group).save()

        # Make the call twice to ensure upsert it isn't fixed twice.
        res = self.jsonpost('/rpc/yo', data={'username': group.username})
        self.assertEquals(res.status_code, 200)
        res = self.jsonpost('/rpc/yo', data={'username': group.username})
        self.assertEquals(res.status_code, 200)
        group_dict = res.json.get('recipient')
        self.assertIsNotNone(group_dict)
        self.assertEquals(group_dict.get('username'), group.username)
        self.assertEquals(group_dict.get('type'), 'group')
        self.assertEquals(group_dict.get('user_id'), group.user_id)

        contact = get_contact_pair(group, self._user1)
        self.assertIsNotNone(contact)
        self.assertTrue(contact.is_group_admin)

        contact = get_contact_pair(self._user1, group)
        self.assertIsNotNone(contact)
        self.assertIsNone(contact.is_group_admin)

        contact = get_contact_pair(group, self._user2)
        self.assertIsNotNone(contact)
        self.assertIsNone(contact.is_group_admin)

        contact = get_contact_pair(self._user2, group)
        self.assertIsNotNone(contact)
        self.assertIsNone(contact.is_group_admin)

        # Get the group and validate it has the right members.
        res = self.jsonpost('/rpc/get_group', data={'username': group.username})
        self.assertEquals(res.status_code, 200)
        group_dict = res.json
        self.assertIsNotNone(group_dict)
        self.assertEquals(group_dict.get('username'), group.username)
        self.assertEquals(group_dict.get('type'), 'group')
        self.assertEquals(group_dict.get('user_id'), group.user_id)
        self.assertEquals(len(group_dict.get('admins')), 1)
        self.assertEquals(len(group_dict.get('members')), 1)
        self.assertEquals(group_dict.get('admins')[0].get('user_id'),
                          self._user1.user_id)
        self.assertEquals(group_dict.get('members')[0].get('user_id'),
                          self._user2.user_id)

    def test_07_non_ascii_name(self):
        # Test that creating a group with proper information works.
        group_name = '__^__'
        group_data = {'name': group_name, 'members': []}
        res = self.jsonpost('/rpc/add_group', data=group_data)
        self.assertEquals(res.status_code, 201)
        group_dict = res.json.get('group')
        self.assertIsNotNone(group_dict)
        self.assertEquals(group_dict.get('name'), group_name)
        self.assertTrue(group_dict.get('username').startswith('GROUP'))

        group_name = u'å∂ƒøˆø˙'
        group_data = {'name': group_name, 'members': []}
        res = self.jsonpost('/rpc/add_group', data=group_data)
        self.assertEquals(res.status_code, 201)
        group_dict = res.json.get('group')
        self.assertIsNotNone(group_dict)
        self.assertEquals(group_dict.get('name'), group_name)
        self.assertTrue(group_dict.get('username').startswith('GROUP'))

    def test_08_group_response_pair(self):
        response_pair = 'dismiss.done'
        res = self.jsonpost('/rpc/yo',
                            data={'username': self._group1.username,
                                  'response_pair': response_pair},
                            jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200)
        yo_id = res.json.get('yo_id')

        # Process yo's
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yo = get_yo_by_id(yo_id)
        self.assertTrue(yo.is_group_yo)
        self.assertEquals(yo.recipient_count, 3)
        medium_rq.create_worker(app=self.worker_app).work(burst=True)
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        self.assertEquals(yo.get_flattened_yo().response_pair, response_pair)
        yos = get_child_yos(yo)
        support_dict = NotificationEndpoint.perfect_payload_support_dict()
        for child_yo in yos:
            flattened_yo = child_yo.get_flattened_yo()
            self.assertEquals(flattened_yo.response_pair, response_pair)
            payload = YoPayload(child_yo, support_dict)
            self.assertEquals(payload.category, response_pair)
