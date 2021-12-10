# -*- coding: utf-8 -*-

"""Temporary library for transitioning to MongoDB"""

import re
import calendar
import csv
import phonenumbers

from phonenumbers.phonenumberutil import NumberParseException

from ..models import User, Contact, Device, NotificationEndpoint, Yo
from ..helpers import iso8601_to_usec

from ..constants.regex import USERNAME_REGEX

from ..yos.queries import clear_get_yo_cache

from bson import ObjectId
from csv import DictWriter
from datetime import datetime
from flask import json, current_app
from flask_mongoengine import get_db
from pprint import pformat
from zipfile import ZipFile

from mongoengine.errors import ValidationError
from pymongo.errors import BulkWriteError


# Disable this pylint long line messsage since this module is temporary.
# pylint: disable=line-too-long


def _load_json_data(filename):
    """All JSON data exported from Parse is collected under the `result` key

    We use prior knowledge of the format to efficiently iterate over the file
    and parse individual objects rather than the entire array at once.
    """
    if filename.endswith('.zip'):
        zf = ZipFile(filename)
        first_file = zf.namelist()[0]
        fin = zf.open(first_file)
    else:
        fin = open(filename)
    json_buffer = ''

    # An opened flag to indicate we've seen the beginning of an object. If
    # we observe the beginning of a new object before closing the last one
    # then an exception must be thrown.
    opened = 0
    array_opened = False
    document_opened = False
    json_buffer = ''
    while True:
        ch = fin.read(1)
        if not ch:
            break

        if ch != '[' and not array_opened:
            continue
        elif not array_opened:
            array_opened = True
            continue

        if ch != '{' and not document_opened:
            continue
        elif not document_opened:
            document_opened = True

        if ch == '{':
            opened += 1
        elif ch == '}':
            opened -= 1

        json_buffer += ch

        if opened == 0:
            yield json.loads(json_buffer.strip('\n'))
            json_buffer = ''
            document_opened = False
        elif opened < 0:
            print json_buffer
            raise ValueError('Cannot close a object that is not opened')


