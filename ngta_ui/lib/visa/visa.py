import time

from pydantic import BaseModel
from contextlib import contextmanager
import pyvisa as visa
from typing import Optional, List, Union

import logging

logger = logging.getLogger(__name__)


def get_instrument_keys_by_rm(instrument_info, rm_list):
    """
    This function checks which instruments from the rm_list are present in the InstrumentInfo class attributes
    and returns the keys for creating a dropdown.

    :param instrument_info: The class containing instrument attribute definitions
    :param rm_list: The list of resource manager identifiers to match against the InstrumentInfo
    :return: List of keys from InstrumentInfo that have values matching the rm_list
    """
    matching_keys = []

    # Loop through all attributes of the class
    for key in dir(instrument_info):
        # Ignore special and private attributes/methods
        if not key.startswith('__'):
            value = getattr(instrument_info, key)
            # Check if any of the rm strings is in the value of the attribute
            if any(rm_string in value for rm_string in rm_list):
                matching_keys.append(key)

    return matching_keys if matching_keys else None


class InstrumentInfo:
    No_instrument = None,
    VI_DP2031: str = "USB0::0x1AB1::0xA4A8::DP2A252000149::INSTR",
    VI_DP2031_1V8: str = "USB0::0x1AB1::0xA4A8::DP2A252000149::INSTR",
    VI_DP2031_1V2: str = "USB0::0x1AB1::0xA4A8::DP2A252000149::INSTR",
    VI_DM3068_0873: str = "USB0::0x1AB1::0x0C94::DM3O252000873::INSTR",
    VI_DM3068_USB: str = "USB0::0x1AB1::0x0C94::DM3O181200237::INSTR",
    VI_PS3255: str = "USB0::0x05E6::0x2200::9203255::INSTR",
    VI_PS3305: str = "USB0::0x05E6::0x2200::9203305::INSTR",
    VI_NRP110T: str = "USB0::0x0AAD::0x015A::101005::INSTR",
    VI_FSW43_NET_50: str = "TCPIP::192.168.255.50::inst0::INSTR",
    VI_FSW43_USB: str = "USB0::0x0AAD::0x00CA::100734::INSTR",
    VI_FSW43_NET_30: str = "TCPIP::192.168.255.30::inst0::INSTR",
    VI_DSA815TG: str = "USB0::0x1AB1::0x0960::DSA8A173102012::INSTR",
    VI_DP83103: str = "TCPIP::192.168.255.3::inst0::INSTR",
    VI_34461A_NET: str = "TCPIP::192.168.255.4::inst0::INSTR",
    VI_34461A_USB: str = "USB0::0x2A8D::0x1301::MY57228861::INSTR",
    VI_DM3068_NET: str = "TCPIP::192.168.255.4::inst0::INSTR",
    VI_DM3068_USB_1093: str = "USB0::0x1AB1::0x0C94::DM3O244501093::INSTR",
    VI_DM3068_0266: str = "USB0::0x1AB1::0x0C94::DM3O242400266::INSTR",
    VI_DM3068_0267: str = "USB0::0x1AB1::0x0C94::DM3O242400267::INSTR",
    VI_DM3068_1092: str = "USB0::0x1AB1::0x0C94::DM3O244501092::INSTR",
    VI_DM3068_1093: str = "USB0::0x1AB1::0x0C94::DM3O244501093::INSTR",
    VI_DM3068_1079: str = "USB0::0x1AB1::0x0C94::DM3O244501079::0::INSTR",
    VI_DP83105: str = "TCPIP::192.168.255.5::inst0::INSTR",
    VI_N9020A_NET: str = "TCPIP::192.168.255.6::inst0::INSTR",
    VI_N9020A_USB: str = "USB0::0x2A8D::0x0A0B::MY54432180::INSTR",
    VI_N9020A_USB_0: str = "USB0::0x2A8D::0x0A0B::MY53292243::INSTR",
    VI_N9020A_USB_1: str = "USB0::10893::2571::MY53292243::0::INSTR",
    VI_N9020A_USB_2: str = "USB0::0x2A8D::0x0A0B::MY53421841::0::INSTR",
    VI_DP83107: str = "TCPIP::192.168.255.7::inst0::INSTR",
    VI_N5183A: str = "TCPIP::192.168.255.8::inst0::INSTR",
    VI_DP83109_NET: str = "TCPIP::192.168.255.9::inst0::INSTR",
    VI_DP83109_USB: str = "USB0::0x1AB1::0x0E11::DP8A171500069::INSTR",
    VI_DG1062_NET: str = "TCPIP::192.168.255.10::inst0::INSTR",
    VI_DG1062_USB: str = "USB0::0x1AB1::0x0642::DG1ZA172601891::INSTR",
    VI_DG4202_USB: str = "USB0::0x1AB1::0x0642::DG1ZA172601891::INSTR",
    VI_MXR056A: str = "USB0::0x2A8D::0x9007::MY61310403::0::INSTR",  # *********add 20231215
    VI_DP83111: str = "TCPIP::192.168.255.11::inst0::INSTR",
    VI_RTO1044Z: str = "TCPIP::192.168.255.12::inst0::INSTR",
    VI_DP83113: str = "TCPIP::192.168.255.13::inst0::INSTR",
    VI_MSO1104: str = "TCPIP::192.168.255.14::inst0::INSTR",
    VI_DS1104: str = "TCPIP::192.168.255.15::inst0::INSTR",
    VI_DP83116_net: str = "TCPIP::192.168.255.16::inst0::INSTR",
    VI_DP83116_usb: str = "USB0::0x1AB1::0x0E11::DP8F201100040::INSTR",
    VI_DP83117: str = "USB0::0x1AB1::0x0E11::DP8B241601301::INSTR",
    VI_DP83118: str = "USB0::0x1AB1::0x0E11::DP8A172400146::INSTR",
    VI_DSA815_net: str = "TCPIP::192.168.255.17::inst0::INSTR",
    VI_DSA815_usb: str = "USB0::0x1AB1::0x0960::DSA8B173100481::INSTR",
    # VI_DSA815TG_net: str = "TCPIP::192.168.255.17::inst0::INSTR",
    VI_DSA815TG_USB_0: str = "USB0::0x1AB1::0x0960::DSA8A173102012::INSTR",
    VI_MS4644B: str = "TCPIP::192.168.255.30::INSTR",
    VI_UXR: str = "TCPIP0::192.168.255.30::5032::SOCKET",
    VI_N6705C_net: str = "TCPIP::192.168.255.19::inst0::INSTR",
    VI_N6705C_usb: str = "USB0::0x2A8D::0x0F02::MY56004125::INSTR",
    VI_DH3286: str = "USB0::0x0957::0xA007::3286386D3137::INSTR",
    VI_DH205C: str = "USB0::0x0957::0xA007::205C337B5253::INSTR",
    VI_DH3890: str = "USB0::0x0957::0xA007::3890346B3137::INSTR",
    VI_DH3267: str = "USB0::0x0957::0xA007::326738673137::INSTR",
    VI_N9020A_NET_SZ: str = "TCPIP::192.168.255.12::INSTR",


