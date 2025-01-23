import asyncio
import logging
from typing import Dict, Optional, Set
import sounddevice as sd
import numpy as np
import threading
import queue
from collections import deque
# 这里假设你在同一项目里有 udp_server.py 模块
from .udp_server import global_audio_queue, queue_lock
from opuslib import Decoder
import traceback
import sys
import webrtcvad
import struct
import time
import whisperx
import torch
import tempfile
import wave
import os
from datetime import datetime, timedelta
from openai import AsyncOpenAI
from dotenv import load_dotenv
import edge_tts  # 添加 edge-tts 导入
import json
from routes.mqtt import mqtt_handler

# 加载环境变量
load_dotenv()

# 配置 OpenRouter API
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY environment variable is not set")

# 初始化 OpenAI 客户端
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": "https://github.com"  # 你的应用URL
    }
)

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

class TempFileManager:
    def __init__(self, cleanup_interval: int = 300):  # 默认5分钟清理一次
        self.temp_files: Set[str] = set()  # 存储临时文件路径
        self.cleanup_interval = cleanup_interval
        self.cleanup_task = None
        self.lock = threading.Lock()
        
    def add_file(self, file_path: str):
        """添加临时文件到管理器"""
        with self.lock:
            self.temp_files.add(file_path)
            logger.debug(f"添加临时文件到管理器: {file_path}")
    
    def remove_file(self, file_path: str):
        """从管理器中移除临时文件"""
        with self.lock:
            self.temp_files.discard(file_path)
            logger.debug(f"从管理器中移除临时文件: {file_path}")
    
    async def cleanup_files(self):
        """清理临时文件的异步任务"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                logger.info("开始清理临时文件...")
                
                with self.lock:
                    current_files = self.temp_files.copy()
                    
                for file_path in current_files:
                    try:
                        if os.path.exists(file_path):
                            # 获取文件的最后修改时间
                            mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                            # 如果文件超过10分钟未被修改，则删除
                            if datetime.now() - mtime > timedelta(minutes=10):
                                os.unlink(file_path)
                                self.remove_file(file_path)
                                logger.info(f"成功清理临时文件: {file_path}")
                    except Exception as e:
                        logger.error(f"清理临时文件失败: {file_path}, 错误: {str(e)}")
                
                logger.info(f"临时文件清理完成，剩余文件数: {len(self.temp_files)}")
                
            except Exception as e:
                logger.error(f"临时文件清理任务出错: {str(e)}")
                await asyncio.sleep(60)  # 出错后等待1分钟再试
    
    def start_cleanup_task(self):
        """启动清理任务"""
        if self.cleanup_task is None:
            self.cleanup_task = asyncio.create_task(self.cleanup_files())
            logger.info("临时文件清理任务已启动")
    
    def stop_cleanup_task(self):
        """停止清理任务"""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            self.cleanup_task = None
            logger.info("临时文件清理任务已停止")

class AudioPlayer:
    def __init__(self, sample_rate: int = 16000):
        print(f"Initializing AudioPlayer with sample_rate={sample_rate}")
        self.sample_rate = sample_rate
        self.stream = None
        self.is_playing = False
        self.audio_buffer = deque(maxlen=100)  # 本地音频缓冲区
        self.buffer_lock = threading.Lock()
        self._monitor_task = None  # 用于存储监控任务
        self.udp_server = None  # 添加UDP服务器引用
        self.processing_lock = asyncio.Lock()  # 添加异步处理锁
        self.ws_manager = None  # 添加 WebSocket 管理器引用
        
        # 初始化临时文件管理器
        self.temp_file_manager = TempFileManager()
        
        # VAD相关初始化
        self.vad = webrtcvad.Vad(3)  # 设置VAD灵敏度为2，可以根据需要调整(0~3)
        
        # === 新增/修改开始 ===
        # 下面这些变量用来辅助做整段语音检测
        self.speech_frames = []       # 用于累积完整说话片段（PCM）
        self.silence_duration = 0     # 记录连续静音的计数
        self.is_speaking = False      # 当前是否在说话
        self.SILENCE_THRESHOLD = 15   # 连续多少帧（这里按我们处理60ms为1帧的逻辑）视为说话结束，你可以灵活调整
        self.last_speech_time = 0     # 记录最后一次检测到语音的时间戳
        self.SPEECH_TIMEOUT = 2.0     # 语音超时时间（秒）
        
        # WhisperX 相关
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.asr_model = None
        self.model_loaded = asyncio.Event()  # 用于跟踪模型加载状态
        
        # 创建Opus编码器和解码器
        try:
            self.frame_size = int(sample_rate * 0.06)  # 60ms
            self.channels = 1
            print("Creating Opus encoder and decoder...")
            from opuslib import Encoder, Decoder
            self.encoder = Encoder(sample_rate, self.channels, 'voip')
            self.decoder = Decoder(sample_rate, self.channels)
            print("Opus encoder and decoder created successfully")
            logger.info(f"Created Opus encoder and decoder with frame size: {self.frame_size}")
        except Exception as e:
            print(f"Failed to create Opus encoder/decoder: {e}")
            logger.error(f"Failed to create Opus encoder/decoder: {str(e)}")
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

    async def load_whisperx_model(self):
        """异步加载 WhisperX 模型"""
        try:
            logger.info(f"正在加载 WhisperX 模型，使用设备: {self.device}")
            self.asr_model = whisperx.load_model(
                "large-v3",
                device=self.device,
                compute_type="float16" if self.device == "cuda" else "int8"
            )
            logger.info("WhisperX 模型加载完成")
            self.model_loaded.set()  # 标记模型已加载完成
        except Exception as e:
            logger.error(f"WhisperX 模型加载失败: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    @classmethod
    async def create(cls, sample_rate: int = 16000):
        """创建并初始化AudioPlayer的异步工厂方法"""
        print("AudioPlayer.create called")
        player = cls(sample_rate)
        await player.initialize()
        return player

    async def initialize(self):
        """异步初始化方法"""
        print("Initializing audio player...")
        
        # 启动临时文件清理任务
        self.temp_file_manager.start_cleanup_task()
        
        # 启动模型加载任务
        model_load_task = asyncio.create_task(self.load_whisperx_model())
        
        # 同时启动音频播放
        self.start_playing()
        
        # 等待模型加载完成
        await model_load_task
        
        print("Audio player initialized")
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
        # 对于 16kHz, 20ms = 16000 * 0.02 * 2 = 640 字节 (单声道16位)
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
        return all(results) if results else False

    async def speech_to_text(self, speech_data: bytes) -> str:
        """
        使用 WhisperX 将语音数据转换为文本
        
        :param speech_data: PCM格式的语音数据 (16kHz, 16-bit, 单声道)
        :return: 识别出的文本
        """
        # 等待模型加载完成
        await self.model_loaded.wait()
        
        temp_wav_path = None
        try:
            # 创建临时WAV文件
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
                temp_wav_path = temp_wav.name
                with wave.open(temp_wav.name, 'wb') as wav_file:
                    wav_file.setnchannels(1)  # 单声道
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(self.sample_rate)
                    wav_file.writeframes(speech_data)
                
                # 将临时文件添加到管理器
                self.temp_file_manager.add_file(temp_wav_path)
            
            # 使用 WhisperX 进行语音识别
            logger.info("开始进行语音识别...")
            result = self.asr_model.transcribe(temp_wav_path, batch_size=16)
            
            # 提取识别结果
            if result and "segments" in result and len(result["segments"]) > 0:
                text = " ".join([segment["text"] for segment in result["segments"]])
                logger.info(f"语音识别结果: {text}")
                return text.strip()
            else:
                logger.warning("语音识别未返回有效结果")
                return ""
                
        except Exception as e:
            logger.error(f"语音识别过程中出错: {str(e)}")
            logger.error(traceback.format_exc())
            return ""

    def set_udp_server(self, server):
        """设置UDP服务器实例"""
        self.udp_server = server
        if server:
            logger.info(f"UDP服务器已设置到音频播放器，sessions数量: {len(server.sessions)}")
        else:
            logger.error("尝试设置空的UDP服务器实例")

    def set_ws_manager(self, manager):
        """设置 WebSocket 管理器实例"""
        self.ws_manager = manager
        if manager:
            logger.info("WebSocket 管理器已设置到音频播放器")
        else:
            logger.error("尝试设置空的 WebSocket 管理器实例")

    async def handle_speech_segment(self, speech_data: bytes):
        """
        在说话结束时被调用，处理完整的语音段
        
        :param speech_data: 完整语音PCM的二进制数据（16k、16bit、单声道）
        """
        # 如果已经在处理语音，则跳过
        if self.processing_lock.locked():
            logger.warning("正在处理其他语音，跳过当前语音")
            return
            
        async with self.processing_lock:  # 获取锁
            logger.info(f"处理完整语音段，大小={len(speech_data)} 字节")
            
            # 检查是否有任何可用的连接（UDP或WebSocket）
            has_udp = self.udp_server and self.udp_server.sessions
            has_ws = self.ws_manager and self.ws_manager.active_connections
            
            if not (has_udp or has_ws):
                logger.warning("没有活跃的UDP或WebSocket会话，跳过音频处理")
                return
            
            # 1. 进行语音识别
            recognized_text = await self.speech_to_text(speech_data)
            if recognized_text:
                logger.info(f"语音识别结果: {recognized_text}")
                
                # 发送语音识别结果
                stt_msg = {
                    "type": "stt",
                    "text": recognized_text
                }
                
                # 跟大语言模型对话
                response = await self.chat_with_model(recognized_text)
                logger.info(f"大语言模型回复: {response}")
                
                # 只有当response有内容时才进行语音播放
                if response and response.strip():
                    try:
                        # 准备消息
                        start_tts_msg = {
                            "type": "tts",
                            "state": "start"
                        }
                        
                        sentence_start_msg = {
                            "type": "tts",
                            "state": "sentence_start",
                            "text": response
                        }
                        
                        stop_tts_msg = {
                            "type": "tts",
                            "state": "stop"
                        }
                        
                        # 为UDP会话发送消息
                        if has_udp:
                            for session in self.udp_server.sessions.values():
                                device_id = session["device_id"]
                                topic = f"esp32/device/{device_id}/out"
                                
                                # 通过MQTT发送消息
                                await mqtt_handler.publish(topic, json.dumps(stt_msg), qos=2)
                                await mqtt_handler.publish(topic, json.dumps(start_tts_msg), qos=2)
                                await mqtt_handler.publish(topic, json.dumps(sentence_start_msg), qos=2)
                        
                        # 为WebSocket会话发送消息
                        if has_ws:
                            for device_id in self.ws_manager.active_connections:
                                # 通过WebSocket发送消息
                                await self.ws_manager.send_message(device_id, stt_msg)
                                await self.ws_manager.send_message(device_id, start_tts_msg)
                                await self.ws_manager.send_message(device_id, sentence_start_msg)
                        
                        # 创建临时文件用于保存音频
                        try:
                            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_audio:
                                temp_audio_path = temp_audio.name
                            
                            # 使用edge-tts生成语音
                            try:
                                communicate = edge_tts.Communicate(response, "zh-CN-XiaoxiaoNeural")
                                await communicate.save(temp_audio_path)
                            except Exception as e:
                                error_msg = f"TTS生成失败: {str(e)}"
                                logger.error(error_msg)
                                # 发送错误通知
                                error_tts_msg = {
                                    "type": "tts",
                                    "state": "stop",
                                    "error": error_msg
                                }
                                await self._send_message_to_all_clients(error_tts_msg)
                                return
                            
                            # 使用ffmpeg将mp3转换为wav格式
                            wav_path = temp_audio_path.replace('.mp3', '.wav')
                            try:
                                ffmpeg_result = os.system(f'ffmpeg -i {temp_audio_path} -acodec pcm_s16le -ar 16000 -ac 1 {wav_path} -y')
                                if ffmpeg_result != 0:
                                    raise Exception(f"FFmpeg转换失败，返回码: {ffmpeg_result}")
                            except Exception as e:
                                error_msg = f"音频格式转换失败: {str(e)}"
                                logger.error(error_msg)
                                await self._send_message_to_all_clients({
                                    "type": "tts",
                                    "state": "stop",
                                    "error": error_msg
                                })
                                # 清理临时文件
                                self._cleanup_temp_files(temp_audio_path)
                                return
                            
                            # 读取wav文件并转换为PCM数据
                            try:
                                with wave.open(wav_path, 'rb') as wav_file:
                                    audio_duration = wav_file.getnframes() / wav_file.getframerate()
                                    audio_data = wav_file.readframes(wav_file.getnframes())
                                
                                    # 将PCM数据分成多个块进行编码
                                    chunk_size = 1920  # 每个块60ms的数据
                                    
                                    # 先编码所有数据
                                    for i in range(0, len(audio_data), chunk_size):
                                        chunk = audio_data[i:i + chunk_size]
                                        if len(chunk) == chunk_size:  # 只处理完整的块
                                            try:
                                                # 使用Opus编码PCM数据
                                                encoded_chunk = self.encoder.encode(chunk, self.frame_size)
                                                for device_id in self.ws_manager.active_connections:
                                                    await self.ws_manager.send_audio(device_id, encoded_chunk)
                                            except Exception as e:
                                                error_msg = f"音频编码或发送失败: {str(e)}"
                                                logger.error(error_msg)
                                                await self._send_message_to_all_clients({
                                                    "type": "tts",
                                                    "state": "error",
                                                    "error": error_msg
                                                })
                                                break
                                
                                # 根据音频时长设置延迟时间（音频时长 + 1秒的缓冲）
                                delay_time = audio_duration + 1
                                logger.info(f"音频时长: {audio_duration:.2f}秒，设置延迟时间: {delay_time:.2f}秒")
                                await asyncio.sleep(delay_time)
                                
                            except Exception as e:
                                error_msg = f"音频处理失败: {str(e)}"
                                logger.error(error_msg)
                                await self._send_message_to_all_clients({
                                    "type": "tts",
                                    "state": "stop",
                                    "error": error_msg
                                })
                            finally:
                                # 清理临时文件
                                self._cleanup_temp_files(temp_audio_path, wav_path)
                            
                            # 发送TTS结束通知
                            stop_tts_msg = {
                                "type": "tts",
                                "state": "stop"
                            }
                            await self._send_message_to_all_clients(stop_tts_msg)
                            logger.info("TTS播放完成")
                            
                        except Exception as e:
                            error_msg = f"TTS处理过程出错: {str(e)}"
                            logger.error(error_msg)
                            logger.error(traceback.format_exc())
                            await self._send_message_to_all_clients({
                                "type": "tts",
                                "state": "stop",
                                "error": error_msg
                            })
                    except Exception as e:
                        logger.error(f"TTS播放出错: {str(e)}")
                        logger.error(traceback.format_exc())
                else:
                    logger.warning("AI回复为空，跳过语音播放")
            else:
                logger.warning("未能识别出有效文本")

    def process_with_vad(self, audio_data: bytes):
        """使用VAD处理音频数据，并放入播放缓冲区（如有需要）"""
        try:
            current_time = time.time()
            
            # 检查是否超时
            if self.is_speaking and (current_time - self.last_speech_time) > self.SPEECH_TIMEOUT:
                logger.warning(f"语音超时 ({self.SPEECH_TIMEOUT}秒无语音)，强制结束当前语音段")
                if self.speech_frames:
                    # 把所有累积的语音帧拼起来
                    speech_data = b"".join(self.speech_frames)
                    # 清空状态
                    self.speech_frames.clear()
                    self.is_speaking = False
                    self.silence_duration = 0
                    # 处理已累积的语音数据
                    asyncio.create_task(self.handle_speech_segment(speech_data))
                return

            # audio_data 已经是PCM的bytes(60ms)
            is_speech = self.vad_60ms_to_20ms_frames(audio_data)
            
            if is_speech:
                logger.debug("检测到语音")
                # 更新最后语音时间戳
                self.last_speech_time = current_time
                # 如果是语音，就累积到 self.speech_frames
                self.speech_frames.append(audio_data)
                
                if not self.is_speaking:
                    self.is_speaking = True
                    logger.debug("Start of speech detected")
                
                # 重置静音计数
                self.silence_duration = 0
            else:
                logger.debug("未检测到语音")
                if self.is_speaking:
                    # 如果原本正在说话，那么累积静音计数
                    self.silence_duration += 1
                    logger.debug(f"Silence detected, silence_duration={self.silence_duration}")
                    
                    # 如果静音持续时间超过阈值，认为说话结束
                    if self.silence_duration >= self.SILENCE_THRESHOLD:
                        logger.info("End of speech detected")
                        # 把所有累积的语音帧拼起来
                        speech_data = b"".join(self.speech_frames)
                        
                        # 清空说话帧
                        self.speech_frames.clear()
                        self.is_speaking = False
                        self.silence_duration = 0
                        
                        # 调用处理完整语音段的函数
                        asyncio.create_task(self.handle_speech_segment(speech_data))
                    
        except Exception as e:
            logger.error(f"VAD处理时出错: {str(e)}")
            logger.error(traceback.format_exc())

    async def play_audio(self, audio_data: bytes):
        """播放音频数据（先解码OPUS，然后做VAD分析，再写入本地播放缓冲）"""
        if not self.is_playing:
            logger.warning("Cannot play audio: player is not started")
            return
            
        try:
            # 使用Opus解码音频数据
            try:
                logger.debug(f"开始解码音频数据，大小: {len(audio_data)} 字节，帧大小: {self.frame_size}")
                pcm_data = self.decoder.decode(audio_data, self.frame_size)
                # pcm_data 现在是 bytes 类型，长度 = frame_size * 2 (因为16bit)
                logger.debug(f"解码成功，PCM数据大小: {len(pcm_data)} 字节")
            except Exception as e:
                logger.error(f"Failed to decode Opus data: {str(e)}")
                logger.error(f"错误堆栈: {traceback.format_exc()}")
                return
            
            # 使用VAD处理音频(60ms)
            self.process_with_vad(pcm_data)


            
        except Exception as e:
            logger.error(f"Error playing audio: {str(e)}")
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            
    def close(self):
        """关闭音频播放器"""
        try:
            self.stop_playing()
            # 停止临时文件清理任务
            self.temp_file_manager.stop_cleanup_task()
            logger.info("Closed audio player")
        except Exception as e:
            logger.error(f"Error closing audio player: {str(e)}")
            
    def __del__(self):
        """析构函数"""
        self.close()

    async def chat_with_model(self, text: str) -> str:
        """
        使用 OpenAI SDK 通过 OpenRouter 调用 OpenAI 模型处理用户的语音输入并返回回复
        
        :param text: 语音识别得到的文本
        :return: 模型的回复
        """
        try:
            # 使用 OpenAI SDK 发送请求
            response = await client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct",  # 使用 OpenAI 的 GPT-4 模型
                messages=[
                    {"role": "system", "content": "你是一个友好的AI助手，请用简洁的中文回答用户的问题。"},
                    {"role": "user", "content": text}
                ]
            )
            
            response_text = response.choices[0].message.content
            
            # 记录对话日志
            logger.info(f"用户: {text}")
            logger.info(f"AI助手: {response_text}")
            
            return response_text
            
        except Exception as e:
            error_msg = f"与 AI 模型对话时出错: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            return "抱歉，我现在无法正常回答，请稍后再试。"

    async def _send_message_to_all_clients(self, message: dict):
        """发送消息给所有已连接的客户端"""
        try:
            # 发送到UDP客户端
            if self.udp_server and self.udp_server.sessions:
                for session in self.udp_server.sessions.values():
                    device_id = session["device_id"]
                    topic = f"esp32/device/{device_id}/out"
                    await mqtt_handler.publish(topic, json.dumps(message), qos=2)
            
            # 发送到WebSocket客户端
            if self.ws_manager and self.ws_manager.active_connections:
                for device_id in self.ws_manager.active_connections:
                    await self.ws_manager.send_message(device_id, message)
        except Exception as e:
            logger.error(f"发送消息到客户端失败: {str(e)}")
    
    def _cleanup_temp_files(self, *file_paths):
        """清理临时文件"""
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.unlink(file_path)
                    logger.debug(f"已删除临时文件: {file_path}")
            except Exception as e:
                logger.error(f"删除临时文件失败 {file_path}: {str(e)}")
