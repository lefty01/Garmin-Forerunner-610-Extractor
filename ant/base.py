# Ant
#
# Copyright (c) 2012, Gustav Tiger <gustav@tiger.name>
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import usb.core
import usb.util

import array
import collections
import threading
import logging

_logger = logging.getLogger("garmin.ant.base")

def _format_list(l):
    return "[" + " ".join(map(lambda a: str.format("{0:02x}", a), l)) + "]"

class Message:

    class ID:
        INVALID                            = 0x00

        # Configuration messages
        UNASSIGN_CHANNEL                   = 0x41
        ASSIGN_CHANNEL                     = 0x42
        SET_CHANNEL_ID                     = 0x51
        SET_CHANNEL_PERIOD                 = 0x43
        SET_CHANNEL_SEARCH_TIMEOUT         = 0x44
        SET_CHANNEL_RF_FREQ                = 0x45
        SET_NETWORK_KEY                    = 0x46
        SET_TRANSMIT_POWER                 = 0x47
        SET_SEARCH_WAVEFORM                = 0x49 # XXX: Not in official docs
        ADD_CHANNEL_ID                     = 0x59
        CONFIG_LIST                        = 0x5A
        SET_CHANNEL_TX_POWER               = 0x60
        LOW_PRIORITY_CHANNEL_SEARCH_TIMOUT = 0x63
        SERIAL_NUMBER_SET_CHANNEL          = 0x65
        ENABLE_EXT_RX_MESGS                = 0x66
        ENABLE_LED                         = 0x68
        ENABLE_CRYSTAL                     = 0x6D
        LIB_CONFIG                         = 0x6E
        FREQUENCY_AGILITY                  = 0x70
        PROXIMITY_SEARCH                   = 0x71
        CHANNEL_SEARCH_PRIORITY            = 0x75
        #SET_USB_INFO                       = 0xff

        # Notifications
        STARTUP_MESSAGE                    = 0x6F
        SERIAL_ERROR_MESSAGE               = 0xAE

        # Control messags
        RESET_SYSTEM                       = 0x4A
        OPEN_CHANNEL                       = 0x4B
        CLOSE_CHANNEL                      = 0x4C
        OPEN_RX_SCAN_MODE                  = 0x5B
        REQUEST_MESSAGE                    = 0x4D
        SLEEP_MESSAGE                      = 0xC5

        # Data messages
        BROADCAST_DATA                     = 0x4E
        ACKNOWLEDGE_DATA                   = 0x4F
        BURST_TRANSFER_DATA                = 0x50

        # Responses (from channel)
        RESPONSE_CHANNEL                   = 0x40
        
        # Responses (from REQUEST_MESSAGE, 0x4d)
        RESPONSE_CHANNEL_STATUS            = 0x52
        RESPONSE_CHANNEL_ID                = 0x51
        RESPONSE_VERSION                   = 0x3E
        RESPONSE_CAPABILITIES              = 0x54
        RESPONSE_SERIAL_NUMBER             = 0x61

    class Code:
        RESPONSE_NO_ERROR                  = 0

        EVENT_RX_SEARCH_TIMEOUT            = 1
        EVENT_RX_FAIL                      = 2
        EVENT_TX                           = 3
        EVENT_TRANSFER_RX_FAILED           = 4
        EVENT_TRANSFER_TX_COMPLETED        = 5
        EVENT_TRANSFER_TX_FAILED           = 6
        EVENT_CHANNEL_CLOSED               = 7
        EVENT_RX_FAIL_GO_TO_SEARCH         = 8
        EVENT_CHANNEL_COLLISION            = 9
        EVENT_TRANSFER_TX_START            = 10

        CHANNEL_IN_WRONG_STATE             = 21
        CHANNEL_NOT_OPENED                 = 22
        CHANNEL_ID_NOT_SET                 = 24
        CLOSE_ALL_CHANNELS                 = 25

        TRANSFER_IN_PROGRESS               = 31
        TRANSFER_SEQUENCE_NUMBER_ERROR     = 32
        TRANSFER_IN_ERROR                  = 33

        MESSAGE_SIZE_EXCEEDS_LIMIT         = 39
        INVALID_MESSAGE                    = 40
        INVALID_NETWORK_NUMBER             = 41
        INVALID_LIST_ID                    = 48
        INVALID_SCAN_TX_CHANNEL            = 49
        INVALID_PARAMETER_PROVIDED         = 51
        EVENT_SERIAL_QUE_OVERFLOW          = 52
        EVENT_QUE_OVERFLOW                 = 53
        NVM_FULL_ERROR                     = 64
        NVM_WRITE_ERROR                    = 65
        USB_STRING_WRITE_FAIL              = 112
        MESG_SERIAL_ERROR_ID               = 174

        EVENT_RX_BROADCAST                 = 1000
        EVENT_RX_FLAG_BROADCAST            = 1001
        EVENT_RX_ACKNOWLEDGED              = 2000
        EVENT_RX_FLAG_ACKNOWLEDGED         = 2001
        EVENT_RX_BURST_PACKET              = 3000
        EVENT_RX_FLAG_BURST_PACKET         = 3001

        @staticmethod
        def lookup(event):
            for key, value in Message.Code.__dict__.items():
                if type(value) == int and value == event:
                    return key

    def __init__(self, mId, data):
        self._sync     = 0xa4
        self._length   = len(data)
        self._id       = mId
        self._data     = data
        self._checksum = (self._sync ^ self._length ^ self._id
                          ^ reduce(lambda x, y: x ^ y, data))

    def __repr__(self):
        return str.format(
                   "<ant.base.Message {0:02x}:{1} (s:{2:02x}, l:{3}, c:{4:02x})>",
                   self._id, _format_list(self._data), self._sync,
                   self._length, self._checksum)

    def get(self):
        return array.array('B', [self._sync, self._length, self._id]
                           + self._data + [self._checksum])

    '''
    Parse a message from an array
    '''
    @staticmethod
    def parse(buf):
        sync     = buf[0]
        length   = buf[1]
        mId      = buf[2]
        data     = buf[3:-1]
        checksum = buf[-1]

        assert sync     == 0xa4
        assert length   == len(data)
        assert checksum == reduce(lambda x, y: x ^ y, buf[:-1])

        return Message(mId, data)


