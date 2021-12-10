# -*- coding: utf-8 -*-
import re

"""Regex constants module"""

# Form regexes cannot be compiled.
LOCATION_REGEX = \
    r'(^[-+]?([1-8]?\d(\,\d+)?|90(\,0+)?)[;]\s*[-+]?(180(\,0+)?' + \
    r'|((1[0-7]\d)|([1-9]?\d))(\,\d+)?)$)|(^[-+]?([1-8]?\d(\.\d+)?' + \
    r'|90(\.0+)?)[;,]\s*[-+]?(180(\.0+)?|((1[0-7]\d)|([1-9]?\d))(\.\d+)?)$)'
LOCATION_ERR_MESSAGE = 'Improper location format. Use: 0.0, 0.0'

CONTEXT_REGEX = r'^.{,30}$'
CONTEXT_ERR_MESSAGE = 'Only 30 chars max allowed.'

USERNAME_REGEX = r'^[A-Z][A-Z0-9]{,49}$|^[0-9]{2,20}$'
USERNAME_ERR_MESSAGE = 'username must start with a letter and contain [A-Z0-9]'
REAL_USERNAME_REGEX = r'^[A-Z][A-Z0-9]{,49}$'

ANDROID_RE = re.compile(
    r'(.+)/(\d+) \(Android; (.+); (\d+); ([\d\.]+)')
IOS_RE = re.compile(
    r'(.+)/([\d\.]+) \((iPhone|iPod touch|iPad); iOS ([\d\.]+); .+\)')
WINPHONE_RE = re.compile(
    r'(.+)/([\d\.]+) \(Windows Phone; (.+?); Microsoft Windows NT ([\d\.]+)\)')



# search for exactly two consecutive periods.
DOUBLE_PERIOD_RE = re.compile(r'(?<!\.)(\.\.)(?!\.)')

# all valid characters in the GSM 7-bit character set
# from http://stackoverflow.com/questions/2452861/python-library-for-converting-plain-text-ascii-into-gsm-7-bit-character-set
# with ` deleted because it's not in GSM-7.
GSM = (u"@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789:;<="
       u">?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ¿abcdefghijklmnopqrstuvwxyzäöñüà")
NOT_GSM_RE = re.compile('[^' + GSM + ']')

# ASCII_GSM is the intersection of GSM characters and ASCII characters.
# ASCII_GSM also contains '\x1b', but I don't know what that is,
# so I removed it.
ASCII_GSM = '@$\n\r_ !"#%&\'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
NOT_ASCII_GSM_RE = re.compile('[^' + ASCII_GSM + ']')

IS_ALNUM_RE = re.compile('^[A-Za-z0-9]+$')
