import json
import logging
from unittest import TestCase
from unittest.mock import patch

from core.utils import _WHATSAPP_CORRELATION_ID, _whatsapp_headers
from core.whatsapp_logging import log_event


class WhatsAppLoggingTestCase(TestCase):
    def test_structured_log_excludes_sensitive_fields(self):
        with self.assertLogs('whatsapp', level=logging.INFO) as captured:
            log_event(
                event='privacy_test',
                phone='+212661234567',
                message='private content',
                api_key='secret-api-key',
                qr='private-qr',
            )

        record = json.loads(captured.records[0].getMessage())
        self.assertEqual(record['event'], 'privacy_test')
        self.assertNotIn('phone', record)
        self.assertNotIn('message', record)
        self.assertNotIn('api_key', record)
        self.assertNotIn('qr', record)

    def test_request_headers_carry_correlation_id(self):
        token = _WHATSAPP_CORRELATION_ID.set('correlation-test')
        try:
            headers = _whatsapp_headers({'Content-Type': 'application/json'})
            self.assertEqual(headers['X-Correlation-ID'], 'correlation-test')
            self.assertEqual(headers['X-Request-ID'], 'correlation-test')
        finally:
            _WHATSAPP_CORRELATION_ID.reset(token)
