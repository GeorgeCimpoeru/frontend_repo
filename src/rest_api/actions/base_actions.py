"""
Author: Mujdei Ruben

The Action class is a utility class designed to be inherited by specific action classes.
It provides a set of pre-created methods that facilitate various tasks such as reading frames,
processing these frames, creating responses, and additional functionalities. This class
serves as a foundation, offering reusable components and standardizing the way frames are
sent and received.

Please note that only the protected methods can be used in your child class.

    _passive_response()
        Collects the response frame from a specific request, verifies it,
        and returns the data carried by the frame.

    _data_from_frame()
        Extracts just the data from the CAN message based on the frame type (excluding SIDs, identifiers, sub-functions, etc).
        Works for read by address, read by identifier, and authentication seed.

    _authentication()
        Sends a sequence of frames for authentication.

    _read_by_identifier()
        Sends a frame for reading by identifier, collects the response, and returns the data carried.

    _to_json()
        Needs to be overridden and implemented in the child class.

    _to_json_error()
        Creates a JSON response for error messages.

    _list_to_number()
        Transforms a list of numbers into a string. Example: [1, 2, 3] -> "010203".

PS: Use: raise CustomError(response_json), every time you want to send a premature JSON response and finish the program.
Check _passive_response() as example.


How to create a new class action, example:

    class CustomAction(Action):

        def run(self):
            try:
                # Example of frame stack

                # Send frame, passive response
                self.generate.frame(self.id)

                # Verify response and provide error message if the frame is not the desired one
                self._passive_response(sid, "Error message")

                # Send frame, request data
                self.generate.frame_request_data(self.id)

                # Collect frame and data from frame, then process it with a custom method
                data_response = self._data_from_frame(self._passive_response(sid, "Error message"))
                self.process_data(data_response)

                # Send all the frames that you need and collect the response if necessary as in the example above
                .......

                # Generate a JSON response. Need to override this method and write the implementation
                response_json = self._to_json()

                # Shutdown the CAN bus interface
                self.bus.shutdown()

                return response_json
            
            except CustomError as e:
                # Handle custom errors from frames
                self.bus.shutdown()
                return e.message

"""

import can
import json
import datetime
import time
from actions.generate_frames import GenerateFrame as GF
from utils.logger import *
from config import Config
from configs.data_identifiers import *

logger_singleton = SingletonLogger('base_action.log')
logger = logger_singleton.logger
logger_frame = logger_singleton.logger_frame

SESSION_CONTROL = 0x10
RESET_ECU = 0x11
READ_BY_ADDRESS = 0x23
READ_BY_IDENTIFIER = 0x022
AUTHENTICATION = 0x29
ROUTINE_CONTROL = 0X31
WRITE_BY_IDENTIFIER = 0X2E
READ_DTC = 0X19
CLEAR_DTC = 0X14
REQUEST_DOWNLOAD = 0X83
TRANSFER_DATA = 0X36
REQUEST_TRANSFER_EXIT = 0X37


class FrameWithData:
    """Base class for frames with data extraction methods."""
    def _data_from_frame(self):
        pass

class ReadByIdentifier(FrameWithData):
    """Extracts data from frames read by identifier."""
    def _data_from_frame(self, msg: can.Message):
        data = msg.data[4:]
        return data

class ReadByAddress(FrameWithData):
    """Extracts data from frames read by address."""
    def _data_from_frame(self, msg: can.Message):
        addr_siz_len = msg.data[2]
        byte_start_data = addr_siz_len % 0x10 + addr_siz_len // 0x10
        data = msg.data[3 + byte_start_data:]
        return data
class AuthenticationSeed(FrameWithData):
    """Extracts seed from frame request seed."""
    def _data_from_frame(self, msg: can.Message):
        data = msg.data[3:]
        return data

class CustomError(Exception):
    """Custom exception class for handling specific update errors."""
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

