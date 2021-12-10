# -*- coding: utf-8 -*-

"""Factories to create test fixtures"""

from uuid import uuid4
from yoapi.models import Contact, User

class UserFactory(object):

    user_counter = 0
    users = []
    username_pattern = 'TESTUSER%s'

    @classmethod
    def spawn_user(cls, **kwargs):
        user = User(**kwargs)
        if not user.username:
            user.username = cls.username_pattern % cls._counter
        if not user.email:
            user.email = user.username + '@test.justyo.co'
        cls.users.append(user)
        cls._counter += 1
        return user

    @classmethod
    def create_parent(cls, **kwargs):
        self.parent = parent = cls.spawn_user()
        parent.children = []
        parent.save()
        return parent

    @classmethod
    def create_contacts(cls, **kwargs):
        # Create some friends.
        users = []
        for i in range(0, user_count):
            user = cls.spawn_user()
            users.append(user)
        users = User.objects.insert(users)

        # Add contact records.
        contacts = []
        for user in users:
            contact = Contact(owner=user, target=parent)
            contacts.append(contact)
        contacts = Contact.objects.insert(contacts)
        return users

    @classmethod
    def create_api_accounts(cls, **kwargs):
        # Add tons of API accounts.
        api_accounts = []
        for i in range(0, 1000):
            api_account = cls.spawn_user()
            api_account.parent = parent
            api_account.api_token = str(uuid4())
            api_accounts.append(api_account)
            parent.children.append(api_account)
        self.api_accounts = User.objects.insert(api_accounts)
        return self.api_accounts