class Ant(threading.Thread):

    def __init__(self, idVendor, idProduct):

        threading.Thread.__init__(self)

        # Find USB device
        _logger.debug("USB Find device, vendor %#04x, product %#04x", idVendor, idProduct)
        dev = usb.core.find(idVendor=idVendor, idProduct=idProduct)

        # was it found?
        if dev is None:
            raise ValueError('Device not found')

        _logger.debug("USB Config values:")
        for cfg in dev:
            _logger.debug(" Config %s", cfg.bConfigurationValue)
            for intf in cfg:
                _logger.debug("  Interface %s, Alt %s", str(intf.bInterfaceNumber), str(intf.bAlternateSetting))
                for ep in intf:
                    _logger.debug("   Endpoint %s", str(ep.bEndpointAddress))

        # unmount a kernel driver (TODO: should probably reattach later)
        if dev.is_kernel_driver_active(0):
            _logger.debug("A kernel driver active, detatching")
            dev.detach_kernel_driver(0)
        else:
            _logger.debug("No kernel driver active")

        # set the active configuration. With no arguments, the first
        # configuration will be the active one
        dev.set_configuration()
        dev.reset()
        #dev.set_configuration()

        # get an endpoint instance
        cfg = dev.get_active_configuration()
        interface_number = cfg[(0,0)].bInterfaceNumber
        alternate_setting = usb.control.get_interface(dev, interface_number)
        intf = usb.util.find_descriptor(
            cfg, bInterfaceNumber = interface_number,
            bAlternateSetting = alternate_setting
        )

        self._out = usb.util.find_descriptor(
            intf,
            # match the first OUT endpoint
            custom_match = \
            lambda e: \
                usb.util.endpoint_direction(e.bEndpointAddress) == \
                usb.util.ENDPOINT_OUT
        )

        _logger.debug("UBS Endpoint out: %s, %s", self._out, self._out.bEndpointAddress)

        self._in = usb.util.find_descriptor(
            intf,
            # match the first OUT endpoint
            custom_match = \
            lambda e: \
                usb.util.endpoint_direction(e.bEndpointAddress) == \
                usb.util.ENDPOINT_IN
        )

        _logger.debug("UBS Endpoint in: %s, %s", self._in, self._in.bEndpointAddress)

        assert self._out is not None and self._in is not None

        self._message_queue_cond = threading.Condition()
        self._message_queue      = collections.deque()

        self._buffer = array.array('B', [])
        self._burst_data = array.array('B', [])
        self._last_data = array.array('B', [])

        self._running = True

    def stop(self):
        self._running = False
        self.join()

    def _on_broadcast(self, message):
        self.channel_event_function(message._data[0],
                Message.Code.EVENT_RX_BROADCAST, message._data[1:])

    def _on_acknowledge(self, message):
        self.channel_event_function(message._data[0],
                Message.Code.EVENT_RX_ACKNOWLEDGED, message._data[1:])

    def _on_burst_data(self, message):

        sequence = message._data[0] >> 5
        channel  = message._data[0] & 0b00011111
        data     = message._data[1:]
        
        self._burst_data.extend(data)
        
        # Last sequence (indicated by bit 3)
        if sequence & 0b100 != 0:
            self.channel_event_function(channel,
                    Message.Code.EVENT_RX_BURST_PACKET, self._burst_data)
            self._burst_data = array.array('B', [])
        # Normal sequence
        else:
            #print "sequence", sequence, message._data[0]
            #assert sequence == burst_seq + 1 or (sequence == 0 and burst_seq & 0b100) or (sequence == 1 and burst_seq == 3)
            return

    def run(self):

        _logger.debug("Ant runner started")

        while self._running:
            try:
                message = self.read_message()

                # TODO: flag and extended for broadcast, acknowledge, and burst

                # Only do callbacks for new data. Resent data only indicates
                # a new channel timeslot.
                if not (message._id == Message.ID.BROADCAST_DATA and 
                    message._data == self._last_data):
                   
                    # Notifications
                    if message._id in [Message.ID.STARTUP_MESSAGE, \
                            Message.ID.SERIAL_ERROR_MESSAGE]:
                        self.response_function(None, message._id, message._data)
                    # Response (no channel)
                    if message._id in [Message.ID.RESPONSE_VERSION, \
                            Message.ID.RESPONSE_CAPABILITIES, \
                            Message.ID.RESPONSE_SERIAL_NUMBER]:
                        self.response_function(None, message._id, message._data)
                    # Response (channel)
                    if message._id in [Message.ID.RESPONSE_CHANNEL_STATUS, \
                            Message.ID.RESPONSE_CHANNEL_ID]:
                        self.response_function(message._data[0], message._id,
                                               message._data[1:])
                    # Response (other)
                    elif (message._id == Message.ID.RESPONSE_CHANNEL \
                          and message._data[1] != 0x01):
                        self.response_function(message._data[0], 
                                message._data[1], message._data[2:])
                    # Channel event
                    elif message._id == Message.ID.BROADCAST_DATA:
                        self._on_broadcast(message)
                    elif message._id == Message.ID.ACKNOWLEDGE_DATA:
                        self._on_acknowledge(message)
                    elif message._id == Message.ID.BURST_TRANSFER_DATA:
                        self._on_burst_data(message)
                    elif message._id == Message.ID.RESPONSE_CHANNEL:
                        _logger.debug("Got channel event, %r", message)
                        self.channel_event_function(message._data[0],
                                message._data[1], message._data[2:])
                    else:
                        _logger.warning("Got unknown message, %r", message)
                else:
                    _logger.debug("No new data this period")

                # Send messages in queue, on indicated time slot
                if message._id == Message.ID.BROADCAST_DATA:
                    _logger.debug("Got broadcast data, examine queue to see if we should send anything back")
                    if self._message_queue_cond.acquire(blocking=False):
                        while len(self._message_queue) > 0:
                            m = self._message_queue.popleft()
                            self.write_message(m)
                            _logger.debug(" - sent message from queue, %r", m)
                            
                            if(m._id != Message.ID.BURST_TRANSFER_DATA or \
                               m._data[0] & 0b10000000):# or m._data[0] == 0):
                                break
                        else:
                            _logger.debug(" - no messages in queue")
                        self._message_queue_cond.release()

                self._last_data = message._data

            except usb.USBError as e:
                _logger.warning("%s, %r", type(e), e.args)

    def write_message_timeslot(self, message):
        with self._message_queue_cond:
            self._message_queue.append(message)

    def write_message(self, message):
        data = message.get()
        self._out.write(data + array.array('B', [0x00, 0x00]))
        _logger.debug("Write data: %s", _format_list(data))


    def read_message(self):
        # If we have a message in buffer already, return it
        if len(self._buffer) >= 5 and len(self._buffer) >= self._buffer[1] + 4:
            packet       = self._buffer[:self._buffer[1] + 4]
            self._buffer = self._buffer[self._buffer[1] + 4:]
            
            return Message.parse(packet)
        # Otherwise, read some data and call the function again
        else:
            data = self._in.read(4096)
            self._buffer.extend(data)
            _logger.debug("Read data: %s (now have %s in buffer)",
                          _format_list(data), _format_list(self._buffer))
            return self.read_message()

    # Ant functions

    def unassign_channel(self, channel):
        pass

    def assign_channel(self, channel, channelType, networkNumber):
        message = Message(Message.ID.ASSIGN_CHANNEL, [channel, channelType, networkNumber])
        self.write_message(message)

    def open_channel(self, channel):
        message = Message(Message.ID.OPEN_CHANNEL, [channel])
        self.write_message(message)

    def set_channel_id(self, channel, deviceNum, deviceType, transmissionType):
        message = Message(Message.ID.SET_CHANNEL_ID, [channel, deviceNum[0], deviceNum[1], deviceType, transmissionType])
        self.write_message(message)

    def set_channel_period(self, channel, messagePeriod):
        message = Message(Message.ID.SET_CHANNEL_PERIOD, [channel] + messagePeriod)
        self.write_message(message)

    def set_channel_search_timeout(self, channel, timeout):
        message = Message(Message.ID.SET_CHANNEL_SEARCH_TIMEOUT, [channel, timeout])
        self.write_message(message)

    def set_channel_rf_freq(self, channel, rfFreq):
        message = Message(Message.ID.SET_CHANNEL_RF_FREQ, [channel, rfFreq])
        self.write_message(message)

    def set_network_key(self, network, key):
        message = Message(Message.ID.SET_NETWORK_KEY, [network] + key)
        self.write_message(message)

    # This function is a bit of a mystery. It is mentioned in libgant,
    # http://sportwatcher.googlecode.com/svn/trunk/libgant/gant.h and is
    # also sent from the official ant deamon on windows.
    def set_search_waveform(self, channel, waveform):
        message = Message(Message.ID.SET_SEARCH_WAVEFORM, [channel] + waveform)
        self.write_message(message)

    def reset_system(self):
        message = Message(Message.ID.RESET_SYSTEM, [0x00])
        self.write_message(message)

    def request_message(self, channel, messageId):
        message = Message(Message.ID.REQUEST_MESSAGE, [0x00, messageId])
        self.write_message(message)

    def send_acknowledged_data(self, channel, broadcastData):
        message = Message(Message.ID.ACKNOWLEDGE_DATA, [0x00] + broadcastData)
        self.write_message_timeslot(message)

    def send_burst_transfer_packet(self, channelSeq, data, first):
        message = Message(Message.ID.BURST_TRANSFER_DATA, [channelSeq] + data)
        self.write_message_timeslot(message)

    def send_burst_transfer(self, channel, data):
        _logger.debug("Send burst transfer, chan %s, data %s", channel, data)
        for i in range(len(data)):
            sequence = i % 4
            if i == len(data) - 1:
                sequence = sequence | 0b100
            channelSeq = channel | sequence << 5
            self.send_burst_transfer_packet(channelSeq, data[i], first=i==0)

    def response_function(self, channel, event, data):
        pass

    def channel_event_function(self, channel, event, data):
        pass

