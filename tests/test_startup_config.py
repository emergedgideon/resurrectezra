import contextlib
import io
import os
import unittest
from unittest.mock import patch

from app.config import ConfigurationError, Settings
from scripts.start_render import arguments, main


class StartupConfigurationTests(unittest.TestCase):
    def environment(self):
        return {'RENDER': 'true', 'EZRA_DATABASE_URL': 'postgresql://postgres.example:[YOUR-PASSWORD]@example.pooler.supabase.com:5432/postgres',
                'EZRA_DATABASE_PASSWORD': 'synthetic-password-never-print', 'SUPABASE_URL': 'https://example.supabase.co',
                'SUPABASE_SERVICE_ROLE_KEY': 'synthetic-key-never-print', 'EZRA_ACCESS_TOKEN': 'synthetic-app-password-long-enough'}

    def log(self, environment):
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), contextlib.redirect_stderr(output), patch('scripts.start_render.os.execv') as execute:
            result = main()
        self.assertEqual(result, 1)
        execute.assert_not_called()
        self.assertNotIn('synthetic-key-never-print', output.getvalue())
        self.assertNotIn('synthetic-password-never-print', output.getvalue())
        return output.getvalue()

    def test_missing_fields_are_named_without_values(self):
        log = self.log({'RENDER': 'true'})
        for field in ('EZRA_DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY'):
            self.assertIn(field, log)

    def test_short_app_password_is_actionable_and_not_echoed(self):
        environment = self.environment(); environment['EZRA_ACCESS_TOKEN'] = 'short-secret'
        log = self.log(environment)
        self.assertIn('EZRA_ACCESS_TOKEN', log)
        self.assertIn('24 characters', log)
        self.assertNotIn(environment['EZRA_ACCESS_TOKEN'], log)

    def test_database_and_storage_urls_are_distinguished(self):
        environment = self.environment(); environment['EZRA_DATABASE_URL'] = 'https://example.supabase.co'
        log = self.log(environment)
        self.assertIn('EZRA_DATABASE_URL', log)
        self.assertIn('postgresql://', log)
        environment = self.environment(); environment['SUPABASE_URL'] = 'postgresql://synthetic-password-never-print@host/database'
        self.assertIn('SUPABASE_URL', self.log(environment))

    def test_malformed_url_and_number_errors_do_not_echo_supplied_content(self):
        environment = self.environment(); environment['EZRA_DATABASE_URL'] = 'postgresql://[synthetic-password-never-print'
        self.assertIn('EZRA_DATABASE_URL', self.log(environment))
        environment = self.environment(); environment['EZRA_MAX_OUTPUT_TOKENS'] = 'synthetic-key-never-print'
        self.assertIn('EZRA_MAX_OUTPUT_TOKENS', self.log(environment))

    def test_valid_config_reaches_launch_and_placeholder_is_supported(self):
        with patch.dict(os.environ, self.environment(), clear=True), patch('scripts.start_render.os.execv') as execute:
            Settings.from_env()
            main()
        execute.assert_called_once()


if __name__ == '__main__':
    unittest.main()
