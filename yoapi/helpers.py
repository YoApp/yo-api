# -*- coding: utf-8 -*-

"""Helper functions for YoAPI."""


# Only certain functions in the string module are deprecated.
# pylint: disable=deprecated-module


import calendar
import inspect
import random
import string
import sys
import time
from datetime import datetime
from functools import update_wrapper

import gevent
import phonenumbers
import pytz
import requests
from PIL import Image, ExifTags
from requests.exceptions import RequestException
from flask import jsonify, current_app, copy_current_request_context, g
from flask.globals import _request_ctx_stack


def assert_valid_time(str_time, time_format='%H:%M'):
    if not str_time:
        raise ValueError('time cannot be None')

    time.strptime(str_time, time_format)


def make_json_response(*args, **kwargs):
    """Adds status_code argument to jsonify."""
    status_code = kwargs.pop('status_code', None)
    log_json_response = kwargs.pop('log_json_response', True)

    response = jsonify(*args, **kwargs)
    response.log_json_response = log_json_response

    if status_code:
        response.status_code = status_code
    return response


def random_number_string(length=16):
    chars = string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def random_string(length=16):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def iso8601_to_usec(datestring):
    return int(
        calendar.timegm(
            datetime.strptime(datestring, "%Y-%m-%dT%H:%M:%S.%fZ").timetuple())
        * 1e6)


def get_usec_timestamp(delta=None):
    offset = 0
    if delta:
        offset = delta.total_seconds()
    return int((time.time() + offset) * 1e6)


def unix_time_millis(dt):
    epoch = datetime.utcfromtimestamp(0)
    return (dt - epoch).total_seconds() * 1000.0


def iso8601_from_usec(usec):
    """Return a microsecond timestamp as an ISO8601 string

    Note that we prefer the UTC format using 'Z' defined by W3 over the
    equally valid +00:00 used by default in Python.
    """
    return datetime.fromtimestamp(usec / 1e6, pytz.utc).isoformat()[:-6] + 'Z'


def generate_thumbnail_from_url(url):
    import hashlib
    from urllib import urlencode

    def url2png(url, api_key, secret, fullpage=None, max_width=89,
                force=None, viewport_width=320, viewport_height=320):
        data = {
            'url': url,
            'fullpage': 'true' if fullpage else 'false',
            'thumbnail_max_width': max_width,
            'force': force,
            'viewport': '{}x{}'.format(viewport_width, viewport_height),
        }
        filtered_data = dict((opt, data[opt]) for opt in data if data[opt])

        query_string = urlencode(filtered_data)

        token = hashlib.md5('{}{}'.format(query_string, secret)).hexdigest()
        return "http://api.url2png.com/v6/{}/{}/png/?{}".format(api_key, token, query_string)

    api_key = "P54E3B2A2019BE"
    secret = "S3F033C68A36DE"

    url = url2png(url, api_key, secret)

    #ping_url.delay(url)  # url2png only renders photo if loaded at least once
    requests.get(url)

    return url


def generate_thumbnail_from_image(image_data):
    size = (89*2, 89*2)
    image = Image.open(image_data)
    image.thumbnail(size, Image.ANTIALIAS)
    if hasattr(image, '_getexif'):  # only present in JPEGs
        for orientation in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation] == 'Orientation':
                break
        e = image._getexif()  # returns None if no EXIF data
        if e is not None:
            exif = dict(e.items())
            orientation = exif[orientation]
            if orientation == 3:
                image = image.transpose(Image.ROTATE_180)
            elif orientation == 6:
                image = image.transpose(Image.ROTATE_270)
            elif orientation == 8:
                image = image.transpose(Image.ROTATE_90)
    background = Image.new('RGBA', size, (255, 255, 255, 0))
    background.paste(
        image, ((size[0] - image.size[0]) / 2, (size[1] - image.size[1]) / 2))

    import cStringIO

    buffer = cStringIO.StringIO()
    image.save(buffer, format="PNG")

    return buffer.getvalue()


def get_image_url(filename):
    if not filename:
        return None
    elif filename.startswith('http'):
        return filename
    else:
        bucket = current_app.config['S3_IMAGE_BUCKET']
        return 'https://s3.amazonaws.com/%s/%s' % (bucket, filename)


def get_remote_addr(request):
    address = request.headers.get('X-Forwarded-For', request.remote_addr)
    if address is not None:
        address = address.encode('utf-8')
        address = address.split(',')[0]
    else:
        address = request.remote_addr

    return address


