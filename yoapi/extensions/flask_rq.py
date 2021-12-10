# -*- coding: utf-8 -*-
"""RQ extension for Flask"""

import sys
import random
import traceback

import redis
import newrelic.agent


# Disable log handler setup before importing rq related code.
import rq.logutils
rq.logutils.setup_loghandlers = lambda: None

from collections import OrderedDict
from datetime import datetime, timedelta
from flask import current_app, g, request
from io import BytesIO
from rq import Queue
from rq_gevent_worker import GeventWorker
from rq.job import Job, _job_stack, Status
from rq.queue import FailedQueue
from rq.utils import utcnow

from . import FlaskExtension
from ..errors import APIError
from ..helpers import make_json_response

_redis_connections = {}

QUEUE_ADDED_CHANNEL = 'rq:queues:add'


def dump_environ(environ):
    """Turns a wsgi environment into an object that can be pickled

    We do not include HTTP_AUTHORIZATION in this list since we choose to
    authenticate differently on the worker.
    """
    # These keys should never be copied to the backend
    new_environ = {'wsgi.input': '', 'HTTP_AUTHORIZATION': '',
                   'HTTP_COOKIE': '', 'CONTENT_LENGTH': 0}
    for key, value in environ.items():
        if isinstance(value, basestring) and key not in new_environ:
            new_environ[key] = value
    return new_environ


def load_environ(environ):
    """Makes an unpickled wsgi environment compatible with wsgi frameworks"""
    environ = environ.copy()
    if 'wsgi.input' in environ:
        environ['wsgi.input'] = BytesIO(environ['wsgi.input'])
    if 'wsgi.errors' not in environ:
        environ['wsgi.errors'] = sys.stderr
    return environ


class YoJob(Job):

    """Subclassing RQ Job to customize behavior"""

    def get_loggable_dict(self):
        """Returns a dictionary for logging purposes"""
        rv = OrderedDict((('job_id', self.id),
                          ('queue_name', self.origin),
                          ('created_at', self.created_at),
                          ('enqueued_at', self.enqueued_at),
                          ('func', self.func.__name__),
                          ('args', self.args),
                          ('kwargs', self.kwargs)))
        if 'failures' in self.meta:
            rv['failures'] = self.meta['failures']
        return rv

    # Job execution
    def perform(self):  # noqa
        """Invokes the job function with the job arguments"""
        _job_stack.push(self.id)
        try:
            self.set_status(Status.STARTED)
            newrelic_decorated_func = newrelic.agent.background_task()(self.func)
            self._result = newrelic_decorated_func(*self.args, **self.kwargs)
            self.ended_at = utcnow()
            self.set_status(Status.FINISHED)
            # We process a pseudo response so latency etc gets recorded in the
            # logs.
            result = {}
            if self._result:
                result.update({'result': self._result})
            current_app.process_response(make_json_response(**result))
        finally:
            assert self.id == _job_stack.pop()

        return self._result


class YoQueue(Queue):

    """Subclassing RQ Job to customize behavior"""

    job_class = YoJob

    def enqueue_job(self, job, set_meta_data=True):
        """Override enqueue job to insert meta data without saving twice"""
        if request:
            request_environ = dump_environ(request.environ)
        else:
            request_environ = {}

        request_environ['REMOTE_USER'] = g.identity.user.user_id if g.identity.user else None
        job.meta['request_environ'] = request_environ

        # Add Queue key set
        added = self.connection.sadd(self.redis_queues_keys, self.key)

        # The rest of this function is copied from the RQ library.
        if set_meta_data:
            job.origin = self.name
            job.enqueued_at = utcnow()

        if job.timeout is None:
            job.timeout = self.DEFAULT_TIMEOUT
        job.save()

        if self._async:
            self.push_job_id(job.id)
        else:
            job.perform()
            job.save()

        return job


class YoFailedQueue(YoQueue, FailedQueue):

    """Subclassing RQ Failed Queue to customize behavior"""

    job_class = YoJob


