# -*- coding: utf-8 -*-

"""Client response category module."""

from flask import current_app
from mongoengine import DoesNotExist

from .core import cache
from .models import ResponseCategory
from yoapi.errors import APIError


def update_categories(payload):
    items = []
    for item in payload:
        item = item.copy()
        items.append(item)

        category_id = item.get('id')
        is_new = False
        if category_id:
            try:
                category = get_category_by_id(category_id)
            except DoesNotExist:
                raise APIError('The category %s does not exist' % category_id)

            if item.get('delete'):
                clear_get_category_cache(category.yo_type,
                                         content=category.content)
                category.delete()
                item.update({'update_status': 'deleted'})
                continue
        else:
            if item.get('delete'):
                item.update({'update_status': 'skipped'})
                continue
            category = ResponseCategory()
            is_new = True

        content = None
        if item.get('content'):
            content = item.get('content').strip()
        left_text = item.get('left_text').strip()
        right_text = item.get('right_text').strip()
        yo_type = item.get('yo_type').strip()

        if category.content != content:
            category.content = content
        if category.left_text != left_text:
            category.left_text = left_text
        if category.right_text != right_text:
            category.right_text = right_text
        if category.yo_type != yo_type:
            category.yo_type = yo_type

        item.update({'update_status': 'nochange'})
        if is_new:
            item.update({'update_status': 'created'})
        elif category._changed_fields:
            item.update({'update_status': 'updated'})

        if is_new or category._changed_fields:
            category = category.save()
            item.update({'id': category.category_id})
            clear_get_category_cache(category.yo_type,
                                     content=category.content)

    return {'items': items}


def clear_get_category_cache(yo_type, content=None):
    cache.delete_memoized(get_category, str(yo_type), content=content)


def get_category_by_id(category_id):
    return ResponseCategory.objects(id=category_id).get()


@cache.memoize()
def get_category(yo_type, content=None):
    category = ResponseCategory.objects(yo_type=yo_type,
                                        content=content).get()
    return category.category
