# Web Configuration App Specification

## Purpose

The controller hosts a web app accessible over the device network.

The web app allows users to configure:
- all 4 menus
- all 9 assignable buttons per menu
- primary actions
- optional secondary/hold actions
- expression pedal modes
- UI colors
- text labels
- low-resolution image uploads
- shift hold time
- secondary hold time
- expression panel width
- wireless settings

## Top-Level Layout

The web app should have:
1. Top menu tabs:
   - Menu 1
   - Menu 2
   - Menu 3
   - Menu 4

2. Main editor area:
   - shows the 9 assignable buttons for selected menu
   - each button has dropdown for primary action type
   - each button can add/remove a secondary action

3. Right sidebar:
   - expression/potentiometer settings
   - expression display width
   - expression active/current mode preview

## Button Editor

For each of the 9 assignable slots in the active menu:
- show button position
- show current label/image preview
- dropdown: action type
- primary action settings
- button: `Add secondary action`
- if secondary action exists:
  - tabs: `Primary` and `Secondary`
  - remove secondary action button at bottom

## Action Type Options

Primary action types:
- Effect CC
- Action CC
- Program Change
- Expression Pedal Type
- Nothing

Secondary action types:
- Effect CC
- Action CC
- Program Change

Secondary actions:
- no image upload
- text only
- not shown as status color
- shown under main action as `Hold for _____`

## Hold Settings

Global/default:
- default secondary hold time: `1.5 seconds`

Per-button secondary action field:
- hold duration seconds
- default `1.5`

Shift Menu 4 hold:
- default `2.0 seconds`
- configurable in web app

## Effect CC Settings

Fields:
- MIDI channel
- CC code/number
- Off color hex
- On color hex
- Label text OR low-res image upload
- Optional secondary action config

Behavior:
- Send CC on press.
- Listen for return matching CC.
- Save effect status for this button assignment.
- UI status rectangle always follows stored effect status.

## Action CC Settings

Fields:
- MIDI channel
- CC code/number
- Default color hex
- Pressed color hex
- Label text OR low-res image upload
- Optional secondary action config

Behavior:
- Send CC on press.
- Do not listen for return.
- Status rectangle uses pressed/not-pressed state.

## Program Change Settings

Fields:
- MIDI channel
- Program number
- Inactive color hex
- Active color hex
- Patch label text OR low-res image upload
- Optional secondary action config

Behavior:
- Send PC on press.
- Listen for Program Change messages globally.
- Store one global current program number.
- Active color if assigned program equals current program.

## Nothing Settings

Fields:
- Optional label
- Optional disabled color
- No MIDI behavior.

## Image Upload

Low-resolution image can be uploaded for:
- Effect CC primary action
- Action CC primary action
- Program Change primary action
- Expression Pedal type label/image

Secondary actions:
- text only, no image.

Image handling:
- Resize/crop server-side to fit button panels.
- Store in local assets directory.
- Reference by ID/path in config JSON.
