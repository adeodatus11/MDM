"""Local safety tests with a simulated Proxmox CLI. No hypervisor connection is made."""
import base64
import json
from pathlib import Path
import tempfile
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
        config = p.guest_config(b"public source archive", "192.168.17.206")
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
        p.create_vm(self.root, b"source", self.root/"image", "192.168.17.206")
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
            p.create_vm(self.root, b"source", self.root/"image", "192.168.17.206")
        commands = [call.args[0][:2] for call in run.call_args_list]
        self.assertNotIn(["qm","set"],commands)
        self.assertNotIn(["qm","start"],commands)

    @patch.object(p,"run")
    @patch.object(p,"api")
    def test_existing_snippet_storage_is_not_overwritten(self, api, run):
        api.return_value = [{"storage":p.SNIPPET_STORAGE}]
        with self.assertRaises(p.InstallError):
            p.create_vm(self.root, b"source", self.root/"image", "192.168.17.206")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
