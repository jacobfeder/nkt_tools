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
    REGS = {
        0x30: ('emission', 'U8'),
        0x31: ('setup bits', 'U8'),
        0x32: ('interlock', 'U16'),
        0x34: ('pulse picker ratio', 'U16'),
        0x3D: ('max pulse picker ratio', 'U16'),
        0x36: ('watchdog interval', 'U8'),
        0x37: ('output power', 'U16'),
        0x39: ('NIM delay', 'U16'),
        0x3B: ('user config', 'U16'),
        0x66: ('status bits', 'U16'),
    }

    COMM_ERRORS = {
        1: 'Arises from a registerWrite function with index > 0, if the pre-read fails.',
        2: 'The function registerCreate has failed.',
        3: 'The module has reported a BUSY error, the kernel automatically retries on busy but have given up.',
        4: 'The module has Nacked the register, which typically means non existing register.',
        5: 'The module has reported a CRC error, which means the received message has CRC errors.',
        6: 'The module has not responded in time. A module should respond in max. 75 ms',
        7: 'The module has reported a COM error, which typically means out of sync or garbage error.',
        8: 'The datatype does not seem to match the register datatype.',
        9: 'The index seem to be out of range of the register length.',
        10: 'The specified port is closed error. Could happen if the USB is unplugged in the middel of a sequence.',
        11: 'The specified register could not be found in the internal register list for the specified device.',
        12: 'The specified device could not be found in the internal device list.',
        13: 'The specified portname could not be found.',
        14: 'The specified portname could not be opened. The port might be in use by another application.',
        15: 'The function is not allowed to be invoked from within a callback function.',
    }

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
        """Connect to the device"""
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
        """Disconnect from the device, closing the COM port."""
        if self._portname is not None:
            nkt.closePorts(self._portname)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def read_reg(self, reg_addr):
        """Read a register from the device, performing error checking.

        Parameters
        ----------
        reg_addr : int
            Register address number to read.

        Raises
        ------
        RuntimeError
            Throws error if there is an issue reading the register.

        """
        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        reg_name, reg_type = self.REGS[reg_addr]
        if reg_type == 'U8':
            comm_result, value = nkt.registerReadU8(
                self._portname,
                self._module_address,
                reg_addr,
                -1
            )
        elif reg_type == 'U16':
            comm_result, value = nkt.registerReadU16(
                self._portname,
                self._module_address,
                reg_addr,
                -1
            )
        else:
            raise RuntimeError('Unrecognized register type from internal register table.')

        if comm_result == 0:
            pass
        elif comm_result in self.COMM_ERRORS:
            raise RuntimeError(self.COMM_ERRORS[comm_result])
        else:
            raise RuntimeError(f'Unknown error type reading reg {reg_addr:02x}: {comm_result}.')

        logger.debug(f'Read NKT {self.__class__.__name__} on port [{self._portname}] reg {reg_addr:02x} = {value}.')

        return value

    def write_reg(self, reg_addr, reg_val):
        """Write a register to the device, performing error checking.

        Parameters
        ----------
        reg_addr : int
            Register address number to write to.
        reg_val : int
            Value to write to the register.

        Raises
        ------
        RuntimeError
            Throws error if there is an issue writing the register.

        """
        if self._portname is None:
            raise RuntimeError('Not connected. Call connect() before any driver calls.')

        reg_name, reg_type = self.REGS[reg_addr]
        if reg_type == 'U8':
            comm_result = nkt.registerWriteU8(
                self._portname,
                self._module_address,
                reg_addr,
                reg_val,
                -1
            )
        elif reg_type == 'U16':
            comm_result = nkt.registerWriteU16(
                self._portname,
                self._module_address,
                reg_addr,
                reg_val,
                -1
            )
        else:
            raise RuntimeError('Unrecognized register type from internal register table.')

        if comm_result == 0:
            pass
        elif comm_result in self.COMM_ERRORS:
            raise RuntimeError(self.COMM_ERRORS[comm_result])
        else:
            raise RuntimeError(f'Unknown error type writing reg {reg_addr:02x}: {comm_result}.')

        logger.debug(f'Write NKT {self.__class__.__name__} on port [{self._portname}] reg {reg_addr:02x} = {reg_val:02x}.')

    @property
    def emission(self):
        """
        Get the emission state of the laser.

        Return
        ------
        bool
            False = emission off; True = emission on
        """
        value = self.read_reg(0x30)
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
            True turns emission on, false turns emission off.
        """
        if state is True:
            reg_val = 0x03
        else:
            reg_val = 0x00

        self.write_reg(0x30, reg_val)
        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'emission state to [{state}].')

    @property
    def setup(self):
        """
        Gets the current setup state.

        See SETUP for possible outcomes. Use set_setup() to change value.

        Returns
        -------
        tuple(int, str)
            (Bits, Description) Current setup status of laser based on manual values.
        """
        setup_bits = self.read_reg(0x31)
        return (setup_bits, self.SETUP[setup_bits])

    def set_setup(self, setup_key):
        """
        Sets the "setup" of the laser according to options in manual.

        Checks value provided is withing SETUP.keys(). Get current status w/ status()

        Parameters
        ----------
        setup_key : int
            Integer corresponding to a key inside SETUP enum.
        """
        if setup_key not in self.SETUP.keys():
            raise ValueError('Invalid setup state key. See SETUP enum for options.')

        self.write_reg(reg_addr=0x31, reg_val=setup_key)
        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'setup state to [0x{setup_key:02x}] ({self.SETUP[setup_key]}).')

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
        reading = self.read_reg(reg_addr=0x32)
        LSB = reading & 0x00FF  # First byte
        MSB = (reading & 0xFF00) >> 8  # Second byte

        if MSB == 255:
            return (0, f'Interlock circuit failure')
        else:
            if LSB == 0:
                reason = self.INTERLOCK[MSB]
                return (LSB, f'Interlocked: {reason}')
            elif LSB == 1:
                return (LSB, 'Waiting for interlock reset')
            elif LSB == 2:
                return (LSB, 'Interlock is OK')

    def set_interlock(self, value):
        """
        Reset or trip interlock with > 0 or 0, respectively.

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
            0 trips interlock. > 0 resets interlock.

        """
        if value > 0:
            value = 1
        else:
            value = 0

        self.write_reg(reg_addr=0x32, reg_val=value)
        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'interlock state to [0x{value:02x}].')

    @property
    def pulse_picker_ratio(self):
        """
        Get pulse picker ratio.

        Manual:
        For SuperK Fianium Systems featuring the pulse picker option, the
        divide ratio for the pulse picker can be controlled with the pulse
        picker ratio register.

        Return
        ------
        ratio : int
            Pulse picker divide ratio
        """
        return self.read_reg(reg_addr=0x34)

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
        max_pp = self.max_pulse_picker_ratio
        
        if not isinstance(ratio, int):
            raise ValueError('Pulse picker division ratio must be an integer.')
        if ratio < 1:
            raise ValueError('Pulse picker division ratio must be >= 1.')
        if ratio > max_pp:
            raise ValueError(f'Pulse picker division ratio must be <= {max_pp}.')

        self.write_reg(reg_addr=0x34, reg_val=ratio)
        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'pulse picker division ratio to [{ratio}].')

    @property
    def max_pulse_picker_ratio(self):
        """
        Get the maximum pulse picker division ratio.

        Parameters
        ----------
        ratio : int
            Integer corresponding to the max division ratio.
        """
        return self.read_reg(reg_addr=0x3D)

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
        return self.read_reg(reg_addr=0x36)

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
        if not isinstance(timeout, int):
            raise ValueError('Watchdog interval must be an integer.')

        self.write_reg(reg_addr=0x36, reg_val=timeout)
        logger.info(f'Set NKT {self.__class__.__name__} on port [{self._portname}] '
            f'watchdog interval to [{timeout}] seconds.')

    @property
    def power_level(self):
        """
        Get power level setpoint with 0.1 % precision.

        Return
        ------
        power_level : float
            Power level setpoint in percent w/ 0.1 % precision.
        """
        return self.read_reg(reg_addr=0x37) / 10

    def set_power(self, power):
        """
        Set power level setpoint with 0.1 % precision.

        Parameters
        ----------
        power : float
            Power level setpoint in percent w/ 0.1% precision. (0 <= P <= 100)
        """
        if (power < 0) or (power > 100):
            self.set_emission(False)
            self.set_power(0)
            raise ValueError('Power must be in the range [0, 100]. Turning off emission.')
        power_tenths = int(power * 10)

        self.write_reg(reg_addr=0x37, reg_val=power_tenths)
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
        step = 9e-12  # Step size for delay is 9 ps
        return self.read_reg(reg_addr=0x39) * step

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
        step = 9e-12  # Step size for delay is 9 ps
        int_delay = int(nim_delay/step)
        if (int_delay < 0) or (int_delay > 1023):
            raise ValueError('NIM delay value out of range [0, 9.207e-9].')

        self.write_reg(reg_addr=0x39, reg_val=int_delay)
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
        return self.read_reg(reg_addr=0x3B)

    def set_user_setup_bits(self):
        """
        Read the value of user setup bits (register 0x3B).

        Returns
        -------
        int
            Current user setup bits.
        """
        return self.read_reg(reg_addr=0x3B)


    @property
    def status_bits(self):
        """
        Reads the status bits register (0x66) and returns corresponding status message.

        Returns
        -------
        tuple(int, str)
            (Bits, Description).
        """
        status_bits = self.read_reg(reg_addr=0x66)
        return (status_bits, self.STATUS_BITS[status_bits])

if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO)

    # test cases
    with Fianium() as laser:
        print(f'status: {laser.status_bits}')

        print(f'emission: {laser.emission}')
        laser.set_emission(False)

        setup_bits, setup_str = laser.setup
        print(f'setup: {setup_str}')
        laser.set_setup(setup_bits)

        interlock_bits, interlock_str = laser.interlock
        print(f'interlock: {interlock_str}')
        laser.set_interlock(interlock_bits)

        max_pp = laser.max_pulse_picker_ratio
        print(f'max pulse picker ratio: {max_pp}')

        pp = laser.pulse_picker_ratio
        print(f'pulse picker ratio: {pp}')
        laser.set_pulse_picker_ratio(100)
        print(f'pulse picker ratio: {laser.pulse_picker_ratio}')
        laser.set_pulse_picker_ratio(pp)

        watchdog = laser.watchdog_interval
        print(f'watchdog interval: {watchdog}')
        laser.set_watchdog_interval(watchdog)

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

        print(f'user setup bits: {laser.user_setup_bits}')
