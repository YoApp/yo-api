# -*- coding: utf-8 -*-
"""A worker for Yo

Usage:
    worker.py [-h] [--burst] [--requeue_failed_jobs]
              [--pool_size POOL_SIZE] [--config CONFIG] --queue {high,low,medium}
"""

from gevent import monkey
monkey.patch_all()

import argparse
import os

# Disable log handler setup before importing rq related code.
import rq.logutils
rq.logutils.setup_loghandlers = lambda: None

from rq.worker import StopRequested

if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='worker.py', description='YoAPI worker')
    parser.add_argument('--burst',
                        action='store_true',
                        default=False,
                        dest='burst',
                        help='Work until queue empty.')
    parser.add_argument('--requeue_failed_jobs',
                        action='store_true',
                        default=False,
                        dest='requeue_failed_jobs',
                        help='Process failed jobs.')
    parser.add_argument('--pool-size',
                        default=10,
                        dest='pool_size',
                        type=int,
                        help='gevent pool size.')
    parser.add_argument('--config',
                        default='yoapi.config.Production',
                        dest='config',
                        help='Dotted module path of config class.')
    parser.add_argument('--queue',
                        dest='queue_name',
                        required=True,
                        help='A queue to process.')

    args = parser.parse_args()

    import newrelic.agent
    newrelic.agent.initialize('newrelic.ini', 'worker%s' % args.queue_name)

    from yoapi.factory import create_worker_app
    from yoapi.services import low_rq, high_rq, medium_rq

    RQ_MAP = {'low': low_rq,
              'high': high_rq,
              'medium': medium_rq}

    app = create_worker_app(name='worker', config=args.config)

    # We need an app context here to acquire configuration variables for all
    # extensions.
    with app.app_context():

        # This is just a string to RQ object mapping so we can use cli arguments
        # to make a selection.
        rq = RQ_MAP[args.queue_name]

        # Command line option to requeue all failed jobs.
        if args.requeue_failed_jobs:
            # Move all failed jobs back to the queue.
            failed_job_ids = rq.failed_queue.get_job_ids()
            for failed_job_id in failed_job_ids:
                job = rq.failed_queue.fetch_job(failed_job_id)
                rq.failed_queue.requeue(failed_job_id)
                app.logger.info({'message': 'Requeued job: ' + failed_job_id,
                                 'job': job.get_loggable_dict()})
        else:
            # Import new relic agent if we're running in production mode.
            worker = rq.create_worker(app=app, pool_size=args.pool_size)
            try:
                # Infinite loop unless burst is True.
                worker.work(burst=args.burst)
            except StopRequested:
                pass
