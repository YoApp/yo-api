# -*- coding: utf-8 -*-

"""Utilities for Flask-Script"""
import sys
from pprint import pprint
import os
from flask import json
from os.path import expanduser
from ..helpers import iso8601_from_usec


CONFIG_FILE = expanduser('~/.yo')


def str_to_class(class_name):
    return getattr(sys.modules[class_name], str)
    #return globals()[class_name]


def print_response(res):
    print_section_header('RESPONSE')
    headers = map(lambda header: header[0] + ': ' + header[1], res.headers)
    print 'status: %s\n%s\n\n%s' % (res.status_code, '\n'.join(headers),
                                    res.data)


def print_object_section(section, obj):
    print_section_header(section)
    if hasattr(obj, 'to_dict'):
        obj = obj.to_dict()
        for key, value in obj.items():
            if isinstance(value, long) and value > 1e15:
                obj[key] = iso8601_from_usec(value)

    print json.dumps(obj, indent=4)


def print_user(user):
    print_section_header('USER')
    pprint(user.to_dict())


def print_decoded_token(decoded_token):
    print_section_header('DECODED TOKEN')
    pprint(decoded_token)


def print_section_header(section_name):
    _, width = os.popen('stty size', 'r').read().split()
    print '\n' + (' ' + section_name + ' ').center(int(width), '#')


def save_config(**kwargs):
    with open(CONFIG_FILE, 'w') as config_file:
        config_file.write(json.dumps(kwargs, indent=4))


def load_config():
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as config_file:
            try:
                return json.loads(config_file.read())
            except (IOError, ValueError):
                # No config. Proceed without
                pass
