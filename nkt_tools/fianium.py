"""
Python module to control NKT Fianium Lasers.

Note: I chose to use specific setter methods over properties so that the user
explicitly has to adjust potentially dangerous conditions
(i.e. laser.set_emission(True)). I felt this style leaves less ambiguity that
the user is actively turning the laser on (vs. laser.emission = True). Less
dangerous properties follow the dedicated setter method format for consistency.
"""
import logging

import nkt_tools.NKTP_DLL as nkt

logger = logging.getLogger(__name__)


class Fianium:
    STATUS_BITS = {
        0: 'Emission on',
        1: 'Interlock relays off',
        2: 'Interlock supply voltage low (possible short circuit)',
        3: 'Interlock loop open',
        4: 'Output Control signal low',
        5: 'Supply voltage low',
        6: 'Inlet temperature out of range',
        7: 'Clock battery low voltage',
        8: 'Date/time not set',
        9: '-',
        10: '-',
        11: '-',
        12: '-',
        13: 'CRC error on startup (possible module address conflict)',
        14: 'Log error code present',
        15: 'System error code present'
        }

    SETUP = {
        0: 'Internal power control mode',
        4: 'External feedback mode',
    }

    INTERLOCK = {
        0: 'Interlock off (interlock circuit open)',
        1: 'Front panel interlock / key switch off',
        2: 'Door switch open',
        3: 'External module interlock',
        4: 'Application interlock',
        5: 'Internal module interlock',
        6: 'Interlock power failure',
        7: 'Interlock disabled by light source'
    }

    def __init__(self, portname=None):
        """
        Searches for connected NKT Fianium lasers and defines instrument parameters.

        Make sure devices are not connected via another program already.
        If multiple Fianium lasers are connected to the same computer,
        specificy the port of the desired laser upon instantiation.

        Parameters
        ----------
        portname : str, optional
            Enter if portname for laser is known/multiple lasers are connected.
            If not supplied, system searches for laser. None by default.

        Raises
        ------
        RuntimeError
            If no laser is found or multiple NKT lasers are found on one computer.
            Supply portname for desired laser if multiple present.
        """
        self._module_type = 0x88
        self._module_address = 0x0F
        self._user_supplied_portname = portname
        self._portname = None

    def connect(self):
        # COM ports to look for NKT devices
        ports_to_check = []
        if self._user_supplied_portname:
            ports_to_check.append(self._user_supplied_portname)
        else:
            ports_to_check += nkt.getAllPorts().split(',')

        logger.info(f'Looking for NKT devices on ports: {ports_to_check}')

        # Attempt to open all potential ports
        nkt.openPorts(','.join(ports_to_check), 1, 1)

        # Collect the ports that were successfully opened
        opened_ports = nkt.getOpenPorts().split(',')
        logger.info(f'Found NKT devices on ports: {opened_ports}')

        # List of ports with confirmed Fianium devices
        device_ports = []

        # Look at each open port
        for port_name in opened_ports:
            # Get array of modules on this bus
            comm_result, dev_list = nkt.deviceGetAllTypes(port_name)
            if comm_result:
                logger.warning(f'Failed opening port [{port_name}] with error code: [{comm_result}]')
                continue
            # Check whether the device_type matches the type for a Fianium laser
            device_type = dev_list[self._module_address]
            if device_type == self._module_type:
                device_ports.append(port_name)

        # Close all unused ports
        ports_to_close = []
        for port_name in opened_ports:
            if port_name not in device_ports[0:1]:
                ports_to_close.append(port_name)
        if len(ports_to_close):
            nkt.closePorts(','.join(ports_to_close))

        if len(device_ports) == 1:
            # Found one device
            self._portname = device_ports[0]
            logger.info(f'Found {self.__class__.__name__} device on port {self._portname}.')
        elif len(device_ports) == 0:
            # Found no devices
            raise RuntimeError(f'No {self.__class__.__name__} device found.')
        elif len(device_ports) > 1:
            # Found multiple devices
            raise RuntimeError(
                f'Multiple {self.__class__.__name__} devices found on ports {device_ports}. '
                'Please initialize with a specific portname to avoid conflict.'
            )

    def disconnect(self):
        if self._portname is not None:
            nkt.closePorts(self._portname)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def _check_comm_result(self, comm_result):
        """Check the return status of a register read."""
        if comm_result == 0:
            return
        elif comm_result == 1:
            raise RuntimeError('Arises from a registerWrite function with index > 0, if the pre-read fails.')
        elif comm_result == 2:
            raise RuntimeError('The function registerCreate has failed.')
        elif comm_result == 3:
            raise RuntimeError('The module has reported a BUSY error, the kernel automatically retries on busy but have given up.')
        elif comm_result == 4:
            raise RuntimeError('The module has Nacked the register, which typically means non existing register.')
        elif comm_result == 5:
            raise RuntimeError('The module has reported a CRC error, which means the received message has CRC errors.')
        elif comm_result == 6:
            raise RuntimeError('The module has not responded in time. A module should respond in max. 75 ms')
        elif comm_result == 7:
            raise RuntimeError('The module has reported a COM error, which typically means out of sync or garbage error.')
        elif comm_result == 8:
            raise RuntimeError('The datatype does not seem to match the register datatype.')
        elif comm_result == 9:
            raise RuntimeError('The index seem to be out of range of the register length.')
        elif comm_result == 10:
            raise RuntimeError('The specified port is closed error. Could happen if the USB is unplugged in the middel of a sequence.')
        elif comm_result == 11:
            raise RuntimeError('The specified register could not be found in the internal register list for the specified device.')
        elif comm_result == 12:
            raise RuntimeError('The specified device could not be found in the internal device list.')
        elif comm_result == 13:
            raise RuntimeError('The specified portname could not be found.')
        elif comm_result == 14:
            raise RuntimeError('The specified portname could not be opened. The port might be in use by another application.')
        elif comm_result == 15:
            raise RuntimeError('The function is not allowed to be invoked from within a callback function.')

    @property
    def emission(self):
        """
        Get the emission state of the laser.

        Return
        ------
        bool
            False = emission off; True = emission on
        """
        register_address = 0x30

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        comm_result, value = nkt.registerReadU8(
            self._portname,
            self._module_address,
            register_address,
            -1
        )
        self._check_comm_result(comm_result)

        if value == 3:
            return True
        elif value == 0:
            return False
        else:
            raise RuntimeError('Unknown emission state detected')

    def set_emission(self, state):
        """
        Change emission state of laser to on/off.

        Parameters
        ----------
        state : bool
            True turns laser on, false turns emission off
        """
        register_address = 0x30

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        if state is True:
            reg_val = 0x03
        else:
            reg_val = 0x00

        comm_result = nkt.registerWriteU8(
            self._portname,
            self._module_address,
            register_address,
            reg_val,
            -1
        )
        self._check_comm_result(comm_result)

        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'emission state to [{state}].')

    @property
    def setup(self):
        """
        Gets the current setup state.

        See SETUP for possible outcomes. Use set_setup() to change value.

        Returns
        -------
        str
            Current setup status of laser based on manual values.
        """
        register_address = 0x31

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        comm_result, setup_key = nkt.registerReadU8(
            self._portname,
            self._module_address,
            register_address,
            -1
        )
        self._check_comm_result(comm_result)

        return self.__class__.SETUP[setup_key]

    def set_setup(self, setup_key):
        """
        Sets the "setup" of the laser according to options in manual.

        Checks value provided is withing SETUP.keys(),
        then writes to register 0x16. Get current status w/ status()

        Parameters
        ----------
        setup_key : int
            Integer corresponding to a key inside SETUP enum.
        """
        register_address = 0x31

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        if setup_key not in self._class__.SETUP.keys():
            raise ValueError('Invalid setup state key. See SETUP enum for options.')

        comm_result = nkt.registerWriteU8(
            self._portname,
            self._module_address,
            register_address,
            setup_key,
            -1
        )
        self._check_comm_result(comm_result)

        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'setup state to [0x{setup_key:02x}] ({self.__class__.SETUP[setup_key]}).')

    @property
    def interlock(self):
        """
        Get the interlock status.

        Manual:
        Reading the interlock register returns the current interlock status,
        which consists of two unsigned bytes. The first byte (LSB) tells if the
        interlock circuit is open or closed. The second byte (MSB) tells where
        the interlock circuit is open, if relevant.

        Return
        ------
        tuple(int, str)
            (LSB, Desription) returns result according to table in manual.
        """
        register_address = 0x32

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        comm_result, reading = nkt.registerRead(
            self._portname,
            self._module_address,
            register_address,
            -1
        )
        self._check_comm_result(comm_result)

        LSB = reading[0]  # First byte
        MSB = reading[1]  # Second byte

        if MSB == 255:
            return (0, f'Interlock circuit failure')
        else:
            if LSB == 0:
                reason = output_options[MSB]
                return (LSB, f'Interlocked: {reason}')
            elif LSB == 1:
                return (LSB, 'Waiting for interlock reset')
            elif LSB == 2:
                return (LSB, 'Interlock is OK')

    def set_interlock(self, value):
        """
        Reset or trip interlock with >0 or 0, respectively.

        Manual:
        If the door interlock is in place, the key switch on the front plate is
        in On position and the External bus is terminated with e.g. a bus
        defeater then the Interlock circuit can be reset via the Interbus
        interface by sending a value greater than 0 to the Interlock register.
        Additionally, the opposite function (switching interlock relays off)
        can be done by sending the value 0 to the interlock register.

        Parameters
        ----------
        value: int
            0 trips interlock. >0 resets interlock.

        """
        register_address = 0x32

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        if value > 0:
            value = 1
        else:
            value = 0

        comm_result = nkt.registerWriteU8(
            self._portname,
            self._module_address,
            register_address,
            value,
            -1
        )
        self._check_comm_result(comm_result)

        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'interlock state to [0x{value:02x}].')

    @property
    def pulse_picker_ratio(self):
        """
        Get pulse picker ratio by reading register 0x34.

        Manual:
        For SuperK Fianium Systems featuring the pulse picker option, the
        divide ratio for the pulse picker can be controlled with the pulse
        picker ratio register.

        Return
        ------
        ratio : int
            Pulse picker divide ratio
        """
        register_address = 0x34

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        comm_result, pulse_picker_ratio = nkt.registerReadU16(
            self._portname,
            self._module_address,
            register_address,
            -1
        )
        self._check_comm_result(comm_result)

        return pulse_picker_ratio

    def set_pulse_picker_ratio(self, ratio):
        """
        Set the pulse rate of the system. The new rate will be (max pulse rate / ratio).

        Manual:
        For SuperK FIANIUM systems featuring the pulse picker option, the division ratio for
        the pulse picker can be controlled with the pulse picker ratio register. 16-bit
        unsigned integer.

        Parameters
        ----------
        ratio : int
            Integer corresponding to the division ratio.
        """
        register_address = 0x34

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        if not isinstance(ratio, int):
            raise ValueError('Pulse picker division ratio must be an integer.')
        if ratio < 1:
            raise ValueError('Pulse picker division ratio must be >= 1.')

        comm_result = nkt.registerWriteU16(
            self._portname,
            self._module_address,
            register_address,
            ratio,
            -1
        )
        self._check_comm_result(comm_result)

        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'pulse picker division ratio to [{ratio}].')

    @property
    def watchdog_interval(self):
        """
        Get the watchdog interval.

        Manual:
        The system can be set to make an automatic shut-off (laser emission
        only - not electrical power) in case of lost communication. The value
        in the watchdog interval register determines how many seconds with no
        communication the system will tolerate. If the value is 0, the
        feature is disabled. 8-bit unsigned integer.

        Return
        ------
        interval : int
            Watchdog interval (s)
        """
        register_address = 0x36

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        comm_result, watchdog_interval = nkt.registerReadU8(
            self._portname,
            self._module_address,
            register_address,
            -1
        )
        self._check_comm_result(comm_result)

        return watchdog_interval

    def set_watchdog_interval(self, timeout):
        """
        Set the watchdog interval.

        Manual:
        The system can be set to automatically shut-off (laser emission only - not electrical
        power) in case communication is lost with the host. The value in the watchdog
        register determines how many seconds without communication the system tolerates
        before disabling emission. If the register value is set to 0, the feature is disabled.
        The format is an 8-bit unsigned integer with a maximum value of 255 seconds.

        Parameters
        ----------
        timeout : int
            time (seconds) the system will toleratre for communication loss.
        """
        register_address = 0x36

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        if not isinstance(timeout, int):
            raise ValueError('Watchdog interval must be an integer.')

        nkt.registerWriteU8(
            self._portname,
            self._module_address,
            register_address,
            timeout,
            -1
        )
        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'watchdog interval to [{timeout}] seconds.')

    @property
    def power_level(self):
        """
        Get power level setpoint with 0.1 % precision.

        Read register 0x37 and converts from permille to percent.

        Return
        ------
        power_level : float
            Power level setpoint in percent w/ 0.1 % precision.
        """
        register_address = 0x37

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        comm_result, power_tenths = nkt.registerReadU16(
            self._portname,
            self._module_address,
            register_address,
            -1
        )
        self._check_comm_result(comm_result)

        return power_tenths / 10

    def set_power(self, power):
        """
        Set power level setpoint with 0.1 % precision.

        Converts from percent to permille and write register 0x37.

        Parameters
        ----------
        power : float
            Power level setpoint in percent w/ 0.1% precision. (0 <= P <= 100)
        """
        register_address = 0x37

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        if (power < 0) or (power > 100):
            self.set_emission(False)
            self.set_power(0)
            raise ValueError('Power must be in the range [0, 100]. Turning off emission.')

        power_tenths = int(power * 10)
        nkt.registerWriteU16(
            self._portname,
            self._module_address,
            register_address,
            power_tenths,
            -1
        )

        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'power to [{power}] %.')

    @property
    def nim_delay(self):
        """
        Get NIM trigger delay time.

        Manual:
        On systems with NIM trigger output, the delay of this trigger signal can be adjusted
        with the NIM delay register. The input for this register is an unsigned 16-bit value
        from 0 to 1023 and the range is 0 - 9.2 ns with an average step size of 9 ps.

        Return
        ------
        nim_delay : float
            Delay time in seconds.
        """
        register_address = 0x39

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        step = 9e-12  # Step size for delay is 9 ps
        comm_result, delay = nkt.registerReadU16(
            self._portname,
            self._module_address,
            register_address,
            -1
        )
        self._check_comm_result(comm_result)

        return delay * step

    def set_nim_delay(self, nim_delay):
        """
        Set NIM trigger delay time.

        Manual:
        On systems with NIM trigger output, the delay of this trigger signal can be adjusted
        with the NIM delay register. The input for this register is an unsigned 16-bit value
        from 0 to 1023 and the range is 0 - 9.2 ns with an average step size of 9 ps.

        Parameters
        ----------
        nim_delay : float
            Delay time given in seconds. (0 <= nim_delay <= 9.207e-9)
        """
        register_address = 0x39

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        step = 9e-12  # Step size for delay is 9 ps
        int_delay = int(nim_delay/step)

        if (int_delay < 0) or (int_delay > 1023):
            raise ValueError('NIM delay value out of range [0, 9.207e-9].')

        nkt.registerWriteU16(
            self._portname,
            self._module_address,
            register_address,
            int_delay,
            -1
        )

        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'NIM delay to [{nim_delay}] seconds.')

    @property
    def user_setup_bits(self):
        """
        Read the value of user setup bits (register 0x3B).

        Returns
        -------
        int
            Current user setup bits.
        """
        register_address = 0x3B

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        comm_result, setup_bits = nkt.registerReadU16(
            self._portname,
            self._module_address,
            register_address,
            -1
        )
        self._check_comm_result(comm_result)

        return setup_bits

    @property
    def status_bits(self):
        """
        Reads the status bits register (0x66) and returns corresponding status message.

        Returns
        -------
        tuple(int, str)
            (status bits, Description).
        """
        register_address = 0x66

        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        comm_result, status_bits = nkt.registerReadU8(
            self._portname,
            self._module_address,
            register_address,
            -1
        )
        self._check_comm_result(comm_result)

        return (status_bits, self.__class__.STATUS_BITS[status_bits])

if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.DEBUG)

    with Fianium() as laser:
        print(f'status: {laser.status_bits}')

        print(f'emission: {laser.emission}')
        laser.set_emission(False)

        print(f'setup: {laser.setup}')
        # TODO
        # laser.set_setup()

        print(f'interlock: {laser.interlock}')
        # TODO
        # laser.set_interlock()

        pp = laser.pulse_picker_ratio
        print(f'pulse picker ratio: {pp}')
        laser.set_pulse_picker_ratio(100)
        print(f'pulse picker ratio: {laser.pulse_picker_ratio}')
        laser.set_pulse_picker_ratio(pp)

        print(f'watchdog timer: {laser.watchdog_interval}')
        # TODO
        # laser.set_watchdog_interval()

        pow = laser.power_level
        print(f'power: {pow} %')
        laser.set_power(10)
        print(f'power: {laser.power_level} %')
        laser.set_power(pow)

        delay = laser.nim_delay
        print(f'NIM delay: {delay}')
        laser.set_nim_delay(20e-12)
        print(f'NIM delay: {laser.nim_delay}')
        laser.set_nim_delay(delay)