class Importer(object):

    """Base class for importing data to mongodb."""

    # Discarded items.
    discarded = []

    # The batch size for bulk writes.
    batch_size = 10000

    def __init__(self, filename=None):
        self.filename = filename
        self.database = get_db('default')
        self.collection = self.database[self.model._get_collection_name()]

    def bulk_merge(self, write_errors, item_keys=None):
        for write_error in write_errors:
            item = write_error['op']['u']['$set']
            try:
                object_criteria = dict(
                    [(key, item.pop(key)) for key in item_keys])
                db_item = self.model.objects(**object_criteria).get()
                for attr, value in item.items():
                    db_value = getattr(db_item, attr)
                    if not db_value:
                        setattr(db_item, attr, value)
                db_item.save()
            except Exception as err:
                print 'EXCEPTION %s' % write_error
                write_error['error_message'] = str(err)
                self.discarded.append(write_error)

    def bulk_upsert(self, items, item_keys=None):
        bulk_writer = self.collection.initialize_unordered_bulk_op()
        for item in items:
            upsert_key = {}
            for key in item_keys:
                upsert_key[key] = item.get(key)
            if 'updated' in item:
                upsert_key['$or'] = [
                    {'updated': {'$lte': item['updated']}},
                    {'updated': {'$exists': 0}}]
                upsert_key['api_token'] = {'$exists': 0}
            bulk_writer.find(upsert_key).upsert().update({'$set': item})
        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            current_app.logger.info(pformat(write_errors))
            if write_errors:
                self.bulk_merge(write_errors, ['username'])

    @property
    def data(self):
        return _load_json_data(self.filename)

    def dump_discarded(self):
        if not self.discarded:
            return
        fieldnames = set()
        for item in self.discarded:
            fieldnames.update(item.keys())
        writer = DictWriter(open(self.discarded_filename, 'w'),
                            fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()

        def enc(value):
            """Convenience function to encode strings"""
            if isinstance(value, basestring):
                return value.encode('utf-8')
            else:
                return value

        for item in self.discarded:
            writer.writerow(dict((k, enc(v)) for k, v in item.iteritems()))
        current_app.logger.info(
            'Discarded items: %s %s' %
            (len(self.discarded),
             self.discarded_filename))

    def run(self, *args, **kwargs):
        self._run(*args, **kwargs)
        self.dump_discarded()


class UserImporter(Importer):

    """Importer for Parse user accounts.

    We incorrectly find duplicates in the user data from Parse. Whenever a
    duplicate is discovered, we discard the record."""

    # The mongoengine data model, used for validation.
    model = User

    # The file where we want to write discarded items.
    discarded_filename = '/tmp/user_discarded.txt'

    def parse_item(self, item):
        """Transforms a dict into a mongoengine data model."""

        # Start with the username.
        username = item.get('username')

        # Do not include the placeholder @yo.com email addresses.
        email = item.get('email') or item.get('emailAddress')
        if email and email.endswith('@yo.com'):
            email = None

        # Lots of callbacks seem to be null strings that should be removed.
        callback = item.get('callback')
        if callback and len(callback.strip()) == 0:
            callback = None

        # Helper function to avoid storing boolean false in mongodb.
        def true_or_none(data, key):
            value = data.get(key)
            return True if value else None

        # Determine if udid is an api token or a device id.
        udid = item.get('udid')
        parent = item.get('parentUser') or \
            item.get('parent') or \
            item.get('parent_user')
        if udid and parent and parent != username:
            api_token = str(udid)
            device_ids = None
        elif udid:
            api_token = None
            device_ids = [str(udid)]
        else:
            api_token = None
            device_ids = None

        return self.model(
            api_token=api_token,
            callback=item.get('callback'),
            created=iso8601_to_usec(item.get('createdAt')),
            description=item.get('bio'),
            device_ids=device_ids,
            email=email,
            name=item.get('name'),
            parse_id=item.get('objectId'),
            password=item.get('bcryptPassword'),
            phone=item.get('phoneNumber'),
            photo=item.get('photo', {}).get('url'),
            request_location=true_or_none(item, 'needsLocation'),
            updated=iso8601_to_usec(item.get('updatedAt')),
            username=username,
            verified=true_or_none(item, 'isVerified'))

    def _run(self):

        # Item buffer for holding data temporarily until bulk inserted.
        item_buffer = []

        for i, item in enumerate(self.data):
            print '\r%s' % i,

            # Get a parsed MongoEngine data model instance representing the
            # parsed data.
            model_instance = self.parse_item(item)

            # If the parse function fails then it returns None so we continue
            if not model_instance:
                continue

            # Discard items that do not validate against the mongoengine
            # requirements. These items are put aside and later dumped
            # to disk.
            try:
                model_instance.validate()
            except ValidationError as err:
                # Store the model data before we nullify error fields in case
                # we are still unable to insert the object. That way we can
                # at least write it to disk and inspect afterwards.
                model_data = model_instance.to_dict()
                for field in err.errors.keys():
                    if field in model_instance:
                        model_instance[field] = None
                try:
                    model_instance.validate()
                    model_instance.migration_errors = json.dumps(
                        [(key, value.message) for key, value in err.errors.items()])
                except ValidationError as err:
                    self.discarded.append(model_data)
                    continue

            item_buffer.append(model_instance.to_dict())

            if len(item_buffer) == self.batch_size:
                self.bulk_upsert(item_buffer, item_keys=['username'])
                item_buffer = []

        # Insert the remainder.
        if item_buffer:
            self.bulk_upsert(item_buffer, item_keys=['username'])


class HierarchyImporter(Importer):

    """Updates parent/child relationships"""

    # The mongoengine data model, used for getting meta data about where we
    # update the relationships.
    model = User

    # Username to parent map.
    parent_map = {}

    # Username to child array map.
    child_map = {}

    # The file where we want to write discarded items.
    discarded_filename = '/tmp/contact_discarded.txt'

    def update_parent_relations(self):
        """Updates parent/child relationship in bulk."""
        affected_usernames = set(
            self.parent_map.keys() +
            self.parent_map.values())

        # Fetch _id and username of user documents.
        users = self.collection.find(
            {'username': {'$in': list(affected_usernames)}},
            {'_id': 1, 'username': 1})
        object_id_map = dict(
            [(user.get('username'), user.get('_id')) for user in users])
        items = []

        for username in object_id_map:
            item = {'username': username}
            # Lookup the parent object id
            parent = self.parent_map.get(username)
            if parent:
                parent_id = object_id_map.get(parent)
                if parent_id:
                    item['parent'] = parent_id
                else:
                    self.discarded.append(
                        {'username': username, 'parent': parent})

            # Create a list of child object id's
            children = self.child_map.get(username)
            if children:
                child_ids = []
                for child in children:
                    child_id = object_id_map.get(child)
                    if child_id:
                        child_ids.append(child_id)
                    else:
                        self.discarded.append(
                            {'username': username, 'child': child})
                if child_ids:
                    item['children'] = child_ids

            if len(item) == 1:
                continue
            items.append(item)

        if items:
            self.bulk_upsert(items, item_keys=['username'])

    def _run(self):

        for i, item in enumerate(self.data):
            print '\r%s' % i,

            username = item.get('username')

            parent = item.get('parentUser') or \
                item.get('parent') or \
                item.get('parent_user')

            # Remember the set of usernames that have a well-defined parent
            # account so we can update their child/parent relationships
            # once all accounts have been inserted and acquired mongo db
            # object ids.
            if (parent and parent != username and
                    re.match(USERNAME_REGEX, parent)):
                self.parent_map[username] = parent
                if not parent in self.child_map:
                    self.child_map[parent] = []
                self.child_map[parent].append(username)

        # Update the parent/child relationships.
        self.update_parent_relations()


class InstallationImporter(Importer):

    """Importer for Parse installations"""

    # Model to be used from mongo
    model = Device

    # Allowed device types
    device_types = ['ios', 'winphone']

    # The file where we want to write discarded items.
    discarded_filename = '/tmp/installation_discarded.txt'

    def bulk_insert(self, items):
        bulk_writer = self.collection.initialize_unordered_bulk_op()
        for item in items:
            bulk_writer.insert(item)
        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            print '%s write error(s)' % len(write_errors)

    def parse_item(self, item):
        """Transforms a dict into a mongoengine data model."""

        platform = item.get('deviceType')

        # Skip devices we can't migrate (I.E. Android)
        if platform not in self.device_types:
            return None

        if platform == 'winphone':
            token = item.get('deviceUris')
            if token:
                token = token.get('_Toast')
        else:
            token = item.get('deviceToken')

        if not token:
            return None

        channels = item.get('channels')
        username = [username for username in channels if username]
        owner = None
        if username:
            username = username[0]
            owner = self.object_id_map.get(username)

        return self.model(token=token,
                          owner=owner,
                          device_type=platform)

    def _load_cache(self):
        try:
            return json.loads(open('/tmp/objectid_map.txt').read())
        except:
            pass

    def _write_cache(self, obj):
        return open(
            '/tmp/objectid_map.txt', 'w').write(
            json.dumps(obj, indent=4))

    def _run(self):

        # Cache these records since it takes a while to query so many
        # records from mongodb.
        object_id_map = self._load_cache()
        if not object_id_map:
            user_collection = self.database[User._get_collection_name()]
            users = user_collection.find({},
                                         {'_id': 1, 'username': 1})
            object_id_map = dict(
                [(user.get('username'), str(user.get('_id'))) for user in users])
            self._write_cache(object_id_map)
        self.object_id_map = object_id_map

        # Item buffer for holding data temporarily until bulk inserted.
        item_buffer = []

        for i, item in enumerate(self.data):
            print '\r%s' % i,

            model_instance = self.parse_item(item)

            # Pass on empty instances
            if not model_instance:
                continue

            # Discard items that do not validate against the mongoengine
            # requirements. These items are put aside and later dumped
            # to disk.
            try:
                model_instance.validate()
            except ValidationError as err:
                model_data = model_instance.to_dict()
                self.discarded.append(model_data)
                continue

            item_buffer.append(model_instance.to_dict())

            if len(item_buffer) == self.batch_size:
                self.bulk_insert(item_buffer)
                item_buffer = []

        # Insert the remainder.
        if item_buffer:
            self.bulk_insert(item_buffer)
        print 'Done'


class ContactImporter(Importer):

    """Importer for Parse contacts"""

    # The mongoengine data model, used for validation.
    model = Contact

    # The file where we want to write discarded items.
    discarded_filename = '/tmp/contact_discarded.txt'

    def parse_item(self, item):
        """Transforms a dict into a mongoengine data model."""

        follower = item.get('follower')
        followee = item.get('followee')

        owner_id = self.object_id_map.get(follower)
        target_id = self.object_id_map.get(followee)

        if not (owner_id and target_id):
            self.discarded.append({'follower': follower, 'followee': followee})
            return None

        latest_yo = item.get('latestYo', {}).get('iso')
        if latest_yo:
            latest_yo = iso8601_to_usec(latest_yo)

        return self.model(
            owner=owner_id,
            target=target_id,
            last_yo=latest_yo)

    def _run(self):

        # Fetch _id and username of user documents.
        user_collection = self.database[User._get_collection_name()]
        users = user_collection.find({},
                                     {'_id': 1, 'username': 1})
        self.object_id_map = dict(
            [(user.get('username'), user.get('_id')) for user in users])

        # Item buffer for holding data temporarily until bulk inserted.
        item_buffer = []

        for i, item in enumerate(self.data):
            print '\r%s' % i,

            # Get a parsed MongoEngine data model instance representing the
            # parsed data.
            model_instance = self.parse_item(item)

            # If the parse function fails then it returns None so we continue
            if not model_instance:
                continue

            # Discard items that do not validate against the mongoengine
            # requirements. These items are put aside and later dumped
            # to disk.
            try:
                model_instance.validate()
            except ValidationError as err:
                # Store the model data before we nullify error fields in case
                # we are still unable to insert the object. That way we can
                # at least write it to disk and inspect afterwards.
                model_data = model_instance.to_dict()
                for field in err.errors.keys():
                    if field in model_instance:
                        model_instance[field] = None
                try:
                    model_instance.validate()
                    model_instance.migration_errors = json.dumps(
                        [(key, value.message) for key, value in err.errors.items()])
                except ValidationError as err:
                    self.discarded.append(model_data)
                    continue

            item_buffer.append(model_instance.to_dict())

            if len(item_buffer) == self.batch_size:
                self.bulk_upsert(item_buffer, item_keys=['owner', 'target'])
                item_buffer = []

        # Insert the remainder.
        if item_buffer:
            self.bulk_upsert(item_buffer, item_keys=['owner', 'target'])


class BlockedImporter(Importer):

    """Importer for Parse contacts"""

    # The mongoengine data model, used for validation.
    model = User

    # The file where we want to write discarded items.
    discarded_filename = '/tmp/blocker_discarded.txt'

    def parse_item(self, item):
        """Transforms a dict into a mongoengine data model."""

        blocker = item.get('blocker')
        blocked = item.get('blocked')

        blocker_id = self.object_id_map.get(blocker)
        blocked_id = self.object_id_map.get(blocked)

        return blocker_id, blocked_id

    def _load_cache(self):
        try:
            return json.loads(open('/tmp/objectid_map.txt').read())
        except:
            pass

    def _write_cache(self, obj):
        return open(
            '/tmp/objectid_map.txt', 'w').write(
            json.dumps(obj, indent=4))

    def _run(self):

        # Cache these records since it takes a while to query so many
        # records from mongodb.
        object_id_map = self._load_cache()
        if not object_id_map:
            users = self.collection.find({}, {'_id': 1, 'username': 1})
            object_id_map = dict(
                [(user.get('username'), str(user.get('_id'))) for user in users])
            self._write_cache(object_id_map)
        self.object_id_map = object_id_map

        # Item buffer for holding data temporarily until bulk inserted.
        item_buffer = {}

        for i, item in enumerate(self.data):
            print '\r%s' % i,

            # Get a parsed MongoEngine data model instance representing the
            # parsed data.
            blocker, blocked = self.parse_item(item)

            # If the parse function fails then it returns None so we continue
            if not (blocker and blocked):
                self.discarded.append(item)
                continue
            else:
                blocker = ObjectId(blocker)
                blocked = ObjectId(blocked)

            if blocker not in item_buffer:
                item_buffer[blocker] = [blocked]
            elif blocked not in item_buffer[blocker]:
                item_buffer[blocker].append(blocked)

        bulk_writer = self.collection.initialize_unordered_bulk_op()
        for blocker, blocked_set in item_buffer.items():
            print blocker, blocked_set
            bulk_writer.find(
                {'_id': blocker}).update(
                {'$pushAll': {'blocked': list(blocked_set)}})

        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            current_app.logger.info(pformat(write_errors))


class BitlyImporter(Importer):

    """Importer for Parse contacts"""

    # The mongoengine data model, used for validation.
    model = User

    # The file where we want to write discarded items.
    discarded_filename = '/tmp/bitly_discarded.txt'

    def parse_item(self, item):
        """Transforms a dict into a mongoengine data model."""

        token = item.get('bitlyToken')
        username = item.get('username')

        user_id = self.object_id_map.get(username)

        return user_id, token

    def _load_cache(self):
        try:
            return json.loads(open('/tmp/objectid_map.txt').read())
        except:
            pass

    def _write_cache(self, obj):
        return open(
            '/tmp/objectid_map.txt', 'w').write(
            json.dumps(obj, indent=4))

    def _run(self):

        # Cache these records since it takes a while to query so many
        # records from mongodb.
        object_id_map = self._load_cache()
        if not object_id_map:
            users = self.collection.find({}, {'_id': 1, 'username': 1})
            object_id_map = dict(
                [(user.get('username'), str(user.get('_id'))) for user in users])
            self._write_cache(object_id_map)
        self.object_id_map = object_id_map

        # Item buffer for holding data temporarily until bulk inserted.
        item_buffer = {}

        for i, item in enumerate(self.data):
            print '\r%s' % i,

            # Get a parsed MongoEngine data model instance representing the
            # parsed data.
            user_id, token = self.parse_item(item)

            # If the parse function fails then it returns None so we continue
            if not (user_id and token):
                self.discarded.append(item)
                continue
            else:
                user_id = ObjectId(user_id)

            if user_id not in item_buffer:
                item_buffer[user_id] = token
            else:
                self.discarded.append(item)
                continue

        bulk_writer = self.collection.initialize_unordered_bulk_op()
        for user_id, token in item_buffer.items():
            print user_id, token
            bulk_writer.find(
                {'_id': user_id}).update(
                {'$set': {'bitly': token}})
        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            current_app.logger.info(pformat(write_errors))


class WelcomeImporter(Importer):

    """Importer for Parse contacts"""

    # The mongoengine data model, used for validation.
    model = User

    # The file where we want to write discarded items.
    discarded_filename = '/tmp/welcome_discarded.txt'

    def parse_item(self, item):
        """Transforms a dict into a mongoengine data model."""

        link = item.get('link')
        username = item.get('username')

        user_id = self.object_id_map.get(username)

        return user_id, link

    def _load_cache(self):
        try:
            return json.loads(open('/tmp/objectid_map.txt').read())
        except:
            pass

    def _write_cache(self, obj):
        return open(
            '/tmp/objectid_map.txt', 'w').write(
            json.dumps(obj, indent=4))

    def _run(self):

        # Cache these records since it takes a while to query so many
        # records from mongodb.
        object_id_map = self._load_cache()
        if not object_id_map:
            users = self.collection.find({}, {'_id': 1, 'username': 1})
            object_id_map = dict(
                [(user.get('username'), str(user.get('_id'))) for user in users])
            self._write_cache(object_id_map)
        self.object_id_map = object_id_map

        # Item buffer for holding data temporarily until bulk inserted.
        item_buffer = {}

        for i, item in enumerate(self.data):
            print '\r%s' % i,

            print item

            # Get a parsed MongoEngine data model instance representing the
            # parsed data.
            user_id, link = self.parse_item(item)

            # If the parse function fails then it returns None so we continue
            if not (user_id and link):
                self.discarded.append(item)
                continue
            else:
                user_id = ObjectId(user_id)

            if user_id not in item_buffer:
                item_buffer[user_id] = link
            else:
                self.discarded.append(item)
                continue

        bulk_writer = self.collection.initialize_unordered_bulk_op()
        for user_id, link in item_buffer.items():
            print user_id, link
            bulk_writer.find(
                {'_id': user_id}).update(
                {'$set': {'welcome_link': link}})
        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            current_app.logger.info(pformat(write_errors))


class YoImporter(Importer):

    """Updates Yo counts for all users from the Yo table."""

    # The mongoengine data model, used for getting meta data about where we
    # update the relationships.
    model = User

    # Username to parent map.
    counts = {}

    # The file where we want to write discarded items.
    discarded_filename = '/tmp/yos_discarded.txt'

    def bulk_upsert(self, items, item_keys=None):
        bulk_writer = self.collection.initialize_unordered_bulk_op()
        for item in items:
            upsert_key = {}
            for key in item_keys:
                upsert_key[key] = item.get(key)
            bulk_writer.find(upsert_key).update({'$set': item})
        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            for write_error in write_errors:
                self.discarded.append(write_error)

    def update_yo_counts(self):
        """Updates parent/child relationship in bulk."""
        affected_usernames = self.counts.keys()

        # Fetch _id and username of user documents.
        users = self.collection.find(
            {'username': {'$in': list(affected_usernames)}},
            {'_id': 1, 'username': 1})
        object_id_map = dict(
            [(user.get('username'), user.get('_id')) for user in users])
        items = []

        for username, user_id in object_id_map.values():
            item = {'_id': user_id}
            item.update(self.counts.get(username, {}))
            if len(item) == 1:
                self.discarded.append(item)
            else:
                items.append(item)

        if items:
            self.bulk_upsert(items, item_keys=['_id'])

    def _run(self):

        for i, item in enumerate(self.data):
            print '\r%s' % i,

            sender = item.get('from')

            recipient = item.get('to')

            if re.match(r'^[A-Z][A-Z0-9]*$', sender):
                if sender not in self.counts:
                    self.counts[sender] = {'count_in': 0, 'count_out': 0}
                self.counts[sender]['count_out'] += 1

            if re.match(r'^[A-Z][A-Z0-9]*$', recipient):
                if recipient not in self.counts:
                    self.counts[recipient] = {'count_in': 0, 'count_out': 0}
                self.counts[recipient]['count_in'] += 1

        self.update_yo_counts()


class UdidImporter(Importer):

    """Updates parent/child relationships"""

    # The mongoengine data model, used for getting meta data about where we
    # update the relationships.
    model = User

    # Username to parent map.
    udid_map = {}

    # The file where we want to write discarded items.
    discarded_filename = '/tmp/udid_discarded.txt'

    def bulk_upsert(self, items, item_keys=None):
        bulk_writer = self.collection.initialize_unordered_bulk_op()
        for item in items:
            upsert_key = {}
            for key in item_keys:
                upsert_key[key] = item.get(key)
            if 'updated' in item:
                upsert_key['$or'] = [
                    {'updated': {'$lte': item['updated']}},
                    {'updated': {'$exists': 0}}]
                upsert_key['api_token'] = {'$exists': 0}
            bulk_writer.find(upsert_key).update({'$set': item})
        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            current_app.logger.info(pformat(write_errors))

    def update_udids(self):
        """Updates parent/child relationship in bulk."""
        affected_usernames = self.udid_map.keys()

        # Fetch _id and username of user documents.
        users = self.collection.find(
            {'username': {'$in': list(affected_usernames)}},
            {'_id': 1, 'username': 1})
        object_id_map = dict(
            [(user.get('username'), user.get('_id')) for user in users])
        items = []

        for username in object_id_map:
            item = {'username': username}
            # Lookup the parent object id
            udid = self.udid_map.get(username)
            if udid:
                item['api_token'] = udid
            else:
                self.discarded.append({'username': username, 'udid': udid})

            if len(item) == 1:
                continue
            items.append(item)

        if items:
            self.bulk_upsert(items, item_keys=['username'])

    def _run(self):

        for i, item in enumerate(self.data):
            print '\r%s' % i,

            username = item.get('username')
            if not re.match(r'^[A-Z][A-Z0-9]*$', username):
                continue

            udid = item.get('udid')
            if not udid:
                continue

            if not re.match(
                    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
                    udid):
                continue

            print i, username, udid
            self.udid_map[username] = udid

        # Update the parent/child relationships.
        self.update_udids()

class YoCollectionCleaner(Importer):

    model = Yo

    # Username to parent map.
    counts = {}

    # The file where we want to write discarded items.
    discarded_filename = '/tmp/yos_discarded.txt'

    def create_child_yos(self, yo_id, recipients):
        """Creates the child yos for yos with multiple recipients
           Each child yo is a placeholder to represent each individual yo
           received"""

        item_buffer = []
        for recipient in recipients:
            child_yo = Yo(parent=yo_id,
                          recipient=recipient,
                          status='sent')
            item_buffer.append(child_yo)
            if len(item_buffer) > 1000:
                Yo.objects.insert(item_buffer, load_bulk=False)
                item_buffer = []

        if item_buffer:
            Yo.objects.insert(item_buffer, load_bulk=False)

    def bulk_upsert(self, items, item_keys=None):
        bulk_writer = self.collection.initialize_unordered_bulk_op()
        for item in items:
            upsert_key = {}
            for key in item_keys:
                upsert_key[key] = item.get(key)
                item.pop('recipients', None)
                item.pop('children', None)
            bulk_writer.find(upsert_key).update({'$set': item,
                                                 '$unset':{'recipients':True},
                                                 '$unset':{'children':True}})
        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            for write_error in write_errors:
                self.discarded.append(write_error)

    def bulk_upsert_inc(self, items, item_keys=None):
        bulk_writer = self.database[User._get_collection_name()].initialize_unordered_bulk_op()
        for item in items:
            upsert_key = {}
            for key in item_keys:
                upsert_key[key] = item.pop(key)
            bulk_writer.find(upsert_key).update({'$inc': item})
        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            for write_error in write_errors:
                self.discarded.append(write_error)

    def update_yo_counts(self):
        """Updates parent/child relationship in bulk."""
        items = []
        for user_id, counts in self.counts.items():
            counts.update({'_id': user_id})
            items.append(counts)

            if len(items) > 1000:
                self.bulk_upsert_inc(items, item_keys=['_id'])
                items = []

        if items:
            self.bulk_upsert_inc(items, item_keys=['_id'])

    def _run(self):

        print 'Getting yos. This make take a while...'
        changes = []
        for i, yo in enumerate(self.data):
            print '\r%s' % i,

            created = int(yo.get('created').get('$numberLong'))
            yo['created'] = created

            if yo.get('updated'):
                updated = int(yo.get('updated').get('$numberLong'))
                yo['updated'] = updated
            recipients = yo.get('recipients', [])
            recipients = [ObjectId(r.get('$oid')) for r in recipients]
            yo['recipients'] = recipients
            sender = yo.get('sender')
            if sender:
                sender = sender.get('$oid')
                yo['sender'] = ObjectId(sender)

            recipient = yo.get('recipient')
            if recipient:
                recipient = recipient.get('$oid')
                yo['recipient'] = ObjectId(recipient)

            parent = yo.get('parent')
            if parent:
                parent = parent.get('$oid')
                yo['parent'] = parent

            yo_id = yo.get('_id').get('$oid')
            yo['_id'] = ObjectId(yo_id)
            if created > 1423269000000000:
                continue
            # Increment counts for non broadcasts
            if not yo.get('broadcast'):
                for recipient in recipients:
                    if recipient not in self.counts:
                        self.counts[recipient] = {'count_in': 0, 'count_out': 0}
                    self.counts[recipient]['count_in'] += 1

                if sender and recipient:
                    if recipient not in self.counts:
                        self.counts[recipient] = {'count_in': 0, 'count_out': 0}
                    self.counts[recipient]['count_in'] += 1

            # Increment counts for all senders if the yo is unparented
            if sender and not parent:
                if sender not in self.counts:
                    self.counts[sender] = {'count_in': 0, 'count_out': 0}
                self.counts[sender]['count_out'] += 1
            recipient_count = len(recipients)

            if yo.get('broadcast') or recipient_count > 1:
                if recipients:
                    self.create_child_yos(yo['_id'], recipients)
                yo['sent_count'] = recipient_count
                yo['recipient_count'] = recipient_count
                yo['recipients'] = None
                yo['children'] = None
                changes.append(yo)
            # Fix yos with 1 recipient
            elif recipient_count > 0:
                yo['sent_count'] = recipient_count
                yo['recipient_count'] = recipient_count
                yo['recipient'] = yo['recipients'][0]
                yo['recipients'] = None
                yo['children'] = None
                changes.append(yo)
            # Fix yos that have an empty recipients array
            else:
                if not parent or (sender and recipient):
                    yo['recipient_count'] = 0
                    yo['sent_count'] = 0
                    if recipient:
                        yo['recipient_count'] = 1
                        yo['sent_count'] = 1
                yo['recipients'] = None
                yo['children'] = None
                changes.append(yo)

            clear_get_yo_cache(yo['_id'])

            if len(changes) > 1000:
                self.bulk_upsert(changes, item_keys=['_id'])
                self.update_yo_counts()
                self.counts = {}
                changes = []

        if changes:
            self.bulk_upsert(changes, item_keys=['_id'])

        print '\nDone'

class DeviceIdCleaner(Importer):

    """Removes duplicate device id's"""

    model = User
    discarded_filename = '/tmp/user_device_ids_discarded.txt'

    def bulk_upsert(self, items, item_keys=None):
        bulk_writer = self.collection.initialize_unordered_bulk_op()
        for item in items:
            upsert_key = {}
            for key in item_keys:
                upsert_key[key] = item.pop(key)
            bulk_writer.find(upsert_key).update({'$set': item})
        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            for write_error in write_errors:
                self.discarded.append(write_error)

    def _run(self):
        changes = []
        changes_made = 0
        for i, user in enumerate(self.data):
            print '\r%s' % "{:,}".format(i),
            user_diff = {}
            ids = user.get('device_ids')
            user_diff['_id'] = ObjectId(user.get('_id').get('$oid'))

            if ids and len(ids) > 1:
                condensed_ids = list(set(ids))
                user_diff['device_ids'] = condensed_ids
                if len(condensed_ids) < len(ids):
                    changes.append(user_diff)
                    changes_made += 1
            if len(changes) > 1000:
                self.bulk_upsert(changes, item_keys=['_id'])
                changes = []
        if changes:
            self.bulk_upsert(changes, item_keys=['_id'])

        print "\nFinished with %s changes" % changes_made


class PhoneNumberCleaner(Importer):
    """Removes invalid phone numbers"""

    model = User
    discarded_filename = '/tmp/users_discarded.txt'

    def bulk_upsert(self, items, item_keys=None):
        bulk_writer = self.collection.initialize_unordered_bulk_op()
        for item in items:
            upsert_key = {}
            for key in item_keys:
                upsert_key[key] = item.pop(key)
            bulk_writer.find(upsert_key).update({'$unset':{'phone':True,
                                                        'verified':True}})
        try:
            bulk_writer.execute()
        except BulkWriteError as err:
            write_errors = err.details.get('writeErrors', {})
            for write_error in write_errors:
                self.discarded.append(write_error)

    def _run(self):
        changes = []
        changes_made = 0
        for i, user in enumerate(self.data):
            print '\r%s    %d changed' % ( "{:,}".format(i),
                                           changes_made),
            user_diff = {}
            phone = user.get('phone')
            if phone is None:
                continue
            user_diff['_id'] = ObjectId(user.get('_id').get('$oid'))

            try:
                phonenumbers.parse(phone)
            except NumberParseException:
                changes.append(user_diff)
                changes_made += 1
            if len(changes) > 1000:
                self.bulk_upsert(changes, item_keys=['_id'])
                changes = []
        if changes:
            self.bulk_upsert(changes, item_keys=['_id'])
