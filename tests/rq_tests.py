# -*- coding: utf-8 -*-
"""Tests the background worker."""

import time

from flask import g, current_app, request
from yoapi.services import low_rq
from yoapi.async import async_job
from yoapi.extensions.flask_rq import dump_environ, load_environ
from yoapi.helpers import make_json_response
from yoapi.errors import APIError

from . import BaseTestCase

TEST_JOB_COUNT = 20
TEST_JOB_SLEEP_SECONDS = 1


@async_job(rq=low_rq)
def get_user_id(*args, **kwargs):
    time.sleep(TEST_JOB_SLEEP_SECONDS)
    return g.identity.user.user_id


@async_job(rq=low_rq)
def get_request_data(*args, **kwargs):
    return request.json

@async_job(rq=low_rq)
def raise_exception(*args, **kwargs):
    raise APIError('This is a test')


class RQTestCase(BaseTestCase):

    def test_01_confirm_empty_queue(self):
        # Test that default queue has the right name.
        self.assertEquals(low_rq.queue.name, 'default')

        # Test that queue is empty.
        self.assertTrue(low_rq.queue.is_empty(), 'Expected empty queue')

    def test_02_test_add_job(self):
        self.become(self._user1)

        # Enqueue a simple job.
        enqueued_job = low_rq.queue.enqueue(get_user_id)
        enqueued_job.meta['user_id'] = g.identity.user.user_id
        enqueued_job.save()

        # Make sure the queue is no longer empty.
        self.assertEquals(low_rq.queue.count, 1, 'Expected one job')

        dequeued_job = low_rq.queue.dequeue()

        # Make sure the right user_id is attached to job.
        self.assertEquals(enqueued_job.id, dequeued_job.id)

        # Test the job has the correct timeout set.
        self.assertEquals(dequeued_job.timeout, low_rq.queue._default_timeout)

        # Test the job has the correct timeout set.
        self.assertIn(get_user_id.__name__, dequeued_job.description)

    def test_03_process_job(self):
        self.become(self._user1)
        # Enqueue a range of jobs to test execution and parallelism.
        jobs = []
        for i in range(0, TEST_JOB_COUNT):
            with self.app.test_request_context('/test_request'):
                job = get_user_id.delay()
                jobs.append(job)

        # Create a worker.
        worker = low_rq.create_worker(app=self.worker_app, pool_size=10)

        # Work until queue is empty.
        start_time = time.time()
        worker.work(burst=True)

        # If the workers have been executing in parallel then time taken
        # is less then half the serial execution.
        max_time = (TEST_JOB_SLEEP_SECONDS * TEST_JOB_COUNT) / 2
        self.assertLess(time.time() - start_time, max_time,
                        'Jobs not processed in parallel')

        for job in jobs:
            self.assertEqual(job.result, self._user1.user_id,
                             'Expected %s' % self._user1.user_id)

    def test_04_test_exception_handler(self):
        """Test that worker thread exception handling works

        The most important thing is that we never lose a job. Either it
        succeeds or we retry the jobs periodically until they do so.
        """
        self.become(self._user1)
        # Enqueue a range of jobs to test execution and parallelism.
        with self.app.test_request_context('/test_request'):
            job = raise_exception.delay()

        # Create a worker.
        worker = low_rq.create_worker(app=self.worker_app)

        # Work until queue is empty.
        worker.work(burst=True)

        # Refresh job from backend to update exception info.
        job.refresh()

        self.assertIn('This is a test', job.exc_info)
        self.assertEqual(job.meta['failures'], low_rq.max_attempts,
                         'Expected %s failures' % low_rq.max_attempts)

        # Assert that job is in failed queue after failed retries.
        self.assertEqual(low_rq.failed_queue.count, 1,
                         'Expected one item in failed queue.')

        # Clear empty queues and verify that the failed item is still present.
        low_rq.clear_empty_queues()
        self.assertEqual(low_rq.failed_queue.count, 1,
                         'Expected one item in failed queue.')

        # Assert that job id is in failed queue.
        self.assertIn(job.id, low_rq.failed_queue.get_job_ids())

        # Requeue failed jobs.
        for job_id in low_rq.failed_queue.get_job_ids():
            low_rq.failed_queue.requeue(job_id)

        # Assert that job id is no longer in the failed queue.
        self.assertNotIn(job.id, low_rq.failed_queue.get_job_ids())

        # Assert that job id is now in the normal queue again.
        self.assertIn(job.id, low_rq.queue.get_job_ids())

    def test_05_worker_attributes(self):
        """Tests that the pool size is at least 50"""
        self.assertTrue(self.worker_app.is_worker(),
                        'Expected Flask app to be marked as a worker')
        pool_size = 100
        worker = low_rq.create_worker(self.worker_app, pool_size=pool_size)
        self.assertEquals(worker.gevent_pool.free_count(), pool_size)

    def test_06_function_reference(self):
        """Tests that a decorated function returns a copy"""

        def func(self):
            pass

        test_fn = async_job(rq=low_rq, custom_queue='test')(func)
        self.assertEquals(test_fn.custom_queue, 'test')

        default_fn = async_job(rq=low_rq)(func)
        self.assertEquals(default_fn.custom_queue, 'default')

        self.assertNotEquals(default_fn, test_fn)
        self.assertFalse(hasattr(func, 'delay'))
        self.assertFalse(hasattr(func, 'custom_queue'))

        self.assertTrue(hasattr(test_fn, 'delay'))
        self.assertTrue(hasattr(test_fn, 'custom_queue'))

        self.assertTrue(hasattr(default_fn, 'delay'))
        self.assertTrue(hasattr(default_fn, 'custom_queue'))

    def test_07_argument_parsing(self):
        """Tests that checking presence and absence of arguments
        in async functions works as expected"""

        self.become(self._user1)

        @async_job(rq=low_rq)
        def foo(a, b, c, d=None, *args, **kwargs):
            pass

        # Expected missing argument error.
        self.assertRaises(TypeError, foo.delay, 1, 2, d=3)

        # Expected multiple values for the same param error.
        self.assertRaises(TypeError, foo.delay, 1, 2, 3, 4, d=5)

        try:
            foo.delay(1, 2, 3, d=5)
            foo.delay(1, 2, 3, 4, 5, 6, e=7, t=8)
            foo.delay(1, 2, 3, 5)
            foo.delay(1, 2, 3)
        except TypeError as err:
            self.fail('Expected foo.delay not to throw an error')

        @async_job(rq=low_rq)
        def foo(a, b, c, d=None, **kwargs):
            pass

        # Expected missing argument error.
        self.assertRaises(TypeError, foo.delay, 1, 2, d=3)

        # Expected multiple values for the same param error.
        self.assertRaises(TypeError, foo.delay, 1, 2, 3, 4, d=5)

        # Expected too many args error.
        self.assertRaises(TypeError, foo.delay, 1, 2, 3, 4, 5, 6, e=7, t=8)

        try:
            foo.delay(1, 2, 3, d=5)
            foo.delay(1, 2, 3, d=4, e=7, t=8)
            foo.delay(1, 2, 3, 5)
            foo.delay(1, 2, 3)
        except TypeError:
            self.fail('Expected foo.delay not to throw an error')

        @async_job(rq=low_rq)
        def foo(a, b, c, d=None):
            pass

        # Expected missing argument error.
        self.assertRaises(TypeError, foo.delay, 1, 2, d=3)

        # Expected multiple values for the same param error.
        self.assertRaises(TypeError, foo.delay, 1, 2, 3, 4, d=5)

        # Expected too many args error.
        self.assertRaises(TypeError, foo.delay, 1, 2, 3, 4, 5, 6, e=7, t=8)

        # Expected too many args error.
        self.assertRaises(TypeError, foo.delay, 1, 2, 3, d=4, e=7, t=8)

        try:
            foo.delay(1, 2, 3, d=5)
            foo.delay(1, 2, 3, 5)
            foo.delay(1, 2, 3)
        except TypeError:
            self.fail('expected foo.delay not to throw an error')

        @async_job(rq=low_rq)
        def foo(a, b, c):
            pass

        # Expected missing argument error.
        self.assertRaises(TypeError, foo.delay, 1, 2, d=3)

        # Expected too many args error.
        self.assertRaises(TypeError, foo.delay, 1, 2, 3, d=4)
        self.assertRaises(TypeError, foo.delay, 1, 2, 3, 4)

        try:
            foo.delay(1, 2, 3)
        except TypeError:
            self.fail('expected foo.delay not to throw an error')

        @async_job(rq=low_rq)
        def foo(a=None, b=None):
            pass

        # Expected missing argument error.
        self.assertRaises(TypeError, foo.delay, 1, d=3)

        # Expected too many args error.
        self.assertRaises(TypeError, foo.delay, 3, a=1, d=4)

        # Expected multiple values for the same param error.
        self.assertRaises(TypeError, foo.delay, 3, a=1, b=4)
        self.assertRaises(TypeError, foo.delay, 3, a=1)

        try:
            foo.delay(1, 2)
            foo.delay(1, b=2)
            foo.delay(a=1, b=2)
        except TypeError:
            self.fail('expected foo.delay not to throw an error')
