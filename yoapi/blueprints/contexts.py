# -*- coding: utf-8 -*-

"""Client context management endpoints."""


from flask import request, current_app, g

from ..contexts import get_contexts, get_gif_phrase
from ..core import imgur, giphy
from ..helpers import make_json_response, get_usec_timestamp
from ..yoflask import Blueprint

# Pylint rules regarding variable names that are not in PEP8.
# https://www.python.org/dev/peps/pep-0008/#global-variable-names
# pylint: disable=invalid-name


# Instantiate a YoFlask customized blueprint that supports JWT authentication.
contexts_bp = Blueprint('context', __name__, url_prefix='/rpc')

@contexts_bp.route('/get_easter_egg')
def route_get_easter_egg():
    """Gets the easter associated with a user if available."""
    easter_egg_url = current_app.config.get('EASTER_EGG_URL')
    easter_egg_text = current_app.config.get('EASTER_EGG_TEXT')
    easter_egg_text = easter_egg_text or 'Sent Yo Doodle'
    easter_egg = {}
    if easter_egg_url:
        easter_egg = {'title': 'Yo',
                      'status_bar_text': 'Tap a name to send this',
                      'sent_text': easter_egg_text,
                      'url': easter_egg_url}
    return make_json_response(easter_egg=easter_egg)


@contexts_bp.route('/giphy')
def route_giphy():
    """Gets the giphy associated with a user if available."""
    gif_phrase = get_gif_phrase(g.identity.user)
    phrase = gif_phrase.keyword
    text = gif_phrase.header
    result = {}
    if phrase and text:
        gifs = giphy.get_gifs_by_phrase(phrase)
        if gifs:
            result = {'title': 'Yo',
                      'status_bar_text': 'Tap a name to send this gif',
                      'phrase': phrase,
                      'sent_text': text,
                      'urls': gifs}
    return make_json_response(payload=result)


@contexts_bp.route('/meme')
def route_get_meme():
    """Gets the meme if available."""
    meme_phrase = current_app.config.get('MEME_PHRASE')
    result = {}
    if meme_phrase:
        meme_urls = imgur.get_meme_urls(meme_phrase)
        if meme_urls:
            result = {'title': 'Yo',
                      'status_bar_text': 'Tap a name to send this meme',
                      'sent_text': 'Sent meme!',
                      'urls': meme_urls}
    return make_json_response(payload=result)


@contexts_bp.route('/get_context_configuration', login_required=False)
def route_get_contexts():
    """Gets the contexts for the client."""
    contexts, default = get_contexts(g.identity.user, request)
    return make_json_response(contexts=contexts, default_context=default)