def list_devices() -> List[str]:
    """
    查找连接到计算机上的设备，并返回一个包含设备信息的字符串
    :return: 一个包含设备序列号的字符串列表
    """
    # 初始化获取网络连接的
    rm_net = visa.ResourceManager("@py")
    # 初始化获取USB的
    rm_usb = visa.ResourceManager()
    # 定义一个设备的列表,前面是网络连接,后面是USB连接的
    devices = []
    # 获取网络连接的
    instr_adder_net = rm_net.list_resources()
    # 获取USB连接的
    instr_adder_usb = rm_usb.list_resources()

    # 使用for循环遍历
    for item in instr_adder_net:
        devices.append(item)

    for item in instr_adder_usb:
        instr_adder_fixed = item.replace("::0::INSTR", "::INSTR")
        devices.append(instr_adder_fixed)

    logger.debug("find VISA devices: %s", devices)
    # 获取要打开设备的信息
    return devices


class VisaConnection:
    def __init__(self, resource_name, timeout: Optional[float] = None) -> None:
        self._resource_name = resource_name
        self._timeout = timeout
        self._visa_resource = None
        self._read_termination = None
        self._write_termination = None

    def __getattr__(self, item):
        if self._visa_resource is not None:
            try:
                return getattr(self._visa_resource, item)
            except AttributeError:
                raise AttributeError(f"'Resource' object has no attribute '{item}'")
        raise AttributeError(f"'VisaConnection' object has no connected resource for attribute '{item}'")

    def _send(self, data: bytes) -> None:
        self._visa_resource.write_raw(data)

    def _recv(self) -> str:
        return self._visa_resource.read()

    def open(self, timeout: Optional[float] = None) -> None:
        rm = visa.ResourceManager()
        resources_list = rm.list_resources() if isinstance(self._resource_name, int) else None

        if resources_list:
            logger.debug(f"Open VISA device at index {self._resource_name}: {resources_list[self._resource_name]}")
            self._resource_name = resources_list[self._resource_name]

        if self._resource_name in InstrumentInfo.__dict__.keys():
            self._resource_name = getattr(InstrumentInfo, self._resource_name)[0]
            print(self._resource_name)
        self._visa_resource = rm.open_resource(self._resource_name, timeout=timeout or self._timeout)

        self.set_read_termination(self._read_termination)
        self.set_write_termination(self._write_termination)

    def close(self) -> None:
        if self._visa_resource is not None:
            self._visa_resource.close()
            self._visa_resource = None

    @property
    def is_open(self) -> bool:
        try:
            return self._visa_resource.session is not None
        except AttributeError:
            return False

    def clear_buffer(self) -> None:
        if self.is_open:
            self._visa_resource.clear()

    def send(self, data: Union[bytes, str]) -> None:
        if isinstance(data, str):
            data = data.encode('utf-8')
        self._send(data)

    def recv(self, timeout: Optional[float] = None) -> Union[bytes, str]:
        original_timeout = self._visa_resource.timeout
        try:
            if timeout is not None:
                self._visa_resource.timeout = timeout
            return self._recv()
        finally:
            self._visa_resource.timeout = original_timeout

    def set_read_termination(self, termination: str) -> None:
        self._read_termination = termination
        if self._visa_resource is not None:
            self._visa_resource.read_termination = termination

    def set_write_termination(self, termination: str) -> None:
        self._write_termination = termination
        if self._visa_resource is not None:
            self._visa_resource.write_termination = termination

    def get_device_id(self) -> Optional[str]:
        try:
            return self.command("*IDN?", sleep=True)
        except visa.VisaIOError as e:
            logger.error(f"Error getting device ID: {e}")
            return None

    def command(self, message: Union[str, bytes], delay: float = 0.1, max_retries: int = 3,
                timeout: Optional[float] = 10, sleep=False, is_clear_buffer=True) -> Optional[str]:
        start_time = time.time()
        for retry in range(max_retries):
            if is_clear_buffer:
                self.clear_buffer()
            try:
                # self.clear_buffer()
                self.send(message)
                if sleep:
                    time.sleep(0.5)
                if isinstance(message, str) and '?' in message:
                    return self.recv(timeout=timeout)
                return None
            except visa.VisaIOError as e:
                if retry >= max_retries - 1:
                    raise e
                time.sleep(delay)

            if timeout is not None and time.time() - start_time >= timeout:
                raise TimeoutError("Command timeout")

    def try_open(self, timeout: Optional[float] = None, interval: float = 1) -> None:
        start_time = time.time()
        while True:
            try:
                self.open()
                if self.is_open:
                    break
            except visa.VisaIOError as e:
                logger.warning(f"Failed to open connection to {self._resource_name}: {e}")
                if timeout is not None and time.time() - start_time >= timeout:
                    raise TimeoutError("Try open timeout")
                time.sleep(interval)

    @contextmanager
    def connection(self, timeout: Optional[float] = None):
        self.open(timeout)
        try:
            yield
        finally:
            self.close()

    def destroy_resources(self) -> None:
        self.close()
        self._resource_name = None
        self._timeout = None
        self._read_termination = None
        self._write_termination = None
        logger.info("VisaConnection resources destroyed.")
