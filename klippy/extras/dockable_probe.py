# Dockable Probe
#   This provides support for probes that are magnetically coupled
#   to the toolhead and stowed in a dock when not in use and
#
# Copyright (C) 2018-2023  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2021       Paul McGowan <mental405@gmail.com>
# Copyright (C) 2023       Alan Smith <alan@airpost.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import probe
from mcu import MCU_endstop
from math import sin, cos, atan2, pi, sqrt

PROBE_VERIFY_DELAY         = .1

PROBE_UNKNOWN   = 0
PROBE_ATTACHED  = 1
PROBE_DOCKED    = 2

MULTI_OFF       = 0
MULTI_FIRST     = 1
MULTI_ON        = 2

HINT_VERIFICATION_ERROR = """
{0}: A probe attachment verification method
was not provided. A method to verify the probes attachment
state must be specified to prevent unintended behavior.

At least one of the following must be specified:
'check_open_attach', 'probe_sense_pin', 'dock_sense_pin'

Please see {0}.md and config_Reference.md.
"""

HINT_VIRTUAL_ENDSTOP_ERROR = """
{0}: Using a 'probe:z_virtual_endstop' Z endstop is
incompatible with 'attach_route'/'dock_route'
containing a Z coordinate.

If the toolhead doesn't need to move in Z to reach the
dock then no Z coordinate should be specified in
'attach_route'/'dock_route'.

Please see {0}.md and config_Reference.md.
"""

# Helper class to handle polling pins for probe attachment states
class PinPollingHelper:
    def __init__(self, config, endstop):
        self.printer = config.get_printer()
        self.query_endstop = endstop
        self.last_verify_time  = 0
        self.last_verify_state = None

    def query_pin(self, curtime):
        if (curtime > (self.last_verify_time + PROBE_VERIFY_DELAY)
            or self.last_verify_state is None):
            self.last_verify_time = curtime
            toolhead = self.printer.lookup_object('toolhead')
            query_time = toolhead.get_last_move_time()
            self.last_verify_state = not not self.query_endstop(query_time)
        return self.last_verify_state

    def query_pin_inv(self, curtime):
        return not self.query_pin(curtime)

# Helper class to verify probe attachment status
class ProbeState:
    def __init__(self, config, aProbe):
        self.printer = config.get_printer()

        if (not config.fileconfig.has_option(config.section,
                                             'check_open_attach')
            and not config.fileconfig.has_option(config.section,
                                               'probe_sense_pin')
            and not config.fileconfig.has_option(config.section,
                                               'dock_sense_pin')):
            raise self.printer.config_error(HINT_VERIFICATION_ERROR.format(
                aProbe.name))

        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)

        # Configure sense pins as endstops so they
        # can be polled at specific times
        ppins = self.printer.lookup_object('pins')
        def configEndstop(pin):
            pin_params = ppins.lookup_pin(pin,
                                            can_invert=True,
                                            can_pullup=True)
            mcu = pin_params['chip']
            mcu_endstop = mcu.setup_pin('endstop', pin_params)
            helper = PinPollingHelper(config, mcu_endstop.query_endstop)
            return helper

        probe_sense_helper = None
        dock_sense_helper = None

        # Setup sensor pins, if configured, otherwise use probe endstop
        # as a dummy sensor.
        ehelper = PinPollingHelper(config, aProbe.query_endstop)

        # Probe sense pin is optional
        probe_sense_pin = config.get('probe_sense_pin', None)
        if probe_sense_pin is not None:
            probe_sense_helper = configEndstop(probe_sense_pin)
            self.probe_sense_pin = probe_sense_helper.query_pin
        else:
            self.probe_sense_pin = ehelper.query_pin_inv

        # If check_open_attach is specified, it takes precedence
        # over probe_sense_pin
        check_open_attach = None
        if config.fileconfig.has_option(config.section, 'check_open_attach'):
            check_open_attach = config.getboolean('check_open_attach')

            if check_open_attach:
                self.probe_sense_pin = ehelper.query_pin_inv
            else:
                self.probe_sense_pin = ehelper.query_pin

        # Dock sense pin is optional
        self.dock_sense_pin = None
        dock_sense_pin = config.get('dock_sense_pin', None)
        if dock_sense_pin is not None:
            dock_sense_helper = configEndstop(dock_sense_pin)
            self.dock_sense_pin = dock_sense_helper.query_pin

    def _handle_ready(self):
        self.last_verify_time = 0
        self.last_verify_state = PROBE_UNKNOWN

    def get_probe_state(self):
        curtime = self.printer.get_reactor().monotonic()
        return self.get_probe_state_with_time(curtime)

    def get_probe_state_with_time(self, curtime):
        if (self.last_verify_state == PROBE_UNKNOWN
            or curtime > self.last_verify_time + PROBE_VERIFY_DELAY):
            self.last_verify_time = curtime
            self.last_verify_state = PROBE_UNKNOWN

            a = self.probe_sense_pin(curtime)

            if self.dock_sense_pin is not None:
                d = self.dock_sense_pin(curtime)

                if a and not d:
                    self.last_verify_state = PROBE_ATTACHED
                elif d and not a:
                    self.last_verify_state = PROBE_DOCKED
            else:
                if a:
                    self.last_verify_state = PROBE_ATTACHED
                elif not a:
                    self.last_verify_state = PROBE_DOCKED
        return self.last_verify_state

