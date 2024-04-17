# Dockable Probe

Dockable probes are typically microswitches mounted to a printed body that
attaches to the toolhead through some means of mechanical coupling.
This coupling is commonly done with magnets though there is support for
a variety of designs including servo and stepper actuated couplings.

## Basic Configuration

To use a dockable probe the following options are required at a minimum.
Some users may be transitioning from a macro based set of commands and
many of the options for the `[probe]` config section are the same.
The `[dockable_probe]` module is first and foremost a `[probe]`
but with additional functionality. Any options that can be specified
for `[probe]` are valid for `[dockable_probe]`.

```
[dockable_probe]
pin:
z_offset:
sample_retract_dist:
attach_route:
dock_route:
(check_open_attach: OR probe_sense_pin:) AND/OR dock_sense_pin:
```

### Attaching and Docking Routes

- `attach_route:`\
  _Required_\
  This is the route of coordinates the toolhead follows in order to attach
  the probe. Each line contains X, Y, and optional Z, separated by commas.
  
  The most common dock designs use a fork or arms that extend out from the dock.
  In order to attach the probe to the toolhead, the toolhead must move into and
  away from the dock to a particular position so these arms can capture the
  probe body.

  Many configurations have the dock attached to a moving gantry. This
  means that Z axis positioning is irrelevant. However, it may be necessary
  to move the gantry clear of the bed or other printer components before
  performing docking steps. In this case, specify `z_hop` to force a Z movement.

  Other configurations may have the dock mounted next to the printer bed so
  that the Z position _must_ be known prior to attaching the probe. In this
  configuration the Z axis parameter _must_ be supplied, and the Z axis
  _must_ be homed prior to attaching the probe.

- `dock_route:`
  _Required_\
  Identical to `attach_route`, but used for putting the probe back into the dock.

  Most probes with magnets require the toolhead to move in a direction that
  strips the magnets off with a sliding motion. This is to prevent the magnets
  from becoming unseated from repeated pulling and thus affecting probe accuracy.
  When creating the `dock_route` make sure that decoupling happens perpendicular
  to the dock so that when the toolhead moves, the probe stays docked but cleanly
  detaches from the toolhead mount.

- `z_hop: 15.0`\
  _Default Value: None_\
  Distance (in mm) to lift the Z axis prior to attaching/docking the probe.
  If the Z axis is already homed and the current Z position is less
  than `z_hop`, then this will lift the head to a height of `z_hop`. If
  the Z axis is not already homed the head is lifted by `z_hop`.
  The default is to not implement Z hop.

## Position Examples

Probe mounted on frame at back of print bed at a fixed Z position. To attach
the probe, the toolhead will move back and then forward. To detach, the toolhead
will move back, and then to the side.

```
+--------+
|   p>   |
|   ^    |
|        |
+--------+
```

```
attach_route:
  150, 300, 5
  150, 330, 5
  150, 300
dock_route:
  150, 300, 5
  150, 330, 5
  170, 330
```


Probe mounted at side of moving gantry with fixed bed. Here the probe is
attachable regardless of the Z position. To attach the probe, the toolhead will
move to the side and back. To detach the toolhead will move to the side and then
forward.

```
+--------+
|        |
| p<     |
| v      |
+--------+
```

```
attach_route:
  50, 150
  10, 150
  50, 150
dock_route:
  50, 150
  10, 150
  10, 130
```


Probe mounted at side of fixed gantry with bed moving on Z. Probe is attachable
regardless of Z but force Z hop for safety. The toolhead movement is the same
as above.

```
+--------+
|        |
| p<     |
| v      |
+--------+
```

```
attach_route:
  50, 150
  10, 150
  50, 150
dock_route:
  50, 150
  10, 150
  10, 130
z_hop: 15
```


Euclid style probe that requires the attach and dock movements to happen in
opposite order. To attach the probe, the toolhead will move to the side and forward.
To detach, the toolhead will move back, and then to the side.

```
Attach:
+--------+
|        |
| p<     |
| v      |
+--------+
Dock:
+--------+
|        |
| p>     |
| ^      |
+--------+
```

```
attach_route:
  50, 150
  10, 150
  10, 130
dock_route:
  10, 130
  10, 150
  50, 150
z_hop: 15
```

### Homing

No configuration specific to the dockable probe is required when using
the probe as a virtual endstop, though it's recommended to consider
using `[safe_z_home]` or `[homing_override]`.

### Probe Attachment Verification

Given the nature of this type of probe, it is necessary to verify whether or
not it has successfully attached prior to attempting a probing move. Several
methods can be used to verify probe attachment states.

