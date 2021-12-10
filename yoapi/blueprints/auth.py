
"""Authentication related endpoints"""

# pylint: disable=invalid-name

from flask import request

from ..accounts import get_user, login
from ..errors import APIError
from ..forms import LoginForm
from ..helpers import make_json_response
from ..jwt import generate_token
from ..security import forget_auth_cookie, set_auth_cookie, load_identity
from ..yoflask import Blueprint

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login', login_required=False)
def route_login_web():
    """Authenticates a user with username and password.

    Returns:
        A secure signed cookie.
    """
    form = LoginForm.from_json(request.json)
    form.validate()
    user = login(**form.data)
    token = generate_token(user)
    load_identity(user.user_id)
    set_auth_cookie(user)
    return make_json_response(**user.get_public_dict(field_list='account'))


@auth_bp.route('/logout', login_required=False)
def route_logout_web():
    """Authenticates a user with username and password.

    Returns:
        A secure signed cookie.
    """
    forget_auth_cookie()
    return make_json_response()
