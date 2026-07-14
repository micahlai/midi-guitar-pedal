"""hardware/sysinfo.wifi_connect + the hotspot helpers.

The regression that matters: a saved Wi-Fi profile must survive a failed
connect attempt. The original code deleted the profile on any failure, so one
mistyped password on the pedal destroyed the credentials for the network the
device was reachable on — an unrecoverable lockout on a headless box.
"""

import unittest
from unittest import mock

from hardware import sysinfo


class FakeNmcli:
    """Records nmcli invocations and replays scripted results.

    `profiles` maps profile NAME -> SSID. They are deliberately allowed to
    differ: Raspberry Pi Imager provisions Wi-Fi via netplan, which names the
    profile `netplan-wlan0-<SSID>`, and a name-based lookup would miss it.
    """

    def __init__(self, profiles=None, psk=None):
        self.profiles = dict(profiles or {})
        self.psk = psk
        self.calls = []
        self.connect_code = 0
        self.modify_code = 0

    def __call__(self, *args, timeout=5):
        self.calls.append(args)  # raw, so privilege assertions can see sudo
        if args[:2] == ("sudo", "-n"):
            args = args[2:]
        if args[:4] == ("nmcli", "-t", "-f", "NAME,TYPE"):
            return 0, "\n".join(f"{name}:802-11-wireless"
                                for name in self.profiles), ""
        if args[:3] == ("nmcli", "-g", "802-11-wireless.ssid"):
            return 0, self.profiles.get(args[-1], ""), ""
        if args[:2] == ("nmcli", "-s"):
            return (0, self.psk, "") if self.psk else (1, "", "")
        if "modify" in args:
            return self.modify_code, "", "" if not self.modify_code else "modify failed"
        if "delete" in args:
            self.profiles.pop(args[-1], None)
            return 0, "", ""
        if "up" in args or "connect" in args:
            if self.connect_code == 0:
                if "wifi" in args:  # `dev wifi connect <ssid>` creates a profile
                    self.profiles[args[4]] = args[4]
                return 0, "Connection successfully activated", ""
            return self.connect_code, "", "Error: Secrets were required"
        return 0, "", ""

    def commands(self):
        """The nmcli verbs actually issued, e.g. {'delete', 'modify'}."""
        return {word for call in self.calls for word in call}


class WifiConnectTest(unittest.TestCase):
    def run_connect(self, fake, ssid, password=None):
        with mock.patch.object(sysinfo, "_run_result", fake):
            return sysinfo.wifi_connect(ssid, password)

    # --- the lockout regression ---------------------------------------------

    def test_failed_retype_keeps_the_existing_profile(self):
        fake = FakeNmcli(profiles={"HomeNet": "HomeNet"}, psk="rightpass")
        fake.connect_code = 4
        ok, message = self.run_connect(fake, "HomeNet", "WRONGpass")
        self.assertFalse(ok)
        self.assertEqual(message, "Wrong password")
        self.assertIn("HomeNet", fake.profiles)  # NOT deleted
        self.assertNotIn("delete", fake.commands())

    def test_failed_retype_restores_the_previous_passphrase(self):
        fake = FakeNmcli(profiles={"HomeNet": "HomeNet"}, psk="rightpass")
        fake.connect_code = 4
        self.run_connect(fake, "HomeNet", "WRONGpass")
        modifies = [c for c in fake.calls if "modify" in c]
        self.assertEqual(modifies[-1][-1], "rightpass")

    def test_failed_connect_to_a_new_network_cleans_up_its_own_profile(self):
        """A profile this call created is ours to remove; a pre-existing one
        never is."""
        fake = FakeNmcli(profiles={"HomeNet": "HomeNet"})
        fake.connect_code = 4
        ok, _ = self.run_connect(fake, "CoffeeShop", "guess")
        self.assertFalse(ok)
        self.assertIn("delete", fake.commands())
        self.assertIn("HomeNet", fake.profiles)  # the other one untouched

    def test_netplan_named_profile_is_found_by_ssid(self):
        """The profile a Pi Imager card boots with is named
        `netplan-wlan0-<SSID>`. A name-based lookup misses it, so a retype
        would create a SECOND profile for the same network instead of
        updating the live one — and the rollback would protect the wrong
        thing. Match on the SSID."""
        fake = FakeNmcli(profiles={"netplan-wlan0-Hogwarts": "Hogwarts"},
                         psk="rightpass")
        fake.connect_code = 4
        ok, _ = self.run_connect(fake, "Hogwarts", "WRONGpass")
        self.assertFalse(ok)
        self.assertIn("netplan-wlan0-Hogwarts", fake.profiles)  # survives
        self.assertNotIn("delete", fake.commands())
        # …and the rollback targeted the netplan profile, by its real name.
        modifies = [c for c in fake.calls if "modify" in c]
        self.assertIn("netplan-wlan0-Hogwarts", modifies[-1])
        self.assertEqual(modifies[-1][-1], "rightpass")

    # --- normal paths --------------------------------------------------------

    def test_new_network_connects_via_dev_wifi_connect(self):
        fake = FakeNmcli()
        ok, message = self.run_connect(fake, "CoffeeShop", "hunter2")
        self.assertTrue(ok)
        self.assertEqual(message, "Connected to CoffeeShop")
        self.assertIn("dev", fake.commands())

    def test_existing_profile_without_password_activates_saved_secrets(self):
        fake = FakeNmcli(profiles={"HomeNet": "HomeNet"})
        ok, _ = self.run_connect(fake, "HomeNet")
        self.assertTrue(ok)
        self.assertIn("up", fake.commands())
        self.assertNotIn("modify", fake.commands())

    def test_existing_profile_with_password_updates_in_place(self):
        fake = FakeNmcli(profiles={"HomeNet": "HomeNet"}, psk="oldpass")
        ok, _ = self.run_connect(fake, "HomeNet", "newpass")
        self.assertTrue(ok)
        self.assertIn("modify", fake.commands())
        self.assertNotIn("delete", fake.commands())
        self.assertIn("HomeNet", fake.profiles)


