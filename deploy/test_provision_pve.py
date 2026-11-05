"""Local safety tests with a simulated Proxmox CLI. No hypervisor connection is made."""
import base64
import argparse
import hashlib
import io
import json
import shlex
import subprocess
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch
from deploy import provision_pve as p


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.vms = [dict(vmid=i, node="pve", status="running", maxmem=gib*p.GIB)
                    for i,gib in [(100,4), (101,4), (103,48), (102,.5)]]
        self.host = {"memory": {"total": 62*p.GIB, "free": 28*p.GIB}, "cpuinfo": {"cpus": 8}}
        self.storage = [{"storage": "local-zfs", "active": 1, "type": "zfspool", "content": "images,rootdir", "avail": 700*p.GIB}]
        self.network = [{"iface": "vmbr0", "type": "bridge", "active": 1}]

    def check(self):
        p.preflight(self.vms, self.host, self.storage, self.network)

    def test_reported_topology_can_fit_small_vm(self):
        self.check()

    def test_collision_with_vm_or_lxc_is_rejected(self):
        for kind in ("qemu", "lxc"):
            with self.subTest(kind=kind):
                self.vms.append({"vmid":104,"type":kind})
                with self.assertRaises(p.InstallError): self.check()
                self.vms.pop()

    def test_respects_configured_ram_not_just_current_free_ram(self):
        self.vms[-1]["maxmem"] = 4*p.GIB
        with self.assertRaises(p.InstallError): self.check()

    def test_missing_storage_capacity_and_bridge(self):
        self.storage[0]["avail"] = 49*p.GIB
        with self.assertRaises(p.InstallError): self.check()
        self.storage[0]["avail"] = 700*p.GIB
        self.network[0]["active"] = 0
        with self.assertRaises(p.InstallError): self.check()


