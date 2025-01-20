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
logger.setLevel(logging.DEBUG)

# 创建控制台处理器
console_handler = logging.StreamHandler(sys.stdout)  # 指定输出到标准输出
console_handler.setLevel(logging.DEBUG)

# 创建文件处理器
file_handler = logging.FileHandler('logs/audio_player.log', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)

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
            # 初始化输出数据为0
            mixed_audio = np.zeros(frames, dtype=np.int16)
            
            with self.buffer_lock:
                buffer_size = len(self.audio_buffer)
                if self.audio_buffer:
                    # 从缓冲区获取音频数据
                    audio_data = self.audio_buffer.popleft()
                    if len(audio_data) >= frames:
                        mixed_audio = audio_data[:frames]
                    else:
                        # 如果数据不够，用零填充
                        mixed_audio[:len(audio_data)] = audio_data
                    logger.debug(f"Playing audio frame, buffer size: {buffer_size-1}")
            
            # 将音频写入输出缓冲区
            outdata[:] = mixed_audio.reshape(-1, 1)
            
        except Exception as e:
            logger.error(f"Error in audio callback: {str(e)}")
            outdata.fill(0)
        
    def process_with_vad(self, audio_array):
        """使用VAD处理音频数据"""
        try:
            # 将音频数据转换为字节
            raw_audio = struct.pack("h" * len(audio_array), *audio_array)
            
            # WebRTC VAD需要10ms、20ms或30ms的帧
            frame_duration = 20  # 使用20ms帧，提高响应速度
            frame_size = int(self.sample_rate * frame_duration / 1000)  # 每帧采样点数
            
            # 将音频分成20ms的帧
            frames = [raw_audio[i:i + frame_size * 2] for i in range(0, len(raw_audio), frame_size * 2)]
            
            # 如果没有在说话状态，直接开始新的语音片段
            if not self.is_speaking:
                self.speech_frames = []
            
            speech_detected = False
            
            for frame in frames:
                if len(frame) == frame_size * 2:  # 确保帧长度正确
                    try:
                        is_speech = self.vad.is_speech(frame, self.sample_rate)
                        if is_speech:
                            speech_detected = True
                            self.silence_duration = 0
                            self.is_speaking = True
                        elif self.is_speaking:
                            self.silence_duration += 1
                    except Exception as e:
                        logger.error(f"VAD处理单帧时出错: {str(e)}")
                        continue
                    
                    # 保存当前帧的音频数据
                    frame_samples = np.frombuffer(frame, dtype=np.int16)
                    self.speech_frames.extend(frame_samples)
            
            # 处理语音片段结束的情况
            if self.is_speaking and (self.silence_duration >= self.SILENCE_THRESHOLD or speech_detected):
                if len(self.speech_frames) > 0:
                    # 将完整的语音片段添加到播放缓冲区
                    with self.buffer_lock:
                        self.audio_buffer.append(np.array(self.speech_frames))
                        logger.debug(f"Added speech segment to buffer, length: {len(self.speech_frames)}")
                    
                    # 重置状态
                    self.speech_frames = []
                    if self.silence_duration >= self.SILENCE_THRESHOLD:
                        self.is_speaking = False
                        self.silence_duration = 0
                
        except Exception as e:
            logger.error(f"Error in VAD processing: {str(e)}")
            logger.error(traceback.format_exc())
            # 发生错误时，直接播放原始音频
            with self.buffer_lock:
                self.audio_buffer.append(audio_array)
                logger.debug("Error occurred, added original audio to buffer")

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
            self.process_with_vad(audio_array)
            
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