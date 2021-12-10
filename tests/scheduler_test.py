# -*- coding: utf-8 -*-
"""Tests the scheduler"""

import time

from yoapi.helpers import get_usec_timestamp
from yoapi.services import low_rq
from yoapi.services.scheduler import yo_scheduler, schedule_yo

from yoapi.yos.helpers import construct_yo

from . import BaseTestCase

TEST_SCHEDULED_DELAY = 5e6 # 5 seconds
JOB_TYPE = 'yo'


class SchedulerTestCase(BaseTestCase):

    def test_01_test_schedule_delay(self):
        res = self.jsonpost('/rpc/sign_up', auth=False,
                            data=self._ephemeral_account)
        self.assertEquals(res.status_code, 201, 'Expected 201 Created.')

        # Give the sign_up yo's time to propogate
        time.sleep(1)

        next_job_time = yo_scheduler.get_time_until_next_job()
        self.assertEquals(next_job_time[0], JOB_TYPE)
        self.assertEquals(next_job_time[1], 0,
                          'Expected sign_up to have created job')
        jobs = yo_scheduler.get_scheduled_jobs_by_type(JOB_TYPE)
        self.assertEquals(len(jobs), 2, 'Expected 2 job')

        yo_scheduler.execute_scheduled_items_now(JOB_TYPE)

        yo = construct_yo(sender=self._user1,
                          recipients=[self._user2],
                          ignore_permission=True)

        delay_until = get_usec_timestamp()
        delay_until += TEST_SCHEDULED_DELAY
        schedule_yo(yo, scheduled_for=delay_until)

        next_job_time = yo_scheduler.get_time_until_next_job()

        self.assertEquals(next_job_time[0], JOB_TYPE)
        self.assertGreater(next_job_time[1], 0,
                           'Expected next job to run in future')

        jobs = yo_scheduler.get_scheduled_jobs_by_type(JOB_TYPE)
        self.assertEquals(len(jobs), 0, 'Expected 0 jobs')

        time.sleep(TEST_SCHEDULED_DELAY/1e6)

        jobs = yo_scheduler.get_scheduled_jobs_by_type(JOB_TYPE)
        self.assertEquals(len(jobs), 1, 'Expected 1 job')

        yo_scheduler.execute_scheduled_items_now(JOB_TYPE)

        yo.reload()
        self.assertEquals(yo.status, 'started',
                          'Expected yo to have started')

        low_rq.create_worker(app=self.worker_app).work(burst=True)

        yo.reload()
        self.assertEquals(yo.status, 'sent',
                          'Expected yo to have sent')