class ArtifactTests(unittest.TestCase):
    @patch.object(p, "run")
    def test_download_uses_ipv4_preserves_tls_and_publishes_complete_file(self, run):
        def transfer(command, **kwargs):
            self.assertIn("--ipv4", command)
            self.assertNotIn("--insecure", command)
            self.assertNotIn("--noproxy", command)
            self.assertEqual(command[command.index("--proto")+1], "=https")
            self.assertEqual(command[command.index("--proto-redir")+1], "=https")
            Path(command[command.index("--output")+1]).write_bytes(b"complete source")
        run.side_effect = transfer
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"artifact"
            p.download("https://example.com/artifact", output)
            self.assertEqual(output.read_bytes(), b"complete source")
            self.assertEqual(list(Path(directory).iterdir()), [output])

    @patch.object(p, "run")
    def test_failed_download_does_not_leave_a_verified_looking_artifact(self, run):
        run.side_effect = p.InstallError("DNS unavailable")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"artifact"
            with self.assertRaises(p.InstallError):
                p.download("https://example.com/artifact", output)
            self.assertEqual(list(Path(directory).iterdir()), [])

    @patch.object(p, "run")
    def test_download_refuses_http_and_existing_output(self, run):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"artifact"
            output.write_bytes(b"preserve existing data")
            with self.assertRaises(FileExistsError): p.download("https://example.com/artifact", output)
            with self.assertRaises(p.InstallError): p.download("http://example.com/artifact", output)
            self.assertEqual(output.read_bytes(), b"preserve existing data")
            run.assert_not_called()

    def test_checksum_selects_only_exact_image(self):
        sha = "a"*64
        self.assertEqual(p.image_checksum(f"{'b'*64} *other.img\n{sha} *{p.IMAGE_NAME}\n"), sha)
        with self.assertRaises(p.InstallError):
            p.image_checksum(f"{sha} *../{p.IMAGE_NAME}")

    def test_digest_and_no_initial_password_in_guest(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/"file"
            file.write_bytes(b"abc")
            self.assertEqual(p.digest(file), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        config = p.guest_config(b"public source archive")
        self.assertFalse(config["ssh_pwauth"])
        self.assertTrue(config["users"][0]["lock_passwd"])
        self.assertNotIn("password", config["users"][0])
        self.assertEqual(base64.b64decode(config["write_files"][0]["content"]), b"public source archive")
        with self.assertRaises(ValueError): p.guest_config(b"source", "1.2.3.4;reboot")

    @patch.object(p, "run")
    def test_guest_error_exit_code_is_not_treated_as_success(self, run):
        run.return_value = json.dumps({"exited":1,"exitcode":1,"out-data":"looks OK","err-data":"failed"})
        with self.assertRaises(p.InstallError): p.guest_exec(["true"])

    @patch.object(p, "run")
    def test_sensitive_input_is_forwarded_via_stdin_not_command_arguments(self, run):
        run.return_value = json.dumps({"exited":1,"exitcode":0,"out-data":"done"})
        payload = b'{"password":"fixture-only"}'
        self.assertEqual(p.guest_exec(["test-helper"], data=payload), "done")
        self.assertEqual(run.call_args.kwargs["data"], payload)
        self.assertNotIn("fixture-only", " ".join(run.call_args.args[0]))


class CreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/"state").mkdir()
        self.patches = [patch.object(p,"SNIPPET_ROOT",self.root/"snippets"),
                        patch.object(p,"STATE_DIR",self.root/"state")]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    @patch.object(p,"run")
    @patch.object(p,"api")
    def test_only_new_vm_is_modified_and_snapshot_precedes_start(self, api, run):
        api.side_effect = [[], {"unused0":"local-zfs:vm-104-disk-0"}]
        p.create_vm(self.root, b"source", self.root/"image")
        commands = [call.args[0] for call in run.call_args_list]
        vm_commands = [command for command in commands if command[0]=="qm"]
        self.assertTrue(all(command[2]=="104" for command in vm_commands))
        self.assertLess(next(i for i,c in enumerate(commands) if c[:2]==["qm","snapshot"]),
                        next(i for i,c in enumerate(commands) if c[:2]==["qm","start"]))
        self.assertTrue((self.root/"state/104.json").is_file())

    @patch.object(p,"run")
    @patch.object(p,"api")
    def test_foreign_or_ambiguous_import_volume_stops_before_attach_or_start(self, api, run):
        api.side_effect = [[], {"unused0":"local-zfs:vm-100-disk-0"}]
        with self.assertRaises(p.InstallError):
            p.create_vm(self.root, b"source", self.root/"image")
        commands = [call.args[0][:2] for call in run.call_args_list]
        self.assertNotIn(["qm","set"],commands)
        self.assertNotIn(["qm","start"],commands)

    @patch.object(p,"run")
    @patch.object(p,"api")
    def test_existing_snippet_storage_is_not_overwritten(self, api, run):
        api.return_value = [{"storage":p.SNIPPET_STORAGE}]
        with self.assertRaises(p.InstallError):
            p.create_vm(self.root, b"source", self.root/"image")
        run.assert_not_called()


class LANOnlyTests(unittest.TestCase):
    def setUp(self):
        self.files = {item["path"]:item["content"] for item in p.guest_config(b"source")["write_files"]}
        self.firewall = self.files["/usr/local/sbin/school-rmm-firewall"]

    def verdict(self, address):
        # Evaluate the actual generated IPv4 rule list for representative clients.
        import ipaddress
        for line in self.firewall.splitlines():
            if not line.startswith("-A SCHOOL_RMM_WEB "):
                continue
            fields = shlex.split(line)
            if "-s" in fields and ipaddress.ip_address(address) not in ipaddress.ip_network(fields[fields.index("-s")+1]):
                continue
            return fields[fields.index("-j")+1]
        return "NO_RULE"

    def test_school_clients_and_vm_are_in_the_same_slash22(self):
        for address in ("192.168.16.1", "192.168.17.206", "192.168.18.2", "192.168.19.254"):
            with self.subTest(address=address):
                self.assertEqual(self.verdict(address), "RETURN")

    def test_other_private_vpn_and_internet_clients_are_dropped(self):
        for address in ("192.168.0.250", "192.168.15.254", "192.168.20.1", "10.0.0.5", "100.64.0.2", "203.0.113.5"):
            with self.subTest(address=address):
                self.assertEqual(self.verdict(address), "DROP")

    def test_no_existing_connection_or_ssh_peer_exception(self):
        self.assertNotIn("ESTABLISHED", self.firewall)
        self.assertNotIn("SSH_CONNECTION", self.firewall)
        self.assertNotIn("192.168.17.", self.firewall)
        self.assertIn("--dport 22 -j SCHOOL_RMM_WEB", self.firewall)
        self.assertIn("--dport 8443 -j SCHOOL_RMM_WEB", self.firewall)
        self.assertIn("-A SCHOOL_RMM_WEB6 -j DROP", self.firewall)

    def test_firewall_is_required_before_docker_start_and_script_has_valid_syntax(self):
        dependency = self.files["/etc/systemd/system/docker.service.d/school-rmm-firewall.conf"]
        self.assertIn("Requires=school-rmm-firewall.service", dependency)
        self.assertIn("After=school-rmm-firewall.service", dependency)
        unit = self.files["/etc/systemd/system/school-rmm-firewall.service"]
        self.assertIn("Before=docker.service", unit)
        self.assertNotIn("Requires=docker.service", unit)
        subprocess.run(["bash", "-n"], input=self.firewall.encode(), check=True)
        subprocess.run(["bash", "-n"], input=self.files["/usr/local/sbin/school-rmm-firstboot"].encode(), check=True)

    def test_guest_package_installation_uses_supported_apt_ipv4_setting(self):
        self.assertEqual(self.files["/etc/apt/apt.conf.d/99-school-rmm-ipv4"], 'Acquire::ForceIPv4 "true";\n')

    def test_only_explicit_private_networks_are_accepted(self):
        self.assertEqual(p.school_network("192.168.16.0/22"), "192.168.16.0/22")
        for value in ("0.0.0.0/0", "192.168.17.206/22", "127.0.0.0/8", "100.64.0.0/10", "203.0.113.0/24", "::/0", "192.168.16.1;reboot"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                p.school_network(value)

    def test_configured_cidr_controls_firewall_and_readiness_boundaries(self):
        files = {item["path"]:item["content"] for item in p.guest_config(b"source", school_lan="10.20.30.0/24")["write_files"]}
        self.assertIn("-s 10.20.30.0/24 -j RETURN", files["/usr/local/sbin/school-rmm-firewall"])
        self.assertIn("IPv4Network('10.20.30.0/24')", files["/usr/local/sbin/school-rmm-firstboot"])
        self.assertTrue(p.valid_address("192.168.18.2", p.SCHOOL_LAN))
        for value in ("192.168.16.0", "192.168.19.255", "192.168.20.1"):
            self.assertFalse(p.valid_address(value, p.SCHOOL_LAN))


class SourceReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "source.tar.gz"
        with tarfile.open(self.archive, "w:gz") as stream:
            for name, data in (("manage.py", b"print('fixture')\n"), ("deploy/init.py", b"# fixture\n")):
                info = tarfile.TarInfo("revision/" + name)
                info.size, info.mode = len(data), 0o644
                stream.addfile(info, io.BytesIO(data))
        self.checksum = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.app = self.root / "app"

    def prepare(self, checksum=None):
        return subprocess.run(["python3", "-c", p.SOURCE_SETUP, str(self.archive), str(self.app), checksum or self.checksum], capture_output=True, text=True)

    def test_extract_then_resume_preserves_settings_key_database_and_source(self):
        self.assertEqual(self.prepare().returncode, 0)
        settings = {"deploy/.env":b"configured-address", "deploy/runtime/django.key":b"fixture-key", "data/db.sqlite3":b"fixture-db"}
        for name, content in settings.items():
            file = self.app / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
        timestamps = {name:(self.app/name).stat().st_mtime_ns for name in settings}
        original = (self.app/"manage.py").stat().st_mtime_ns
        self.assertEqual(self.prepare().returncode, 0)
        for name, content in settings.items():
            self.assertEqual((self.app/name).read_bytes(), content)
            self.assertEqual((self.app/name).stat().st_mtime_ns, timestamps[name])
        self.assertEqual((self.app/"manage.py").stat().st_mtime_ns, original)

    def test_changed_source_or_corrupt_archive_stops_without_overwriting(self):
        self.assertEqual(self.prepare().returncode, 0)
        source = self.app / "manage.py"
        source.write_bytes(b"preserve local edit")
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Zmieniony", result.stderr)
        self.assertEqual(source.read_bytes(), b"preserve local edit")
        self.assertNotEqual(self.prepare("0"*64).returncode, 0)
        self.assertEqual(source.read_bytes(), b"preserve local edit")

    def test_linked_existing_source_is_not_followed_or_overwritten(self):
        self.assertEqual(self.prepare().returncode, 0)
        source = self.app / "manage.py"
        source.unlink()
        other = self.root / "other"
        other.write_bytes(b"preserve other file")
        source.symlink_to(other)
        self.assertNotEqual(self.prepare().returncode, 0)
        self.assertEqual(other.read_bytes(), b"preserve other file")


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/"104-work").mkdir()
        self.state = {"vmid":104, "marker":"school-rmm-installer:" + "a"*32, "work":str(self.root/"104-work")}
        (self.root/"104.json").write_text(json.dumps(self.state))
        replacement = patch.object(p, "STATE_DIR", self.root)
        replacement.start()
        self.addCleanup(replacement.stop)

    @patch.object(p, "api")
    def test_foreign_vm_and_foreign_work_directory_are_rejected(self, api):
        api.return_value = {"name":"school-rmm", "description":"unrelated VM"}
        with self.assertRaises(p.InstallError): p.owned_state()
        api.return_value["description"] = self.state["marker"]
        self.assertEqual(p.owned_state(), self.state)
        state = dict(self.state, work="/root")
        (self.root/"104.json").write_text(json.dumps(state))
        with self.assertRaises(p.InstallError): p.owned_state()

    @patch.object(p, "guest_exec")
    @patch.object(p, "run")
    @patch.object(p, "api")
    def test_resume_snapshots_owned_vm_then_updates_only_installer_files(self, api, run, guest):
        api.side_effect = [{"name":"school-rmm", "description":self.state["marker"]}, {"status":"running"}]
        events = []
        guest.side_effect = lambda *a, **k: events.append("guest") or "ok"
        run.side_effect = lambda *a, **k: events.append("snapshot") or ""
        state = p.resume_vm(self.state, p.SCHOOL_LAN)
        self.assertEqual(events, ["guest", "snapshot", "guest"])
        self.assertEqual(run.call_args.args[0][:3], ["qm", "snapshot", "104"])
        repair_payload = json.loads(guest.call_args.kwargs["data"])
        paths = {item["path"] for item in repair_payload["files"]}
        self.assertNotIn("/var/lib/school-rmm/source.tar.gz", paths)
        self.assertTrue(all(path.startswith(("/usr/local/sbin/school-rmm-", "/etc/")) for path in paths))
        self.assertIn("--no-block", guest.call_args.args[0][2])
        self.assertEqual(state["school_lan"], "192.168.16.0/22")
        self.assertEqual(json.loads((self.root/"104.json").read_text()), state)

    @patch.object(p, "guest_exec", side_effect=p.InstallError("Źródła zmienione lub cloud-init pracuje"))
    @patch.object(p, "run")
    @patch.object(p, "api")
    def test_failed_read_only_check_stops_before_snapshot_or_repair(self, api, run, guest):
        api.side_effect = [{"name":"school-rmm", "description":self.state["marker"]}, {"status":"running"}]
        with self.assertRaises(p.InstallError): p.resume_vm(self.state, p.SCHOOL_LAN)
        run.assert_not_called()
        self.assertEqual(guest.call_count, 1)

    @patch.object(p, "guest_exec")
    def test_finish_preserves_existing_admin_without_prompt_or_password_reset(self, guest):
        guest.return_value = "RMM_ADMIN_EXISTS\n"
        with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")), patch.object(p.getpass, "getpass", side_effect=AssertionError("Unexpected password prompt")):
            p.bootstrap_admin()
        self.assertEqual(guest.call_count, 1)


class BootDiagnosticsTests(unittest.TestCase):
    @patch.object(p, "guest_exec")
    def test_running_resume_ignores_the_previous_cloud_init_error(self, guest):
        guest.return_value = json.dumps({"returncode":0, "status":"ActiveState=activating", "log":"old cloud-init error"})
        self.assertIsNone(p.installation_failure("school-rmm-resume-fixture.service"))
        command = guest.call_args.args[0]
        self.assertIn("systemctl", command[2])
        self.assertNotIn("cloud-init", command[2])
        self.assertEqual(command[3], "school-rmm-resume-fixture.service")

    @patch.object(p, "installation_failure")
    @patch.object(p, "guest_exec")
    def test_ready_slash22_vm_is_accepted_even_with_historical_cloud_init_error(self, guest, failure):
        status = {"ip":"192.168.18.2", "url":"https://192.168.18.2/", "revision":p.REVISION}
        guest.return_value = json.dumps(status)
        self.assertEqual(p.wait_ready(p.SCHOOL_LAN, "resume.service"), status)
        failure.assert_not_called()

    @patch.object(p, "guest_exec")
    def test_completed_cloud_init_failure_returns_actual_installation_error(self, guest):
        guest.return_value = json.dumps({"returncode":1, "status":"error", "log":"Nieoczekiwana sieć DHCP: 192.168.18.2"})
        self.assertIn("192.168.18.2", p.installation_failure())

    @patch.object(p, "guest_exec")
    def test_unavailable_agent_does_not_claim_cloud_init_failed(self, guest):
        guest.side_effect = p.InstallError("Agent not responding")
        self.assertIsNone(p.installation_failure())

    @patch.object(p.time, "sleep")
    @patch.object(p, "installation_failure", return_value="Nieoczekiwana sieć DHCP: 192.168.18.2")
    @patch.object(p, "guest_exec", side_effect=p.InstallError("Ready file missing"))
    def test_boot_failure_stops_waiting_without_another_25_minute_delay(self, guest, failure, sleep):
        with self.assertRaisesRegex(p.InstallError, "192.168.18.2"):
            p.wait_ready()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