class DockableProbe:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.name = config.get_name()

        # Configuration Options
        self.position_endstop    = config.getfloat('z_offset')
        self.x_offset            = config.getfloat('x_offset', 0.)
        self.y_offset            = config.getfloat('y_offset', 0.)
        self.speed               = config.getfloat('speed', 5.0, above=0.)
        self.lift_speed          = config.getfloat('lift_speed',
                                                   self.speed, above=0.)
        self.dock_retries        = config.getint('dock_retries', 0)
        self.auto_attach_dock    = config.getboolean('auto_attach_dock',
                                                     True)
        self.travel_speed        = config.getfloat('travel_speed',
                                                   self.speed, above=0.)
        self.attach_speed        = config.getfloat('attach_speed',
                                                   self.travel_speed, above=0.)
        self.dock_speed          = config.getfloat('dock_speed',
                                                   self.travel_speed, above=0.)
        self.sample_retract_dist = config.getfloat('sample_retract_dist',
                                                   2., above=0.)

        # Positions (approach, dock, etc)
        self.z_hop               = config.getfloat('z_hop', 0., above=0.)

        self.attach_route        = self._config_getcoordlists(config, 'attach_route')
        self.dock_route          = self._config_getcoordlists(config, 'dock_route')
        self.dock_requires_z     = max(list(map(lambda coords: len(coords),
                                                   self.attach_route + self.dock_route))) > 2

        # Pins
        ppins = self.printer.lookup_object('pins')
        pin = config.get('pin')
        pin_params = ppins.lookup_pin(pin, can_invert=True, can_pullup=True)
        mcu = pin_params['chip']
        mcu.register_config_callback(self._build_config)
        self.mcu_endstop = mcu.setup_pin('endstop', pin_params)

        # Wrappers
        self.get_mcu              = self.mcu_endstop.get_mcu
        self.add_stepper          = self.mcu_endstop.add_stepper
        self.get_steppers         = self.mcu_endstop.get_steppers
        self.home_wait            = self.mcu_endstop.home_wait
        self.query_endstop        = self.mcu_endstop.query_endstop
        self.finish_home_complete = self.wait_trigger_complete = None

        # State
        self.last_z = -9999
        self.multi = MULTI_OFF
        self._last_homed = None
        self._return_pos = None

        pstate = ProbeState(config, self)
        self.get_probe_state = pstate.get_probe_state
        self.last_probe_state = PROBE_UNKNOWN

        self.probe_states = {
            PROBE_ATTACHED: 'ATTACHED',
            PROBE_DOCKED: 'DOCKED',
            PROBE_UNKNOWN: 'UNKNOWN'
        }

        # Gcode Commands
        self.gcode.register_command('QUERY_DOCKABLE_PROBE',
                                    self.cmd_QUERY_DOCKABLE_PROBE,
                                    desc=self.cmd_QUERY_DOCKABLE_PROBE_help)

        self.gcode.register_command('SET_DOCKABLE_PROBE',
                                    self.cmd_SET_DOCKABLE_PROBE,
                                    desc=self.cmd_SET_DOCKABLE_PROBE_help)
        self.gcode.register_command('ATTACH_PROBE',
                                    self.cmd_ATTACH_PROBE,
                                    desc=self.cmd_ATTACH_PROBE_help)
        self.gcode.register_command('DOCK_PROBE',
                                    self.cmd_DOCK_PROBE,
                                    desc=self.cmd_DOCK_PROBE_help)

        # Event Handlers
        self.printer.register_event_handler('klippy:connect',
                                            self._handle_connect)

    def _config_getcoordlists(self, config, name, min_dims=2, max_dims=3):
        val = config.getlists(name, seps=(',', '\n'), parser=float)
        for coord in val:
            if not min_dims <= len(coord) <= max_dims:
                raise config.error("Unable to parse {0} in {1}: {2}".format(name, self.name,
                                "Invalid number of coordinates"))
        return val
    
    def _build_config(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        for stepper in kin.get_steppers():
            if stepper.is_active_axis('z'):
                self.add_stepper(stepper)

    def _handle_connect(self):
        self.toolhead = self.printer.lookup_object('toolhead')

        # If no z hop necessary return early
        if self.z_hop <= 0.0:
            return

        query_endstops = self.printer.lookup_object('query_endstops')
        for endstop, name in query_endstops.endstops:
            if name == 'z':
                # Check for probe being used as virtual endstop
                if not isinstance(endstop, MCU_endstop):
                    raise self.printer.config_error(
                        HINT_VIRTUAL_ENDSTOP_ERROR.format(self.name))

    #######################################################################
    # GCode Commands
    #######################################################################

    cmd_QUERY_DOCKABLE_PROBE_help = ("Prints the current probe state," +
                " valid probe states are UNKNOWN, ATTACHED, and DOCKED")
    def cmd_QUERY_DOCKABLE_PROBE(self, gcmd):
        self.last_probe_state = self.get_probe_state()
        state = self.probe_states[self.last_probe_state]

        gcmd.respond_info('Probe Status: %s' % (state))

    def get_status(self, curtime):
        # Use last_'status' here to be consistent with QUERY_PROBE_'STATUS'.
        return {
            'last_status': self.last_probe_state,
        }

    cmd_SET_DOCKABLE_PROBE_help = "Set probe parameters"
    def cmd_SET_DOCKABLE_PROBE(self, gcmd):
        auto = gcmd.get('AUTO_ATTACH_DOCK', None)
        if auto is None:
            return

        if int(auto) == 1:
            self.auto_attach_dock = True
        else:
            self.auto_attach_dock = False

    cmd_ATTACH_PROBE_help = "Check probe status and attach probe using" \
                            "the movement gcodes"
    def cmd_ATTACH_PROBE(self, gcmd):
        return_pos = self.toolhead.get_position()
        self.attach_probe(return_pos)

    cmd_DOCK_PROBE_help = "Check probe status and dock probe using" \
                            "the movement gcodes"
    def cmd_DOCK_PROBE(self, gcmd):
        return_pos = self.toolhead.get_position()
        self.dock_probe(return_pos)

    def attach_probe(self, return_pos=None):
        retry = 0
        while (self.get_probe_state() != PROBE_ATTACHED
               and retry < self.dock_retries + 1):
            if self.get_probe_state() != PROBE_DOCKED:
                raise self.printer.command_error(
                    'Attach Probe: Probe not detected in dock, aborting')
            
            self._align_z()

            travel = True
            for position in self.attach_route:
                speed = self.travel_speed if travel else self.attach_speed
                travel = False
                z_pos = None if len(position) <= 2 else position[2]
                
                self.toolhead.manual_move([position[0], position[1], z_pos],
                                  speed)

            retry += 1

        if self.get_probe_state() != PROBE_ATTACHED:
            raise self.printer.command_error('Probe attach failed!')
        
        self._align_z()

        if return_pos:
            self.toolhead.manual_move(
                [return_pos[0], return_pos[1], None],
                self.travel_speed)
            # Do NOT return to the original Z position after attach
            # as the probe might crash into the bed.

    def dock_probe(self, return_pos=None):
        retry = 0
        while (self.get_probe_state() != PROBE_DOCKED
               and retry < self.dock_retries + 1):
            
            self._align_z()
            
            travel = True
            for position in self.dock_route:
                speed = self.travel_speed if travel else self.dock_speed
                travel = False
                z_pos = None if len(position) <= 2 else position[2]
                
                self.toolhead.manual_move([position[0], position[1], z_pos],
                                  speed)

            retry += 1

        if self.get_probe_state() != PROBE_DOCKED:
            raise self.printer.command_error('Probe dock failed!')
        
        self._align_z()

        if return_pos:
            self.toolhead.manual_move(
                [return_pos[0], return_pos[1], None],
                self.travel_speed)
            # Return to original Z position after dock as
            # there's no chance of the probe crashing into the bed.
            self.toolhead.manual_move(
                [None, None, return_pos[2]],
                self.travel_speed)

    def auto_dock_probe(self, return_pos=None):
        if self.get_probe_state() == PROBE_DOCKED:
           return
        if self.auto_attach_dock:
            self.dock_probe(return_pos)

    def auto_attach_probe(self, return_pos=None):
        if self.get_probe_state() == PROBE_ATTACHED:
           return
        if not self.auto_attach_dock:
            raise self.printer.command_error("Cannot probe, probe is not " \
                                        "attached and auto-attach is disabled")
        self.attach_probe(return_pos)

    #######################################################################
    # Functions for calculating points and moving the toolhead
    #######################################################################

    # Align z axis to prevent crashes
    def _align_z(self):
        curtime = self.printer.get_reactor().monotonic()
        homed_axes = self.toolhead.get_status(curtime)['homed_axes']
        self._last_homed = homed_axes

        if self.dock_requires_z:
            self._align_z_required()

        if self.z_hop > 0.0:
            if 'z' in self._last_homed:
                tpos = self.toolhead.get_position()
                if tpos[2] < self.z_hop:
                    self.toolhead.manual_move([None, None, self.z_hop],
                        self.lift_speed)
            else:
                self._force_z_hop()

    def _align_z_required(self):
        if 'z' not in self._last_homed:
            raise self.printer.command_error(
                "Cannot attach/detach probe, must home Z axis first")

    # Hop z and return to un-homed state
    def _force_z_hop(self):
        this_z = self.toolhead.get_position()[2]
        if self.last_z == this_z:
            return

        tpos = self.toolhead.get_position()
        self.toolhead.set_position([tpos[0], tpos[1], 0.0, tpos[3]],
                            homing_axes=[2])
        self.toolhead.manual_move([None, None, self.z_hop],
            self.lift_speed)
        kin = self.toolhead.get_kinematics()
        kin.note_z_not_homed()
        self.last_z = self.toolhead.get_position()[2]

    #######################################################################
    # Probe Wrappers
    #######################################################################

    def multi_probe_begin(self):
        self.multi = MULTI_FIRST

        # Attach probe before moving to the first probe point and
        # return to current position. Move because this can be called
        # before a multi _point_ probe and a multi probe at the same
        # point but for the latter the toolhead is already in position.
        # If the toolhead is not returned to the current position it
        # will complete the probing next to the dock.
        self._return_pos = self.toolhead.get_position()
        self.auto_attach_probe()

    def multi_probe_end(self):
        self.multi = MULTI_OFF

        # Move to z hop to ensure the probe isn't triggered,
        # preventing docking in the event there's no probe/dock sensor.
        self._align_z()
        self.auto_dock_probe(self._return_pos)

    def probe_prepare(self, hmove):
        if self.multi == MULTI_OFF or self.multi == MULTI_FIRST:
            if self._return_pos is None:
                self._return_pos = self.toolhead.get_position()
            self.auto_attach_probe()
        if self.multi == MULTI_FIRST:
            self.multi = MULTI_ON

    def probe_finish(self, hmove):
        self.wait_trigger_complete.wait()
        if self.multi == MULTI_OFF:
            # Move to z hop to ensure the probe isn't triggered,
            # preventing docking in the event there's no probe/dock sensor.
            self._align_z()
            self.auto_dock_probe(self._return_pos)

    def home_start(self, print_time, sample_time, sample_count, rest_time,
                   triggered=True):
        self.finish_home_complete = self.mcu_endstop.home_start(
            print_time, sample_time, sample_count, rest_time, triggered)
        r = self.printer.get_reactor()
        self.wait_trigger_complete = r.register_callback(self.wait_for_trigger)
        return self.finish_home_complete

    def wait_for_trigger(self, eventtime):
        self.finish_home_complete.wait()

    def get_position_endstop(self):
        return self.position_endstop

def load_config(config):
    msp = DockableProbe(config)
    config.get_printer().add_object('probe', probe.PrinterProbe(config, msp))
    return msp
