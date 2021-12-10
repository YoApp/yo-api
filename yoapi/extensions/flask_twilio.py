# -*- coding: utf-8 -*-

"""Flask extension pacakge for Twilio"""

import random

from . import FlaskExtension
from ..errors import APIError
from flask import current_app
import requests
from requests.auth import HTTPBasicAuth
from twilio.rest import TwilioRestClient


blocked = [
    '+351938422382'
]


class Twilio(FlaskExtension):

    """A helper class for managing a the twilio API calls"""

    EXTENSION_NAME = 'twilio'

    def __init__(self, app=None):
        super(Twilio, self).__init__(app=app)

    def _create_instance(self, app):
        """Init and store the twilio object on the stack on first use."""
        client = TwilioRestClient(
            app.config.get('TWILIO_ACCOUNT_SID'),
            app.config.get('TWILIO_AUTH_TOKEN'))
        return client

    def send(self, number, message, media_url=None, sender=None):
        """Sends an SMS to a phone number"""

        if number in blocked:
            return

        requests.post('https://api.plivo.com/v1/Account/MAYTC0MWFJODHJMZVKNT/Message/',
                      auth=HTTPBasicAuth('MAYTC0MWFJODHJMZVKNT', 'ZjQ4MWUwNGRmZjY1Y2MyYTViYWQ4YmUwOTI1YWYw'),
                      json={
                          "src": "+14156128793",
                          "dst": number,
                          "text": message
                      })
        return

        if sender is None:
            twilio_numbers = current_app.config.get('TWILIO_NUMBERS')
            numbers = ''.join([n for n in number if n.isdigit()])
            sender = twilio_numbers[int(numbers) % len(twilio_numbers)]

        if media_url:
            self.instance.messages.create(to=number,
                                          from_=sender,
                                          body=message,
                                          media_url=[media_url])
        else:
            self.instance.messages.create(to=number,
                                          from_=sender,
                                          body=message)

