import json

import re

from mongoengine import DoesNotExist
from yoapi.accounts import get_user
from yoapi.core import cache
from yoapi.errors import APIError
from yoapi.models import Header
from yoapi.models.region import Region
from yoapi.models.reengagement_push import ReengagementPush
import sys


def camel_case_to_snake_case(name):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def str_to_class(name):
    return getattr(getattr(sys.modules['yoapi.models'], camel_case_to_snake_case(name)), name)


def update_items(payload):
    try:
        class_name = payload.get('class_name')
        rows = payload.get('items')
        updated_rows = []
        for row in rows:
            row = row.copy()
            updated_rows.append(row)

            item_id = row.pop('id')
            is_new = False
            if item_id:
                try:
                    if item_id == 'undefined':
                        item = get_item_by_name(class_name, row['app_name'])
                    else:
                        item = get_item_by_id(class_name, item_id)
                except DoesNotExist:
                    row.update({'update_status': 'deleted'})
                    continue
                    #raise APIError('The item %s does not exist' % item_id)

                if row.get('delete'):
                    clear_get_item_cache(class_name, item_id)
                    item.delete()
                    row.update({'update_status': 'deleted'})
                    continue
            else:
                if row.get('delete'):
                    row.update({'update_status': 'skipped'})
                    continue
                try:
                    item_class = str_to_class(class_name)
                except Exception as e:
                    pass
                item = item_class()
                is_new = True

            if row.get('app_name') and row.get('username'):
                user = get_user(username=row.get('username'))
                user.app_name = row.get('app_name')
                user.save()

            for key in row.keys():

                if key == 'config':
                    try:
                        config_arr = json.loads(row[key])
                        setattr(item, key, config_arr)
                    except:
                        pass
                    continue

                value = row[key]

                if key == 'delete':
                    if value:
                        clear_get_item_cache(class_name, item_id)
                        item.delete()
                        row.update({'update_status': 'deleted'})
                        continue
                    else:
                        continue

                if getattr(item, key) != value:
                    if type(value) is str and ',' in value:
                        object_ids = value.split(',')
                        objects = []
                        for object_id in object_ids:
                            object = Header.objects.get(id=object_id)
                            objects.append(object)
                        value = objects

                    setattr(item, key, value)

            row.update({'update_status': 'nochange'})
            if is_new:
                row.update({'update_status': 'created'})
            elif item._changed_fields:
                row.update({'update_status': 'updated'})

            if is_new or item._changed_fields:
                item.save()
                clear_get_item_cache(class_name, item_id)

            row.update({'id': str(item.id)})

        return {'items': updated_rows}

    except Exception as e:
        raise e


def clear_get_item_cache(class_name, item_id):
    cache.delete_memoized(get_item_by_id, class_name, item_id)


#@cache.memoize()
def get_item_by_id(class_name, item_id):
    item_class = str_to_class(class_name)
    item = item_class.objects.get(id=item_id)
    return item

#@cache.memoize()
def get_item_by_name(class_name, app_name):
    item_class = str_to_class(class_name)
    item = item_class.objects.get(app_name=app_name)
    return item
