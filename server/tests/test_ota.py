import sys
import os
from fastapi.testclient import TestClient
import pytest

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from main import app

client = TestClient(app)

def test_check_version(test_device_info):
    """测试检查版本接口"""
    headers = {
        "Device-Id": test_device_info["mac_address"],
        "Content-Type": "application/json"
    }

    response = client.post("/api/v1/check_version", headers=headers, json=test_device_info)
    assert response.status_code == 200
    
    data = response.json()
    assert "mqtt" in data
    assert "firmware" in data
    
    # 验证MQTT配置
    mqtt = data["mqtt"]
    assert mqtt["endpoint"]
    assert mqtt["client_id"] == f"esp32_{test_device_info['mac_address']}"
    assert mqtt["subscribe_topic"] == f"esp32/device/{test_device_info['mac_address']}/in"
    assert mqtt["publish_topic"] == f"esp32/device/{test_device_info['mac_address']}/out"
    
    # 验证固件信息
    firmware = data["firmware"]
    assert "version" in firmware
    assert "url" in firmware

def test_check_version_minimal_device_info():
    """测试最小化的设备信息"""
    # 只提供必要的信息
    device_info = {
        "application": {
            "version": "0.9.0"  # 客户端主要使用这个来检查版本
        }
    }

    headers = {
        "Content-Type": "application/json"
    }

    response = client.post("/api/v1/check_version", headers=headers, json=device_info)
    assert response.status_code == 200
    
    data = response.json()
    assert "firmware" in data
    firmware = data["firmware"]
    assert "version" in firmware
    assert "url" in firmware

def test_check_version_with_post_data():
    """测试带有 POST 数据的请求"""
    # 客户端会发送 board.GetJson() 的内容
    device_info = {
        "flash_size": 4194304,
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "chip_model_name": "esp32s3",
        "application": {
            "version": "0.9.0",
            "name": "xiaozhi",
            "compile_time": "2024-01-17T10:00:00Z",
            "idf_version": "5.0.0"
        },
        "board": {
            "type": "esp32-s3-box",
            "revision": "v1.0"
        }
    }

    headers = {
        "Content-Type": "application/json"
    }

    response = client.post("/api/v1/check_version", headers=headers, json=device_info)
    assert response.status_code == 200
    
    data = response.json()
    assert "mqtt" in data
    assert "firmware" in data 