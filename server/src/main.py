from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import ota, websocket, mqtt
from services.udp_server import UDPServer
from config import SERVER_HOST, SERVER_PORT, UDP_PORT
import asyncio
import logging

# 配置根日志记录器
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=False  # 不覆盖已存在的日志配置
)

# 创建UDP服务器实例
udp_server = UDPServer("0.0.0.0", UDP_PORT)
# 设置MQTT处理器的UDP服务器
mqtt.set_udp_server(udp_server)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    await mqtt.mqtt_handler.connect()
    await udp_server.start()
    yield
    # 关闭时
    await mqtt.mqtt_handler.disconnect()
    udp_server.stop()

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

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        app, 
        host=SERVER_HOST, 
        port=SERVER_PORT,
        log_level="info",
        access_log=True
    ) 