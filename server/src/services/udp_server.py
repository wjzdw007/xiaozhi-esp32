import json
import asyncio
import logging
from typing import Dict, Optional, Callable, List
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import struct
import binascii
from collections import deque
import queue
import threading
import sys

# 配置UDP服务器的日志
logger = logging.getLogger("udp_server")
logger.setLevel(logging.INFO)

# 创建控制台处理器
console_handler = logging.StreamHandler(sys.stdout)  # 指定输出到标准输出
console_handler.setLevel(logging.INFO)

# 创建文件处理器
file_handler = logging.FileHandler('logs/udp_server.log', encoding='utf-8')
file_handler.setLevel(logging.INFO)

# 设置日志格式，添加行号信息
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# 移除所有已存在的处理器
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# 添加处理器到logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# 确保日志会传播到根logger
logger.propagate = True

logger.info("UDP服务器日志系统初始化完成")

# 创建全局音频队列和锁
global_audio_queue = queue.Queue(maxsize=1000)
queue_lock = threading.Lock()

class UDPServer:
    def __init__(self, host: str, port: int, mqtt_handler):
        self.host = host
        self.port = port
        self.transport = None
        self.protocol = None
        self.sessions: Dict[str, dict] = {}
        self.mqtt_handler = mqtt_handler
        self.audio_player = None
        logger.info(f"UDP服务器初始化 - 主机: {host}, 端口: {port}")
        
    def set_audio_player(self, audio_player):
        """设置音频播放器实例"""
        self.audio_player = audio_player
        logger.info("音频播放器已设置到UDP服务器")

    async def start(self):
        """启动UDP服务器"""
        try:
            logger.info("正在启动UDP服务器...")
            loop = asyncio.get_running_loop()
            
            # 创建 UDP endpoint
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: UDPServerProtocol(self),
                local_addr=(self.host, self.port)
            )
            self.transport = transport
            self.protocol = protocol
            logger.info(f"UDP服务器启动成功 - 监听地址: {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"UDP服务器启动失败: {str(e)}")
            raise
        
    def stop(self):
        """停止UDP服务器"""
        if self.transport:
            self.transport.close()
            self.transport = None
            
    def add_session(self, session_id: str, key: str, nonce: str, device_id: str):
        """添加新的会话"""
        try:
            # 将十六进制字符串转换为字节
            key_bytes = binascii.unhexlify(key)
            nonce_bytes = binascii.unhexlify(nonce)
            
            self.sessions[session_id] = {
                "session_id": session_id,
                "key": key_bytes,
                "nonce": nonce_bytes,
                "remote_sequence": 0,
                "local_sequence": 0,
                "device_id": device_id
            }
            logger.info(f"Added UDP session: {session_id}")
            logger.info(f"Session key (hex): {key}")
            logger.info(f"Session nonce (hex): {nonce}")
            
        except Exception as e:
            logger.error(f"Failed to add UDP session: {str(e)}")
        
    def remove_session(self, session_id: str):
        """移除会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Removed UDP session: {session_id}")

    async def get_next_audio(self) -> Optional[bytes]:
        """
        从全局队列中获取下一个音频数据
        :return: 音频数据，如果队列为空则返回None
        """
        try:
            with queue_lock:
                return global_audio_queue.get_nowait()
        except queue.Empty:
            return None

    def process_audio_packet(self, data: bytes, addr):
        """处理音频数据包"""
        logger.debug(f"收到来自 {addr} 的音频数据包，大小: {len(data)} 字节")
        
        if len(data) < 16:
            logger.warning(f"数据包太小: {len(data)} 字节")
            return
            
        nonce = data[0:16]
        # 检查数据包类型
        packet_type = nonce[0]
        if packet_type != 0x01:
            logger.warning(f"无效的音频数据包类型: {packet_type:x}")
            return
            
        # 从 nonce 中获取数据大小和序列号
        data_size = struct.unpack(">H", nonce[2:4])[0]
        sequence = struct.unpack(">I", nonce[12:16])[0]
        encrypted = data[16:]
        
        logger.debug(f"数据包信息 - 大小: {data_size}, 序列号: {sequence}")
        
        if len(encrypted) != data_size:
            logger.warning(f"数据大小不匹配: 期望 {data_size}, 实际 {len(encrypted)}")
            return
            
        # 查找对应的会话
        session = None
        session_nonce = nonce[4:12].hex()
        logger.debug(f"查找会话 nonce: {session_nonce}")
        
        for s in self.sessions.values():
            if s["nonce"][4:12] == nonce[4:12]:
                session = s
                logger.debug(f"找到匹配的会话: {s['session_id']}")
                break
                
        if not session:
            logger.warning(f"未找到对应的会话, nonce: {nonce.hex()}")
            return
            
        # 检查序列号
        remote_sequence = session.get("remote_sequence", 0)
        if sequence < remote_sequence:
            logger.warning(f"收到过期的音频数据包 - 序列号: {sequence}, 期望: {remote_sequence}")
            return
        if sequence != remote_sequence + 1:
            logger.warning(f"收到错误序列号的数据包 - 当前: {sequence}, 期望: {remote_sequence + 1}")
            
        logger.debug(f"开始解密数据包 - 大小: {len(encrypted)} 字节")
        
        # 使用 AES-CTR 模式解密
        try:
            cipher = Cipher(
                algorithms.AES(session["key"]),
                modes.CTR(nonce),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted) + decryptor.finalize()
            logger.debug(f"数据包解密成功 - 解密后大小: {len(decrypted)} 字节")
        except Exception as e:
            logger.error(f"数据包解密失败: {str(e)}")
            return
        
        # 更新远程序列号
        session["remote_sequence"] = sequence
        
        # 将解密后的音频数据添加到全局队列
        with queue_lock:
            try:
                global_audio_queue.put_nowait(decrypted)
                logger.debug(f"音频数据已添加到全局队列 - 当前队列大小: {global_audio_queue.qsize()}")
            except queue.Full:
                logger.warning("全局音频队列已满，丢弃数据包")

class UDPServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: UDPServer):
        self.server = server  # 保存对 UDPServer 的引用
        self.transport = None
        logger.info("UDP协议处理器已初始化")
        
    def connection_made(self, transport):
        self.transport = transport
        logger.info(f"UDP传输层连接已建立: {transport}")
        
    def datagram_received(self, data: bytes, addr):
        try:
            logger.debug(f"收到UDP数据包 - 来源: {addr}, 大小: {len(data)} 字节")
            # 打印数据包的前16字节（如果有）用于调试
            if len(data) >= 16:
                logger.debug(f"数据包头16字节: {data[:16].hex()}")
            
            # 调用 UDPServer 的方法处理音频数据包
            self.server.process_audio_packet(data, addr)
        except Exception as e:
            logger.error(f"处理UDP数据包时出错: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
    def error_received(self, exc):
        logger.error(f"UDP协议错误: {str(exc)}")
        
    def connection_lost(self, exc):
        if exc:
            logger.error(f"UDP连接断开: {str(exc)}")
        else:
            logger.info("UDP连接正常关闭") 