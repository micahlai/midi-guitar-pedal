# MIDI Controller Pedal

Raspberry Pi Zero 2 W based MIDI foot controller for guitar rigs (MainStage
focused). 10 footswitches, 1920x480 HDMI display, expression pot via SPI ADC,
USB + BLE MIDI, browser-based configuration. Full specs live in `docs/`.

## Layout

```
app/            Python application (deployed to /opt/midi-controller/app/)
  main.py       entrypoint (systemd runs this)
  hardware/     GPIO/SPI constants and (later) input drivers
  config/       JSON config defaults, load/save
  state/        state manager — single source of truth
  ui/           1920x480 renderer (placeholder)
  midi/         USB/BLE MIDI engine (placeholder)
  web/          configuration web server (placeholder)
systemd/        midi-controller.service unit file
deploy.sh       rsync to the Pi + restart service
docs/           all specifications and project state
```

## Pi setup (one time)

Flash Raspberry Pi OS Lite with SSH + Wi-Fi enabled, then:

```bash
# from this repo on your dev machine ("pedal" is an ~/.ssh/config alias)
ssh pedal '
  sudo mkdir -p /opt/midi-controller/{app,config,assets/images} &&
  sudo chown -R micah:micah /opt/midi-controller &&
  python3 -m venv /opt/midi-controller/venv
'
./deploy.sh
ssh pedal sudo systemctl enable midi-controller
```

## Develop

Edit locally, then:

```bash
./deploy.sh                                   # rsync + restart service
ssh pedal journalctl -u midi-controller -f    # follow logs
```

Runtime config is at `/opt/midi-controller/config/config.json` on the Pi
(created from defaults on first run; deploys never touch it).
