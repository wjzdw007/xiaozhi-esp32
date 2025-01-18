import pytest
import sys
import os

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

@pytest.fixture
def test_device_info():
    """返回测试用的设备信息"""
    return {
        "flash_size": 4194304,
        "minimum_free_heap_size": 123456,
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "chip_model_name": "esp32s3",
        "chip_info": {
            "model": 1,
            "cores": 2,
            "revision": 0,
            "features": 0
        },
        "application": {
            "name": "xiaozhi",
            "version": "0.9.0",
            "compile_time": "2024-01-17T10:00:00Z",
            "idf_version": "5.0.0",
            "elf_sha256": "0123456789abcdef"
        },
        "partition_table": [
            {
                "label": "app",
                "type": 1,
                "subtype": 2,
                "address": 65536,
                "size": 1048576
            }
        ],
        "ota": {
            "label": "ota_0"
        },
        "board": {
            "type": "esp32-s3-box"
        }
    } 