- `check_open_attach:`\
  _Default Value: None_\
  Certain probes will report `OPEN` when they are attached and `TRIGGERED`
  when they are detached in a non-probing state. When `check_open_attach` is
  set to `True`, the state of the probe pin is checked after performing a
  probe attach or detach maneuver. If the probe does not read `OPEN`
  immediately after attaching the probe, an error will be raised and any
  further action will be aborted.

  This is intended to prevent crashing the nozzle into the bed since it is
  assumed if the probe pin reads `TRIGGERED` prior to probing, the probe is
  not attached.

  Setting this to `False` will cause all action to be aborted if the probe
  does not read `TRIGGERED` after attaching.

- `probe_sense_pin:`\
  _Default Value: None_\
  The probe may include a separate pin for attachment verification. This is a
  standard pin definition, similar to an endstop pin that defines how to handle
  the input from the sensor. Much like the `check_open_attach` option, the check
  is done immediately after the tool attaches or detaches the probe. If the
  probe is not detected after attempting to attach it, or it remains attached
  after attempting to detach it, an error will be raised and further
  action aborted.

- `dock_sense_pin:`\
  _Default Value: None_\
  Docks can have a sensor or switch incorporated into their design in
  order to report that the probe is presently located in the dock. A
  `dock_sense_pin` can be used to provide verification that the probe is
  correctly positioned in the dock. This is a standard pin definition similar
  to an endstop pin that defines how to handle the input from the sensor.
  Prior to attempting to attach the probe, and after attempting to detach it,
  this pin is checked. If the probe is not detected in the dock, an error will
  be raised and further action aborted.

- `dock_retries: 5`\
  _Default Value: 0_\
  A magnetic probe may require repeated attempts to attach or detach. If
  `dock_retries` is specified and the probe fails to attach or detach, the
  attach/detach action will be repeated until it succeeds. If the retry limit
  is reached and the probe is still not in the correct state, an error will be
  raised and further action aborted.

## Tool Velocities

- `attach_speed: 5.0`\
  _Default Value: Probe `speed` or 5_\
  Movement speed when attaching the probe during `ATTACH_PROBE`.

- `dock_speed: 5.0`\
  _Default Value: Probe `speed` or 5_\
  Movement speed when docking the probe during `DOCK_PROBE`.

- `travel_speed: 5.0`\
  _Default Value: Probe `speed` or 5_\
  Movement speed when moving to the first position of `attach_route` and
  `dock_route` and returning the toolhead to its previous position after
  attach/detach.

## Dockable Probe Gcodes

### General

`ATTACH_PROBE`

This command will move the toolhead to the dock, attach the probe, and return
it to its previous position. If the probe is already attached, the command
does nothing.

`DOCK_PROBE`

This command will move the toolhead to the dock, dock the probe, and return
it to its previous position. If the probe is already docked, the command
will do nothing.

### Status

`QUERY_DOCKABLE_PROBE`

Responds in the gcode terminal with the current probe status. Valid
states are UNKNOWN, ATTACHED, and DOCKED. This is useful during setup
to confirm probe configuration is working as intended.

`SET_DOCKABLE_PROBE AUTO_ATTACH_DETACH=0|1`

Enable/Disable the automatic attaching/docking of the probe during
actions that require the probe.

This command can be helpful in print-start macros where multiple actions will
be performed with the probe and there's no need to detach the probe.
For example:

```
SET_DOCKABLE_PROBE AUTO_ATTACH_DETACH=0
G28
ATTACH_PROBE                             # Explicitly attach the probe
QUAD_GANTRY_LEVEL                        # Tram the gantry parallel to the bed
BED_MESH_CALIBRATE                       # Create a bed mesh
DOCK_PROBE                               # Manually detach the probe
SET_DOCKABLE_PROBE AUTO_ATTACH_DETACH=1  # Make sure the probe is attached in future
```

## Typical probe execution flow

### Probing is Started:

    - A gcode command requiring the use of the probe is executed.

    - This triggers the probe to attach.

    - If configured, the dock sense pin is checked to see if the probe is
      presently in the dock.

    - The toolhead position is compared to the dock position.

    - The toolhead will go to the first position of `attach_route` at `travel_speed`
      and continue following the given coordinates at `attach_speed`.
      (ATTACH_PROBE)

    - If configured, the probe is checked to see if it is attached.

    - If the probe is not attached, the module may retry until it's attached or
      an error is raised.

    - If configured, the dock sense pin is checked to see if the probe is still
      present, the module may retry until the probe is absent not or an error
      is raised.

    - The probe moves to the first probing point and begins probing.

### Probing is Finished:

    - After the probe is no longer needed, the probe is triggered to detach.

    - The toolhead position is compared to the dock position.

    - The toolhead will go to the first position of `dock_route` at `travel_speed`
      and continue following the given coordinates at `dock_speed`.
      (DOCK_PROBE)

    - If configured, the probe is checked to see if it detached.

    - If the probe did not detach, the module moves the toolhead back to the
      approach vector and may retry until it detaches or an error is raised.

    - If configured, the dock sense pin is checked to see if the probe is
      present in the dock. If it is not the module moves the toolhead back to
      the approach vector and may retry until it detaches or an error is raised.
