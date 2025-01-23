from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import json
from typing import Dict, Optional, Callable
import logging
import asyncio

router = APIRouter()
security = HTTPBearer()
logger = logging.getLogger(__name__)

# 全局变量
audio_player = None

def set_audio_player(player):
    """设置音频播放器实例"""
    global audio_player
    audio_player = player
    if player:
        # 设置 WebSocket 管理器到音频播放器
        player.set_ws_manager(ws_manager)
        logger.info("已设置 WebSocket 管理器到音频播放器")

class WebSocketManager:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.active_connections: Dict[str, WebSocket] = {}
        
        # 回调函数
        self.on_audio_data: Optional[Callable[[str, bytes], None]] = None
        self.on_client_connected: Optional[Callable[[str], None]] = None
        self.on_client_disconnected: Optional[Callable[[str], None]] = None

    async def authenticate(self, websocket: WebSocket) -> Optional[str]:
        """验证客户端连接"""
        headers = websocket.headers
        
        # 验证 token
        auth = headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != self.access_token:
            await websocket.close(code=4001, reason="无效的访问令牌")
            return None
            
        # 验证协议版本
        if headers.get("protocol-version") != "1":
            await websocket.close(code=4002, reason="不支持的协议版本")
            return None
            
        # 获取设备ID
        device_id = headers.get("device-id")
        if not device_id:
            await websocket.close(code=4003, reason="缺少设备ID")
            return None
            
        return device_id

    async def handle_hello(self, websocket: WebSocket, message: dict) -> bool:
        """处理客户端 hello 消息"""
        if message.get("transport") != "websocket":
            await websocket.close(code=4004, reason="不支持的传输方式")
            return False
            
        # 发送服务端 hello 响应
        response = {
            "type": "hello",
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1
            }
        }
        await websocket.send_text(json.dumps(response))
        return True

    async def connect(self, websocket: WebSocket, device_id: str):
        """连接新的 WebSocket 客户端"""
        await websocket.accept()
        self.active_connections[device_id] = websocket
        if self.on_client_connected:
            self.on_client_connected(device_id)

    async def disconnect(self, device_id: str):
        """断开 WebSocket 客户端连接"""
        if device_id in self.active_connections:
            del self.active_connections[device_id]
            if self.on_client_disconnected:
                self.on_client_disconnected(device_id)

    async def send_message(self, device_id: str, message: dict):
        """发送JSON消息到指定客户端"""
        if device_id in self.active_connections:
            await self.active_connections[device_id].send_text(json.dumps(message))

    async def send_audio(self, device_id: str, audio_data: bytes):
        """发送音频数据到指定客户端"""
        if device_id in self.active_connections:
            await self.active_connections[device_id].send_bytes(audio_data)

# 创建 WebSocket 管理器实例
ws_manager = WebSocketManager(access_token="test-token")  # 替换为实际的 token

# 定义回调函数
def on_ws_client_connected(device_id: str):
    """当 WebSocket 客户端连接时的回调"""
    logger.info(f"WebSocket设备 {device_id} 已连接")

def on_ws_client_disconnected(device_id: str):
    """当 WebSocket 客户端断开连接时的回调"""
    logger.info(f"WebSocket设备 {device_id} 已断开")

def on_ws_audio_data(device_id: str, audio_data: bytes):
    """当收到音频数据时的回调"""
    logger.debug(f"收到来自WebSocket设备 {device_id} 的音频数据: {len(audio_data)} 字节")
    if audio_player:
        asyncio.create_task(audio_player.play_audio(audio_data))

# 设置回调函数
ws_manager.on_client_connected = on_ws_client_connected
ws_manager.on_client_disconnected = on_ws_client_disconnected
ws_manager.on_audio_data = on_ws_audio_data

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    device_id = None
    try:
        # 验证客户端
        device_id = await ws_manager.authenticate(websocket)
        if not device_id:
            return

        # 连接客户端
        await ws_manager.connect(websocket, device_id)

        # 等待并处理 hello 消息
        data = await websocket.receive_text()
        hello_msg = json.loads(data)
        
        if hello_msg.get("type") != "hello":
            await websocket.close(code=4005, reason="需要先发送 hello 消息")
            return
            
        if not await ws_manager.handle_hello(websocket, hello_msg):
            return

        # 持续处理消息
        while True:
            try:
                message = await websocket.receive()
                
                if "text" in message:
                    # 处理文本消息
                    data = json.loads(message["text"])
                    logger.info(f"收到来自 {device_id} 的JSON消息: {data}")
                    
                elif "bytes" in message:
                    # 处理二进制音频数据
                    if ws_manager.on_audio_data:
                        ws_manager.on_audio_data(device_id, message["bytes"])
                    
            except WebSocketDisconnect:
                break
                
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        
    finally:
        if device_id:
            await ws_manager.disconnect(device_id) 