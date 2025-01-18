from fastapi import APIRouter, Request, Header
from typing import Optional
from models.mqtt import MQTTConfig
from models.device import DeviceInfo
from config import MQTT_HOST, MQTT_USER, MQTT_PASSWORD

router = APIRouter()

@router.post("/check_version")
async def check_version(
    request: Request,
    device_id: Optional[str] = Header(None, alias="Device-Id")
):
    """
    检查固件版本并返回MQTT配置
    客户端会在header中设置Device-Id，在body中发送设备信息JSON
    
    请求格式：
    Headers:
        Device-Id: "设备MAC地址"
        Content-Type: "application/json"
    
    Body: {
        "flash_size": 4194304,
        "minimum_free_heap_size": 123456,
        "mac_address": "00:00:00:00:00:00",
        "chip_model_name": "esp32s3",
        "chip_info": {
            "model": 1,
            "cores": 2,
            "revision": 0,
            "features": 0
        },
        "application": {
            "name": "my-app",
            "version": "1.0.0",
            "compile_time": "2021-01-01T00:00:00Z",
            "idf_version": "4.2-dev",
            "elf_sha256": "..."
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
            "type": "esp32-s3",
            ...  # 不同板子的额外信息
        }
    }

    返回格式：
    {
        "mqtt": {
            "endpoint": "mqtt.example.com",
            "client_id": "esp32_client",
            ...
        },
        "firmware": {
            "version": "1.0.0",
            "url": "http://example.com/firmware.bin"
        }
    }
    """
    # 读取设备信息
    body = await request.json()
    device_info = DeviceInfo.model_validate(body)
    
    # 创建MQTT配置
    # 这里可以根据设备信息来生成对应的配置
    mqtt_config = MQTTConfig(
        endpoint=MQTT_HOST,  # MQTT服务器地址
        client_id=f"esp32_{device_info.mac_address}",  # 使用MAC地址作为客户端ID
        username=MQTT_USER,  # MQTT用户名
        password=MQTT_PASSWORD,  # MQTT密码
        subscribe_topic=f"esp32/device/{device_info.mac_address}/in",  # 设备特定的主题
        publish_topic=f"esp32/device/{device_info.mac_address}/out"  # 设备特定的主题
    )
    
    # 检查版本并返回固件信息
    current_version = device_info.application.version
    latest_version = "0.9.9"  # 固定版本号
    firmware_url = "http://example.com/firmware.bin"  # 这里应该是实际的固件URL
    
    return {
        "mqtt": mqtt_config.model_dump(),
        "firmware": {
            "version": latest_version,
            "url": firmware_url
        }
    } 