class YoWorker(GeventWorker):

    """Subclassing RQ Job to customize behavior"""

    job_class = YoJob
    max_attempts = None
    queue_class = YoQueue
    _queues = None
    discard_on = (APIError, )

    def __init__(self, *args, **kwargs):
        if 'app' not in kwargs:
            raise Exception('Expected keyword-argument "app".')
        self.app = kwargs.pop('app')
        self.max_attempts = kwargs.pop('max_attempts')
        self._queues = {}
        super(YoWorker, self).__init__(*args, **kwargs)

    @property
    def queues(self):
        """Returns queues in random order while giving priority to the
        default queue by always returning it in the front"""
        queue_names = self.connection.smembers(Queue.redis_queues_keys)
        paused_queues = current_app.config.get('RQ_PAUSED_QUEUES')
        queue_names = [q for q in queue_names if q not in paused_queues]
        for queue_name in queue_names:
            if queue_name not in self._queues and not queue_name.endswith(
                    'failed'):
                queue = YoQueue.from_queue_key(
                    queue_name,
                    connection=self.connection)
                self._queues[queue_name] = queue

        prefix = self.queue_class.redis_queue_namespace_prefix
        default_queue_key = prefix + 'default'
        default_queue = self._queues[default_queue_key]

        queues_copy = [q for q in self._queues.values()
                       if q is not default_queue]
        random.shuffle(queues_copy)

        queues_copy.insert(0, default_queue)
        return queues_copy

    @queues.setter
    def queues(self, value):
        if isinstance(value, YoQueue):
            value = [value]
        if isinstance(value, list):
            for item in value:
                self._queues[item.key] = item

    def perform_job(self, job):
        with self.app.app_context():
            # Without this try catch statement we would not see any tracebacks
            # on errors raised outside of the queued function. In other words,
            # bugs in flask-rq inside of greenlets would fail silently.
            try:
                if job.meta.get('request_environ'):
                    # If a request environment is attached to the job then we simulate
                    # a real request environment.
                    request_context = current_app.request_context(
                        load_environ(job.meta['request_environ']))
                else:
                    # Otherwise we use a test_request_context.
                    request_context = current_app.test_request_context()

                with request_context:
                    current_app.preprocess_request()
                    # Set job attr on request so it can be logged in
                    # after_request.
                    setattr(request, 'job', job)
                    return super(YoWorker, self).perform_job(job)

            except Exception as err:
                self.app.log_exception(sys.exc_info(), job=job)
                return False

    def handle_exception(self, job, *exc_info):
        """Overrides handler for failed jobs

        When a job fails we retry a few more times before we let the job be moved
        to the failed queue.

        It's important to note that there is a default exception handler, and that
        this function forms part of a chain. If the default handler is reached,
        the job gets moved to the failed queue. When this function returns None or
        True, we move up the chain of handlers. If this function returns False
        then the chain execution is halted.

        As a result, we return False when a job has been retried the maximum
        number of times.
        """

        # If the job fails and we no longer want to retry then save job with
        # latest retry count and move it to the failed queue.
        exc_type, exc_value, tb = exc_info
        job.meta.setdefault('failures', 0)
        job.meta['failures'] += 1
        job.meta['exception'] = str(exc_value.message)

        # Format the traceback string.
        exc_string = ''.join(traceback.format_exception(*exc_info))

        # Compute conditions first to keep if statements clean.
        max_attempts_reached = job.meta['failures'] >= self.max_attempts
        discard_immediately = isinstance(exc_type, self.discard_on)
        too_old = job.created_at < datetime.now() - timedelta(seconds=60)

        if (discard_immediately):
            # There is no need to retry, just log the error.
            self.app.log_exception(exc_info, job=job)
        if (max_attempts_reached or too_old):
            # This is likely an important job, put it in the failed queue.
            self.app.log_exception(exc_info, job=job)
            self.failed_queue.quarantine(job, exc_info=exc_string)
        else:
            # Otherwise we mark the job as queued again and resubmit it to
            # the queue it came from.
            job.set_status(Status.QUEUED)
            queue_lookup = dict([(q.name, q) for q in self.queues])
            queue = queue_lookup.get(job.origin)
            if queue:
                queue.enqueue_job(job)
            else:
                self.app.logger.error({'message': 'Queue disappeared',
                                       'job': job.get_loggable_dict()})


