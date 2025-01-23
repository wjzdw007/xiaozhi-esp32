import socket
import netifaces
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def get_local_ip():
    """获取本机内网IP地址"""
    try:
        # 优先获取 en0 或 eth0 的IP
        for iface in ['en0', 'eth0', 'wlan0']:
            if iface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(iface)
                if netifaces.AF_INET in addrs:
                    return addrs[netifaces.AF_INET][0]['addr']
        
        # 如果没有找到首选接口，遍历所有接口
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in addrs:
                for addr in addrs[netifaces.AF_INET]:
                    ip = addr['addr']
                    # 跳过回环地址和docker地址
                    if not ip.startswith('127.') and not ip.startswith('172.'):
                        return ip
        return "0.0.0.0"  # 如果找不到合适的IP，返回0.0.0.0
    except Exception as e:
        print(f"Error getting local IP: {e}")
        return "0.0.0.0"

# 全局配置
MQTT_HOST = get_local_ip()  # 使用本机IP作为MQTT服务器地址
MQTT_PORT = 1883
MQTT_USER = os.getenv("MQTT_USER", "xiaozhi")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "mac8688965")

# 服务器配置
SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# UDP服务器配置
UDP_PORT = int(os.getenv("UDP_PORT", "8888"))

# WebSocket服务器配置
WEBSOCKET_PORT = int(os.getenv("WEBSOCKET_PORT", "8765"))
WEBSOCKET_ACCESS_TOKEN = os.getenv("WEBSOCKET_ACCESS_TOKEN", "test-token")

# MQTT配置
MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.emqx.io")  # 外部MQTT服务器地址
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")  # 外部MQTT服务器用户名
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "xiaozhi_server")  # MQTT客户端ID

# 音频配置
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_FRAME_DURATION_MS = 20

# 固件配置
FIRMWARE_VERSION = "1.0.0"
FIRMWARE_URL = os.getenv("FIRMWARE_URL", "http://example.com/firmware.bin") 