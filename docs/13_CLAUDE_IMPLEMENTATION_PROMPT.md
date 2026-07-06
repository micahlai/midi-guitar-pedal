# Claude Code Implementation Prompt

You are helping implement a Raspberry Pi Zero 2 W based MIDI foot controller.

Before coding, read:
- `01_PROJECT_BRIEF.md`
- `02_HARDWARE_SPEC.md`
- `03_UI_SPEC.md`
- `04_MIDI_SPEC.md`
- `05_CONFIGURATION_WEB_APP_SPEC.md`
- `06_BUTTON_MENU_LOGIC_SPEC.md`
- `07_ACTION_TYPES_SPEC.md`
- `08_EXPRESSION_PEDAL_SPEC.md`
- `09_SOFTWARE_ARCHITECTURE.md`
- `10_ROADMAP_MILESTONES.md`
- `11_PROJECT_STATE.md`

Rules:
1. Treat `11_PROJECT_STATE.md` as the living status file.
2. Update `11_PROJECT_STATE.md` after every meaningful change.
3. Do not skip milestones without noting why.
4. Keep GPIO numbers centralized in one constants file.
5. Keep hardware-dependent code isolated from pure logic.
6. Keep config schema versioned.
7. Prefer small testable modules.
8. Do not assume a desktop environment; target Raspberry Pi OS Lite over SSH.
9. Build the UI for 1920x480 specifically.
10. The controller must support bidirectional MIDI state updates.

Initial task:
Set up the repository skeleton for the project:
- app entrypoint
- config module
- hardware constants
- state manager
- placeholder UI renderer
- placeholder MIDI engine
- placeholder web server
- systemd service file draft
- README with setup commands

Then update `11_PROJECT_STATE.md`.
