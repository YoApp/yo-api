# -*- coding: utf-8 -*-

"""Contact model"""


from bson import DBRef
from flask_mongoengine import Document
from mongoengine import BooleanField, LongField, CASCADE, StringField

from .helpers import DocumentMixin, ReferenceField
from .user import User
from .yo import Yo


class Contact(DocumentMixin, Document):

    """MongoDB user follower model"""

    meta = {'collection': 'contact',
            'indexes': ['owner', 'target'],
            'auto_create_index': False}

    # The contact owner.
    owner = ReferenceField(User, unique_with='target',
                           reverse_delete_rule=CASCADE,
                           required=True)

    # Is the contact hidden from the client.
    hidden = BooleanField()

    # The contact target.
    target = ReferenceField(User, reverse_delete_rule=CASCADE,
                            required=True)

    # Store username in contact for fast response on get_contacts_status
    target_username = StringField()

    # 'sent'/'received'/'delivered'/'opened'
    last_yo_state = StringField()

    # Field used for sorting contacts in the order they were last contacted.
    last_yo = LongField()

    # Field used to reference the last yo between the two users.
    last_yo_object = ReferenceField(Yo)

    # group admin indicator.
    is_group_admin = BooleanField()

    is_status_push_disabled = BooleanField()

    # Name choosen by the contact owner.
    contact_name = StringField()

    # Time when mute ends.
    mute_until = LongField()

    # Did send confirmation push on polls ("are you still interested in receving these polls?")
    did_send_confirmation_push = BooleanField()

    def get_name(self):
        '''Return contact_name or display_name.'''
        return self.contact_name or self.target.display_name

    def has_dbrefs(self):
        """Checks if there are any users that could not be
        dereferenced.
        NOTE: last_yo_object is not checked since yo's will
        likely never be deleted"""
        if isinstance(self.owner, DBRef):
            return True

        if isinstance(self.target, DBRef):
            return True

        return False

    def __str__(self):
        return "%s:%s" % (self.owner, self.target)
