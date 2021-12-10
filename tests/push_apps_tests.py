import json
from tests import BaseTestCase
from yoapi.models import User
from yoapi.models.push_app import PushApp


class PushAppsTestCase(BaseTestCase):

    def test_update_apps(self):
        '''f = open('/Volumes/Data/Development/api/tests/fixtures/push_apps.json')
        payload = json.loads(f.read())
        print payload

        admin_user = User(username='ADMINACCOUNT', is_admin=True)
        admin_user.api_token = '1111'
        admin_user.save()

        PushApp()

        res = self.jsonput('/ab_test/update_items?api_token=1111', data=payload, auth=False)
        print res'''