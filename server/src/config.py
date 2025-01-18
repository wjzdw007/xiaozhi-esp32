import socket
import netifaces

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
                    # 跳过回环地址
                    if not ip.startswith('127.'):
                        return ip
        return "127.0.0.1"
    except Exception as e:
        print(f"Error getting local IP: {e}")
        return "127.0.0.1"

# 全局配置
MQTT_HOST = get_local_ip()
FIRMWARE_VERSION = "1.0.0"
FIRMWARE_URL = "http://example.com/firmware.bin" 