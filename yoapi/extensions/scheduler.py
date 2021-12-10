# -*- coding: utf-8 -*-

"""Scheduler module that can execute any type of job
as long as a handler is defined for the job type"""

import sys
import math

import gevent
from gevent.event import Event
from flask import json
from ..core import principals, redis
from ..helpers import get_usec_timestamp, make_json_response
from ..security import YoIdentity


class Scheduler(object):
    REDIS_CHAN = 'scheduler'
    DEFAULT_JOB_TYPE = 'job'
    DEFAULT_SLEEP = 3e10

    _redis_greenlet = None
    _schedule_greenlet = None

    # Grace period in microseconds.
    grace_period = 3e8

    # Store registered callbacks
    listen_rules = {}
    lock_key_rules = {}
    execute_rules = {}
    fail_rules = {}
    schedule_rules = {}
    execute_delay_rules = {}

    execute_headers = {'User-Agent': 'JobScheduler'}
    execute_path = '/scheduled_job'

    def __init__(self, schedule_key, grace_period=None, ignore_failures=False):
        self.wake_up = Event()
        if grace_period:
            self.grace_period = grace_period
        self.ignore_failures = ignore_failures
        self.schedule_key = schedule_key

    def init_app(self, app):
        self.app = app
        self.pubsub = redis.pubsub()

    def announce_new(self, job, job_type):
        """Register a WebSocket connection for Redis updates."""
        job_json_message = job.to_dict()
        if '_job_type' not in job_json_message:
            job_json_message.update({'_job_type': job_type})
        job_json_message = json.dumps(job_json_message)

        redis.publish(self.REDIS_CHAN, job_json_message)

    def get_scheduled_jobs_by_type(self, job_type):
        """Gets yos scheduled between grace period start and now"""
        if not self.can_handle_job(job_type):
            message = 'Can not handle job of type %s'
            raise NotImplementedError(message % job_type)

        return self.schedule_rules[job_type]()


    def get_all_scheduled_jobs(self, include_unhandled=False):
        """Gets yos scheduled between grace period start and now"""

        for job_type, schedule_rule in self.schedule_rules.items():
            if not (include_unhandled or self.can_handle_job(job_type)):
                continue

            jobs_ready = schedule_rule()
            if jobs_ready:
                yield job_type, jobs_ready


    def get_time_until_next_job(self):
        """Returns the number of microseconds until the next wakeup"""

        next_job_time = (None, self.DEFAULT_SLEEP)
        for job_type, execute_delay_rule in self.execute_delay_rules.items():
            if not self.can_handle_job(job_type):
                continue

            jobs = execute_delay_rule()
            next_job_time = self._get_minimum_delay(job_type, jobs,
                                                    next_job_time)
            if next_job_time[1] == 0:
                break

        return next_job_time


    def _get_minimum_delay(self, job_type, jobs, next_job_time):

        usec_now = get_usec_timestamp()
        for job in jobs:
            key = self.get_job_lock_key(job_type, job)
            if redis.get(key):
                continue

            schedule_time = job[self.schedule_key] - usec_now
            if schedule_time < 0:
                schedule_time = 0

            if schedule_time < next_job_time[1]:
                next_job_time = (job_type, schedule_time)

            if schedule_time == 0:
                break

        return next_job_time


    def can_handle_job(self, job_type):
        """Asserts the scheduler has the rules defined to
        execute this job"""
        if job_type not in self.execute_delay_rules:
            return False

        if job_type not in self.schedule_rules:
            return False

        if job_type not in self.execute_rules:
            return False

        # This should always go last so that it can return True
        # if failires are ignored
        if job_type not in self.fail_rules:
            return self.ignore_failures

        return True


    def should_wake_up(self, job_type, scheduled_for):
        """Asserts the scheduler can handle this type of job
        and the job is scheduled to run prior to the next wake time"""

        if scheduled_for > self.wake_time:
            return False

        return self.can_handle_job(job_type)


    def redis_loop(self):
        """Consume redis messages forever"""
        try:
            self.pubsub.subscribe(self.REDIS_CHAN)

            for message in self.pubsub.listen():
                if message['type'] == 'message':
                    # We assume at this point that any message sent to this
                    # channel means a new job has been added. Therefore we
                    # wake up the schedule_loop to refresh the sleep_time.
                    data = message.get('data')
                    message_json = json.loads(data)
                    job_type = message_json.get('_job_type',
                                                self.DEFAULT_JOB_TYPE)
                    scheduled_for = message_json.get('scheduled_for',
                                                     get_usec_timestamp())

                    if self.should_wake_up(job_type, scheduled_for):
                        self.wake_up.set()

                    if self.listen_rules and job_type in self.listen_rules:
                        self.listen_rules[job_type](message_json)
        except:
            with self._make_context():
                self.app.log_exception(sys.exc_info())


    def _make_context(self, path=None, headers=None):
        """Private function to get a request context. In the future
        a pattern needs to be defined to make this more public. Or,
        a global context needs to be applied perhaps to the greenlet"""

        if not path:
            path = self.execute_path
        if not headers:
            headers = self.execute_headers

        return self.app.test_request_context(path, headers=headers)


    def schedule_loop(self):
        """Wakes up every now and then and executes scheduled items."""
        try:
            while True:
                job_type, sleep_time_usec = self.get_time_until_next_job()
                # Sleep until next Yo or max 300 sec.
                sleep_time_sec = math.ceil(sleep_time_usec / 1e6) + 5
                self.wake_time = sleep_time_usec + get_usec_timestamp()

                announced_data = self.wake_up.wait(timeout=sleep_time_sec)
                if announced_data:
                    # If we wake up because a new Yo has been announced then
                    # we loop again before trying to send scheduled items.
                    self.wake_up.clear()

                elif job_type:
                    self.execute_scheduled_items_now(job_type)
        except:
            with self._make_context():
                self.app.log_exception(sys.exc_info())


    def execute_scheduled_items_now(self, job_type):
        """Execute items scheduled between grace period start and now"""

        jobs = self.get_scheduled_jobs_by_type(job_type)
        for job in jobs:
            key = self.get_job_lock_key(job_type, job)
            locked = redis.incr(key)
            if locked == 1:
                key_expire_sec = int(self.grace_period / 1e6) + 1
                redis.expire(key, key_expire_sec)
                with self._make_context():
                    try:
                        self.execute_rules[job_type](job)
                    except Exception:
                        # We assume the job can never
                        # sucessfully retry
                        if not self.ignore_failures:
                            self.fail_rules[job_type](job)
                            self.app.log_exception(sys.exc_info())
                    else:
                        self.app.process_response(make_json_response(**job.to_dict()))
                redis.delete(key)


    def get_job_lock_key(self, job_type, job):
        if job_type not in self.lock_key_rules:
            return 'scheduler_state_lock_%s' % str(job.id)

        return self.lock_key_rules[job_type](job)


    def become(self, user):
        """Impersates a user"""
        principals.set_identity(YoIdentity(str(user.id)))


    def get_scheduled_jobs_handler(self, job_type=None):
        if not job_type:
            job_type = self.DEFAULT_JOB_TYPE

        def _inner(func):
            self.schedule_rules[job_type] = func
            return func

        return _inner


    def get_execute_delay_handler(self, job_type=None):
        if not job_type:
            job_type = self.DEFAULT_JOB_TYPE

        def _inner(func):
            self.execute_delay_rules[job_type] = func
            return func

        return _inner


    def get_job_lock_key_handler(self, job_type=None):
        if not job_type:
            job_type = self.DEFAULT_JOB_TYPE

        def _inner(func):
            self.lock_key_rules[job_type] = func
            return func

        return _inner


    def new_job_handler(self, job_type=None):
        if not job_type:
            job_type = self.DEFAULT_JOB_TYPE

        def _inner(func):
            self.listen_rules[job_type] = func
            return func

        return _inner


    def execute_job_handler(self, job_type=None):
        if not job_type:
            job_type = self.DEFAULT_JOB_TYPE

        def _inner(func):
            self.execute_rules[job_type] = func
            return func

        return _inner


    def failed_job_handler(self, job_type=None):
        if not job_type:
            job_type = self.DEFAULT_JOB_TYPE

        def _inner(func):
            self.fail_rules[job_type] = func
            return func

        return _inner


    def start(self, burst=False, background=False):
        """Starts both the redis and schedule loops"""
        if burst:
            self.send_scheduled_items_now()
        else:
            self.start_redis_loop()
            self.start_schedule_loop()
            if not background:
                self._schedule_greenlet.join()


    def stop(self):
        self._redis_greenlet.kill()
        self._schedule_greenlet.kill()


    def start_redis_loop(self, dead_greenlet=None):
        """Starts the schedule loop"""
        self._redis_greenlet = gevent.spawn(self.redis_loop)
        self._redis_greenlet.link(self.start_redis_loop)


    def start_schedule_loop(self, dead_greenlet=None):
        """Starts the schedule loop"""
        self._schedule_greenlet = gevent.spawn(self.schedule_loop)
        self._schedule_greenlet.link(self.start_schedule_loop)


    def _handle_greenlet_error(self, func, greenlet=None):
        """Relaunched a greenlet and logs an exception if a greenlet dies
        from an error"""
        greenlet.start()
