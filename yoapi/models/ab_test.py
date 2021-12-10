# -*- coding: utf-8 -*-

"""ABTest model"""


from bson import DBRef
from flask import current_app
from flask_mongoengine import Document
from mongoengine import (StringField, ListField, BooleanField,
                         DecimalField, IntField)

from planout.experiment import DefaultExperiment
from planout.ops.random import UniformChoice, BernoulliTrial

from .helpers import DocumentMixin, ReferenceField
from ..constants.context import ALLOWED_CONTEXT_IDS, DEFAULT_CONTEXTS

# TODO: Move this to constants.
VALID_TEST_DIMENSIONS = ['context', 'notification']

class ABTest(DocumentMixin, Document):
    """MongoDB ABTest model."""

    meta = {'collection': 'abtest',
            'indexes': [{'fields': ['title'], 'unique': True}],
            'auto_create_index': False}

    # The title for the test.
    title = StringField(required=True)

    # The dimesions being tested.
    dimensions = ListField(StringField(required=True,
                                       choices=VALID_TEST_DIMENSIONS),
                           required=True)

    # Is this enabled?
    enabled = BooleanField(required=True)

    # The context being tested.
    context = ListField(StringField(choices=ALLOWED_CONTEXT_IDS))
    context_position = ListField(IntField())
    default_context = ListField(StringField(choices=DEFAULT_CONTEXTS))

    # The Header being tested.
    header = ListField(ReferenceField('Header'))

    # What percentage of users will be exposed.
    exposure = DecimalField(required=True, min_value=0, max_value=1)

    # if enabled this will always be given to beta testers.
    debug = BooleanField()

    @property
    def test_id(self):
        return str(self.id) if self.id else None


class ABExperiment(DefaultExperiment):
    """Wrapper for the PlanOut Experiment"""

    def __init__(self, ab_test, **kwargs):
        """Set the ab_test on the instance without putting it
        in the inputs"""

        self.ab_test = ab_test
        super(ABExperiment, self).__init__(**kwargs)
        self.set_auto_exposure_logging(False)

    def setup(self):
        ab_test = self.ab_test
        self.name = ab_test.title
        self.salt = ab_test.title

    def previously_logged(self):
        """Assume we haven't logged this yet"""
        return False

    @classmethod
    def get_analytic_dict(cls, log_data):
        params = log_data.get('params')
        extras = log_data.get('extra_data')
        dimension = extras.get('dimension')
        analytic_dict = {'ab_test': log_data.get('name'),
                         'dimension': dimension,
                         'event': log_data.get('event'),
                         'user_id': log_data.get('inputs').get('user').user_id,
                         'default_context': params.get('default_context')}

        if dimension == 'context':
            analytic_dict.update({
                'context': params.get('context'),
                'context_position': params.get('context_position')})

        if dimension == 'notification':
            header = params.get('header')
            analytic_dict.update({'header': header.header_id,
                                  'yo_type': header.yo_type,
                                  'group_yo': header.group_yo})

        for key, val in analytic_dict.items():
            if val is None:
                analytic_dict.pop(key, None)

        return analytic_dict

    def log(self, data):
        analytic_dict = self.get_analytic_dict(data)
        current_app.log_analytics(analytic_dict)


    def assign(self, params, user):
        ab_test = self.ab_test

        if 'notification' in ab_test.dimensions:
            params.header = UniformChoice(choices=ab_test.header,
                                          unit=user.user_id)
        if 'context' in ab_test.dimensions:
            if ab_test.context:
                params.context = UniformChoice(choices=ab_test.context,
                                               unit=user.user_id)
            if ab_test.context_position:
                params.context_position = UniformChoice(unit=user.user_id,
                    choices=ab_test.context_position)

            default_context_choices = ab_test.default_context or []
            if ab_test.context:
                default_context_choices.append(params.context)
            if default_context_choices:
                params.default_context = UniformChoice(unit=user.user_id,
                    choices=default_context_choices)

        if ab_test.debug:
            if (user.is_beta_tester or
                (user.migrated_to and user.migrated_to.is_beta_tester)):
                params.in_experiment = True
            else:
                params.in_experiment = False
        else:
            params.in_experiment = BernoulliTrial(p=float(ab_test.exposure),
                                                  unit=user.user_id)
