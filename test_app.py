import os
import unittest
from unittest.mock import patch

os.environ.setdefault('FACEBOOK_PAGE_ID','1219495331244769')
os.environ.setdefault('FACEBOOK_TIMEZONE','America/New_York')

import app

class FacebookTests(unittest.TestCase):
    def post(self): return {'caption':'Test InvoMe caption','media_file':'post_1.mp4'}

    def test_payload_is_safe_facebook_draft(self):
        body=app.facebook_payload(self.post(),live=False,base_url='https://example.test')
        self.assertEqual(body['published'],'false')
        self.assertEqual(body['description'],'Test InvoMe caption')
        self.assertEqual(body['file_url'],'https://example.test/media/post_1.mp4')

    def test_live_payload(self):
        body=app.facebook_payload(self.post(),live=True,base_url='https://example.test')
        self.assertEqual(body['published'],'true')

    def test_missing_token(self):
        with patch.dict(os.environ,{'FACEBOOK_PAGE_ACCESS_TOKEN':''}):
            ok,message=app.publish_post(999,force_test=True)
        self.assertFalse(ok)
        self.assertEqual(message,'FACEBOOK_PAGE_ACCESS_TOKEN is not configured')

    def test_autopilot_requires_live_and_on(self):
        for settings in ({'publishing_mode':'test','autopilot':'1'}, {'publishing_mode':'live','autopilot':'0'}):
            with patch.object(app,'get_settings',return_value=settings), patch.object(app,'create_post') as create:
                app.autopilot_tick()
                create.assert_not_called()

    def test_api_cannot_bypass_safety(self):
        with patch.object(app,'get_settings',return_value={'publishing_mode':'test','autopilot':'0'}):
            response=app.app.test_client().post('/api/autopilot/run')
        self.assertEqual(response.status_code,409)

if __name__=='__main__': unittest.main()
