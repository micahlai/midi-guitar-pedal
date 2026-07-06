# Action Types Specification

## Primary Action Types

### 1. Effect CC

Use case:
- distortion on/off
- delay on/off
- reverb on/off
- any effect state controlled by CC

User fields:
- MIDI channel
- CC code/number
- Off color hex
- On color hex
- Display text OR low-res image
- Optional secondary action

Press behavior:
- send CC message
- expected DAW/MainStage feedback comes back as same CC
- internal effect status updates only from incoming matching CC

State:
- saved effect status per button assignment
- display status rectangle follows effect status

### 2. Action CC

Use case:
- tempo tap
- tuner
- momentary command
- one-way trigger

User fields:
- MIDI channel
- CC code/number
- Color A default
- Color B while pressed
- Display text OR low-res image
- Optional secondary action

Press behavior:
- send CC message
- do not listen for return for this action
- visual state depends only on physical press

### 3. Program Change

Use case:
- patch selection
- song/scene selection

User fields:
- MIDI channel
- Program number
- Inactive color hex
- Active color hex
- Display text OR low-res image
- Optional secondary action

Press behavior:
- send Program Change

Receive behavior:
- listen for any Program Change
- store global current program number
- buttons compare their assigned program to current program

Display:
- active color if assigned program equals current program
- inactive color otherwise

### 4. Expression Pedal Type

Use case:
- select what the potentiometer/expression controls:
  - volume
  - pitch
  - wah

User fields:
- MIDI channel
- CC code/number
- Label text OR low-res image
- Hex color
- Value map min/max
- Reverse bool
- Has home value bool
- Home value int if enabled

Press behavior:
- set current expression mode to this action
- status color shows active expression mode
- expression bar uses this mode's label/color/image
- potentiometer sends CC according to this mode

### 5. Nothing

Use case:
- intentionally blank button

User fields:
- optional label
- optional disabled color

Behavior:
- no MIDI sent
- no MIDI listened for
