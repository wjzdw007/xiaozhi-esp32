from fastapi import APIRouter
import asyncio
import json
import logging
from typing import Dict, Optional
import secrets
from datetime import datetime
from aiomqtt import Client, Message
from config import MQTT_HOST, MQTT_USER, MQTT_PASSWORD

router = APIRouter()
logger = logging.getLogger(__name__)

# 存储所有活跃的音频会话
active_sessions: Dict[str, dict] = {}

# UDP服务器实例（将在main.py中设置）
udp_server = None

def set_udp_server(server):
    """设置UDP服务器实例"""
    global udp_server
    udp_server = server

class MQTTHandler:
    def __init__(self):
        self.client = None
        self.connected = False
        self._message_loop_task = None
        
    async def connect(self):
        """连接到MQTT broker"""
        try:
            # aiomqtt 的新版本使用异步上下文管理器
            self.client = Client(
                hostname=MQTT_HOST,
                port=1883,  # 默认MQTT端口
                username=MQTT_USER,
                password=MQTT_PASSWORD
            )
            
            # 启动消息处理循环
            self._message_loop_task = asyncio.create_task(self._message_loop())
            logger.info("Connected to MQTT broker")
            
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {str(e)}")
            self.connected = False
            
    async def _message_loop(self):
        """处理接收到的MQTT消息"""
        try:
            async with self.client as client:
                self.connected = True
                # 订阅所有设备的主题
                await client.subscribe("esp32/device/+/in")
                
                async for message in client.messages:
                    try:
                        # 解析主题，格式：esp32/device/{device_id}/in
                        topic = message.topic.value
                        parts = topic.split("/")
                        if len(parts) != 4:
                            continue
                        device_id = parts[2]
                        
                        # 解析消息内容
                        payload = json.loads(message.payload)
                        message_type = payload.get("type")
                        
                        if message_type == "hello":
                            await self._handle_hello(device_id, payload)
                        elif message_type == "goodbye":
                            await self._handle_goodbye(device_id, payload)
                        # 处理其他消息类型...
                        
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON message from device {device_id}")
                    except Exception as e:
                        logger.error(f"Error processing message: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Message loop error: {str(e)}")
            self.connected = False
            # 如果连接断开，尝试重新连接
            await asyncio.sleep(5)  # 等待5秒后重试
            await self.connect()
            
    async def _handle_hello(self, device_id: str, payload: dict):
        """处理设备的hello消息"""
        try:
            # 生成会话信息
            session_id = secrets.token_hex(16)
            key = secrets.token_hex(16)
            nonce = secrets.token_hex(8)
            
            # 创建响应消息
            response = {
                "type": "hello",
                "session_id": session_id,
                "transport": "udp",
                "version": 3,
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 16000,
                    "channels": 1,
                    "frame_duration": 20
                },
                "udp": {
                    "server": MQTT_HOST,  # 使用相同的主机
                    "port": 8888,
                    "key": key,
                    "nonce": nonce,
                    "encryption": "aes-128-ctr"
                }
            }
            
            # 存储会话信息
            active_sessions[session_id] = {
                "device_id": device_id,
                "created_at": datetime.utcnow(),
                "udp_info": response["udp"]
            }
            
            # 在UDP服务器中注册会话
            if udp_server:
                udp_server.add_session(session_id, key, nonce)
            
            # 发送响应
            if self.client and self.connected:
                await self.client.publish(
                    f"esp32/device/{device_id}/out",
                    payload=json.dumps(response)
                )
            
        except Exception as e:
            logger.error(f"Error handling hello message: {str(e)}")
            
    async def _handle_goodbye(self, device_id: str, payload: dict):
        """处理设备的goodbye消息"""
        session_id = payload.get("session_id")
        if session_id in active_sessions:
            # 从UDP服务器中移除会话
            if udp_server:
                udp_server.remove_session(session_id)
            # 从活跃会话中移除
            del active_sessions[session_id]
            
    async def disconnect(self):
        """断开MQTT连接"""
        if self._message_loop_task:
            self._message_loop_task.cancel()
            try:
                await self._message_loop_task
            except asyncio.CancelledError:
                pass
            
        if self.client:
            await self.client.__aexit__(None, None, None)
            self.connected = False
            self.client = None

# 创建全局MQTT处理器实例
mqtt_handler = MQTTHandler() 