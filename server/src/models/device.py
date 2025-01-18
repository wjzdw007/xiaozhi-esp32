from pydantic import BaseModel
from typing import List, Optional

class ApplicationInfo(BaseModel):
    version: str
    name: Optional[str] = None
    compile_time: Optional[str] = None
    idf_version: Optional[str] = None
    elf_sha256: Optional[str] = None

class BoardInfo(BaseModel):
    type: Optional[str] = None
    revision: Optional[str] = None
    carrier: Optional[str] = None
    csq: Optional[str] = None
    imei: Optional[str] = None
    iccid: Optional[str] = None
    ssid: Optional[str] = None
    rssi: Optional[int] = None
    channel: Optional[int] = None
    ip: Optional[str] = None
    mac: Optional[str] = None

class DeviceInfo(BaseModel):
    """设备信息模型"""
    application: ApplicationInfo
    flash_size: Optional[int] = None
    minimum_free_heap_size: Optional[int] = None
    mac_address: Optional[str] = None
    chip_model_name: Optional[str] = None
    board: Optional[BoardInfo] = None 