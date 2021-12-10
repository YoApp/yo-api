# -*- coding: utf-8 -*-

"""Implementation of the Scheduler interface. This implementation only
supports sending yos"""

# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name

# Scheduled task manager
import sys

from flask import current_app
from ..extensions.scheduler import Scheduler
from yoapi.contacts import get_contact_usernames, get_subscriptions
from ..yos.helpers import construct_auto_follow_yo, construct_first_yo, construct_yo
from ..yos.queries import clear_get_yo_cache
from ..helpers import get_usec_timestamp, make_json_response
from ..models import Yo, Header


GRACE_PERIOD = 3e8
YO_JOB_TYPE = 'yo'

yo_scheduler = Scheduler('scheduled_for', grace_period=GRACE_PERIOD)


@yo_scheduler.execute_job_handler(job_type=YO_JOB_TYPE)
def send_scheduled_yo(yo):
    """Send a scheduled yo"""
    from ..yos.send import _send_yo

    yo.status = 'started'
    yo.save()
    clear_get_yo_cache(yo.yo_id)

    if yo.header and str(yo.header.id) == '55c1035f6461740061000027':

        if len(get_contact_usernames(yo.recipient)) + len(get_subscriptions(yo.recipient)) == 0:

            yo_scheduler.become(yo.sender)
            _send_yo.delay(yo_id=yo.yo_id)

        else:
            pass

    else:
        yo_scheduler.become(yo.sender)
        _send_yo.delay(yo_id=yo.yo_id)


@yo_scheduler.get_scheduled_jobs_handler(job_type=YO_JOB_TYPE)
def get_scheduled_jobs():
    """Gets yos scheduled between grace period start and now"""
    schedule_name = yo_scheduler.app.config.get('SCHEDULE_NAME')
    usec_now = get_usec_timestamp()
    cutoff_usec = usec_now - GRACE_PERIOD
    query = Yo.objects(scheduled_for__exists=True,
                       scheduled_for__lte=usec_now,
                       scheduled_for__gte=cutoff_usec,
                       schedule_name=schedule_name,
                       status='scheduled')
    return query.order_by('scheduled_for')


@yo_scheduler.get_execute_delay_handler(job_type=YO_JOB_TYPE)
def get_time_until_next_jobs():
    """Returns the number of microseconds until next Yo"""
    schedule_name = yo_scheduler.app.config.get('SCHEDULE_NAME')
    usec_now = get_usec_timestamp()
    cutoff_usec = usec_now - GRACE_PERIOD
    query = Yo.objects(scheduled_for__exists=True,
                       scheduled_for__gte=cutoff_usec,
                       schedule_name=schedule_name,
                       status='scheduled')
    return query.order_by('scheduled_for')


@yo_scheduler.failed_job_handler(job_type=YO_JOB_TYPE)
def handle_failed_job(yo):
    yo.status='failed'
    yo.save()
    clear_get_yo_cache(yo.yo_id)


@yo_scheduler.new_job_handler(job_type=YO_JOB_TYPE)
def handle_new_scheduled_yo(yo):
    """log new yos as they are announced"""

    with yo_scheduler._make_context():
        yo_scheduler.app.process_response(
            make_json_response(**yo))


def schedule_yo(yo, scheduled_for=None, schedule_name=None):
    """schedule a yo for a specific time"""
    if not schedule_name:
        schedule_name = current_app.config.get('SCHEDULE_NAME')

    if not scheduled_for:
        scheduled_for = get_usec_timestamp()

    yo.reload()
    yo.status = 'scheduled'
    yo.scheduled_for = scheduled_for
    yo.schedule_name = schedule_name
    yo.save()
    yo_scheduler.announce_new(yo, YO_JOB_TYPE)


def schedule_auto_follow_yo(user, auto_follow_user):
    auto_follow_yo = construct_auto_follow_yo(user, auto_follow_user)

    if auto_follow_yo:
        # 10 seconds from now
        auto_follow_delay = current_app.config.get('AUTO_FOLLOW_DELAY')
        auto_follow_delay = auto_follow_delay*1e6 + get_usec_timestamp()
        schedule_yo(auto_follow_yo, auto_follow_delay)


def schedule_first_yo(user, first_yo_from):
    yo_link, yo_location = construct_first_yo(user, first_yo_from)

    first_yo_delay = current_app.config.get('FIRST_YO_DELAY')
    first_yo_delay = first_yo_delay.replace(' ', '').split(',')

    first_yo_link_delay = int(first_yo_delay[0])*1e6
    first_yo_location_delay = int(first_yo_delay[1])*1e6

    # If the delay is equal to 0 assume it is disabled
    if first_yo_location_delay:
        first_yo_location_delay += get_usec_timestamp()
        schedule_yo(yo_location, first_yo_location_delay)

    if first_yo_link_delay:
        first_yo_link_delay += get_usec_timestamp()
        schedule_yo(yo_link, first_yo_link_delay)


def schedule_no_contacts_yo(user, first_yo_from):

    try:
        header = Header.objects.get(id='55c1035f6461740061000027')

        yo_link = construct_yo(sender=first_yo_from, recipients=[user],
                               link='https://index.justyo.co', ignore_permission=True,
                               header=header, link_content_type='text/html')

        hour = int(60 * 60)*1e6

        delay = hour + get_usec_timestamp()
        schedule_yo(yo_link, delay)
    except:
        current_app.log_exception(sys.exc_info())