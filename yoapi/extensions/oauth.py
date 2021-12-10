from datetime import datetime, timedelta
from flask import session
from flask.ext.oauthlib.provider import OAuth2Provider
from yoapi.models import User
from yoapi.models.oauth import Token, Grant, Client


class YoOAuth2Provider(OAuth2Provider):

    def current_user(self):
        if 'identity.id' in session:
            uid = session['identity.id']
            return User.objects(id=uid).get()
        return None

    def init_app(self, app):
        super(YoOAuth2Provider, self).init_app(app)

        @self.clientgetter
        def load_client(client_id):
            try:
                return Client.objects.get(client_id=client_id)
            except:
                return None

        @self.grantgetter
        def load_grant(client_id, code):
            return Grant.objects.get(client_id=client_id, code=code)

        @self.grantsetter
        def save_grant(client_id, code, request, *args, **kwargs):
            expires = datetime.utcnow() + timedelta(seconds=100)
            Grant(client_id=client_id,
                  code=code['code'],
                  redirect_uri=request.redirect_uri,
                  scopes=request.scopes,
                  user=self.current_user(),
                  expires=expires).save()

        @self.tokengetter
        def load_token(access_token=None, refresh_token=None):
            if access_token:
                try:
                    return Token.objects.get(access_token=access_token)
                except:
                    return None
            elif refresh_token:
                try:
                    return Token.objects.get(refresh_token=refresh_token)
                except:
                    return None


        @self.tokensetter
        def save_token(token, request, *args, **kwargs):

            refresh_token = None
            try:
                old_token = Token.objects.get(client_id=request.client.client_id, user=request.user)
                refresh_token = old_token.refresh_token
            except:
                pass

            if not refresh_token:
                refresh_token = token['refresh_token']

            token['refresh_token'] = refresh_token

            expires = datetime.utcnow() + timedelta(days=365)

            user = request.user or self.current_user()

            Token(access_token=token['access_token'],
                  token_type=token['token_type'],
                  refresh_token=token['refresh_token'],
                  scopes=[token['scope']],
                  expires=expires,
                  client_id=request.client.client_id,
                  client=request.client,
                  user=user).save()
