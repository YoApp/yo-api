# -*- coding: utf-8 -*-

"""Error module to standardize the way the API can do a clean exit"""


from .helpers import make_json_response

from collections import OrderedDict
from flask import current_app, request
from twilio import TwilioRestException

from mongoengine.errors import ValidationError
from werkzeug.exceptions import ClientDisconnected


class ErrorManager(object):

    """Helper class to dispatch and monitor errors."""

    def __init__(self, app=None):
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initializes error handles"""

        @app.errorhandler(400)
        def handle_general_error(err):
            """Handler for too many requests

            TODO: Refactor this error handling. We are creating an APIerror
                  to preserve logic around custom error messages for certain
                  platforms.
            """
            error_message = 'Uh oh. An error yet to be described has occurred.'
            new_err = APIError(error_message, status_code=400)
            return make_json_response(**new_err.to_dict())

        @app.errorhandler(401)
        def handle_unauthorized_error(err):
            """Handler for unauthorized requests"""

            return make_json_response(error='Unauthorized', status_code=401)

        @app.errorhandler(429)
        def handle_ratelimit_error(err):
            """Handler for too many requests

            TODO: Refactor this error handling. We are creating an APIerror
                  to preserve logic around custom error messages for certain
                  platforms.
            """
            new_err = APIError(err.description, status_code=429)
            return make_json_response(**new_err.to_dict())

        @app.errorhandler(500)
        def handle_error(err):
            message = 'An unhandled exception occurred.'
            return make_json_response(error=message, status_code=500)

        @app.errorhandler(APIFormError)
        def handle_form_error(err):  # pylint: disable=unused-variable
            """Handles form validation errors

            These exceptions do not, as of yet, occurr automatically. Instead
            they should be raised manually where needed. For isntance, if the
            signup form does not validate then this error is raised.

            Args:
                err: An APIFormError instance.

            """
            # If called within the dashboard, the message displayed will
            # be [Object object] because it cannot parse err.to_dict().
            # Because of this, print a simple message and include the
            # errors payload for future implementation
            return make_json_response(**err.to_dict())

        @app.errorhandler(APIError)
        def handle_api_error(err):  # pylint: disable=unused-variable
            """Generic handler making it easy to do a clean exit from anywhere

            It is good practice to initialize this instance with a status_code
            property as that will be picked up by `make_json_response`.

            Args:
                err: An APIError instance.

            """
            resp = make_json_response(**err.to_dict())
            resp.headers['Content-type'] = 'application/json; charset=utf-8'
            return resp

        @app.errorhandler(ClientDisconnected)
        def handle_client_disconnect_error(err):  # pylint: disable=unused-variable
            """Generic handler making it easy to do a clean exit from anywhere

            It is good practice to initialize this instance with a status_code
            property as that will be picked up by `make_json_response`.

            Args:
                err: An ClientDisconnected instance.

            """
            return make_json_response(error=err.description, status_code=400)

        @app.errorhandler(UnicodeEncodeError)
        def handle_unicode_encode_error(err):
            """Handler to catch unicode issues that arise with usernames

            In the future unicode should be properly handled and used for
            all strings

            Args:
                err: An UnicodeEncodeError instance.

            """
            return make_json_response(error=err.reason, status_code=400)

        @app.errorhandler(ValidationError)
        def handle_mongo_validation_error(err):
            """Handler to catch MongoEngine validation errors that are missed

            In the future this would hopefully go away and the source errors
            will be caught directly
            Args:
                err: An MongoEngine.errors.ValidationError instance.
            """
            # If called within the dashboard, the message displayed will
            # be [Object object] because it cannot parse a dict.
            # Because of this, print a simple message and include the
            # errors payload for future implementation
            return make_json_response(error='Received invalid data',
                                      payload=err.to_dict(), status_code=400)

        @app.errorhandler(TwilioRestException)
        def handle_twilio_rest_exception(err):
            """Handler to catch TwilioRestExceptions raised when a sms cannot
               be sent to a user for verification

            In the future this exception should raise an api error and the
            method for phone verification on the device should be a 2 call
            process where the first simply sets and validates the number and
            the second attempts to send the sms"""

            return make_json_response(error=err.msg, status_code=200)

class APIError(Exception):

    """Error for when a generic error occurs"""
    # TODO: The code parameter is solely for iOS compatibility that will be
    # changed

    iphone_bug_paths = ['/rpc/yo', '/rpc/yoall', '/rpc/yo_all']

    def __init__(self, message, status_code=400, payload=None, code=None):
        super(APIError, self).__init__()
        self.message = str(message)
        self.status_code = status_code
        self.payload = payload
        self.code = code

    def __str__(self):
        return 'API error: ' + self.message

    def to_dict(self):
        if (not current_app.is_worker() and
                str(request.user_agent).startswith('Yo/1.4.1') and
                'iphone' in str(request.user_agent).lower() and
                request.path.rstrip('/') in self.iphone_bug_paths and
                self.status_code not in (403, 404)):
            # This is a hotfix for an issue where the iOS client 4.4.1
            # mistakenly calls /rpc/remove_contact for failure response
            # codes other than 403 and 404. The fix malformats the
            # response such that the client will throw an exception
            # and display "FAILED".
            # error = {'error': {'message':self.message}}
            self.status_code = 200
            error = {'message': self.message}
        elif (not current_app.is_worker() and
              str(request.user_agent).startswith('Yo') and
              'iphone' in str(request.user_agent).lower() and
              request.path.rstrip('/') in self.iphone_bug_paths):
            # TODO: Fixes issue #41. In the future clients
            # Should use a single standard error structure
            # TODO: Fixes #56. Only the yo and yoall need the
            # adjusted structure
            error = {'error': {'message': self.message}}
        else:
            error = {'error': self.message, 'errors': [{'message': self.message}]}
        if self.status_code:
            error['status_code'] = self.status_code
        if self.payload:
            error['payload'] = self.payload
        if self.code:
            error['code'] = self.code
        return error


class APIFormError(APIError):

    """Error for when input validation fails"""

    def __str__(self):
        return 'Form error: ' + self.message


class YoTokenInvalidError(Exception):
    """Token incorrect."""
    pass


class YoTokenUsedError(Exception):
    """Token already used."""
    pass


class YoTokenExpiredError(Exception):
    """Token expired."""
    pass
