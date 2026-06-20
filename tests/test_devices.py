import stat
import tempfile
import unittest
from pathlib import Path

from codex_devices import (
    DeviceRecord,
    MeshReadinessReport,
    devices_from_tailscale_status_json,
    import_memory_text,
    local_agent_command,
    local_probe_command,
    load_devices,
    load_memory,
    merge_discovered_devices,
    memory_markdown,
    mesh_readiness_report,
    mesh_state,
    build_mesh_readiness_report,
    mesh_readiness_markdown,
    readiness_from_probe_summary,
    new_device,
    parse_probe_output,
    remote_path_expr,
    remote_agent_command,
    remote_team_dir,
    remote_file_sha256sum_command,
    rsync_memory_command,
    rsync_project_command,
    rsync_team_chat_command,
    rsync_team_chat_pull_command,
    rsync_team_package_command,
    rsync_team_results_command,
    save_devices,
    save_memory,
    ssh_mkdir_command,
    ssh_probe_command,
    ssh_launch_command,
    ssh_test_command,
    tailscale_status_command,
    tailscale_approval_url,
    team_prompt,
    update_device_from_probe,
    upsert_device,
)


class DeviceMeshTests(unittest.TestCase):
    def test_new_device_builds_stable_ssh_target(self) -> None:
        device = new_device(name="Atlas Builder", host="atlas-builder", user="ao", port=2222)

        self.assertTrue(device.id.startswith("atlas-builder-"))
        self.assertEqual(device.target(), "ao@atlas-builder")
        self.assertEqual(device.ssh_prefix(), ("ssh", "-p", "2222", "ao@atlas-builder"))

    def test_device_round_trip_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "devices.json"
            one = new_device(name="Laptop", host="laptop.local", user="ao")
            two = new_device(name="Workstation", host="10.0.0.5", user="ao")

            save_devices(path, upsert_device((one,), two))
            loaded = load_devices(path)

            self.assertEqual([device.name for device in loaded], ["Workstation", "Laptop"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_tailscale_status_json_discovers_magicdns_devices(self) -> None:
        payload = """
        {
          "MagicDNSSuffix": "tailabc.ts.net",
          "Self": {
            "HostName": "ubuntu-aio",
            "DNSName": "atlas-ubuntu.tailabc.ts.net.",
            "OS": "linux",
            "Online": true,
            "TailscaleIPs": ["100.99.25.89", "fd7a:115c:a1e0::1"]
          },
          "Peer": {
            "nodekey:builder": {
              "HostName": "atlas-builder",
              "DNSName": "atlas-builder.tailabc.ts.net.",
              "OS": "linux",
              "Online": true,
              "TailscaleIPs": ["100.66.164.109"]
            },
            "nodekey:cockpit": {
              "HostName": "parrot",
              "DNSName": "atlas-cockpit.tailabc.ts.net.",
              "OS": "linux",
              "Online": false,
              "LastSeen": "2026-06-17T00:24:15.1Z",
              "TailscaleIPs": ["100.73.251.93"]
            }
          }
        }
        """

        devices = devices_from_tailscale_status_json(payload, user="ao")
        by_name = {device.name: device for device in devices}

        self.assertEqual(tailscale_status_command(), ("tailscale", "status", "--json"))
        self.assertEqual([device.name for device in devices], ["atlas-ubuntu", "atlas-builder", "atlas-cockpit"])
        self.assertEqual(by_name["atlas-builder"].host, "atlas-builder.tailabc.ts.net")
        self.assertEqual(by_name["atlas-builder"].target(), "ao@atlas-builder.tailabc.ts.net")
        self.assertEqual(by_name["atlas-builder"].status, "unknown")
        self.assertIn("tailnet online", by_name["atlas-builder"].note)
        self.assertEqual(by_name["atlas-cockpit"].status, "offline")
        self.assertIn("last seen 2026-06-17T00:24:15.1Z", by_name["atlas-cockpit"].note)

    def test_discovered_tailnet_devices_merge_without_losing_probe_status(self) -> None:
        existing = (
            DeviceRecord(
                id="manual-builder",
                name="atlas-builder",
                host="atlas-builder",
                user="ao",
                status="ready",
                note="codex-cli 0.140.0 | project ready",
                updated=1,
            ),
        )
        discovered = (
            DeviceRecord(
                id="discovered-builder",
                name="atlas-builder",
                host="atlas-builder.tailabc.ts.net",
                user="ao",
                status="unknown",
                note="tailnet online | linux | 100.66.164.109",
                updated=2,
            ),
            DeviceRecord(
                id="discovered-cockpit",
                name="atlas-cockpit",
                host="atlas-cockpit.tailabc.ts.net",
                user="ao",
                status="offline",
                note="tailnet offline | linux | 100.73.251.93",
                updated=2,
            ),
        )

        merged = merge_discovered_devices(existing, discovered)
        by_name = {device.name: device for device in merged}

        self.assertEqual(len(merged), 2)
        self.assertEqual(by_name["atlas-builder"].id, "manual-builder")
        self.assertEqual(by_name["atlas-builder"].host, "atlas-builder.tailabc.ts.net")
        self.assertEqual(by_name["atlas-builder"].status, "ready")
        self.assertEqual(by_name["atlas-builder"].note, "codex-cli 0.140.0 | project ready")
        self.assertEqual(by_name["atlas-cockpit"].status, "offline")

    def test_tailnet_discovery_can_filter_to_online_worker_machines(self) -> None:
        payload = """
        {
          "MagicDNSSuffix": "tailabc.ts.net",
          "Self": {
            "HostName": "ubuntu-aio",
            "DNSName": "atlas-ubuntu.tailabc.ts.net.",
            "OS": "linux",
            "Online": true,
            "TailscaleIPs": ["100.99.25.89"]
          },
          "Peer": {
            "nodekey:main": {
              "HostName": "ao",
              "DNSName": "atlas-main.tailabc.ts.net.",
              "OS": "linux",
              "Online": true,
              "TailscaleIPs": ["100.100.175.65"]
            },
            "nodekey:phone": {
              "HostName": "phone",
              "DNSName": "pixel.tailabc.ts.net.",
              "OS": "android",
              "Online": true,
              "TailscaleIPs": ["100.80.10.20"]
            },
            "nodekey:offline": {
              "HostName": "old",
              "DNSName": "old-worker.tailabc.ts.net.",
              "OS": "linux",
              "Online": false,
              "TailscaleIPs": ["100.80.10.21"]
            }
          }
        }
        """

        devices = devices_from_tailscale_status_json(
            payload,
            user="ao",
            include_offline=False,
            worker_os=("linux", "macos"),
        )

        self.assertEqual([device.name for device in devices], ["atlas-ubuntu", "atlas-main"])

    def test_memory_import_save_and_markdown(self) -> None:
        imported = import_memory_text(
            (),
            """
            editor: prefer GTK-native controls
            always run codex doctor before final
            editor: prefer dense professional UI
            """,
            source="chatgpt-summary",
        )

        self.assertEqual(len(imported), 2)
        self.assertEqual(next(item for item in imported if item.key == "editor").value, "prefer dense professional UI")
        rendered = memory_markdown(imported)
        self.assertIn("# Codex Control Portable Memory", rendered)
        self.assertIn("- editor: prefer dense professional UI", rendered)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.md"
            save_memory(path, imported)
            loaded = load_memory(path)

            self.assertEqual([item.key for item in loaded], [item.key for item in imported])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_commands_are_safe_and_explicit(self) -> None:
        device = DeviceRecord(
            id="atlas",
            name="Atlas",
            host="atlas-builder",
            user="ao",
            port=2222,
            project_root="~/Projects/codex-gui",
            codex_bin="~/.local/bin/codex",
        )

        self.assertEqual(ssh_test_command(device)[:4], ("ssh", "-p", "2222", "ao@atlas-builder"))
        launch = " ".join(ssh_launch_command(device))
        sync = rsync_memory_command(Path("/tmp/memory.md"), device)

        self.assertIn("Use the Codex Control portable memory", launch)
        self.assertEqual(sync[0], "rsync")
        self.assertIn("ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -p 2222", sync)
        self.assertIn("--timeout=20", sync)
        self.assertNotIn("password", launch.lower())
        self.assertNotIn("token", launch.lower())

    def test_remote_paths_expand_home_without_breaking_absolute_paths(self) -> None:
        self.assertEqual(remote_path_expr("~/.local/bin/codex"), '"$HOME"/.local/bin/codex')
        self.assertEqual(remote_path_expr("/opt/Codex Bin/codex"), "'/opt/Codex Bin/codex'")

    def test_project_sync_commands_create_remote_root_and_exclude_transients(self) -> None:
        device = DeviceRecord(
            id="builder",
            name="Builder",
            host="builder.tailnet",
            user="ao",
            port=2222,
            project_root="/home/ao/Projects/codex-gui",
        )

        mkdir = ssh_mkdir_command(device, device.project_root)
        sync = rsync_project_command(Path("/var/home/ao/Projects/codex-gui"), device)

        self.assertEqual(mkdir[:4], ("ssh", "-p", "2222", "ao@builder.tailnet"))
        self.assertIn("mkdir -p /home/ao/Projects/codex-gui", mkdir[-1])
        self.assertEqual(sync[0], "rsync")
        self.assertIn("__pycache__/", sync)
        self.assertIn(".pytest_cache/", sync)
        self.assertIn("ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -p 2222", sync)
        self.assertIn("--timeout=20", sync)
        self.assertEqual(sync[-2], "/var/home/ao/Projects/codex-gui/")
        self.assertEqual(sync[-1], "ao@builder.tailnet:/home/ao/Projects/codex-gui/")

    def test_probe_command_and_parser_update_device_status(self) -> None:
        device = DeviceRecord(
            id="atlas",
            name="Atlas",
            host="atlas-builder",
            user="ao",
            port=2222,
            project_root="~/Projects/codex-gui",
            codex_bin="~/.local/bin/codex",
        )
        command = ssh_probe_command(device)

        self.assertEqual(command[0], "ssh")
        self.assertIn("BatchMode=yes", command)
        self.assertIn("ConnectTimeout=8", command)
        self.assertIn("2222", command)
        self.assertIn("ao@atlas-builder", command)
        self.assertIn("bash -lc", command[-1])
        self.assertIn("CODEX_PROBE=1", command[-1])
        self.assertNotIn("token", " ".join(command).lower())

        output = "\n".join([
            "CODEX_PROBE=1",
            "UNAME=Linux x86_64",
            "CODEX_EXIT=0",
            "CODEX_VERSION=codex-cli 0.140.0",
            "PROJECT_ROOT=/home/ao/Projects/codex-gui",
            "PROJECT_EXISTS=yes",
            "PROJECT_PWD=/home/ao/Projects/codex-gui",
            "GIT_STATE=## main | branch=main | changes=0",
            "MEMORY_STATE=present bytes=128",
        ])
        probe = parse_probe_output(device, output, 0, timestamp=123)
        updated = update_device_from_probe(device, probe)

        self.assertEqual(probe.status, "ready")
        self.assertEqual(probe.codex_version, "codex-cli 0.140.0")
        self.assertEqual(probe.project_root, "/home/ao/Projects/codex-gui")
        self.assertEqual(updated.status, "ready")
        self.assertIn("codex-cli 0.140.0", updated.note)

    def test_probe_parser_marks_missing_project_for_review(self) -> None:
        device = DeviceRecord(id="one", name="One", host="one.local", project_root="/missing")
        output = "\n".join([
            "CODEX_EXIT=0",
            "CODEX_VERSION=codex-cli 0.140.0",
            "PROJECT_ROOT=/missing",
            "PROJECT_EXISTS=no",
        ])

        probe = parse_probe_output(device, output, 0, timestamp=123)

        self.assertEqual(probe.status, "review")
        self.assertIn("project missing", probe.summary)

    def test_probe_parser_classifies_tailnet_ssh_auth_blockers(self) -> None:
        device = DeviceRecord(id="main", name="Main", host="atlas-main.tailnet")
        output = "\n".join([
            "# Tailscale SSH requires an additional check.",
            "# To authenticate, visit: https://login.tailscale.com/a/example",
        ])

        probe = parse_probe_output(device, output, 124, timestamp=123)

        self.assertEqual(probe.status, "blocked")
        self.assertEqual(probe.summary, "Tailscale SSH approval required")
        self.assertEqual(tailscale_approval_url(output), "https://login.tailscale.com/a/example")

    def test_probe_parser_classifies_plain_ssh_permission_denied(self) -> None:
        device = DeviceRecord(id="builder", name="Builder", host="atlas-builder.tailnet")

        probe = parse_probe_output(device, "ao@atlas-builder: Permission denied (publickey).", 255, timestamp=123)

        self.assertEqual(probe.status, "blocked")
        self.assertEqual(probe.summary, "SSH auth denied")

    def test_mesh_readiness_report_categorizes_ssh_resolution_failure(self) -> None:
        device = DeviceRecord(id="builder", name="Builder", host="atlas-builder.tailnet")
        probe = parse_probe_output(
            device,
            "ssh: Could not resolve hostname atlas-builder.tailnet: Name or service not known",
            255,
            timestamp=123,
        )

        report = mesh_readiness_report((device,), {device.id: probe})
        row = report.by_device(device.id)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(probe.status, "blocked")
        self.assertEqual(probe.summary, "SSH host cannot be resolved")
        self.assertEqual(row.status, "blocked")
        self.assertEqual(row.blocker_category, "ssh-host-unresolved")
        self.assertEqual(row.action_priority, 15)
        self.assertTrue(any("Tailnet Discover" in action for action in row.next_actions))

    def test_mesh_readiness_report_categorizes_refused_ssh_service(self) -> None:
        device = DeviceRecord(id="builder", name="Builder", host="atlas-builder.tailnet", port=2222)
        probe = parse_probe_output(
            device,
            "ssh: connect to host atlas-builder.tailnet port 2222: Connection refused",
            255,
            timestamp=123,
        )

        report = mesh_readiness_report((device,), {device.id: probe})
        row = report.by_device(device.id)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(probe.status, "blocked")
        self.assertEqual(probe.summary, "SSH connection refused")
        self.assertEqual(row.blocker_category, "ssh-connection-refused")
        self.assertTrue(any("port 2222" in action for action in row.next_actions))

    def test_mesh_readiness_report_categorizes_unreachable_ssh_host(self) -> None:
        device = DeviceRecord(id="builder", name="Builder", host="atlas-builder.tailnet")
        probe = parse_probe_output(
            device,
            "ssh: connect to host atlas-builder.tailnet port 22: No route to host",
            255,
            timestamp=123,
        )

        report = mesh_readiness_report((device,), {device.id: probe})
        row = report.by_device(device.id)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(probe.status, "offline")
        self.assertEqual(probe.summary, "SSH host unreachable")
        self.assertEqual(row.status, "offline")
        self.assertEqual(row.blocker_category, "ssh-host-unreachable")
        self.assertTrue(any("Tailscale" in action for action in row.next_actions))

    def test_mesh_readiness_report_categorizes_missing_codex(self) -> None:
        device = DeviceRecord(
            id="codex-missing",
            name="Builder",
            host="atlas-builder.tailnet",
            codex_bin="~/.local/bin/codex",
        )

        probe = parse_probe_output(device, "codex executable not found", 127, timestamp=123)
        report = mesh_readiness_report((device,), {device.id: probe})
        row = report.by_device(device.id)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(probe.status, "blocked")
        self.assertEqual(probe.summary, "Codex CLI missing")
        self.assertEqual(row.status, "blocked")
        self.assertEqual(row.blocker_category, "missing-codex")
        self.assertEqual(row.action_priority, 20)
        self.assertTrue(any("Install Codex CLI" in action for action in row.next_actions))

    def test_mesh_readiness_report_categorizes_missing_project(self) -> None:
        device = DeviceRecord(id="one", name="Builder", host="atlas-builder.tailnet", project_root="~/Projects/codex-gui")
        output = "\n".join([
            "CODEX_EXIT=0",
            "CODEX_VERSION=codex-cli 0.140.0",
            "PROJECT_ROOT=~/Projects/codex-gui",
            "PROJECT_EXISTS=no",
        ])

        probe = parse_probe_output(device, output, 0, timestamp=123)
        report = mesh_readiness_report((device,), {device.id: probe})
        row = report.by_device(device.id)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.status, "review")
        self.assertEqual(row.blocker_category, "missing-project")
        self.assertEqual(report.review_count, 1)
        self.assertIn("project missing", row.summary.lower())

    def test_mesh_readiness_report_categorizes_tailscale_approval_blocker(self) -> None:
        device = DeviceRecord(id="two", name="Builder", host="atlas-builder.tailnet")
        output = "\n".join([
            "# Tailscale SSH requires an additional check.",
            "# To authenticate, visit: https://login.tailscale.com/a/example",
        ])

        probe = parse_probe_output(device, output, 124, timestamp=123)
        report = mesh_readiness_report((device,), {device.id: probe})
        row = report.by_device(device.id)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.status, "blocked")
        self.assertEqual(row.blocker_category, "tailscale-approval-required")
        self.assertTrue(any("https://login.tailscale.com/a/example" in action for action in row.next_actions))

    def test_mesh_readiness_report_detects_stale_checkout(self) -> None:
        device = DeviceRecord(id="three", name="Builder", host="atlas-builder.tailnet", project_root="~/Projects/codex-gui")
        output = "\n".join([
            "CODEX_EXIT=0",
            "CODEX_VERSION=codex-cli 0.140.0",
            "PROJECT_ROOT=~/Projects/codex-gui",
            "PROJECT_EXISTS=yes",
            "PROJECT_PWD=~/Projects/codex-gui",
            "GIT_STATE=## HEAD detached at abc123 | branch=abc123 | changes=0",
        ])

        probe = parse_probe_output(device, output, 0, timestamp=123)
        report = mesh_readiness_report((device,), {device.id: probe})
        row = report.by_device(device.id)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.blocker_category, "stale-checkout")
        self.assertEqual(row.status, "review")

    def test_mesh_readiness_report_uses_saved_ready_status_without_probe(self) -> None:
        local = DeviceRecord(id="four", name="Saved Local", host="localhost", status="ready")
        remote = DeviceRecord(id="five", name="Saved Remote", host="atlas-main.tailnet", status="ready")

        local_report = mesh_readiness_report((local,), {})
        local_row = local_report.by_device(local.id)
        self.assertIsNotNone(local_row)
        assert local_row is not None
        self.assertEqual(local_row.status, "ready")
        self.assertIn(local_row.blocker_category, {"ready-saved", "local-ready"})
        self.assertEqual(local_row.action_priority, 90)
        remote_report = mesh_readiness_report((remote,), {})
        remote_row = remote_report.by_device(remote.id)
        self.assertIsNotNone(remote_row)
        assert remote_row is not None
        self.assertEqual(remote_row.status, "review")
        self.assertEqual(remote_row.blocker_category, "needs-probe")
        self.assertLess(remote_row.action_priority, 90)

    def test_mesh_readiness_report_classifies_saved_blocker_notes_without_raw_note(self) -> None:
        auth = DeviceRecord(
            id="auth",
            name="Auth",
            host="atlas-auth.tailnet",
            status="blocked",
            note="ao@atlas-auth: Permission denied (publickey). PRIVATE_RAW_OUTPUT SENSITIVE_MARKER",
        )
        missing_codex = DeviceRecord(
            id="codex",
            name="Codex",
            host="atlas-codex.tailnet",
            status="blocked",
            note="codex executable not found PRIVATE_RAW_OUTPUT",
        )
        stale = DeviceRecord(
            id="stale",
            name="Stale",
            host="atlas-stale.tailnet",
            status="review",
            note="## main...origin/main [behind 1] PRIVATE_RAW_OUTPUT",
        )

        report = mesh_readiness_report((auth, missing_codex, stale), {})
        by_device = {row.device_id: row for row in report.rows}

        self.assertEqual(by_device[auth.id].status, "blocked")
        self.assertEqual(by_device[auth.id].blocker_category, "ssh-auth-denied")
        self.assertEqual(by_device[missing_codex.id].blocker_category, "missing-codex")
        self.assertEqual(by_device[stale.id].status, "review")
        self.assertEqual(by_device[stale.id].blocker_category, "stale-checkout")

        detail = report.detail_text()
        self.assertIn("ssh-auth-denied", detail)
        self.assertIn("missing-codex", detail)
        self.assertIn("stale-checkout", detail)
        self.assertNotIn("PRIVATE_RAW_OUTPUT", detail)
        self.assertNotIn("SENSITIVE_MARKER", detail)
        self.assertNotIn("Permission denied", detail)

    def test_mesh_readiness_report_exposes_action_priority(self) -> None:
        auth_device = DeviceRecord(id="auth", name="Auth", host="atlas-auth.tailnet")
        offline_device = DeviceRecord(id="offline", name="Offline", host="atlas-offline.tailnet", status="offline")
        missing_project_device = DeviceRecord(
            id="project",
            name="Project",
            host="atlas-project.tailnet",
            project_root="~/Projects/codex-gui",
        )
        ready_device = DeviceRecord(id="ready", name="Ready", host="atlas-ready.tailnet", status="ready")
        missing_project_output = "\n".join([
            "CODEX_EXIT=0",
            "CODEX_VERSION=codex-cli 0.140.0",
            "PROJECT_ROOT=~/Projects/codex-gui",
            "PROJECT_EXISTS=no",
        ])
        probes = {
            auth_device.id: parse_probe_output(
                auth_device,
                "ao@atlas-auth: Permission denied (publickey).",
                255,
                timestamp=123,
            ),
            missing_project_device.id: parse_probe_output(
                missing_project_device,
                missing_project_output,
                0,
                timestamp=123,
            ),
        }

        report = mesh_readiness_report(
            (ready_device, missing_project_device, offline_device, auth_device),
            probes,
        )
        by_device = {row.device_id: row for row in report.rows}

        self.assertEqual(by_device[auth_device.id].blocker_category, "ssh-auth-denied")
        self.assertLess(by_device[auth_device.id].action_priority, by_device[offline_device.id].action_priority)
        self.assertLess(by_device[offline_device.id].action_priority, by_device[missing_project_device.id].action_priority)
        self.assertLess(by_device[missing_project_device.id].action_priority, by_device[ready_device.id].action_priority)

    def test_remote_team_commands_use_prompt_files_not_raw_prompt(self) -> None:
        device = DeviceRecord(
            id="builder",
            name="Builder",
            host="builder.tailnet",
            user="ao",
            port=2222,
            project_root="/home/ao/project",
            codex_bin="/home/ao/.local/bin/codex",
        )
        package = rsync_team_package_command(Path("/tmp/team-run"), device, "Run 1")
        collect = rsync_team_results_command(Path("/tmp/team-run"), device, "Run 1")
        launch = remote_agent_command(device, "Run 1", "UI Polish")
        prompt = team_prompt(
            lane_title="UI Polish",
            lane_slug="ui-polish",
            focus="Improve fit and visual hierarchy.",
            base_prompt="secret prompt body should stay in files",
            run_id="Run 1",
            device=device,
            teammates=("Builder on builder",),
            role_id="ui-polish",
            role_title="Product / GTK UX Engineer",
            role_profile="maximum-power",
            role_focus="Refine visual hierarchy.",
            role_boundary="Do not alter backend behavior without signoff.",
        )
        self.assertEqual(remote_team_dir("Run 1"), "~/.config/codex-gui/team/run-1")
        self.assertEqual(package[0], "rsync")
        self.assertEqual(collect[0], "rsync")
        chat_sync = rsync_team_chat_command(Path("/tmp/team-run"), device, "Run 1")
        self.assertEqual(chat_sync[0], "rsync")
        self.assertIn("team-chat.md", " ".join(chat_sync))
        self.assertIn("ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -p 2222", chat_sync)
        chat_pull = rsync_team_chat_pull_command(Path("/tmp/team-run"), device, "Run 1")
        self.assertEqual(chat_pull[0], "rsync")
        self.assertIn("team-chat.md", " ".join(chat_pull))
        self.assertIn("ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -p 2222", chat_pull)
        self.assertIn("ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -p 2222", package)
        self.assertIn("builder.tailnet", launch[3])
        self.assertIn("ensure_team_chat()", launch[-1])
        self.assertIn("# Codex Team Chat", launch[-1])
        self.assertIn("team chat write failed", launch[-1])
        self.assertIn("chmod 600", launch[-1])
        self.assertIn("cat \"$HOME\"/.config/codex-gui/team/run-1/lanes/ui-polish.md", launch[-1])
        self.assertIn("-p \"$role_profile\"", launch[-1])
        self.assertIn("exec -s workspace-write", launch[-1])
        self.assertIn("--add-dir \"$HOME\"/.config/codex-gui/team/run-1/out", launch[-1])
        self.assertIn("--output-last-message", launch[-1])
        self.assertIn("ui-polish.status.txt", launch[-1])
        self.assertNotIn("> \"$HOME\"/.config/codex-gui/team/run-1/out/ui-polish.handoff.md", launch[-1])
        self.assertNotIn("secret prompt body", " ".join(launch))
        self.assertIn("Team protocol", prompt)
        self.assertIn("secret prompt body should stay in files", prompt)
        self.assertIn("Assigned role: Product / GTK UX Engineer", prompt)
        self.assertIn("Role preset: maximum-power", prompt)
        self.assertIn("Role focus: Refine visual hierarchy.", prompt)
        self.assertIn("Role boundary: Do not alter backend behavior without signoff.", prompt)
        self.assertIn("team-chat.md", prompt)

    def test_remote_sha256sum_command_targets_expected_remote_path(self) -> None:
        device = DeviceRecord(id="builder", name="Builder", host="builder.tailnet", user="ao", port=2222)
        command = remote_file_sha256sum_command(device, "~/.config/codex-gui/team/run-1/out/handoff-bus.md")
        command_text = " ".join(command)

        self.assertEqual(command[:3], ("ssh", "-p", "2222"))
        self.assertIn("sha256sum", command_text)
        self.assertIn("handoff-bus.md", command_text)
        self.assertIn("missing", command_text)

    def test_local_team_commands_skip_ssh_but_use_same_prompt_files(self) -> None:
        device = DeviceRecord(
            id="local",
            name="This Device",
            host="localhost",
            project_root="/home/ao/project",
            codex_bin="/home/ao/.local/bin/codex",
        )
        probe = local_probe_command(device)
        launch = local_agent_command(device, "Run 1", "Coordinator")

        self.assertEqual(probe[:2], ("bash", "-lc"))
        self.assertIn("CODEX_PROBE=1", probe[-1])
        self.assertEqual(launch[:2], ("bash", "-lc"))
        self.assertIn("ensure_team_chat()", launch[-1])
        self.assertIn("cat \"$HOME\"/.config/codex-gui/team/run-1/lanes/coordinator.md", launch[-1])
        self.assertIn("exec -s workspace-write", launch[-1])
        self.assertIn("--add-dir \"$HOME\"/.config/codex-gui/team/run-1/out", launch[-1])
        self.assertIn("--output-last-message", launch[-1])
        self.assertNotIn("ssh", launch[0])

    def test_mesh_summary_counts_ready_devices_and_memories(self) -> None:
        devices = (
            DeviceRecord(id="one", name="One", host="one.local", status="ready"),
            DeviceRecord(id="two", name="Two", host="two.local", status="unknown"),
        )
        memories = import_memory_text((), "profile: maximum-power")

        self.assertEqual(mesh_state(devices, memories).summary(), "2 device(s) | 1 ready | 1 memory item(s)")

    def test_readiness_classification_for_fleet_blockers(self) -> None:
        devices = (
            DeviceRecord(
                id="local", name="Local", host="localhost", user="", status="ready",
                note="local execution path",
            ),
            DeviceRecord(
                id="auth", name="Builder", host="atlas-builder", status="blocked",
                note="ao@atlas-builder: Permission denied (publickey).",
            ),
            DeviceRecord(
                id="approve", name="Main", host="atlas-main", status="blocked",
                note="# Tailscale SSH requires an additional check.",
            ),
            DeviceRecord(
                id="missing", name="Remote", host="atlas-remote", status="review",
                note="Codex ready, project missing: ~/Projects/codex-gui",
            ),
            DeviceRecord(
                id="stale", name="Legacy", host="stale.local", status="ready",
                note="codex-cli 0.150.0 | ## main...origin/main [behind 3]",
            ),
        )

        report = build_mesh_readiness_report(devices)
        summary = report.summary_text()

        self.assertEqual(report.ready_count, 2)
        self.assertEqual(report.warning_count, 2)
        self.assertEqual(report.blocked_count, 2)
        self.assertIn("5 device(s)", summary)

        by_name = {entry.device_name: entry for entry in report.entries}
        self.assertEqual(by_name["Local"].readiness, "local-ready")
        self.assertEqual(by_name["Builder"].readiness, "blocked-ssh-auth")
        self.assertEqual(by_name["Main"].readiness, "blocked-tailscale-approval")
        self.assertEqual(by_name["Remote"].readiness, "missing-project")
        self.assertEqual(by_name["Legacy"].readiness, "stale-checkout")

        markdown = mesh_readiness_markdown(report)
        self.assertIn("# Mesh readiness", markdown)
        self.assertIn("Local (localhost)", markdown)
        self.assertIn("next:", markdown)

    def test_readiness_from_probe_summary_rules(self) -> None:
        self.assertEqual(
            readiness_from_probe_summary("review", "Codex ready, project missing: ~/Projects/codex-gui"),
            (
                "missing-project",
                "Project path missing",
                "Create/sync the project root path and retry Check Fleet.",
            ),
        )
        self.assertEqual(
            readiness_from_probe_summary("blocked", "tailscale ssh requires an additional check"),
            (
                "blocked-tailscale-approval",
                "Tailscale approval required",
                "Approve the Tailscale SSH request from this identity in the browser.",
            ),
        )


if __name__ == "__main__":
    unittest.main()
