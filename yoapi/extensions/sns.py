# -*- coding: utf-8 -*-

"""Amazon SNS extension module"""

import boto.sns

from . import FlaskExtension


class SNS(FlaskExtension):

    """A helper class for managing an SNS connection

    At this stage, we do not actively manage removal of endpoints, topics
    or subscriptions. Documentation on uninstall hooks is necessary before
    we can make inferences about what subscriptions have expired.

    The constructor does nothing in this class since we lazily create the
    connection on first access. We don't remove the constructor, however,
    as the ideal format of these Flask extension packages has yet to be
    defined. See http://flask.pocoo.org/docs/0.10/extensiondev/ for more
    information on flask extensions.
    """

    EXTENSION_NAME = 'aws-sns'
    SYS_DELIVERY_FAILURE_ARN = 'arn:aws:sns:us-east-1:131325091098:sys_delivery_failure'
    REMOVE_ON_FAILURE_TYPES = ['EndpointDisabled']

    ARN_BY_DEVICE_TYPE = {
        'ios': 'arn:aws:sns:us-east-1:131325091098:app/APNS/iOS',
        'ios-beta': 'arn:aws:sns:us-east-1:131325091098:app/APNS/iOS-Beta',
        'ios-development': 'arn:aws:sns:us-east-1:131325091098:app/APNS_SANDBOX/iOS-Dev',
        'android': 'arn:aws:sns:us-east-1:131325091098:app/GCM/Android',
        'winphone': 'arn:aws:sns:us-east-1:131325091098:app/MPNS/WindowsPhone',
        'com.flashpolls.beta.dev': 'arn:aws:sns:us-east-1:131325091098:app/APNS_SANDBOX/com.flashpolls.beta.dev',
        'com.flashpolls.beta.prod': 'arn:aws:sns:us-east-1:131325091098:app/APNS/com.flashpolls.beta.prod',
        'com.flashpolls.flashpolls.dev': 'arn:aws:sns:us-east-1:131325091098:app/APNS_SANDBOX/com.flashpolls.flashpolls.dev',
        'com.flashpolls.flashpolls.prod': 'arn:aws:sns:us-east-1:131325091098:app/APNS/com.flashpolls.flashpolls.prod',
        'com.flashpolls.beta': 'arn:aws:sns:us-east-1:131325091098:app/APNS/com.flashpolls.beta.prod',
        'com.thenet.flashpolls.dev': 'arn:aws:sns:us-east-1:131325091098:app/APNS_SANDBOX/com.thenet.flashpolls.dev',
        'com.thenet.flashpolls.prod': 'arn:aws:sns:us-east-1:131325091098:app/APNS/com.thenet.flashpolls.prod',
        'com.flashpolls.android': 'arn:aws:sns:us-east-1:131325091098:app/GCM/com.flashpolls.android',
        'co.justyo.polls.android': 'arn:aws:sns:us-east-1:131325091098:app/GCM/co.justyo.polls.android',
        'com.yo.polls.dev': 'arn:aws:sns:us-east-1:131325091098:app/APNS_SANDBOX/com.yo.polls.dev',
        'com.yo.polls.prod': 'arn:aws:sns:us-east-1:131325091098:app/APNS/com.yo.polls.prod',
        'com.orarbel.yostatus.ios.dev': 'arn:aws:sns:us-east-1:131325091098:app/APNS_SANDBOX/com.orarbel.status.ios.dev',
        'com.orarbel.yostatus.ios.prod': 'arn:aws:sns:us-east-1:131325091098:app/APNS/com.orarbel.yostatus.ios.prod',
        'co.justyo.status.ios.dev': 'arn:aws:sns:us-east-1:131325091098:app/APNS_SANDBOX/co.justyo.status.ios.dev',
        'co.justyo.status.ios.prod': 'arn:aws:sns:us-east-1:131325091098:app/APNS/co.justyo.status.ios.prod',
        'co.justyo.polls.enterprise.prod': 'arn:aws:sns:us-east-1:131325091098:app/APNS/co.justyo.polls.enterprise.prod',
        'co.justyo.yostatus.android': 'arn:aws:sns:us-east-1:131325091098:app/GCM/co.justyo.status.android.prod',
        'co.justyo.noapp.ios.dev': 'arn:aws:sns:us-east-1:131325091098:app/APNS_SANDBOX/co.justyo.noapp.ios.dev',
        'co.justyo.noapp.ios.prod': 'arn:aws:sns:us-east-1:131325091098:app/APNS/co.justyo.noapp.ios.prod',
        'co.orarbel.noapp.ios.prod': 'arn:aws:sns:us-east-1:131325091098:app/APNS/co.orarbel.noapp.ios.prod'
    }

    def __init__(self, app=None):
        super(SNS, self).__init__(app=app)

    def _create_instance(self, app):
        """Init and store the SNS object on the stack on first use."""
        boto_sns_connection = boto.sns.connect_to_region(
            'us-east-1',
            aws_access_key_id=app.config['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=app.config['AWS_SECRET_ACCESS_KEY'])
        return boto_sns_connection

    def create_platform_application_with_p12(self, name, platform, p12_content, p12_password=None):
        from OpenSSL import crypto
        p12 = crypto.load_pkcs12(p12_content, p12_password)
        cert = crypto.dump_certificate(crypto.FILETYPE_PEM, p12.get_certificate())
        private_key = crypto.dump_privatekey(crypto.FILETYPE_PEM, p12.get_privatekey())

        rv = self.create_platform_application_with_pem(
            name=name,
            platform=platform,
            pem_cert=cert,
            pem_private_key=private_key
        )

        return rv

    def create_platform_application_with_pem(self, name, platform, pem_cert, pem_private_key):
        arn = self.instance.create_platform_application(
            name=name,
            platform=platform,
            attributes={
                'PlatformPrincipal': pem_cert,
                'PlatformCredential': pem_private_key
            })
        return arn

    def create_endpoint(self, device_type, push_token, platform_arn=None):
        """Creates an endpoint and returns the ARN

        An endpoint represents a device in the context that we care about.
        The device type, and hence platform, can be deduce from the token
        pattern.

        Args:
            push_token: APNS or GCM issued notification token.

        """
        if not platform_arn:
            platform_arn = self.ARN_BY_DEVICE_TYPE[device_type]

        conn = self.instance
        return conn.create_platform_endpoint(platform_arn, push_token) \
            .get('CreatePlatformEndpointResponse') \
            .get('CreatePlatformEndpointResult') \
            .get('EndpointArn')

    def create_topic(self, topic_name):
        """Creates an topic and returns the ARN

        An topic represents a user's mailbox of which endpoints subscribe to.
        The topic_name is the user's ObjectId

        Args:
            topic_name: Name for the topic being created.

        """
        conn = self.instance
        return conn.create_topic(topic_name) \
            .get('CreateTopicResponse') \
            .get('CreateTopicResult') \
            .get('TopicArn')

    def get_endpoint(self, endpoint_arn):
        """Gets endpoint attributes.

        Args:
            endpoint_arn: ARN provided by amazon.

        """
        return self.instance.get_endpoint_attributes(endpoint_arn)

    def delete_endpoint(self, endpoint_arn):
        """Deletes an endpoint

        When a device is unregistered we delete the endpoint from AWS.

        Args:
            endpoint_arn: ARN returned when endpoint was created.

        """
        return self.instance.delete_endpoint(endpoint_arn)

    def set_endpoint(self, endpoint_arn, attributes):
        """Sets the attributes in sns for a given endpoint arn

        Args:
            endpoint_arn: ARN returned when endpoint was created.
            attributes: A dict of endpoint attributes
                CustomUserData: Arbitrary data
                Enabled: Bool flag to enable/disable this endpoint
                Token: device provided push token

        """
        self.instance.set_endpoint_attributes(endpoint_arn=endpoint_arn,
                                              attributes=attributes)

    def subscribe(self, topic_arn, endpoint_arn, protocol='application'):
        """Subscribes an endpoint to a topic arn

        Args:
            topic_arn: ARN returned when topic was created.
            endpoint_arn: ARN returned when endpoint was created.
            protocol: The protocol for the endpoint
                 email|email-json|http|https|sqs|sms|application

        Note: 'application' is used for mobile apps and devices
        """

        return self.instance.subscribe(topic_arn, protocol, endpoint_arn) \
            .get('SubscribeResponse') \
            .get('SubscribeResult') \
            .get('SubscriptionArn')

    def publish(self, **kwargs):
        """Publish a push message to the provided topic or endpoint arn

        Args:
            message: (For our purposes) The JSON formatted message to send
                http://docs.aws.amazon.com/sns/latest/APIReference/API_Publish.html
            target_arn: ARN for topic or endpoint but not both.

        Note:
            message_structure is always set to json to send a different
                message for different protocols
            message_attributes has to be defined for mpns push to work
        """

        message_attributes = {
            'AWS.SNS.MOBILE.MPNS.NotificationClass': {
                'string_value': 'realtime',
                'data_type': 'String'
            },
            'AWS.SNS.MOBILE.MPNS.Type': {
                'string_value': 'toast',
                'data_type': 'String'
            }
        }
        return self.instance.publish(
            message_structure='json',
            message_attributes=message_attributes,
            **kwargs)