def gevent_thread(decorated_func):
    def inner(*args, **kwargs):
        return gevent.spawn(copy_current_request_context(decorated_func),
                            *args, **kwargs)

    return inner


def partition_list(l, n):
    """ Yield successive n-sized chunks from l.
    """
    for i in xrange(0, len(l), n):
        yield l[i:i + n]


def copy_current_request_context(f):
    top = _request_ctx_stack.top
    if top is None:
        raise RuntimeError('This decorator can only be used at local scopes '
                           'when a request context is on the stack.  For instance within '
                           'view functions.')
    identity = g.identity
    reqctx = top.copy()

    def wrapper(*args, **kwargs):
        with reqctx:
            g.identity = identity
            return f(*args, **kwargs)

    return update_wrapper(wrapper, f)


def get_link_content_type(link):
    # All links uploaded via the dashboard begin with this prefix
    if link.startswith(current_app.config.get('IMAGE_WRAPPER_PREFIX')):
        return 'image/jpg'

    resp = requests.head(link, timeout=10, allow_redirects=True)
    resp.raise_for_status()

    return resp.headers.get('Content-Type', 'application/unknown')


def clean_phone_number(number, country_code_if_missing='1', user_phone=None):
    original_number = number
    # Tack on a country code if missing from the phonebook entry.
    if not number.startswith('+'):
        number = '+%s%s' % (country_code_if_missing, number)
    elif user_phone:
        # TODO: fixes issue 68: Take into account
        # improperly formatted phone numbers
        # starting with a '+' and not containing a
        # country code
        user_phone = str(user_phone)
        country_code_if_missing = str(country_code_if_missing)
        if ((len(user_phone) - len(country_code_if_missing)) ==
                len(number)):
            number = '+%s%s' % (country_code_if_missing, number[1:])
    # Parse number to make sure we have a clean version.
    parsed_number = phonenumbers.parse(number)
    valid_number = '+%s%s' % (parsed_number.country_code,
                              parsed_number.national_number)
    return valid_number


def assert_function_arguments(fn, *args, **kwargs):
    """Asserts that the parameters passed to the given function are
    acceptable
    """
    fn_args, varargs, keywords, defaults = inspect.getargspec(fn)

    missing = '__missing__arg__'
    fn_args_len = len(fn_args)
    defaults_len = len(defaults) if defaults else 0

    args_len = len(args) if args else 0

    if fn_args_len - defaults_len > len(args):
        error_msg = ('%s() takes at least %s positional arguments. '
                     '%s provided')
        error_msg = error_msg % (fn.__name__,
                                 (fn_args_len - defaults_len),
                                 args_len)
        raise TypeError(error_msg)
    elif args_len > fn_args_len and not varargs:
        error_msg = ('%s() takes at most %s arguments. '
                     '%s provided')
        error_msg = error_msg % (fn.__name__, fn_args_len, args_len)
        raise TypeError(error_msg)

    defaults = list(defaults) if defaults else []
    defaults = ([missing] * (fn_args_len - defaults_len)) + defaults

    param_map = dict(zip(fn_args, [missing] * fn_args_len))

    for key, val in kwargs.items():
        if key in param_map:
            param_map[key] = val
        elif not keywords:
            error_msg = '%s() does not except keyword argument %s'
            raise TypeError(error_msg % (fn.__name__, key))

    for i in xrange(min(args_len, fn_args_len)):

        if param_map.get(fn_args[i]) != missing:
            error_msg = ('%s() got multiple values for keyword '
                         'argument %s')
            raise TypeError(error_msg % (fn.__name__, fn_args[i]))
        else:
            param_map[fn_args[i]] = args[i]

    missing_params = 0
    for i in xrange(fn_args_len):
        if (param_map.get(fn_args[i]) == missing and
                    defaults[i] == missing):
            missing_params += 1
        else:
            param_map[fn_args[i]] = defaults[i]

    if missing_params:
        error_msg = ('%s() takes at least %s arguments. '
                     '%s provided')
        error_msg = error_msg % (fn.__name__,
                                 (fn_args_len - defaults_len),
                                 (fn_args_len - missing_params))
        raise TypeError(error_msg % (fn.__name__, fn_args[i]))


def get_location_data(ip):
    # TODO This needs to use a Yo owned server
    # currently it is using a 1 off box that is
    # a bit buggy
    # Request geo location data
    geoip_server = current_app.config.get('GEOIP_SERVER')
    if not (ip and geoip_server):
        return

    url = '%s/%s' % (geoip_server, ip)
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        return resp.json()
    except (ValueError, RequestException):
        current_app.log_exception(sys.exc_info(),
                                  message='error getting location data')
