"""DNS packet validation and transactional changes, without contacting the school."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from deploy import repair_guest_dns as d


class DNSPacketTests(unittest.TestCase):
    def response(self, record=1, ident=123, flags=0x8180, answers=1):
        question = d.dns_question(d.NAMES[0], record)
        return struct.pack('!6H', ident, flags, 1, answers, 0, 0) + question

    def test_a_reply_and_aaaa_nodata_are_valid(self):
        for record, answers in ((1, 1), (28, 0)):
            d.validate_reply(self.response(record=record, answers=answers), 123, d.dns_question(d.NAMES[0], record), record)

    def test_wrong_transaction_errors_truncation_and_empty_ipv4_are_rejected(self):
        question = d.dns_question(d.NAMES[0], 1)
        responses = (b'invalid', self.response(ident=124), self.response(flags=0x8182),
                     self.response(flags=0x8380), self.response(flags=0x9180), self.response(answers=0), self.response(record=28))
        for response in responses:
            with self.subTest(response=response), self.assertRaises(d.DNSError):
                d.validate_reply(response, 123, question, 1)

    @patch.object(d.socket, 'socket')
    @patch.object(d.secrets, 'randbelow', return_value=123)
    def test_both_record_types_must_respond_before_server_is_selected(self, random, factory):
        stream = factory.return_value.__enter__.return_value
        stream.recv.side_effect = [self.response(), self.response(record=28, answers=0)]
        d.probe_server('8.8.8.8')
        self.assertEqual(stream.send.call_count, 2)
        self.assertEqual(stream.connect.call_args.args[0], ('8.8.8.8', 53))
        stream.recv.side_effect = [self.response(), TimeoutError('AAAA timeout')]
        with self.assertRaises(TimeoutError): d.probe_server('8.8.8.8')


class GuardTests(unittest.TestCase):
    @patch.object(d.os, 'geteuid', return_value=0)
    @patch.object(d.socket, 'gethostname', return_value='pve')
    @patch.object(d, 'run')
    def test_proxmox_host_is_rejected_before_any_command(self, run, hostname, uid):
        with self.assertRaises(d.DNSError): d.guest_interface()
        run.assert_not_called()

    @patch.object(d.os, 'geteuid', return_value=0)
    @patch.object(d.socket, 'gethostname', return_value='school-rmm')
    @patch.object(d, 'run')
    def test_ipv4_and_mac_are_read_separately_and_foreign_vm_is_rejected(self, run, hostname, uid):
        network = [json.dumps([{'dev':'eth0', 'gateway':'192.168.16.1'}]),
                   json.dumps([{'addr_info':[{'family':'inet', 'local':'192.168.18.2'}]}]),
                   json.dumps([{'address':d.EXPECTED_MAC}])]
        run.side_effect = network
        self.assertEqual(d.guest_interface(), ('eth0', '192.168.16.1'))
        run.side_effect = network[:2] + [json.dumps([{'address':'00:00:00:00:00:01'}])]
        with self.assertRaises(d.DNSError): d.guest_interface()


class DNSChangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root/'etc/resolved.conf.d/90-school-rmm-dns.conf'
        self.backups = self.root/'backups'

    @patch.object(d, 'run', return_value='Link 2 (eth0): 10.76.10.19 10.76.10.20\n')
    @patch.object(d, 'native_dns_works', return_value=True)
    def test_success_persists_only_owned_vm_dns_file_and_keeps_previous_copy(self, native, run):
        self.target.parent.mkdir(parents=True)
        self.target.write_text('# previous DNS config\n')
        other = self.target.parent/'10-existing.conf'
        other.write_text('# preserve unrelated settings\n')
        d.apply_dns('8.8.8.8', self.target, self.backups)
        self.assertIn('DNS=8.8.8.8\nDomains=~.\n', self.target.read_text())
        self.assertEqual(other.read_text(), '# preserve unrelated settings\n')
        self.assertEqual(next(self.backups.glob('*/90-school-rmm-dns.conf')).read_text(), '# previous DNS config\n')
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands, [['resolvectl','dns'], ['systemctl','restart','systemd-resolved'], ['resolvectl','flush-caches']])

    @patch.object(d, 'run', return_value='previous DNS')
    @patch.object(d, 'native_dns_works', return_value=False)
    def test_failed_verification_restores_existing_content_and_permissions(self, native, run):
        self.target.parent.mkdir(parents=True)
        self.target.write_text('# old setting\n')
        self.target.chmod(0o600)
        with self.assertRaises(d.DNSError): d.apply_dns('8.8.8.8', self.target, self.backups)
        self.assertEqual(self.target.read_text(), '# old setting\n')
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)

    @patch.object(d, 'run', return_value='previous DNS')
    @patch.object(d, 'native_dns_works', return_value=False)
    def test_failed_verification_removes_only_new_dropin(self, native, run):
        with self.assertRaises(d.DNSError): d.apply_dns('8.8.8.8', self.target, self.backups)
        self.assertFalse(self.target.exists())
        self.assertTrue(next(self.backups.glob('*/previous-dns.txt')).is_file())

    @patch.object(d, 'run')
    def test_symlink_and_invalid_server_are_rejected_before_commands(self, run):
        self.target.parent.mkdir(parents=True)
        other = self.root/'other'
        other.write_text('preserve')
        self.target.symlink_to(other)
        with self.assertRaises(d.DNSError): d.apply_dns('8.8.8.8', self.target, self.backups)
        with self.assertRaises(ValueError): d.apply_dns('8.8.8.8\nDomains=bad', self.target, self.backups)
        self.assertEqual(other.read_text(), 'preserve')
        run.assert_not_called()


class SelectionTests(unittest.TestCase):
    @patch.object(d, 'guest_interface', return_value=('eth0', '192.168.16.1'))
    @patch.object(d, 'run', return_value='Global:\nLink 2 (eth0): 10.76.10.19 10.76.10.20')
    @patch.object(d, 'native_dns_works', return_value=False)
    @patch.object(d, 'probe_server')
    @patch.object(d, 'apply_dns')
    def test_only_tested_fallback_is_applied_after_configured_servers_fail(self, apply, probe, native, run, guest):
        probe.side_effect = [TimeoutError('no DNS reply')]*4 + [None]
        with patch.object(d.sys, 'argv', ['repair_guest_dns.py', '--apply']):
            d.main()
        self.assertEqual([call.args[0] for call in probe.call_args_list],
                         ['10.76.10.19','10.76.10.20','192.168.16.1','192.168.0.1','8.8.8.8'])
        apply.assert_called_once_with('8.8.8.8')

    @patch.object(d, 'guest_interface', return_value=('eth0', '192.168.16.1'))
    @patch.object(d, 'run', return_value='Link 2 (eth0): 10.76.10.19')
    @patch.object(d, 'native_dns_works', return_value=False)
    @patch.object(d, 'probe_server', side_effect=TimeoutError('no DNS reply'))
    @patch.object(d, 'apply_dns')
    def test_no_response_stops_without_any_configuration_change(self, apply, probe, native, run, guest):
        with patch.object(d.sys, 'argv', ['repair_guest_dns.py', '--apply']), self.assertRaises(d.DNSError):
            d.main()
        apply.assert_not_called()

    @patch.object(d, 'guest_interface', return_value=('eth0', '192.168.16.1'))
    @patch.object(d, 'run', return_value='Link 2 (eth0): 10.76.10.19')
    @patch.object(d, 'native_dns_works')
    @patch.object(d, 'probe_server')
    @patch.object(d, 'apply_dns')
    def test_working_dns_and_diagnostic_mode_preserve_existing_configuration(self, apply, probe, native, run, guest):
        native.return_value = True
        with patch.object(d.sys, 'argv', ['repair_guest_dns.py', '--apply']):
            d.main()
        probe.assert_not_called()
        apply.assert_not_called()
        native.return_value = False
        with patch.object(d.sys, 'argv', ['repair_guest_dns.py']):
            d.main()
        probe.assert_called_once_with('10.76.10.19')
        apply.assert_not_called()


if __name__ == '__main__':
    unittest.main()