class RQ(FlaskExtension):

    """A helper class for managing RQ connections

    We're using RQ over alternatives like Celery because the package has a very
    simple structure that allows us to both fully understand the worker
    process.
    """

    EXTENSION_NAME = 'rq'

    URL_CONFIG_KEY = 'RQ_%s_URL'
    TIMEOUT_CONFIG_KEY = 'RQ_%s_TIMEOUT'
    MAX_ATTEMPTS_CONFIG_KEY = 'RQ_%s_MAX_ATTEMPTS'

    def __init__(self, app=None, name='default'):
        # This allows us to specify multiple instances of this extension that
        # work against different redis instances.

        self._name = name
        super(RQ, self).__init__(app=app)

    def _create_instance(self, app):

        # Read configs at the time of creating an instance.
        default_timeout_key = self.TIMEOUT_CONFIG_KEY % self._name.upper()
        default_timeout = app.config.get(default_timeout_key)
        if not default_timeout:
            raise Exception('Timeout config not found: ' + default_timeout_key)

        redis_url_key = self.URL_CONFIG_KEY % self._name.upper()
        redis_url = app.config.get(redis_url_key)
        if not redis_url:
            raise Exception('Connection config not found: %s' % redis_url_key)

        max_attempts_key = self.MAX_ATTEMPTS_CONFIG_KEY % self._name.upper()
        max_attempts = app.config.get(max_attempts_key)
        if not max_attempts:
            raise Exception('Max attempts not found: %s' % max_attempts_key)

        return _RQ(self._name, redis_url, default_timeout, max_attempts)


class _RQ(object):

    _queue = None
    _failed_queue = None
    _name = None
    _timeout = None
    max_attempts = None
    result_ttl = 1800

    def __init__(self, name, redis_url, default_timeout, max_attempts):
        self._name = name
        self._redis_url = redis_url
        self._timeout = default_timeout
        self.max_attempts = max_attempts

    def clear_empty_queues(self):
        queues = self.get_all_queues()
        empty_queues = [queue for queue in queues if queue.is_empty()]
        for queue in empty_queues:
            if queue.name not in ['failed', 'default']:
                self.connection.delete(queue.key)
                self.connection.srem(queue.redis_queues_keys, queue.key)

    @property
    def connection(self):
        # Re-use connections if they are determined equivalent.
        if self._redis_url not in _redis_connections:
            _redis_connections[self._redis_url] = redis.from_url(
                self._redis_url)

        return _redis_connections[self._redis_url]

    @property
    def queue(self):
        if not self._queue:
            self._queue = YoQueue('default',
                                  connection=self.connection,
                                  default_timeout=self._timeout)
        return self._queue

    def get_queue(self, queue_name):
        queue = YoQueue(queue_name,
                        connection=self.connection,
                        default_timeout=self._timeout)
        return queue

    def get_all_queues(self):
        return YoQueue.all(self.connection)

    @property
    def failed_queue(self):
        if not self._failed_queue:
            self._failed_queue = YoFailedQueue(connection=self.connection)
        return self._failed_queue

    def create_worker(self, app=None, **kwargs):
        """Creates a gevent worker to consume a queue

        The app instance passed as an argument to this function will be used
        by the worker to simulate request contexts for the individual jobs,
        allowing us to re-use important functionality like logging.

        Note that the app name should be different from the frontend servers
        to easily distinguish backend messages from frotnend messages.

        Also note that we do not initialize the worker with a specific set
        of queues since it is itself responsible for discovering all
        queues on the given connection.
        """
        return YoWorker(self.queue, app=app, connection=self.connection,
                        max_attempts=self.max_attempts,
                        default_result_ttl=self.result_ttl, **kwargs)
