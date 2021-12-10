# -*- coding: utf-8 -*-

"""Yo A-B copy test operations package."""

import re

from flask import current_app
from mongoengine import MultipleObjectsReturned, DoesNotExist
from mongoengine.errors import ValidationError

from .core import cache
from .errors import APIError
from .models import ABTest, ABExperiment
from .constants.regex import DOUBLE_PERIOD_RE
from .constants.context import ALLOWED_CONTEXT_IDS, DEFAULT_CONTEXTS


def update_ab_tests(payload, header_map):
    items = []
    objects = []
    should_clear_active = False

    for item in payload:
        item = item.copy()
        items.append(item)

        debug = None
        test_id = item.get('id')
        enabled = item.get('enabled')
        if item.get('debug'):
            debug = True

        if test_id:
            try:
                test = get_ab_test_by_id(test_id)
            except DoesNotExist:
                raise APIError('The ab test %s does not exist' % test_id)

            changed = False
            if test.enabled and enabled is False:
                test.enabled = enabled
                changed = True

            if test.debug != debug:
                test.debug = debug
                changed = True

            if changed:
                test.save()
                clear_get_ab_test_cache(test_id)
                should_clear_active = True

                item.update({'update_result': 'upserted'})
            else:
                item.update({'update_result': 'nochange'})

            objects.append(test.to_dict())
            continue

        title = item.get('title')

        if enabled is None:
            enabled = True
        if enabled == False:
            item.update({'update_result': 'skipped'})
            continue


        dimensions = item.get('dimensions')
        dimensions = [d.strip() for d in dimensions if d.strip()]

        exposure_percent = item.get('exposure_percent')
        if exposure_percent:
            exposure_percent = float(exposure_percent)
        else:
            exposure_percent = 1

        contexts = None
        context_position  = None
        headers = None
        default_context = None

        test = ABTest(title=title, dimensions=dimensions, enabled=enabled,
                      exposure=exposure_percent)

        if 'notification' in dimensions:
            headers = item.get('notification')
            headers = [header_map.get(s.strip()) for s in headers
                       if s.strip()]

        if 'context' in dimensions:
            contexts = item.get('context')
            contexts = [c.strip() for c in contexts if c.strip()]
            for context in contexts:
                if context not in ALLOWED_CONTEXT_IDS:
                    raise APIError('Invalid context id %s' % context)

            context_position = item.get('context_position')
            if context_position:
                context_position = [int(p.strip()) for p in context_position
                                    if p.strip()]

            default_context = item.get('default_context')
            if default_context:
                for context in default_context:
                    if context not in DEFAULT_CONTEXTS:
                        raise APIError(('default_context must only contain '
                                        'location, justyo, or camera. '
                                        'Got %s') % context)

                default_context = [p.strip() for p in default_context
                                   if p.strip()]


        test.debug = debug
        test.header = headers or None
        test.context = contexts or None
        test.context_position = context_position or None
        test.default_context = default_context or None

        try:
            test = test.save()
        except ValidationError as err:
            message = 'Tried to update ab test with invalid information.'
            current_app.log_error({'message': message, 'payload': err.errors,
                                   'item': item})
            item.update({'update_result': 'discarded'})
            continue

        item.update({'id': str(test.id)})
        item.update({'update_result': 'upserted'})
        should_clear_active = True
        objects.append(test.to_dict())

    if should_clear_active:
        clear_get_active_ab_tests_cache()

    return {'items': items, 'should_clear_active': should_clear_active}


def clear_get_active_ab_tests_cache():
    cache.delete_memoized(_get_active_ab_tests)


def clear_get_ab_test_cache(test_id):
    cache.delete_memoized(get_ab_test_by_id, test_id)


@cache.memoize()
def get_ab_test_by_id(test_id):
    return ABTest.objects(id=test_id).get()


def get_active_ab_tests(dimension=None):
    tests = _get_active_ab_tests()
    tests = [get_ab_test_by_id(test.test_id) for test in tests]
    if dimension:
        tests = [test for test in tests
                 if dimension in test.dimensions]
    return tests


@cache.memoize()
def _get_active_ab_tests():
    tests = ABTest.objects(enabled=True).order_by('created').only('id')
    return list(tests)


def get_enrolled_experiments(user, dimension=None):
    experiments_enabled = current_app.config.get('AB_TESTS_ENABLED')
    if not experiments_enabled:
        return []

    if user.migrated_from:
        user = user.migrated_from

    active_tests = get_active_ab_tests(dimension)
    experiments = []
    for test in active_tests:
        experiment = ABExperiment(ab_test=test, user=user)
        if experiment.get('in_experiment'):
            experiments.append(experiment)

    return experiments

def log_ab_test_data(user, dimension, context_id=None, header=None):
    experiments = get_enrolled_experiments(user, dimension)
    if not experiments:
        return

    if dimension == 'context':
        for experiment in experiments:
            # Don't log experiments if they are for debugging.
            if experiment.ab_test.debug:
                continue

            assignments = experiment.get_params()
            exp_context = assignments.get('context')
            if exp_context == context_id:
                experiment.log_event('%s_ab_test_score' % dimension,
                                     extras={'dimension': dimension})
                break

    if dimension == 'notification':
        for experiment in experiments:
            # Don't log experiments if they are for debugging.
            if experiment.ab_test.debug:
                continue

            assignments = experiment.get_params()
            exp_header = assignments.get('header')
            if exp_header == header:
                experiment.log_event('%s_ab_test_score' % dimension,
                                     extras={'dimension': dimension})
                break
