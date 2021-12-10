# -*- coding: utf-8 -*-

"""Flask extension pacakge for Sendgrid"""

from . import FlaskExtension

from sendgrid import SendGridClient, Mail


class SendGrid(FlaskExtension):

    """A helper class for managing a the SendGrid API calls"""

    EXTENSION_NAME = 'sendgrid'

    def __init__(self, app=None):
        super(SendGrid, self).__init__(app=app)

    def _create_instance(self, app):
        client = SendGridClient(
            app.config.get('SENDGRID_USERNAME'),
            app.config.get('SENDGRID_PASSWORD'))
        return client

    def send_mail(self, body=None, subject=None, recipient=None, sender=None):
        """Sends an email"""
        mail = Mail(to=recipient,
                    from_email=sender,
                    subject=subject,
                    text=body)
        self.instance.send(mail)
