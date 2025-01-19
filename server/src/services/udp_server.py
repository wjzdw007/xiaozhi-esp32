import asyncio
import logging
from typing import Dict, Optional, Callable
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import struct
import binascii

# 配置UDP服务器的日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 设置为DEBUG级别以显示所有日志

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

# 设置日志格式
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# 添加处理器到logger
logger.addHandler(console_handler)

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
                "remote_sequence": 0  # 远程序列号
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
            # 数据包格式：[16字节nonce][N字节加密数据]
            logger.info(f"Received UDP packet from {addr}, total size: {len(data)} bytes")
            logger.info(f"Raw packet data (hex): {data.hex()}")
            
            if len(data) < 16:  # 最小包长度
                logger.warning(f"Invalid packet size from {addr}")
                return
                
            # 提取nonce和加密数据
            nonce = data[:16]
            logger.info(f"Nonce (hex): {nonce.hex()}")
            logger.info(f"Nonce bytes: {[b for b in nonce]}")
            
            # 检查数据包类型
            packet_type = nonce[0]
            logger.info(f"Packet type: 0x{packet_type:02x} ({packet_type})")
            if packet_type != 0x01:  # 音频数据包类型
                logger.warning(f"Invalid audio packet type: {packet_type:x}")
                return
                
            data_size = struct.unpack(">H", nonce[2:4])[0]  # 大小存储在nonce[2:4]
            sequence = struct.unpack(">I", nonce[12:16])[0]  # 序列号存储在nonce[12:16]
            encrypted_data = data[16:]
            
            logger.info(f"Data size from nonce: {data_size}")
            logger.info(f"Sequence number: {sequence}")
            logger.info(f"Encrypted data size: {len(encrypted_data)}")
            
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
                logger.info("Available sessions nonces:")
                for s in self.sessions.values():
                    logger.info(f"Session nonce: {s['nonce'].hex()}")
                return
                
            # 检查序列号
            remote_sequence = session.get("remote_sequence", 0)
            if sequence < remote_sequence:
                logger.warning(f"Received audio packet with old sequence: {sequence}, expected: {remote_sequence}")
                return
            if sequence != remote_sequence + 1:
                logger.warning(f"Received audio packet with wrong sequence: {sequence}, expected: {remote_sequence + 1}")
            
            # 解密数据
            decryptor = session["cipher"].decryptor()
            audio_data = decryptor.update(encrypted_data)
            
            # 更新远程序列号
            session["remote_sequence"] = sequence
            
            # 记录日志
            logger.info(f"Successfully decrypted {len(audio_data)} bytes of audio data")
            
            # 构造响应nonce，与客户端完全一致：
            # - 使用初始nonce作为基础
            # - 2-4字节：数据大小
            # - 12-16字节：使用相同的序列号
            new_nonce = bytearray(session["nonce"])  # 使用初始nonce
            new_nonce[0] = 0x02  # 响应类型
            struct.pack_into(">H", new_nonce, 2, len(audio_data))  # 数据大小
            struct.pack_into(">I", new_nonce, 12, sequence)  # 使用相同的序列号
            
            # 创建新的cipher实例用于加密
            cipher = Cipher(
                algorithms.AES(session["key"]),
                modes.CTR(bytes(new_nonce)),
                backend=default_backend()
            )
            
            # 加密响应数据
            encryptor = cipher.encryptor()
            encrypted_audio = encryptor.update(audio_data)
            
            # 发送响应数据包：[16字节nonce][N字节加密数据]
            response_data = bytes(new_nonce) + encrypted_audio
            self.transport.sendto(response_data, addr)
            logger.info(f"Sent response packet: nonce={new_nonce.hex()}, encrypted_size={len(encrypted_audio)}")
                
        except Exception as e:
            logger.error(f"Error processing UDP packet: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
    def error_received(self, exc):
        logger.error(f"UDP protocol error: {str(exc)}")
        
    def connection_lost(self, exc):
        if exc:
            logger.error(f"UDP connection lost: {str(exc)}") 