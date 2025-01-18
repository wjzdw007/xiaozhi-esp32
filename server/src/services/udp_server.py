import asyncio
import logging
from typing import Dict, Optional, Callable
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import struct
import binascii

logger = logging.getLogger(__name__)

class UDPServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.transport = None
        self.protocol = None
        self.sessions: Dict[str, dict] = {}
        
    async def start(self):
        """启动UDP服务器"""
        loop = asyncio.get_running_loop()
        
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: UDPServerProtocol(self.sessions),
            local_addr=(self.host, self.port)
        )
        logger.info(f"UDP server started on {self.host}:{self.port}")
        
    def stop(self):
        """停止UDP服务器"""
        if self.transport:
            self.transport.close()
            self.transport = None
            
    def add_session(self, session_id: str, key: str, nonce: str):
        """添加新的会话"""
        try:
            # 将十六进制字符串转换为字节
            key_bytes = binascii.unhexlify(key)
            nonce_bytes = binascii.unhexlify(nonce)
            
            # 创建AES-CTR加密器
            cipher = Cipher(
                algorithms.AES(key_bytes),
                modes.CTR(nonce_bytes),
                backend=default_backend()
            )
            
            self.sessions[session_id] = {
                "key": key_bytes,
                "nonce": nonce_bytes,
                "cipher": cipher,
                "sequence": 0
            }
            logger.info(f"Added UDP session: {session_id}")
            
        except Exception as e:
            logger.error(f"Failed to add UDP session: {str(e)}")
        
    def remove_session(self, session_id: str):
        """移除会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Removed UDP session: {session_id}")

class UDPServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, sessions: Dict[str, dict]):
        self.sessions = sessions
        self.transport = None
        
    def connection_made(self, transport):
        self.transport = transport
        
    def datagram_received(self, data: bytes, addr):
        try:
            # 数据包格式：
            # [1字节类型][1字节保留][2字节大小][12字节nonce][N字节加密数据]
            if len(data) < 16:  # 最小包长度
                logger.warning(f"Invalid packet size from {addr}")
                return
                
            packet_type = data[0]
            if packet_type != 0x01:  # 音频数据包类型
                logger.warning(f"Unknown packet type: {packet_type}")
                return
                
            data_size = struct.unpack(">H", data[2:4])[0]
            nonce = data[4:16]
            encrypted_data = data[16:]
            
            if len(encrypted_data) != data_size:
                logger.warning(f"Data size mismatch: expected {data_size}, got {len(encrypted_data)}")
                return
                
            # 查找对应的会话
            session = None
            for s in self.sessions.values():
                if s["nonce"][:12] == nonce[:12]:
                    session = s
                    break
                    
            if not session:
                logger.warning(f"Unknown session for nonce: {nonce.hex()}")
                return
                
            # 解密数据
            decryptor = session["cipher"].decryptor()
            audio_data = decryptor.update(encrypted_data)
            
            # 这里可以处理解密后的音频数据
            # 例如：转发到语音识别服务
            logger.debug(f"Received {len(audio_data)} bytes of audio data")
            
            # 发送响应
            # 这里可以根据需要发送响应数据
            # self.transport.sendto(response_data, addr)
                
        except Exception as e:
            logger.error(f"Error processing UDP packet: {str(e)}")
            
    def error_received(self, exc):
        logger.error(f"UDP protocol error: {str(exc)}")
        
    def connection_lost(self, exc):
        if exc:
            logger.error(f"UDP connection lost: {str(exc)}") 