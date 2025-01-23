from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import ota, websocket, mqtt
from routes.mqtt import mqtt_handler
from routes.websocket import ws_manager
from services.udp_server import UDPServer
from services.audio_player import AudioPlayer
from config import SERVER_HOST, SERVER_PORT, UDP_PORT, WEBSOCKET_ACCESS_TOKEN
import asyncio
import logging
import sys
import traceback

# 配置根日志记录器
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    force=True,  # 强制覆盖已存在的日志配置
    handlers=[
        logging.StreamHandler(sys.stdout),  # 输出到标准输出
        logging.FileHandler('logs/server.log', encoding='utf-8')  # 输出到文件
    ]
)

logger = logging.getLogger(__name__)
logger.info("服务器日志系统初始化完成")

# 全局异常处理器
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # 对于键盘中断，调用默认处理器
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    logger.critical("Uncaught exception:", exc_info=(exc_type, exc_value, exc_traceback))
    # 打印完整的堆栈跟踪
    traceback.print_exception(exc_type, exc_value, exc_traceback)

# 设置全局异常处理器
sys.excepthook = handle_exception

# 创建服务器实例
udp_server = UDPServer("0.0.0.0", UDP_PORT, mqtt_handler)

# 设置MQTT处理器的UDP服务器
mqtt.set_udp_server(udp_server)

# 设置正确的访问令牌
ws_manager.access_token = WEBSOCKET_ACCESS_TOKEN

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    try:
        print("Starting server initialization...")
        
        print("Connecting to MQTT...")
        await mqtt.mqtt_handler.connect()
        
        print("Starting UDP server...")
        await udp_server.start()
        
        print("Creating audio player...")
        try:
            audio_player = await AudioPlayer.create()
            # 设置 WebSocket 的音频播放器
            websocket.set_audio_player(audio_player)
        except Exception as e:
            print(f"Error creating audio player: {e}")
            print("Traceback:")
            traceback.print_exc()
            raise
            
        print("Setting up UDP server audio player...")
        udp_server.set_audio_player(audio_player)
        audio_player.set_udp_server(udp_server)
        
        print("Server initialization completed successfully")
        yield
    except Exception as e:
        print(f"Error during server startup: {e}")
        print("Traceback:")
        traceback.print_exc()
        logger.error(f"Error during server startup: {str(e)}")
        logger.error("Exception details:", exc_info=True)
        raise
    finally:
        # 关闭时
        try:
            print("Starting server shutdown...")
            await mqtt.mqtt_handler.disconnect()
            udp_server.stop()
            if audio_player:
                audio_player.close()
            print("Server shutdown completed successfully")
        except Exception as e:
            print(f"Error during server shutdown: {e}")
            print("Traceback:")
            traceback.print_exc()
            logger.error(f"Error during server shutdown: {str(e)}")
            logger.error("Exception details:", exc_info=True)

app = FastAPI(
    title="小智ESP32后台服务",
    description="ESP32设备管理和OTA更新服务",
    version="1.0.0",
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加路由
app.include_router(ota.router, prefix="/ota", tags=["OTA"])
app.include_router(websocket.router, tags=["WebSocket"])
app.include_router(mqtt.router, tags=["MQTT"])

@app.get("/")
async def root():
    return {"message": "欢迎使用小智ESP32后台服务"}

def run():
    """运行服务器的函数"""
    import uvicorn
    uvicorn.run(
        app,
        host=SERVER_HOST,
        port=SERVER_PORT,
        log_level="debug",
        reload=False  # 禁用重载器
    )

if __name__ == "__main__":
    run() 