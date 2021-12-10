# -*- coding: utf-8 -*-

"""Yo model"""


from bson import DBRef
from datetime import datetime

from flask_mongoengine import Document
from mongoengine import (BooleanField, StringField, LongField, ListField,
                         GeoPointField, PULL, DictField)

from .header import Header
from .helpers import URLField, DocumentMixin, ReferenceField
from .user import User
from .yo_token import YoToken
from ..constants.yos import STATUS_PRIORITY_MAP
from yoapi.models import oauth
from yoapi.models.region import Region


class Yo(DocumentMixin, Document):

    """MongoDB Yo model."""

    meta = {'collection': 'yo',
            'indexes': ['recipient',
                        {'fields': ['photo'], 'sparse': True},
                        {'fields': ['is_favorite'], 'sparse': True},
                        {'fields': ['scheduled_for'], 'sparse': True},
                        {'fields': ['reply_to'], 'sparse': True},
                        ('scheduled_for', 'status'),
                        ('sender', 'created'),
                        ('recipient', 'created'),
                        ('sender', 'recipient', 'created'),
                        ('recipient', 'sender', 'created')],
            'auto_create_index': False}

    not_on_yo = None

    # The user sending the Yo.
    sender = ReferenceField(User)

    # DEPRECATED: The users receiving the yos
    recipients = ListField(ReferenceField(User), default=None)

    # DEPRECATED: The child yos associated with this
    # This should only have been used with welcome links
    children = ListField(ReferenceField('self', reverse_delete_rule=PULL),
                         default=None)

    # The user receiving the yo
    recipient = ReferenceField(User, default=None)

    # If this Yo is a reply, this is the original Yo
    reply_to = ReferenceField('self', reverse_delete_rule=PULL, default=None)

    # The OAuth client used to sent this Yo, can be None if sent from our clients.
    oauth_client = ReferenceField(oauth.Client, default=None)

    # Recipient count.
    recipient_count = LongField()

    # Boolean indicator for group type.
    is_group_yo = BooleanField()

    # Boolean indicator if the yo was favorited.
    is_favorite = BooleanField()

    is_poll = BooleanField()

    is_push_only = BooleanField()

    duration_in_minutes = LongField()

    # Boolean indicator for broadcast type.
    broadcast = BooleanField()

    # Optional location from which Yo was sent.
    location = GeoPointField()

    # The city of which the location refers to.
    location_city = StringField()

    # Optional max 30 chars of text.
    text = StringField()

    # Optional max 30 chars of additional information.
    context = StringField()

    # Optional link to be opened on tapping left button. StringField because sms: link is a valid link
    left_link = StringField()

    # Optional link to be opened on tapping right button. StringField because sms: link is a valid link
    right_link = StringField()

    # Optional link attachment.
    link = URLField()

    # Optional link for thumbnail.
    thumbnail_url = URLField()

    # Optional photo.
    photo = ReferenceField('Image')

    # Optional cover image (Yo Byte).
    cover = ReferenceField('Image')

    # content type returned by a head request to the link
    link_content_type = StringField()

    # Optional parent Yo. This should be set by e.g. welcome links.
    parent = ReferenceField('self')

    # Optional origin Yo. This should be set by when forwarding a yo.
    origin_yo = ReferenceField('self')

    # Boolean indicator for location
    sent_location = BooleanField()

    # Recipient count.
    sent_count = LongField()

    # Optional link attachment.
    short_link = URLField()

    # Optional link attachment.
    sound = StringField()

    # String field to specify status
    status = StringField()

    # reference for what header to use for the payload
    header = ReferenceField(Header)

    # usec field indicating what time this yo is scheduled for
    scheduled_for = LongField()

    # denotes which schedule this belongs to
    schedule_name = StringField()

    # The token used to send this yo.
    yo_token = ReferenceField(YoToken, default=None)

    # For localized Yos
    region = ReferenceField(Region, default=None)

    # The context id this was sent from (provided by client).
    context_id = StringField()

    # The two available responses for the Yo in the format: "left.title" i.e "nope.yep"
    response_pair = StringField()

    question = StringField()

    left_replies_count = LongField()

    right_replies_count = LongField()

    left_share_template = StringField()

    right_share_template = StringField()

    left_reply = StringField()

    right_reply = StringField()

    user_info = DictField()

    app_id = StringField()

    # The two available responses for the Yo in the format: "left.title" i.e "nope.yep"
    sent_add_response_preflight_push = BooleanField()

    def __str__(self):
        return 'id=%s' % self.yo_id

    def save(self):
        if not self.created_date:
            self.created_date = datetime.now()
        return super(Yo, self).save()

    def has_children(self):
        return self.broadcast or self.is_group_yo or self.recipients and len(self.recipients) > 1

    def has_content(self):
        flattened_yo = self.get_flattened_yo()
        if flattened_yo.location:
            return True

        if flattened_yo.link:
            return True

        if flattened_yo.photo:
            return True

        if flattened_yo.cover:
            return True

        return False

    def should_trigger_response(self):
        # Never trigger a response when sending to multiple recipients
        if self.has_children():
            return False

        # If there is no recipient no need to go further
        if not self.recipient:
            return False

        # If there is a callback to be triggered no need to go further
        if self.recipient.callback:
            return False

        # Prevent possible callback loops
        if self.sender and self.sender == self.recipient:
            return False

        # Never trigger a callback if yo has a parent
        # This prevents broadcasts as well as welcome links
        if self.parent:
            return False

        # If the recipient is not in the store don't allow a response
        if not self.recipient.in_store:
            return False

        return True

    def should_trigger_callback(self):

        if self.reply_to:
            if self.reply_to.parent:
                return self.reply_to.parent.sender.callback or self.reply_to.parent.sender.callbacks
            else:
                return self.reply_to.sender.callback or self.reply_to.sender.callbacks

        # If there is no callback to be triggered no need to go further
        if not self.recipient:
            return False

        # If there is no callback to be triggered no need to go further
        if not self.recipient.callback:
            return False

        # Never trigger a callback during a broadcast
        if self.broadcast:
            return False

        # Prevent possible callback loops
        if self.sender and self.sender == self.recipient:
            return False

        if self.parent:
            # Never trigger a callback if yo has a parent
            # This prevents broadcasts as well as welcome links
            return False

        return True

    def should_trigger_oauth_callback(self):

        # Only perform callbacks for Yos that are replies to the originating oauth client
        if not self.reply_to:
            return False

        if not self.reply_to.oauth_client:
            return False

        # If there is no callback to be triggered no need to go further
        if self.reply_to.oauth_client and not self.reply_to.oauth_client.callback_url:
            return False

        # Prevent possible callback loops
        if self.sender and self.sender == self.recipient:
            return False

        if self.parent:
            # Never trigger a callback if yo has a parent
            # This prevents broadcasts as well as welcome links
            return False

        return True

    @property
    def yo_id(self):
        return str(self.id) if self.id else None

    @classmethod
    def priority_for_status(cls, status):
        return STATUS_PRIORITY_MAP.get(status, -1)

    @property
    def is_read(self):
        read_priority = self.priority_for_status('read')
        status_priority = self.priority_for_status(self.status)
        return status_priority >= read_priority

    @property
    def is_received(self):
        received_priority = self.priority_for_status('received')
        status_priority = self.priority_for_status(self.status)
        return status_priority >= received_priority

    def get_type(self):
        yo_type = ''

        flattened_yo = self.get_flattened_yo()

        if flattened_yo.link:
            yo_type = 'link'

        if flattened_yo.location:
            yo_type = 'location'

        if flattened_yo.photo:
            yo_type = 'photo'

        if (flattened_yo.link_content_type and
            flattened_yo.link_content_type.startswith('image')):
            yo_type = 'photo'

        return yo_type

    def get_flattened_yo(self):
        flattened_yo = FlattenedYo()

        flattened_yo.origin_yo_id = self.yo_id
        flattened_yo.origin_sender = None
        flattened_yo.location_str = None
        flattened_yo.parent_yo_id = None
        flattened_yo.group = None

        if self.recipient and self.recipient.is_group:
            flattened_yo.group = self.recipient

        # NOTE: mogoengine.Document iterators use the private field
        # _fields_ordered so that you don't need to worry about
        # callables and other private attrs
        for attr in self:
            setattr(flattened_yo, attr, getattr(self, attr))

        if self.parent and self.parent.has_children():
            flattened_yo.parent_yo_id = self.parent.yo_id
            if self.parent.recipient and self.parent.recipient.is_group:
                flattened_yo.group = self.parent.recipient

            # Only set values from the parent if they aren't already set
            # in the child
            if not flattened_yo.origin_yo:
                flattened_yo.origin_yo_id = self.parent.yo_id

            for attr in self.parent:
                if not getattr(flattened_yo, attr):
                    setattr(flattened_yo, attr, getattr(self.parent, attr))

        if flattened_yo.location:
            flattened_yo.location_str = '%s;%s' % (flattened_yo.location[0],
                                                   flattened_yo.location[1])

        if (flattened_yo.origin_yo and flattened_yo.origin_yo.parent and
            flattened_yo.origin_yo.parent.has_children()):
                flattened_yo.origin_yo = flattened_yo.origin_yo.parent

        if flattened_yo.origin_yo:
            flattened_yo.origin_yo_id = flattened_yo.origin_yo.yo_id
            flattened_yo.origin_sender = flattened_yo.origin_yo.sender

        flattened_yo.yo_id = self.yo_id
        flattened_yo.left_link = self.left_link
        flattened_yo.right_link = self.right_link

        # A link and photo should never exist at the same time
        # So overidding the link here should be fine.
        if flattened_yo.photo:
            flattened_yo.link = flattened_yo.photo.make_full_url()
            flattened_yo.short_link = flattened_yo.photo.short_link

        return flattened_yo

    def get_flattened_dict(self):
        flattened_yo = self.get_flattened_yo()

        origin_sender = None
        if flattened_yo.origin_sender:
            origin_sender = flattened_yo.origin_sender.username

        recipient = None
        if flattened_yo.recipient:
            recipient = flattened_yo.recipient.username

        cover = None
        if flattened_yo.cover:
            cover = flattened_yo.cover.make_full_url()

        flattened_dict = {
            'broadcast': flattened_yo.broadcast,
            'cover': cover,
            'created_at': flattened_yo.created,
            'is_favorite': bool(flattened_yo.is_favorite),
            'is_group_yo': bool(flattened_yo.is_group_yo),
            'is_read': self.is_read,
            'is_received': self.is_received,
            'link': flattened_yo.link,
            'location': flattened_yo.location_str,
            'origin_sender': origin_sender,
            'origin_yo_id': flattened_yo.origin_yo_id,
            'recipient': recipient,
            'recipient_count': flattened_yo.recipient_count,
            'sender': flattened_yo.sender.username,
            'short_link': flattened_yo.short_link,
            'status': flattened_yo.status,
            'yo_id': flattened_yo.yo_id}

        return flattened_dict

    def get_sender(self, safe=False):
        """Get the sender from the parent if needed.
        params:
            safe - Returns a new yoapi.models.User instead of None
        """

        sender = self.sender
        if sender:
            return sender

        parent = self.parent
        if parent:
            sender = parent.sender

        if safe and not sender:
            sender = User()

        return sender

    def get_friend(self, user, safe=False):
        """Get the user whom sent or received this Yo that is not
        the supplied user.
        params:
            user - a valid yoapi.models.User object
            safe - Returns a new yoapi.models.User instead of None
        """

        sender = self.get_sender()
        recipient = self.recipient

        if user == sender:
            friend = recipient
        elif user == recipient:
            friend = sender
        else:
            friend = None

        if safe and isinstance(self.sender, (None.__class__, DBRef)):
            if isinstance(friend, DBRef):
                friend = User(id=friend.value)
            else:
                friend = User()

        return friend

    def get_status_dict(self, user=None):
        flattened_yo = self.get_flattened_yo()
        original_status = flattened_yo.status

        # If the yo has content dismissed means they truly didn't read it.
        if self.has_content() and original_status == 'dismissed':
            original_status = 'received'

        # If a yo does not have content as long as it was dismissed it was
        # still read.
        status_map = {'received': 'delivered',
                      'dismissed': 'read',
                      'read': 'read',
                      'pending': 'sent',
                      'sent': 'sent'}
        # It is safest to assume any other status as sent.
        status = status_map.get(original_status, 'sent')

        # If the current yo was sent by someone other than the specified user
        # mark it as delivered.
        status = status if flattened_yo.sender == user else 'received'

        # The username to be returned is the opposite of the specified user.
        if user != flattened_yo.sender:
            username = flattened_yo.sender.username
            user_id = flattened_yo.sender.user_id
        elif flattened_yo.recipient:
            username = flattened_yo.recipient.username
            user_id = flattened_yo.recipient.user_id
        else:
            # This should only happen with legacy group yos.
            return None

        status_dict =  {
            'status': status,
            'original_status': flattened_yo.status,
            'username': username,
            'user_id': user_id,
            'yo_id': flattened_yo.yo_id,
            'type': self.get_type(),
            'time': flattened_yo.updated or flattened_yo.created
        }

        parent = flattened_yo.parent if flattened_yo.parent else flattened_yo
        group = parent.recipient
        if flattened_yo.is_group_yo and group and group.is_group:
            status_dict.update({'group_username': group.username,
                                'group_user_id': group.user_id})

        return status_dict

    def has_dbrefs(self):
        """Checks if there are any users that could not be
        dereferenced"""

        if isinstance(self, DBRef):
            return True

        if isinstance(self.sender, DBRef):
            return True

        if isinstance(self.recipient, DBRef):
            return True

        if isinstance(self.parent, DBRef):
            return True

        if self.parent and isinstance(self.parent.sender, DBRef):
            return True

        if self.parent and isinstance(self.parent.recipient, DBRef):
            return True

        return False


class FlattenedYo(object):
    """Psuedo class used when flattening a yo"""
    pass
