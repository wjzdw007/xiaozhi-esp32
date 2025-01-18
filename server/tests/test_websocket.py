import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routes.websocket import router
import json

@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    return app

@pytest.fixture
def client(app):
    return TestClient(app)

def test_websocket_unauthorized(client):
    """测试未授权的连接请求"""
    with client.websocket_connect("/ws") as websocket:
        # 由于没有提供认证信息，应该立即断开连接
        with pytest.raises(Exception):
            websocket.receive_text()

def test_websocket_missing_device_id(client):
    """测试缺少设备ID的连接请求"""
    with client.websocket_connect(
        "/ws",
        headers={"Authorization": "Bearer your-access-token"}
    ) as websocket:
        # 由于没有提供设备ID，应该立即断开连接
        with pytest.raises(Exception):
            websocket.receive_text()

def test_websocket_successful_connection(client):
    """测试成功的连接和握手过程"""
    with client.websocket_connect(
        "/ws",
        headers={
            "Authorization": "Bearer your-access-token",
            "Device-Id": "test-device-001",
            "Protocol-Version": "1"
        }
    ) as websocket:
        # 发送客户端 hello 消息
        hello_msg = {
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 20
            }
        }
        websocket.send_text(json.dumps(hello_msg))
        
        # 接收服务器的 hello 响应
        response = websocket.receive_text()
        response_data = json.loads(response)
        
        assert response_data["type"] == "hello"
        assert response_data["version"] == 1
        assert response_data["transport"] == "websocket"
        assert "audio_params" in response_data
        assert response_data["audio_params"]["format"] == "opus"
        assert response_data["audio_params"]["sample_rate"] == 16000

def test_websocket_binary_message(client):
    """测试二进制音频数据的发送和接收"""
    with client.websocket_connect(
        "/ws",
        headers={
            "Authorization": "Bearer your-access-token",
            "Device-Id": "test-device-001",
            "Protocol-Version": "1"
        }
    ) as websocket:
        # 完成握手
        hello_msg = {
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 20
            }
        }
        websocket.send_text(json.dumps(hello_msg))
        websocket.receive_text()  # 接收服务器的 hello 响应
        
        # 发送二进制音频数据
        test_audio_data = bytes([0x1, 0x2, 0x3, 0x4])
        websocket.send_bytes(test_audio_data)

def test_websocket_text_message(client):
    """测试文本消息的发送和接收"""
    with client.websocket_connect(
        "/ws",
        headers={
            "Authorization": "Bearer your-access-token",
            "Device-Id": "test-device-001",
            "Protocol-Version": "1"
        }
    ) as websocket:
        # 完成握手
        hello_msg = {
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 20
            }
        }
        websocket.send_text(json.dumps(hello_msg))
        websocket.receive_text()  # 接收服务器的 hello 响应
        
        # 发送文本消息
        test_message = {
            "type": "command",
            "action": "test",
            "data": "test message"
        }
        websocket.send_text(json.dumps(test_message))

def test_multiple_connections(client):
    """测试多个设备同时连接的情况"""
    # 创建第一个连接
    with client.websocket_connect(
        "/ws",
        headers={
            "Authorization": "Bearer your-access-token",
            "Device-Id": "device-001",
            "Protocol-Version": "1"
        }
    ) as ws1:
        # 创建第二个连接
        with client.websocket_connect(
            "/ws",
            headers={
                "Authorization": "Bearer your-access-token",
                "Device-Id": "device-002",
                "Protocol-Version": "1"
            }
        ) as ws2:
            # 两个设备都发送 hello
            hello_msg = {
                "type": "hello",
                "version": 1,
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 16000,
                    "channels": 1,
                    "frame_duration": 20
                }
            }
            
            ws1.send_text(json.dumps(hello_msg))
            ws2.send_text(json.dumps(hello_msg))
            
            # 验证两个设备都收到了服务器的 hello 响应
            response1 = json.loads(ws1.receive_text())
            response2 = json.loads(ws2.receive_text())
            
            assert response1["type"] == "hello"
            assert response2["type"] == "hello" 