class PrivilegeTest(unittest.TestCase):
    """NetworkManager's polkit policy only authorizes scans/edits for an
    ACTIVE LOCAL SESSION. The controller is a session-less systemd service, so
    an unprivileged scan is refused — and nmcli reports that by printing its
    cached list, i.e. it looks like an empty neighborhood, not an error. Every
    call that scans, mutates NM, or reads its secrets must go through sudo."""

    def assert_sudo(self, fake, verb):
        calls = [c for c in fake.calls if verb in c]
        self.assertTrue(calls, f"no nmcli call containing {verb!r}")
        for call in calls:
            self.assertEqual(call[:2], ("sudo", "-n"),
                             f"{verb} must run as root, got {call}")

    def test_scan_requests_the_rescan_as_root(self):
        fake = FakeNmcli()
        with mock.patch.object(sysinfo, "_run_result", fake), \
                mock.patch.object(sysinfo, "SCAN_SETTLE_SECONDS", 0):
            sysinfo.wifi_scan(force=True)
        self.assert_sudo(fake, "rescan")

    def test_connect_and_psk_read_run_as_root(self):
        fake = FakeNmcli(profiles={"HomeNet": "HomeNet"}, psk="pw")
        with mock.patch.object(sysinfo, "_run_result", fake):
            sysinfo.wifi_connect("HomeNet", "newpass")
        self.assert_sudo(fake, "modify")
        self.assert_sudo(fake, "-s")  # reading the stored passphrase

    def test_hotspot_runs_as_root(self):
        fake = FakeNmcli()
        with mock.patch.object(sysinfo, "_run_result", fake):
            sysinfo.ap_start("GuitarPedal", "pedalsetup")
        self.assert_sudo(fake, "hotspot")


class HotspotTest(unittest.TestCase):
    def test_ap_start_rejects_a_short_password(self):
        with mock.patch.object(sysinfo, "_run_result") as run:
            ok, message = sysinfo.ap_start("GuitarPedal", "short")
            self.assertFalse(ok)
            self.assertEqual(message, "Password must be 8+ chars")
            run.assert_not_called()  # never touch the radio on bad input

    def test_ap_start_disables_autoconnect(self):
        """A hotspot that auto-started on boot would strand the pedal off the
        network it can otherwise reach."""
        fake = FakeNmcli()
        with mock.patch.object(sysinfo, "_run_result", fake):
            ok, _ = sysinfo.ap_start("GuitarPedal", "pedalsetup")
        self.assertTrue(ok)
        modify = [c for c in fake.calls if "modify" in c][-1]
        self.assertIn("connection.autoconnect", modify)
        self.assertEqual(modify[-1], "no")

    def test_ap_stop_reconnects_the_client(self):
        fake = FakeNmcli(profiles={sysinfo.AP_CONNECTION: "GuitarPedal"})
        with mock.patch.object(sysinfo, "_run_result", fake):
            ok, _ = sysinfo.ap_stop()
        self.assertTrue(ok)
        self.assertIn("down", fake.commands())
        self.assertIn("device", fake.commands())  # nmcli device connect wlan0


if __name__ == "__main__":
    unittest.main()
