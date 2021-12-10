from yoapi.yoflask import Blueprint


websocket_bp = Blueprint('websocket', __name__)


@websocket_bp.socket_route('message', login_required=False)
def socket_to_dashboard(queue, message):
    """A socket handler to send yo's to the live counter based on logged in"""
    return message