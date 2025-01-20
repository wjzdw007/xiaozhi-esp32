import asyncio
import sys
import os
import logging
import numpy as np
import sounddevice as sd

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 确保能找到 services 模块
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
print(f"添加到 Python 路径: {parent_dir}")

try:
    print("正在导入 AudioPlayer...")
    from services.audio_player import AudioPlayer
    print("AudioPlayer 导入成功!")
except ImportError as e:
    print(f"导入 AudioPlayer 失败: {e}")
    print("\n完整的导入错误信息:")
    import traceback
    traceback.print_exc()
    sys.exit(1)
except Exception as e:
    print(f"导入时发生未知错误: {type(e).__name__}: {e}")
    print("\n完整的错误信息:")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 检查必要的依赖
def check_dependencies():
    print("\n检查依赖项...")
    try:
        import opuslib
        print("✓ opuslib 已安装")
    except ImportError:
        print("❌ opuslib 未安装")
        return False

    try:
        print("检查 sounddevice 配置...")
        devices = sd.query_devices()
        print("✓ sounddevice 配置正常")
    except Exception as e:
        print(f"❌ sounddevice 配置错误: {e}")
        return False

    return True

def print_audio_devices():
    """打印所有可用的音频设备"""
    print("\n可用的音频设备:")
    try:
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            print(f"[{i}] {device['name']}")
            print(f"    输入通道: {device['max_input_channels']}")
            print(f"    输出通道: {device['max_output_channels']}")
            print(f"    默认采样率: {device['default_samplerate']}")
    except Exception as e:
        print(f"获取音频设备信息失败: {e}")

async def test_audio_player():
    try:
        print("\n=== 系统信息 ===")
        print(f"Python 版本: {sys.version}")
        print(f"当前工作目录: {os.getcwd()}")
        
        if not check_dependencies():
            print("\n❌ 依赖项检查失败，请安装所需的包")
            return False, "依赖项检查失败"
            
        print_audio_devices()
        
        print("\n1. 创建 AudioPlayer 实例...")
        print("正在初始化 AudioPlayer...")
        player = await AudioPlayer.create()
        print("✓ AudioPlayer 创建成功!")

        print("\n2. 测试生成测试音频...")
        # 生成一个简单的正弦波作为测试音频
        duration = 2  # 2秒
        sample_rate = 16000
        frequencies = [440, 880]  # A4 和 A5 音
        t = np.linspace(0, duration, int(sample_rate * duration))
        
        # 生成双音合成的测试音频
        test_audio = np.zeros_like(t)
        for freq in frequencies:
            test_audio += np.sin(2 * np.pi * freq * t)
        
        # 归一化并转换为16位整数
        test_audio = (test_audio * 32767 / len(frequencies)).astype(np.int16)
        print(f"✓ 测试音频生成成功! (采样率: {sample_rate}Hz, 时长: {duration}s)")
        print(f"音频数据范围: [{np.min(test_audio)}, {np.max(test_audio)}]")

        print("\n3. 测试音频播放...")
        # 将音频数据转换为字节
        audio_bytes = test_audio.tobytes()
        print(f"音频数据大小: {len(audio_bytes)} 字节")
        await player.play_audio(audio_bytes)
        print("✓ 音频数据已发送到播放队列")
        
        print("\n4. 等待音频播放完成...")
        print("播放中...")
        await asyncio.sleep(duration + 0.5)  # 等待音频播放完成，额外等待0.5秒
        print("等待完成")
        
        print("\n5. 测试停止播放...")
        player.stop_playing()
        print("✓ 播放停止成功!")
        
        print("\n6. 测试重新开始播放...")
        player.start_playing()
        print("✓ 重新开始播放成功!")
        
        # 再次播放测试音频
        print("\n7. 再次测试音频播放...")
        await player.play_audio(audio_bytes)
        print("✓ 第二次音频数据已发送到播放队列")
        await asyncio.sleep(duration + 0.5)
        
        print("\n8. 测试关闭播放器...")
        player.close()
        print("✓ 播放器关闭成功!")
        
        return True, "所有测试通过!"
        
    except Exception as e:
        print(f"\n❌ 测试失败: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, f"测试失败: {str(e)}"

if __name__ == "__main__":
    print("=== 开始测试 AudioPlayer ===")
    try:
        success, message = asyncio.run(test_audio_player())
        print(f"\n测试结果: {'✓ 成功' if success else '❌ 失败'}")
        print(f"详细信息: {message}")
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n测试遇到意外错误: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc() 