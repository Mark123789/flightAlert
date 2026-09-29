import unittest
from unittest.mock import Mock

import requests

from notifications import send_notification
from tests.helpers import response


class NotificationTests(unittest.TestCase):
    def test_http_200_without_business_success_is_failure(self):
        result = send_notification("message", "token", post=Mock(return_value=response({"code": 401})))
        self.assertFalse(result.success)
        self.assertIn("401", result.error)

    def test_valid_response_is_success(self):
        post = Mock(return_value=response({"code": 200}))
        self.assertTrue(send_notification("message", "token", post=post).success)
        self.assertEqual(post.call_args.kwargs["json"]["content"], "message")

    def test_network_or_invalid_response_returns_failure_reason(self):
        for post in (Mock(side_effect=requests.Timeout("read timeout")),
                     Mock(return_value=response([]))):
            result = send_notification("message", "token", post=post)
            self.assertFalse(result.success)
            self.assertTrue(result.error)

    def test_blank_token_does_not_send(self):
        post = Mock()
        self.assertFalse(send_notification("message", "", post=post).success)
        post.assert_not_called()
