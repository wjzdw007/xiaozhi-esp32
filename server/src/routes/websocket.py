from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import json
from typing import Dict, Optional
import logging

router = APIRouter()
security = HTTPBearer()

# 存储所有活跃的 WebSocket 连接
active_connections: Dict[str, WebSocket] = {}

logger = logging.getLogger(__name__)

async def get_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """验证 Bearer Token"""
    if credentials.scheme != "Bearer":
        raise HTTPException(status_code=403, detail="Invalid authentication scheme")
    if credentials.credentials != "your-access-token":  # 替换为实际的 token 验证逻辑
        raise HTTPException(status_code=403, detail="Invalid token")
    return credentials.credentials

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    device_id = None  # 初始化 device_id
    try:
        # 等待客户端连接
        await websocket.accept()
        
        # 获取并验证 headers
        headers = websocket.headers
        auth_header = headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            await websocket.close(code=4001, reason="Unauthorized")
            return
            
        device_id = headers.get("device-id")
        if not device_id:
            await websocket.close(code=4002, reason="Missing device ID")
            return
            
        # 存储连接
        active_connections[device_id] = websocket
        
        # 等待客户端的 hello 消息
        data = await websocket.receive_text()
        hello_msg = json.loads(data)
        
        if hello_msg.get("type") != "hello":
            await websocket.close(code=4003, reason="Invalid hello message")
            return
            
        # 发送服务器的 hello 响应
        server_hello = {
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1
            }
        }
        await websocket.send_text(json.dumps(server_hello))
        
        # 持续接收消息
        while True:
            try:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                    
                if "text" in message:
                    # 处理文本消息
                    data = json.loads(message["text"])
                    # 在这里处理不同类型的文本消息
                    
                elif "bytes" in message:
                    # 处理二进制音频数据
                    audio_data = message["bytes"]
                    # 在这里处理音频数据
                    
            except WebSocketDisconnect:
                break
                
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        
    finally:
        if device_id and device_id in active_connections:
            del active_connections[device_id]
        try:
            await websocket.close()
        except:
            pass

# 用于向特定设备发送消息的辅助函数
async def send_message_to_device(device_id: str, message: str):
    if device_id in active_connections:
        await active_connections[device_id].send_text(message)
        
async def send_audio_to_device(device_id: str, audio_data: bytes):
    if device_id in active_connections:
        await active_connections[device_id].send_bytes(audio_data) 