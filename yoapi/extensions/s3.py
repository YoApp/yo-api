# -*- coding: utf-8 -*-

"""Amazon S3 module"""

import mimetypes
import boto.sns

from boto.s3.key import Key
from flask import _app_ctx_stack, g

from . import FlaskExtension
from ..helpers import get_image_url, random_string
from ..errors import APIError
from ..models import Image


class S3(FlaskExtension):

    """A helper class for managing a S3 buckets."""

    EXTENSION_NAME = 's3'

    def __init__(self, app=None):
        super(S3, self).__init__(app=app)

    def _create_instance(self, app):
        """Do nothing"""
        return None

    def init_app(self, app):
        """Do nothing"""
        pass

    @property
    def conn(self):
        """Init and store the bucket object on the stack on first use."""
        ctx = _app_ctx_stack.top
        app = ctx.app
        if not hasattr(ctx, 'boto_sns_connection'):
            ctx.boto_s3_connection = boto.connect_s3(
                aws_access_key_id=app.config['AWS_ACCESS_KEY_ID'],
                aws_secret_access_key=app.config['AWS_SECRET_ACCESS_KEY'])
        return ctx.boto_s3_connection

    def get_bucket(self, bucket_name):
        """Gets an S3 bucket from the connection"""
        ctx = _app_ctx_stack.top
        if not hasattr(ctx, 's3_buckets'):
            ctx.s3_buckets = {}
        if not bucket_name in ctx.s3_buckets:
            ctx.s3_buckets[bucket_name] = self.conn.get_bucket(bucket_name)
        return ctx.s3_buckets[bucket_name]

    def delete_image(self, filename, bucket_name=None):
        """Delete a file from the image bucket"""
        app = _app_ctx_stack.top.app
        bucket_name = bucket_name or app.config['S3_IMAGE_BUCKET']
        bucket = self.get_bucket(bucket_name)
        bucket.delete_key(filename)

    def upload_image(self, filename, data):
        """Upload a profile image to s3."""
        app = _app_ctx_stack.top.app
        bucket_name = app.config.get('S3_IMAGE_BUCKET')
        if not bucket_name:
            raise APIError('No image bucket specified')
        self.upload(filename=filename, data=data, bucket_name=bucket_name)
        return get_image_url(filename)

    def upload(self, filename=None, data=None, bucket_name=None):
        """Upload a file to s3.

        Return:
            A boto.s3.Key
        """
        if not filename:
            raise APIError('No filename provided')
        if not data:
            raise APIError('No file data provided')
        if not bucket_name:
            raise APIError('No bucket name provided')

        bucket = self.get_bucket(bucket_name)
        mimetype = mimetypes.guess_type(filename)[0]
        key = Key(bucket, filename)
        key.set_metadata('Content-Type', mimetype)
        key.set_metadata(
            'Cache-Control',
            'max-age=31536000, public')  # one year
        key.set_contents_from_string(
            data,
            replace=True,
            reduced_redundancy=True)
        key.make_public()
        return key

    def upload_photo(self, datauri, owner=None):
        """Uploads a Yo cover image to S3 and returns the filename."""
        if not datauri.is_image:
            raise APIError('Image data invalid')
        if not owner:
            owner = g.identity.user

        app = _app_ctx_stack.top.app
        bucket_name = app.config.get('YO_PHOTO_BUCKET')
        filename = '%s.%s' % (random_string(length=7), datauri.extension)
        image = Image(filename=filename,
                      is_public=True,
                      owner=owner).save()
        self.upload(filename=filename, bucket_name=bucket_name,
                    data=datauri.data)
        return image
