from datetime import date
import json
import io
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bkk_active.api_capture import ApiCapture
from bkk_active.api_events import ApiEvents, REDACTED, message_info, safe_url
from bkk_active.run_artifacts import RunArtifacts
from bkk_active.cli import main


def message(body=b'', content_type='application/json', **extra):
    return SimpleNamespace(headers={'Content-Type': content_type, 'Authorization': 'Bearer secret',
                                    'Cookie': 'private', 'Set-Cookie': 'secret'},
                           raw_content=body, content=body, **extra)


def flow():
    return SimpleNamespace(id='flow-1', metadata={},
                           request=message(b'{"token":"secret","court":3}', host='api.example.test',
                                           pretty_url='https://api.example.test/courts?token=secret',
                                           method='POST', timestamp_start=100),
                           response=message(b'{"status":"busy"}', status_code=503, timestamp_end=101.25),
                           error=None)


class ApiCaptureTests(unittest.TestCase):
    def test_api_options_require_capture_host_and_valid_port(self):
        for options in (['--api-bodies'], ['--api-host', 'api.test'],
                        ['--capture-api', '--api-bodies'], ['--api-port', '65536']):
            with self.subTest(options=options), \
                    patch('sys.argv', ['open_booking.py'] + options), \
                    patch('sys.stderr', io.StringIO()), \
                    patch('bkk_active.cli.execute_run') as execute:
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)
                execute.assert_not_called()

    def test_capture_does_not_replace_an_existing_reverse_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            artifacts = RunArtifacts(folder)
            config = SimpleNamespace(serial='test', date=date(2026, 10, 14), api_port=18080)
            capture = ApiCapture(artifacts, config)
            with patch.object(capture, 'command', side_effect=['device', 'test tcp:18080 tcp:9000']) as command, \
                    patch('bkk_active.api_capture.shutil.which', return_value='/fake/mitmdump'), \
                    patch('bkk_active.api_capture.Path.is_file', return_value=True), \
                    patch('bkk_active.api_capture.PROJECT_ROOT', Path(folder)), \
                    patch('bkk_active.api_capture.subprocess.Popen') as process:
                with self.assertRaisesRegex(RuntimeError, 'ใช้อยู่แล้ว'):
                    with capture:
                        pass
                process.assert_not_called()
                self.assertEqual(command.call_count, 2)

    def test_request_context_stays_fixed_after_ui_changes(self):
        with tempfile.TemporaryDirectory() as parent:
            folder = Path(parent)
            context = folder / 'api-context.json'
            context.write_text(json.dumps({'step': 'court-schedule', 'court': 3,
                                           'booking_date': '2026-10-15'}))
            recorder = ApiEvents(folder)
            request = flow()
            recorder.request(request)
            context.write_text(json.dumps({'step': 'back-to-courts', 'court': 4}))
            recorder.finished(request)
            events = [json.loads(line) for line in (folder / 'api.jsonl').read_text().splitlines()]
            self.assertEqual(events[0]['context'], events[1]['context'])
            self.assertEqual(events[1]['duration_ms'], 1250)
            self.assertEqual(events[1]['status_code'], 503)
            self.assertNotIn('secret', (folder / 'api.jsonl').read_text())
            self.assertNotIn('body', events[0])
            self.assertEqual(recorder.summary()['unfinished_requests'], 0)

    def test_redacts_credentials_and_nested_personal_fields(self):
        info = message_info(message(json.dumps({'court': 3, 'access_token': 'secret',
                                                'data': [{'email': 'person@example.test',
                                                          'fullName': 'Someone', 'phone': '0812345678'}]}).encode()), True)
        self.assertEqual(info['body']['court'], 3)
        self.assertEqual(info['body']['access_token'], REDACTED)
        self.assertEqual(info['body']['data'][0], dict.fromkeys(('email', 'fullName', 'phone'), REDACTED))
        self.assertEqual(set(info['headers']), {'content-type'})
        for body, kind in ((b'private', 'text/plain'), (b'invalid', 'application/json'),
                           (b'x' * 65537, 'application/json')):
            self.assertIn('body_omitted', message_info(message(body, kind), True))
        self.assertNotIn('secret', json.dumps(message_info(message(b'token=secret&court=3',
                                                        'application/x-www-form-urlencoded'), True)))

    def test_url_removes_auth_query_fragment_and_long_ids(self):
        url = safe_url('https://user:secret@api.example.test/users/123456789?auth=secret#private')
        self.assertNotIn('secret', url)
        self.assertNotIn('private', url)
        self.assertNotIn('123456789', url)

    def test_host_filter_pending_and_connection_error(self):
        with tempfile.TemporaryDirectory() as parent:
            recorder = ApiEvents(parent, hosts=['other.example.test'])
            request = flow()
            recorder.request(request)
            self.assertFalse((Path(parent) / 'api.jsonl').exists())
            recorder.hosts = {'api.example.test'}
            recorder.request(request)
            self.assertEqual(recorder.summary()['unfinished_requests'], 1)
            request.response = None
            request.error = SimpleNamespace(timestamp=103, msg='secret error URL')
            recorder.finished(request, failed=True)
            self.assertEqual(recorder.summary()['counts']['error'], 1)
            self.assertNotIn('secret error', (Path(parent) / 'api.jsonl').read_text())

    def test_tls_failure_is_distinct_from_http_response(self):
        with tempfile.TemporaryDirectory() as parent:
            events = ApiEvents(parent)
            data = SimpleNamespace(context=SimpleNamespace(server=SimpleNamespace(address=('api.test', 443))))
            events.tls_failed(data, 'client')
            self.assertEqual(events.summary()['counts'], {'tls_error': 1})
            self.assertFalse(events.summary()['http_visible'])

    def test_artifact_context_updates_day_court_step_and_attempt(self):
        with tempfile.TemporaryDirectory() as parent:
            artifacts = RunArtifacts(parent)
            artifacts.api_context_file = artifacts.folder / 'api-context.json'
            config = SimpleNamespace(serial='test', date=date(2026, 10, 14))
            artifacts.set_api_context(config, 3)
            artifacts.attempt = 2
            artifacts.set_step('court-list/court-schedule')
            data = json.loads(artifacts.api_context_file.read_text())
            self.assertEqual((data['court'], data['attempt'], data['step']), (3, 2, 'court-list/court-schedule'))
            config.date = date(2026, 10, 15)
            artifacts.set_api_context(config)
            self.assertIsNone(json.loads(artifacts.api_context_file.read_text())['court'])

    def run_capture(self, folder, previous='null', body_error=False, fail_write=False):
        artifacts = RunArtifacts(folder)
        config = SimpleNamespace(serial='test', date=date(2026, 10, 14), api_port=18080)
        capture = ApiCapture(artifacts, config)
        commands = []
        processes = []

        def command(*args):
            commands.append(args)
            if args == ('get-state',):
                return 'device'
            if args == ('reverse', '--list'):
                return ''
            if args == ('shell', 'settings', 'get', 'global', 'http_proxy'):
                return previous
            if fail_write and args[-1] == '127.0.0.1:18080':
                raise subprocess.TimeoutExpired('adb', 15)
            return ''

        def start(*args, **kwargs):
            (artifacts.folder / '.api-ready').touch()
            process = Mock()
            process.poll.return_value = None
            processes.append(process)
            return process

        with patch.object(capture, 'command', side_effect=command), \
                patch('bkk_active.api_capture.shutil.which', return_value='/fake/mitmdump'), \
                patch('bkk_active.api_capture.Path.is_file', return_value=True), \
                patch('bkk_active.api_capture.PROJECT_ROOT', Path(folder)), \
                patch('bkk_active.api_capture.subprocess.Popen', side_effect=start) as popen:
            if body_error or fail_write:
                expected = subprocess.TimeoutExpired if fail_write else RuntimeError
                with self.assertRaises(expected):
                    with capture:
                        raise RuntimeError('booking failed')
            else:
                with capture:
                    pass
        processes[0].terminate.assert_called_once()
        processes[0].wait.assert_called_once_with(timeout=5)
        self.assertIn(('reverse', '--remove', 'tcp:18080'), commands)
        restore = ('shell', 'settings', 'delete', 'global', 'http_proxy') if previous == 'null' else (
            'shell', 'settings', 'put', 'global', 'http_proxy', previous)
        self.assertIn(restore, commands)
        self.assertTrue((artifacts.folder / 'api-summary.json').exists())
        self.assertIsNone(artifacts.api_context_file)

    def test_restores_proxy_on_success_exception_and_partial_startup(self):
        for previous, body_error, fail_write in (('null', False, False), ('old:9999', True, False),
                                                ('null', False, True)):
            with self.subTest(previous=previous, fail_write=fail_write), tempfile.TemporaryDirectory() as folder:
                self.run_capture(folder, previous, body_error, fail_write)
