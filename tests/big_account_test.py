# -*- coding: utf-8 -*-
"""Tests for speedy operations with big accounts."""

import time
import gevent

from . import BaseTestCase
from yoapi.models import User, Contact
from yoapi.accounts import clear_get_user_cache

ACCOUNT_COUNT = 1000


class BigAccountTestCase(BaseTestCase):

    """Test case for working with large accounts"""

    def setUp(self):
        # Spawn lots of API child accounts.
        super(BigAccountTestCase, self).setUp()
        children = []
        for i in xrange(0, ACCOUNT_COUNT):
            username = 'BIGACCOUNT_%s' % i
            user = User(username=username, parent=self._user1)
            children.append(user)
        User.objects.insert(children)
        self._user1.children = list(User.objects(parent=self._user1))

        # Spawn lots of friends.
        friends = []
        for i in xrange(0, ACCOUNT_COUNT):
            username = 'BIGACCOUNT_FRIEND_%s' % i
            user = User(username=username)
            friends.append(user)
        User.objects.insert(friends)
        friend_usernames = [friend.username for friend in friends]

        # Reload friends since it appears MongoEngine doesn't mark them
        # as inserted after bulk insert.
        friends = list(User.objects(username__in=friend_usernames))

        # Add these friends as contacts.
        contacts = []
        for friend in friends:
            contact = Contact(owner=self._user1, target=friend)
            contacts.append(contact)
        Contact.objects.insert(contacts)

        self._user1.save()
        clear_get_user_cache(self._user1)

    def test_01_list_many_children(self):
        """Make sure listing api accounts is a fast process"""
        start_time = time.time()
        res = self.jsonpost('/rpc/list_my_api_accounts')
        duration = time.time() - start_time
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')
        # Expect +1 api accounts since it includes parent account.
        self.assertEquals(len(res.json['accounts']), ACCOUNT_COUNT,
                          'Expected %s api accounts.' % ACCOUNT_COUNT)
        message = 'Lasted %s. Expected this call to last less than 3s.'
        message = message % duration
        self.assertLess(duration, 3, message)

    def test_02_get_contacts(self):
        """Make sure listing friends is a fast process"""
        start_time = time.time()
        res = self.jsonpost('/rpc/get_contacts')
        self.assertEquals(res.status_code, 200, 'Expected 200 OK')
        self.assertEquals(len(res.json['contacts']), ACCOUNT_COUNT,
                          'Expected %s friends.' % ACCOUNT_COUNT)
        self.assertLess(time.time() - start_time, 3,
                        'Expected this call to last less than 3s.')
