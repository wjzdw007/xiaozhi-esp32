from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import ota
from routes import websocket

app = FastAPI(
    title="小智ESP32后台服务",
    description="ESP32设备管理和OTA更新服务",
    version="1.0.0"
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
app.include_router(ota.router, prefix="/api/v1", tags=["OTA"])
app.include_router(websocket.router, tags=["WebSocket"])

@app.get("/")
async def root():
    return {"message": "欢迎使用小智ESP32后台服务"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 