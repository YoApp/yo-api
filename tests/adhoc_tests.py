# -*- coding: utf-8 -*-
"""Tests for various issues unrelated to any specific endpoint"""

import mock

from . import BaseTestCase
from bson import DBRef
from flask import request
from werkzeug.exceptions import ClientDisconnected
from yoapi.models import Contact, User, Yo, NotificationEndpoint
from yoapi.helpers import make_json_response
from yoapi.contacts import get_contact_objects, add_contact

from yoapi.models.helpers import ReferenceField


def dereferenceFromCache(document_type, dbref):
    return document_type(id='12345678901234567890abcd')

class AdHocTestCase(BaseTestCase):

    @classmethod
    def setup_class(cls):
        super(AdHocTestCase, cls).setup_class()

        @cls.app.route('/print_installation_id', login_required=False)
        def route_print_installation_id():
            return make_json_response(
                {'installation_id': request.installation_id})

        @cls.app.route('/disconnect', login_required=False)
        def route_disconnect():
            raise ClientDisconnected


    def test_client_disconnected(self):

        response = self.jsonpost('/disconnect', auth=False)
        self.assertEquals(response.status_code, 400)

        # This ensures that our error handler that handled the response. It
        # would otherwise be text/html.
        self.assertEquals('application/json', response.content_type)

    def test_update_field_on_models(self):

        # When saving an object that has only been saved once then the
        # updated field should be updated.
        self.assertIsNone(self._user1.updated, 'Expected null')
        self._user1.save()
        self.assertIsNotNone(self._user1.updated, 'Expected not null')

        # Test Yo model.
        yo = Yo(sender=self._user1)
        self.assertIsNone(yo.created, 'Expected null')
        self.assertIsNone(yo.updated, 'Expected null')
        yo.save()
        self.assertIsNotNone(yo.created, 'Expected not null')
        self.assertIsNone(yo.updated, 'Expected null')
        yo.save()
        self.assertIsNotNone(yo.updated, 'Expected not null')

        # Test Contact model.
        contact = Contact(owner=self._user1, target=self._user2)
        self.assertIsNone(contact.created, 'Expected null')
        self.assertIsNone(contact.updated, 'Expected null')
        contact.save()
        self.assertIsNotNone(contact.created, 'Expected not null')
        self.assertIsNone(contact.updated, 'Expected null')
        contact.save()
        self.assertIsNotNone(contact.updated, 'Expected not null')

        # Test NotificationEndpoint model.
        endpoint = NotificationEndpoint(arn='test', platform='test',
                                        token='test', installation_id='test')
        self.assertIsNone(endpoint.created, 'Expected null')
        self.assertIsNone(endpoint.updated, 'Expected null')
        endpoint.save()
        self.assertIsNotNone(endpoint.created, 'Expected not null')
        self.assertIsNone(endpoint.updated, 'Expected null')
        endpoint.save()
        self.assertIsNotNone(endpoint.updated, 'Expected not null')

    def test_installation_id_header(self):

        response = self.jsonpost('/print_installation_id')
        self.assertEquals(response.json.get('installation_id'),
                          self.installation_id)

        different_installation_id = 'differnt-string'
        headers = {'X-RPC-UDID': different_installation_id}
        response = self.jsonpost('/print_installation_id', headers=headers)
        self.assertEquals(response.json.get('installation_id'),
                          different_installation_id)

    def test_sns_callback(self):
        # Just test that the callback endpoint doesn't raise an error.
        response = self.jsonpost('/callback/sns')
        self.assertEquals(response.status_code, 200,
                          'Expected endpoint to work')

    def test_unpickling_old_documents(self):
        # Tests that when an old Object instance is unpickled it does
        # not change the _fields_ordered attr on the global type,
        # or contain old fields no longer defined on the global type
        user_instance = User()
        random_attr = 'new_field_name'
        self.assertNotIn(random_attr, User._fields_ordered)
        self.assertNotIn(random_attr, user_instance._fields_ordered)

        new_data = user_instance.__getstate__()
        new_data['_fields_ordered'] += (random_attr, )
        user_instance.__setstate__(new_data)

        self.assertNotIn(random_attr, User._fields_ordered)
        self.assertNotIn(random_attr, user_instance._fields_ordered)

    def test_display_names(self):
        # Test that names are properly converted.
        user = User(name='John Doe', username='TEST')
        self.assertEquals(user.display_name, 'John D.')

        user.first_name = 'Jon'
        user.last_name = 'Doe'
        self.assertEquals(user.display_name, 'Jon D.')

        user.first_name = 'Jon'
        user.last_name = None
        self.assertEquals(user.display_name, 'Jon')

        user.first_name = None
        user.last_name = 'Doe'
        self.assertEquals(user.display_name, 'Doe')

        user.last_name = None
        user.name = 'John Person Doe'
        self.assertEquals(user.display_name, 'John P.')

        user.name = None
        self.assertEquals(user.display_name, 'Test')

        user.name = 'JON DOE'
        self.assertEquals(user.display_name, 'Jon D.')

        user.name = None
        user.first_name = 'More than one'
        self.assertEquals(user.display_name, 'More T.')

        user.last_name = 'This one too'
        self.assertEquals(user.display_name, 'More T.')

        user.first_name = None
        self.assertEquals(user.display_name, 'This O.')

        user.first_name = 'Normal'
        user.last_name = '\U0001f43c' # a panda
        self.assertEquals(user.display_name, '%s %s' % ('Normal', '\U0001f43c'))

        user.first_name = ' TWB'
        user.last_name = '   '
        self.assertEquals(user.display_name, 'Twb')

        user.first_name = '  '
        user.last_name = ' Weird  '
        self.assertEquals(user.display_name, 'Weird')

        user.first_name = '  '
        user.last_name = '   '
        self.assertEquals(user.display_name, 'Test')

        user.first_name = None
        user.last_name = '   '
        self.assertEquals(user.display_name, 'Test')

        user.last_name = 'Name  Last'
        self.assertEquals(user.display_name, 'Name L.')

        user.first_name = 'Name  Last'
        user.last_name = 'Name  Last'
        self.assertEquals(user.display_name, 'Name N.')

    def test_full_names(self):
        # Test that names are properly converted.
        user = User(name='John Doe', username='TEST')
        self.assertEquals(user.full_name, 'John Doe')

        user.first_name = 'Jon'
        user.last_name = 'Doe'
        self.assertEquals(user.full_name, 'Jon Doe')

        user.first_name = 'Jon'
        user.last_name = None
        self.assertEquals(user.full_name, 'Jon')

        user.first_name = None
        user.last_name = 'Doe'
        self.assertEquals(user.full_name, 'Doe')

        user.last_name = None
        user.name = 'John Person Doe'
        self.assertEquals(user.full_name, 'John Person Doe')

        user.name = None
        self.assertEquals(user.full_name, None)

        user.name = 'JON DOE'
        self.assertEquals(user.full_name, 'JON DOE')

    def test_contact_user_caching(self):

        # Test that reference fields aren't cached with the main object.
        # Since reference fields are now dereferenced from cache, this
        # should really test that the actual object is pulled from cache
        # and not the database. However
        new_name = 'LOIJEO'
        old_name = 'IHOIH'

        dereference_patcher = mock.patch.object(ReferenceField,
                                                'dereference_from_cache')
        dereference_mock = dereference_patcher.start()

        dereference_mock.side_effect = dereferenceFromCache

        # Prepare some contact data.
        add_contact(self._user1, self._user2, ignore_permission=True)

        # NOTE: The contact below was not returned from cache because
        # the add_contact function cleared it.
        contact = get_contact_objects(self._user1)[0]
        self.assertEquals(contact.owner, self._user1)

        # Test that this is from cache by asserting 'owner' is a DBRef.
        contact2 = get_contact_objects(self._user1)[0]
        self.assertTrue(isinstance(contact2._data['owner'], DBRef))

        # By access the Contact 'owner' property it gets dereferenced.
        self.assertEquals(contact2.owner.name, None)
        self.assertEquals(str(contact2.owner.id), '12345678901234567890abcd')

        # Assert that the User was dereferenced from cache instead of
        # the database.
        self.assertEquals(dereference_mock.call_count, 1)
        self.assertTrue(isinstance(contact2._data['owner'], User))

        dereference_patcher.stop()
