# -*- coding: utf-8 -*-

"""Helper class for dealing with data URI's.

Code adapted from: https://gist.github.com/zacharyvoase/5538178
"""

import mimetypes
import re
import urllib


MIMETYPE_REGEX = r'[\w]+\/[\w\-\+\.]+'
_MIMETYPE_RE = re.compile('^{}$'.format(MIMETYPE_REGEX))

CHARSET_REGEX = r'[\w\-\+\.]+'
_CHARSET_RE = re.compile('^{}$'.format(CHARSET_REGEX))

DATA_URI_REGEX = (
    r'data:' +
    r'(?P<mimetype>{})?'.format(MIMETYPE_REGEX) +
    r'(?:\;charset\=(?P<charset>{}))?'.format(CHARSET_REGEX) +
    r'(?P<base64>\;base64)?' +
    r',(?P<data>.*)')
_DATA_URI_RE = re.compile(r'^{}$'.format(DATA_URI_REGEX), re.DOTALL)


class DataURI(str):

    _match = None

    @classmethod
    def make(cls, mimetype, charset, base64, data):
        parts = ['data:']
        if mimetype is not None:
            if not _MIMETYPE_RE.match(mimetype):
                raise ValueError("Invalid mimetype: %r" % mimetype)
            parts.append(mimetype)
        if charset is not None:
            if not _CHARSET_RE.match(charset):
                raise ValueError("Invalid charset: %r" % charset)
            parts.extend([';charset=', charset])
        if base64:
            parts.append(';base64')
            encoded_data = data.encode('base64').replace('\n', '')
        else:
            encoded_data = urllib.quote(data)
        parts.extend([',', encoded_data])
        return cls(''.join(parts))

    def __new__(cls, *args, **kwargs):
        uri = super(DataURI, cls).__new__(cls, *args, **kwargs)
        uri._parse  # Trigger any ValueErrors on instantiation.
        return uri

    def __repr__(self):
        return 'DataURI(%s)' % (super(DataURI, self).__repr__(),)

    @property
    def mimetype(self):
        return self._parse[0]

    @property
    def extension(self):
        mimetype = self.mimetype
        if mimetype in ['image/jpeg', 'image/jpg']:
            return 'jpg'
        elif mimetype == 'image/png':
            return 'png'
        elif mimetype == 'image/gif':
            return 'gif'
        else:
            return None

    @property
    def is_image(self):
        return self.extension in ['jpg', 'png']

    @property
    def charset(self):
        return self._parse[1]

    @property
    def is_base64(self):
        return self._parse[2]

    @property
    def data(self):
        return self._parse[3]

    @property
    def _parse(self):

        match = self._match
        if not match:
            match = _DATA_URI_RE.match(self)

        if match:
            self._match = match
        else:
            raise ValueError("Not a valid data URI: %r" % self)

        mimetype = match.group('mimetype') or None
        charset = match.group('charset') or None
        if match.group('base64'):
            data = match.group('data').decode('base64')
        else:
            data = urllib.unquote(match.group('data'))
        return mimetype, charset, bool(match.group('base64')), data
