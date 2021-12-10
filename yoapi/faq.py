# -*- coding: utf-8 -*-

"""Yo FAQ operations package."""

from flask import current_app
from mongoengine import MultipleObjectsReturned, DoesNotExist

from .core import cache
from .errors import APIError
from .models import FAQ


def update_faq(faq_json):

    discarded = []
    upserted = []
    for i, item in enumerate(faq_json):
        app_id = item.get('app_id').strip()
        question = item.get('question').strip()
        answer = item.get('answer').strip()

        if not (app_id and question and answer):
            message = 'Tried to update with incomplete information: %s %s.'
            message = message % (question, answer)
            current_app.log_error(message)
            discarded.append(item)
            continue

        faq_item = get_faq_item(question.lower())
        if not faq_item:
            message = 'Tried to update %s but multiple objects were returned'
            message = message % question
            current_app.log_error(message)
            discarded.append(item)
            continue

        faq_item.rank = i
        faq_item.app_id = app_id
        faq_item.question = question
        faq_item.answer = answer
        faq_item.save()

        upserted.append(faq_item)

    deleted = FAQ.objects(id__nin=[str(f.id) for f in upserted])
    deleted_items = [(str(i.id), i.question, i.answer) for i in deleted]
    upserted = [(str(i.id), i.question, i.answer) for i in upserted]
    deleted.delete()
    clear_get_faq_items_cache()
    cache.delete_memoized(get_faq_items_for_app)

    return {'discarded': discarded,
            'deleted': deleted_items, 
            'upserted': upserted}


def clear_get_faq_items_cache():
    cache.delete_memoized(get_faq_items)


@cache.memoize()
def get_faq_items():
    return get_faq_items_for_app('co.justyo.yoapp')


@cache.memoize()
def get_faq_items_for_app(app_id):
    return list(FAQ.objects.filter(app_id=app_id).order_by('rank'))


def get_faq_item(question):
    try:
        item = FAQ.objects(question=question).get()
        return item
    except DoesNotExist:
        return FAQ()
    except MultipleObjectsReturned:
        return None
