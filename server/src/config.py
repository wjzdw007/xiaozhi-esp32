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
MQTT_HOST = get_local_ip()  # 使用本机IP
MQTT_PORT = 1883
MQTT_USER = os.getenv("MQTT_USER", "xiaozhi")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "mac8688965")

# 服务器配置
SERVER_HOST = "0.0.0.0"  # 监听所有网络接口
SERVER_PORT = 8000  # HTTP服务端口
UDP_PORT = 8888    # UDP服务端口

FIRMWARE_VERSION = "1.0.0"
FIRMWARE_URL = "http://example.com/firmware.bin" 