import asyncio
import logging
from typing import Dict, Optional
import sounddevice as sd
import numpy as np
import threading
import queue
from collections import deque
from .udp_server import global_audio_queue, queue_lock
from opuslib import Decoder
import traceback
import sys
import webrtcvad
import struct

print("Audio player module loaded")  # 添加这行来确认模块被正确加载

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 创建控制台处理器
console_handler = logging.StreamHandler(sys.stdout)  # 指定输出到标准输出
console_handler.setLevel(logging.INFO)

# 创建文件处理器
file_handler = logging.FileHandler('logs/audio_player.log', encoding='utf-8')
file_handler.setLevel(logging.INFO)

# 设置日志格式
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

logger.info("音频播放器日志系统初始化完成")

# 定义 Opus 应用类型常量
OPUS_APPLICATION_VOIP = 2048
OPUS_APPLICATION_AUDIO = 2049
OPUS_APPLICATION_RESTRICTED_LOWDELAY = 2051

class AudioPlayer:
    def __init__(self, sample_rate: int = 16000):
        print(f"Initializing AudioPlayer with sample_rate={sample_rate}")
        self.sample_rate = sample_rate
        self.stream = None
        self.is_playing = False
        self.audio_buffer = deque(maxlen=100)  # 本地音频缓冲区
        self.buffer_lock = threading.Lock()
        self._monitor_task = None  # 用于存储监控任务
        
        # VAD相关初始化
        self.vad = webrtcvad.Vad(2)  # 降低VAD灵敏度为2
        self.vad_buffer = []  # 存储待处理的音频数据
        self.speech_frames = []  # 存储检测到的语音帧
        self.silence_duration = 0  # 记录静音持续时间
        self.is_speaking = False  # 当前是否在说话
        self.SILENCE_THRESHOLD = 15  # 降低静音阈值
        
        # 创建Opus解码器
        try:
            self.frame_size = int(sample_rate * 0.06)  # 60ms
            self.channels = 1
            print("Creating Opus decoder...")
            self.decoder = Decoder(sample_rate, self.channels)
            print("Opus decoder created successfully")
            logger.info(f"Created Opus decoder with frame size: {self.frame_size}")
        except Exception as e:
            print(f"Failed to create Opus decoder: {e}")
            logger.error(f"Failed to create Opus decoder: {str(e)}")
            raise
        
        # 打印可用的音频设备信息
        try:
            logger.info("=== 音频设备信息 ===")
            devices = sd.query_devices()
            logger.info("可用的音频设备列表:")
            for i, dev in enumerate(devices):
                logger.info(f"[{i}] {dev['name']}")
                logger.info(f"    输入通道: {dev['max_input_channels']}")
                logger.info(f"    输出通道: {dev['max_output_channels']}")
                logger.info(f"    默认采样率: {dev['default_samplerate']}")
            
            # 获取默认输出设备
            default_device = sd.query_devices(kind='output')
            logger.info("=== 默认输出设备信息 ===")
            logger.info(f"设备名称: {default_device['name']}")
            logger.info(f"输出通道数: {default_device['max_output_channels']}")
            logger.info(f"默认采样率: {default_device['default_samplerate']}")
            logger.info(f"设备ID: {sd.default.device[1]}")  # 获取默认输出设备ID
            
            # 测试音频设备是否可用
            logger.info("正在测试音频设备...")
            test_stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype=np.int16
            )
            test_stream.start()
            test_stream.stop()
            test_stream.close()
            logger.info("音频设备测试成功")
            
        except Exception as e:
            logger.error(f"音频设备初始化失败: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    @classmethod
    async def create(cls, sample_rate: int = 16000):
        """创建并初始化AudioPlayer的异步工厂方法"""
        print("AudioPlayer.create called")  # 添加这行
        player = cls(sample_rate)
        await player.initialize()
        return player

    async def initialize(self):
        """异步初始化方法"""
        print("Initializing audio player...")  # 添加这行
        self.start_playing()
        print("Audio player initialized")  # 添加这行
        logger.info("Audio player initialized and started automatically")
        
    async def _monitor_audio_queue(self):
        """监控全局音频队列的后台任务"""
        logger.info("Starting audio queue monitor")
        while self.is_playing:
            try:
                # 尝试从全局队列获取音频数据
                with queue_lock:
                    try:
                        audio_data = global_audio_queue.get_nowait()
                        logger.debug(f"Got audio data from global queue, size: {len(audio_data)} bytes")
                        await self.play_audio(audio_data)
                    except queue.Empty:
                        pass
                
                # 短暂休眠以避免CPU过度使用
                await asyncio.sleep(0.001)
            except Exception as e:
                logger.error(f"Error in audio queue monitor: {str(e)}")
                await asyncio.sleep(1)  # 发生错误时等待较长时间
        
    def start_playing(self):
        """开始播放音频"""
        try:
            if not self.is_playing:
                self.is_playing = True
                # 创建音频流
                if self.stream is None:
                    logger.info("=== 创建音频流 ===")
                    logger.info(f"采样率: {self.sample_rate}Hz")
                    logger.info(f"通道数: {self.channels}")
                    logger.info(f"帧大小: {self.frame_size}")
                    
                    self.stream = sd.OutputStream(
                        samplerate=self.sample_rate,
                        channels=self.channels,
                        dtype=np.int16,
                        callback=self._audio_callback,
                        blocksize=self.frame_size
                    )
                    self.stream.start()
                    logger.info("音频流创建并启动成功")
                
                # 启动监控任务
                if self._monitor_task is None:
                    self._monitor_task = asyncio.create_task(self._monitor_audio_queue())
                    logger.info("音频队列监控任务已启动")
                
        except Exception as e:
            logger.error(f"启动音频播放失败: {str(e)}")
            logger.error(traceback.format_exc())
            self.is_playing = False
                
    def stop_playing(self):
        """停止播放音频"""
        try:
            self.is_playing = False
            # 停止监控任务
            if self._monitor_task is not None:
                self._monitor_task.cancel()
                self._monitor_task = None
                logger.info("Stopped audio queue monitor task")
            
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
                self.stream = None
                logger.info("Stopped audio playback")
            with self.buffer_lock:
                self.audio_buffer.clear()
        except Exception as e:
            logger.error(f"Error stopping audio playback: {str(e)}")
                
    def _audio_callback(self, outdata, frames, time, status):
        """音频回调函数"""
        if status:
            logger.warning(f"Audio callback status: {status}")
            
        try:
            with self.buffer_lock:
                buffer_size = len(self.audio_buffer)
                # 只有当缓冲区有足够的数据时才消费和输出
                if buffer_size > 0 and len(self.audio_buffer[0]) >= frames:
                    # 从缓冲区获取音频数据
                    audio_data = self.audio_buffer.popleft()
                    mixed_audio = audio_data[:frames]
                    # 只在有数据时才写入输出缓冲区
                    outdata[:] = mixed_audio.reshape(-1, 1)
                    logger.debug(f"Playing audio frame, buffer size: {buffer_size-1}")
                else:
                    # 没有数据时直接填充0（静音）
                    outdata.fill(0)
                    logger.debug(f"等待更多音频数据，当前buffer大小: {buffer_size}")
            
        except Exception as e:
            logger.error(f"Error in audio callback: {str(e)}")
            outdata.fill(0)

    def vad_60ms_to_20ms_frames(self, frame_60ms, sample_rate=16000):
        """
        输入一帧 60ms 的 PCM 数据 (16kHz, mono, 16-bit)，
        拆分为 3 个 20ms 子帧，每个子帧用 VAD 检测。
        
        :param frame_60ms: 60ms 的 PCM 数据 (bytes)，长度应为 1920 字节
        :param sample_rate: 采样率，默认 16kHz
        :return: 该 60ms 帧是否包含语音（布尔值）
        """
        # 确保输入数据是字节格式
        pcm_bytes = frame_60ms if isinstance(frame_60ms, bytes) else bytes(frame_60ms)
        
        # WebRTC VAD 仅支持 10/20/30ms 帧
        # 对于 16kHz, 20ms = 16000 * 0.02 * 2 = 640 bytes
        chunk_size_20ms = 640
        results = []
        
        # 拆分出 3 个 20ms 子帧
        for i in range(3):
            start = i * chunk_size_20ms
            end = start + chunk_size_20ms
            if end <= len(pcm_bytes):
                sub_frame = pcm_bytes[start:end]
                # 调用 VAD
                try:
                    is_speech = self.vad.is_speech(sub_frame, sample_rate)
                    results.append(is_speech)
                except Exception as e:
                    logger.error(f"VAD处理子帧时出错: {str(e)}")
                    continue
        
        # 只要有一个子帧是 True，就认为 60ms 里有人声
        return any(results) if results else False

    def process_with_vad(self, audio_data):
        """使用VAD处理音频数据"""
        try:
            # 将音频数据转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            if self.vad_60ms_to_20ms_frames(audio_data):
                logger.debug("检测到语音")
                with self.buffer_lock:
                    self.audio_buffer.append(audio_array)
            else:
                logger.debug("未检测到语音")
                # # 即使未检测到语音，我们也将音频添加到缓冲区，以保持连续性
                # with self.buffer_lock:
                #     self.audio_buffer.append(audio_array)
                    
        except Exception as e:
            logger.error(f"VAD处理时出错: {str(e)}")
            logger.error(traceback.format_exc())
            # 发生错误时，直接播放原始音频
            with self.buffer_lock:
                self.audio_buffer.append(audio_array)
                logger.debug("错误发生，添加原始音频到缓冲区")

    async def play_audio(self, audio_data: bytes):
        """播放音频数据"""
        if not self.is_playing:
            logger.warning("Cannot play audio: player is not started")
            return
            
        try:
            # 使用Opus解码音频数据
            try:
                logger.debug(f"开始解码音频数据，大小: {len(audio_data)} 字节，帧大小: {self.frame_size}")
                pcm_data = self.decoder.decode(audio_data, self.frame_size)
                # 将解码后的数据转换为numpy数组
                audio_array = np.frombuffer(pcm_data, dtype=np.int16)
                logger.debug(f"解码成功，PCM数据大小: {len(audio_array)} 采样点")
            except Exception as e:
                logger.error(f"Failed to decode Opus data: {str(e)}")
                logger.error(f"错误堆栈: {traceback.format_exc()}")
                return
            
            # 使用VAD处理音频
            self.process_with_vad(pcm_data)
            
        except Exception as e:
            logger.error(f"Error playing audio: {str(e)}")
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            
    def close(self):
        """关闭音频播放器"""
        try:
            self.stop_playing()
            logger.info("Closed audio player")
        except Exception as e:
            logger.error(f"Error closing audio player: {str(e)}")
            
    def __del__(self):
        """析构函数"""
        self.close() 