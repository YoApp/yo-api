# -*- coding: utf-8 -*-
"""Tests that planout is working as implemented"""

from functools import partial

from . import BaseTestCase

from yoapi import ab_test

from yoapi.accounts import update_user
from yoapi.models import ABExperiment, ABTest, Header, NotificationEndpoint
from yoapi.notification_endpoints import IOS
from yoapi.services import low_rq
from yoapi.constants.context import *

class ExperimentTestCase(BaseTestCase):

    def setUp(self):
        super(ExperimentTestCase, self).setUp()

        # Creae some experiments.
        self.tested_contexts = [AUDIO_CTX, GIPHY_CTX, EMOJI_CTX]
        context_ab_test = ABTest(dimensions=['context'],
                                 context=self.tested_contexts,
                                 default_context=[DEFAULT_CTX],
                                 exposure=1, enabled=True,
                                 title='test 1', context_position=[0]).save()

        debug_ab_test = ABTest(dimensions=['context'],
                               context=self.tested_contexts,
                               default_context=[DEFAULT_CTX],
                               exposure=1, enabled=True, debug=True,
                               title='debug test 1', context_position=[0]).save()

        header1 = Header(sms='Test default sms', push='Test default push',
                         ending='fin', yo_type='default_yo', group_yo=False,
                         is_default=False).save()

        header2 = Header(sms='Test default sms 2', push='Test default push 2',
                         ending='fin 2', yo_type='default_yo', group_yo=False,
                         is_default=False).save()

        self.tested_headers = [header1, header2]
        notification_ab_test = ABTest(dimensions=['notification'],
                                      header=self.tested_headers,
                                      exposure=1, enabled=True,
                                      title='test 2').save()
        self.context_ab_test = context_ab_test
        self.notification_ab_test = notification_ab_test

        self.experiment_logger_mock = self.experiment_logger_patcher.start()
        self.experiment_logger_mock.side_effect = self.experimentLogger
        self.analytic_logs = []

    def experimentLogger(self, data):
        self.analytic_logs.append(ABExperiment.get_analytic_dict(data))

    def test_01_get_contexts(self):
        # Test that one of the ab test contexts are added.
        res = self.jsonpost('/rpc/get_context_configuration')
        self.assertEquals(res.status_code, 200)

        contexts = res.json.get('contexts')
        default_context = res.json.get('default_context')
        self.assertIn(contexts[0], self.tested_contexts)
        self.assertIn(default_context, self.tested_contexts + [DEFAULT_CTX])
        self.assertEquals(self.experiment_logger_mock.call_count, 1)

        self.assertEquals(len(self.analytic_logs), 1)
        self.assertEquals(self.analytic_logs[0].get('event'),
                          'context_ab_test_enrolled')
        self.assertEquals(self.analytic_logs[0].get('user_id'),
                          self._user1.user_id)
        context_id = self.analytic_logs[0].get('context')
        self.assertIn(context_id, self.tested_contexts)

        experiment = ABExperiment(self.context_ab_test,
                                  user=self._user1)
        self.assertEquals(experiment.get('context'), context_id)

    def test_02_scoring_context(self):
        # Test that when sending a Yo from a given context it
        # is properly scored.

        experiment = ABExperiment(self.context_ab_test,
                                  user=self._user1)
        context_id = experiment.get('context')
        self.assertIn(context_id, self.tested_contexts)

        res = self.jsonpost('/rpc/yo',
                            data={'to': self._user2.username,
                                  'context_identifier': context_id})
        self.assertEquals(res.status_code, 200)

        # send yo.
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        self.assertEquals(self.experiment_logger_mock.call_count, 1)
        self.assertEquals(len(self.analytic_logs), 1)
        self.assertEquals(self.analytic_logs[0].get('event'),
                          'context_ab_test_score')
        self.assertEquals(self.analytic_logs[0].get('user_id'),
                          self._user1.user_id)
        self.assertEquals(context_id, self.analytic_logs[0].get('context'))

    def test_03_enroll_notification(self):
        # Test that when sending a Yo it will use the ab test header.

        # Give user1 a endpoint so that they can be enrolled.
        NotificationEndpoint(owner=self._user2, arn='test',
                             version='2.0.3', os_version='8.4',
                             platform=IOS, token='test',
                             installation_id='test').save()
        experiment = ABExperiment(self.notification_ab_test,
                                  user=self._user2)
        header = experiment.get('header')
        header_id = header.header_id
        self.assertIn(header, self.tested_headers)

        res = self.jsonpost('/rpc/yo', data={'to': self._user2.username})
        self.assertEquals(res.status_code, 200)

        # send yo.
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        self.assertEquals(self.experiment_logger_mock.call_count, 1)
        self.assertEquals(len(self.analytic_logs), 1)
        self.assertEquals(self.analytic_logs[0].get('event'),
                          'notification_ab_test_enrolled')
        self.assertEquals(self.analytic_logs[0].get('user_id'),
                          self._user2.user_id)
        self.assertEquals(header_id, self.analytic_logs[0].get('header'))

    def test_04_score_notification(self):
        # Test that when acknowledging a Yo that had a
        # custom header, it is scored.

        experiment = ABExperiment(self.notification_ab_test,
                                  user=self._user2)
        header = experiment.get('header')
        header_id = header.header_id
        self.assertIn(header, self.tested_headers)

        res = self.jsonpost('/rpc/yo', data={'to': self._user2.username})
        self.assertEquals(res.status_code, 200)
        yo_id = res.json.get('yo_id')

        # send yo.
        low_rq.create_worker(app=self.worker_app).work(burst=True)

        # Since the user does not have any endpoints they should
        # not have been enrolled.
        self.assertEquals(self.experiment_logger_mock.call_count, 0)
        self.assertEquals(len(self.analytic_logs), 0)

        # Acknowledge yo.
        res = self.jsonpost('/rpc/yo_ack', data={'yo_id': yo_id},
                            jwt_token=self._user2_jwt)
        self.assertEquals(res.status_code, 200)

        self.assertEquals(self.experiment_logger_mock.call_count, 1)
        self.assertEquals(len(self.analytic_logs), 1)
        self.assertEquals(self.analytic_logs[0].get('event'),
                          'notification_ab_test_score')
        self.assertEquals(self.analytic_logs[0].get('user_id'),
                          self._user2.user_id)
        self.assertEquals(header_id, self.analytic_logs[0].get('header'))

    def test_05_debug_mode(self):
        # test that when a test is in debug mode it doesn't apply
        # to non beta tester users.

        self.context_ab_test.enabled = False
        self.context_ab_test.save()
        ab_test.clear_get_ab_test_cache(self.context_ab_test.test_id)
        ab_test.clear_get_active_ab_tests_cache()

        res = self.jsonpost('/rpc/get_context_configuration')
        self.assertEquals(res.status_code, 200)

        contexts = res.json.get('contexts')
        for context in contexts:
            self.assertIn(context, DEFAULT_CONTEXTS)

        self.assertEquals(self.experiment_logger_mock.call_count, 0)
        self.assertEquals(len(self.analytic_logs), 0)

        update_user(self._user1, is_beta_tester=True, ignore_permission=True)

        res = self.jsonpost('/rpc/get_context_configuration')
        self.assertEquals(res.status_code, 200)

        contexts = res.json.get('contexts')
        default_context = res.json.get('default_context')
        self.assertIn(contexts[0], self.tested_contexts)
        self.assertIn(default_context, self.tested_contexts + [DEFAULT_CTX])

        self.assertEquals(self.experiment_logger_mock.call_count, 0)
        self.assertEquals(len(self.analytic_logs), 0)
