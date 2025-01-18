# 小智ESP32后台服务

这是小智ESP32项目的后台服务端代码。

## 功能特性

- 设备管理
- OTA固件更新
- 用户认证
- API接口

## 开发环境设置

### 1. 安装 Miniconda

如果你还没有安装 Miniconda，请先下载并安装：

- Linux/Mac: 
```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
```

- Windows: 
从 [Miniconda官网](https://docs.conda.io/en/latest/miniconda.html) 下载安装包安装

### 2. 创建并激活 Conda 环境

```bash
# 创建名为 xiaozhi-server 的环境，使用 Python 3.9
conda create -n xiaozhi-server python=3.9
# 激活环境
conda activate xiaozhi-server
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 运行开发服务器

```bash
cd src
uvicorn main:app --reload
```

服务器将在 http://localhost:8000 运行

## API文档

启动服务器后，可以访问以下地址查看API文档：

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 项目结构

```
server/
├── config/         # 配置文件
├── src/            # 源代码
│   ├── main.py     # 主程序入口
│   ├── models/     # 数据模型
│   ├── routes/     # API路由
│   └── utils/      # 工具函数
├── tests/          # 测试文件
└── requirements.txt # 项目依赖
```

## 开发指南

### 环境管理

```bash
# 更新依赖
pip freeze > requirements.txt

# 导出环境
conda env export > environment.yml

# 从环境文件创建环境
conda env create -f environment.yml
```

### 运行测试

```bash
# 在 server 目录下运行测试
pytest tests/
``` 