class Action:
    """
    Base class for actions involving CAN bus communication.
    
    Attributes:
    - my_id: Identifier for the device initiating the action.
    - id_ecu: Identifier for the specific ECU being communicated with.
    - g: Instance of GenerateFrame for generating CAN bus frames.
    """

    def __init__(self, my_id, id_ecu: list=[]):
        self.bus = can.interface.Bus(channel=Config.CAN_CHANNEL, interface='socketcan')
        self.my_id = my_id
        self.id_ecu = id_ecu
        self.generate = GF(self.bus)

    def __collect_response(self, sid: int):
        """
        Collects the response message from the CAN bus.
        
        Args:
        - sid: Service identifier to verify the response.

        Returns:
        - The collected CAN message if valid, otherwise None.
        """
        flag = False
        msg_ext = None
        msg = self.bus.recv(3)
        while msg is not None:
            # First Frame
            if msg.data[0] == 0x10:
                flag = True
                msg_ext = msg[1:]
            # Consecutive frame
            elif flag and 0x20 < msg.data[0] < 0x30:
                msg_ext.data += msg.data[1:]
            # Simple Frame
            else:
                break
            msg = self.bus.recv(3)
        if flag:
            msg = msg_ext
        if msg is not None and self.__verify_frame(msg, sid):
            return msg
        return None

    def __verify_frame(self, msg: can.Message, sid: int):
        """
        Verifies the validity of the received CAN message.
        
        Args:
        - msg: The received CAN message.
        - sid: Service identifier to verify the response.

        Returns:
        - True if the frame is valid, False otherwise.
        """
        if msg.arbitration_id % 0x100 != self.my_id:
            return False
        if msg.data[0] != 0x10:
            if msg.data[1] != sid + 0x40:
                return False
        else:
            if msg.data[2] != sid + 0x40:
                return False
        return True

    def _passive_response(self, sid, error_str="Error service"):
        """
        Collects and verifies the response, raising an error if invalid.
        
        Args:
        - sid: Service identifier to verify the response.
        - error_str: Error message to raise if the response is invalid.

        Raises:
        - CustomError: If the response is invalid.
        """
        log_info_message(logger, "Collecting the response")
        response = self.__collect_response(sid)
        if response is None:
            log_error_message(logger,error_str)
            response_json = self._to_json_error("interrupted", 1)
            # raise CustomError(response_json)
        return response

    def _data_from_frame(self, msg: can.Message):
        """
        Extracts data from the CAN message based on the frame type. Implemented for 
        ReadByIdentifier and ReadByAddress
        
        Args:
        - msg: The CAN message to extract data from.

        Returns:
        - The extracted data if the frame type is recognized, otherwise None.
        """
        #debugging
        if msg is None:
            return [1,2,3,4,5]
        handlers = {
            0x62: ReadByIdentifier(),
            0x63: ReadByAddress(),
            0x29: AuthenticationSeed(),
        }
        handler = handlers.get(msg.data[1] if msg.data[0] != 0x10 else msg.data[2])
        if handler:
            return handler._data_from_frame(msg)
        return None
    
    def _read_by_identifier(self,id, identifier):
        """
        Function to read data from a specific identifier. The function requests, reads the data, and processes it.

        Args:
        - identifier: Identifier of the data.

        Returns:
        - Data as a string.
        """
        log_info_message(logger, "Read from identifier {identifier}")
        self.generate.read_data_by_identifier(id, identifier)
        frame_response = self._passive_response(READ_BY_IDENTIFIER, f"Error reading data from identifier {identifier}")
        data = self._data_from_frame(frame_response)
        data_str = self._list_to_number(data)
        return data_str

    def __algorithm(self, seed:list):
        """
        Method to generate a key based on the seed.
        """
        key = []
        bit_width = 8
        for value in seed:
            if value < 0:
                value = (1 << bit_width) + value
            key.append( value & ((1 << bit_width) - 1))
        return key

    def _authentication(self,id):
        """
        Function to authenticate. Makes the proper request to the ECU.
        """
        log_info_message(logger, "Authenticating")
        self.generate.authentication_seed(id)
        frame_response = self._passive_response(AUTHENTICATION, "Error requesting seed")
        seed = self._data_from_frame(frame_response)
        key = self.__algorithm(seed)
        self.generate.authentication_key(id, key)
        self._passive_response(AUTHENTICATION, "Error sending key")

    # Implement in the child class
    def _to_json(self, status, no_errors):
        pass
    def _to_json_error(self, error, no_errors):
        response_to_frontend = {
            "ERROR": error,
            "No of errors": no_errors,
            "time_stamp": datetime.datetime.now().isoformat()
        }
        return json.dumps(response_to_frontend)
    def _list_to_number(self, list: list):
        number = ""
        for item in list:
            if item <= 0xF:
                number += "0"
            number += hex(item)[2:]
        return number