from fastapi import APIRouter
import asyncio
import json
import logging
from typing import Dict, Optional
import secrets
from datetime import datetime
from aiomqtt import Client, Message
from config import MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASSWORD

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
            if self.client:
                await self.client.disconnect()
                self.client = None
                
            # aiomqtt 的新版本使用异步上下文管理器
            self.client = Client(
                hostname=MQTT_HOST,
                port=MQTT_PORT,  # 使用配置文件中的端口
                username=MQTT_USER,
                password=MQTT_PASSWORD,
                keepalive=90  # 设置keepalive为90秒
            )
            
            # 启动消息处理循环
            if self._message_loop_task:
                self._message_loop_task.cancel()
            self._message_loop_task = asyncio.create_task(self._message_loop())
            logger.info(f"Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")
            
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {str(e)}")
            self.connected = False
            
    async def _message_loop(self):
        """处理接收到的MQTT消息"""
        try:
            async with self.client as client:
                self.connected = True
                # 订阅所有设备的主题，使用 QoS 2
                await client.subscribe([
                    ("esp32/device/+/in", 2),  # 设备发送的消息
                    ("esp32/device/+/out", 2)  # 设备接收的消息
                ])
                
                async for message in client.messages:
                    try:
                        # 解析主题，格式：esp32/device/{device_id}/{direction}
                        topic = message.topic.value
                        parts = topic.split("/")
                        if len(parts) != 4:
                            continue
                        device_id = parts[2]
                        direction = parts[3]  # 'in' 或 'out'
                        
                        # 只处理 'in' 方向的消息
                        if direction != "in":
                            continue
                        
                        # 解析消息内容
                        payload = json.loads(message.payload)
                        message_type = payload.get("type")
                        
                        if message_type == "hello":
                            await self._handle_hello(device_id, payload)
                        elif message_type == "goodbye":
                            await self._handle_goodbye(device_id, payload)
                        elif message_type == "listen":
                            await self._handle_listen(device_id, payload)
                        elif message_type == "abort":
                            await self._handle_abort(device_id, payload)
                        elif message_type == "iot":
                            await self._handle_iot(device_id, payload)
                        else:
                            logger.warning(f"Unknown message type: {message_type}")
                        
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON message from device {device_id}")
                    except Exception as e:
                        logger.error(f"Error processing message: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Message loop error: {str(e)}")
            self.connected = False
            # 如果连接断开，尝试重新连接
            await self._reconnect()
            
    async def _reconnect(self):
        """重新连接到MQTT broker"""
        retry_count = 0
        max_retries = 5
        base_delay = 5  # 基础延迟5秒
        
        while retry_count < max_retries:
            try:
                # 等待一段时间后重试，使用指数退避
                delay = base_delay * (2 ** retry_count)
                await asyncio.sleep(delay)
                
                logger.info(f"Attempting to reconnect (attempt {retry_count + 1}/{max_retries})")
                
                # 确保旧的连接已经清理
                if self.client:
                    try:
                        await self.client.disconnect()
                    except:
                        pass
                    self.client = None
                
                if self._message_loop_task:
                    self._message_loop_task.cancel()
                    self._message_loop_task = None
                
                await self.connect()
                
                if self.connected:
                    logger.info("Successfully reconnected to MQTT broker")
                    return
                    
            except Exception as e:
                logger.error(f"Reconnection attempt failed: {str(e)}")
                
            retry_count += 1
            
        logger.error("Failed to reconnect after maximum retries")

    async def _handle_hello(self, device_id: str, payload: dict):
        """处理设备的hello消息"""
        try:
            # 检查客户端版本
            version = payload.get("version", 1)
            if version != 3:
                logger.warning(f"Unsupported protocol version: {version}")
                return

            # 检查传输方式
            transport = payload.get("transport")
            if transport != "udp":
                logger.warning(f"Unsupported transport: {transport}")
                return

            # 检查音频参数
            audio_params = payload.get("audio_params", {})
            if audio_params.get("format") != "opus" or audio_params.get("sample_rate") != 16000:
                logger.warning(f"Unsupported audio parameters: {audio_params}")
                return

            # 生成会话信息
            session_id = secrets.token_hex(16)
            key = secrets.token_hex(16)  # 128位AES密钥
            
            # 生成nonce，确保第一个字节为0x01
            nonce_bytes = bytearray(8)  # 创建8字节的nonce
            nonce_bytes[0] = 0x01      # 设置第一个字节为音频数据包类型
            # 生成剩余的随机字节
            random_bytes = secrets.token_bytes(7)
            nonce_bytes[1:] = random_bytes
            nonce = nonce_bytes.hex()  # 转换为十六进制字符串
            
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
                    "frame_duration": payload.get("audio_params", {}).get("frame_duration", 60)
                },
                "udp": {
                    "server": MQTT_HOST,
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
                "udp_info": response["udp"],
                "iot_descriptors": None,  # 初始化IoT描述符
                "iot_states": None,       # 初始化IoT状态
            }
            
            # 在UDP服务器中注册会话
            if udp_server:
                udp_server.add_session(session_id, key, nonce)
            
            # 发送响应，使用 QoS 2
            if self.client and self.connected:
                await self.client.publish(
                    f"esp32/device/{device_id}/out",
                    payload=json.dumps(response),
                    qos=2
                )
            
        except Exception as e:
            logger.error(f"Error handling hello message: {str(e)}")
            
    async def _handle_goodbye(self, device_id: str, payload: dict):
        """处理设备的goodbye消息"""
        try:
            session_id = payload.get("session_id")
            if session_id in active_sessions:
                # 从UDP服务器中移除会话
                if udp_server:
                    udp_server.remove_session(session_id)
                # 从活跃会话中移除
                del active_sessions[session_id]
                
                # 发送goodbye响应，使用 QoS 2
                if self.client and self.connected:
                    response = {
                        "type": "goodbye",
                        "session_id": session_id
                    }
                    await self.client.publish(
                        f"esp32/device/{device_id}/out",
                        payload=json.dumps(response),
                        qos=2
                    )
                    
        except Exception as e:
            logger.error(f"Error handling goodbye message: {str(e)}")
            
    async def _handle_listen(self, device_id: str, payload: dict):
        """处理listen相关消息"""
        try:
            session_id = payload.get("session_id")
            if session_id not in active_sessions:
                logger.warning(f"Unknown session: {session_id}")
                return

            state = payload.get("state")
            if state == "detect":
                # 唤醒词检测
                wake_word = payload.get("text", "")
                logger.info(f"Wake word detected: {wake_word}")
                # 这里可以添加唤醒词处理逻辑
            elif state == "start":
                # 开始监听
                mode = payload.get("mode", "manual")
                logger.info(f"Start listening, mode: {mode}")
                # 这里可以添加开始监听的处理逻辑
            elif state == "stop":
                # 停止监听
                logger.info("Stop listening")
                # 这里可以添加停止监听的处理逻辑
            else:
                logger.warning(f"Unknown listen state: {state}")

        except Exception as e:
            logger.error(f"Error handling listen message: {str(e)}")

    async def _handle_abort(self, device_id: str, payload: dict):
        """处理abort消息"""
        try:
            session_id = payload.get("session_id")
            if session_id not in active_sessions:
                logger.warning(f"Unknown session: {session_id}")
                return

            reason = payload.get("reason")
            if reason == "wake_word_detected":
                logger.info("Abort speaking due to wake word detection")
                # 这里可以添加中断语音的处理逻辑
            else:
                logger.info("Abort speaking")
                # 这里可以添加其他中断原因的处理逻辑

        except Exception as e:
            logger.error(f"Error handling abort message: {str(e)}")

    async def _handle_iot(self, device_id: str, payload: dict):
        """处理IoT相关消息"""
        try:
            session_id = payload.get("session_id")
            if session_id not in active_sessions:
                logger.warning(f"Unknown session: {session_id}")
                return

            # 处理设备描述符
            if "descriptors" in payload:
                descriptors = payload["descriptors"]
                logger.info(f"Received IoT descriptors from device {device_id}: {descriptors}")
                # 存储设备描述符
                active_sessions[session_id]["iot_descriptors"] = descriptors

            # 处理设备状态
            if "states" in payload:
                states = payload["states"]
                logger.info(f"Received IoT states from device {device_id}: {states}")
                # 更新设备状态
                active_sessions[session_id]["iot_states"] = states

        except Exception as e:
            logger.error(f"Error handling IoT message: {str(e)}")

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