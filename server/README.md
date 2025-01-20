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

### 2. 安装 MQTT Broker

项目需要MQTT服务器，推荐使用Mosquitto：

Windows:
1. 下载安装包：https://mosquitto.org/download/
2. 创建密码文件：
```bash
# 创建密码文件（在mosquitto安装目录下执行）
mosquitto_passwd -c passwordfile xiaozhi
# 根据提示输入密码
```

3. 修改配置文件 `C:\Program Files\mosquitto\mosquitto.conf`：
```conf
# 禁用匿名访问
allow_anonymous false

# 配置监听端口和IP
listener 1883 0.0.0.0

# 配置密码文件
password_file passwordfile

# 日志配置
log_dest file
log_file mosquitto.log
log_timestamp true
```

4. 启动服务：
```bash
# 以服务方式启动
net start mosquitto

# 或直接启动（调试时推荐）
mosquitto -v -c mosquitto.conf
```

Linux:
```bash
# Ubuntu/Debian
sudo apt-get install mosquitto mosquitto-clients

# 创建密码文件
sudo mosquitto_passwd -c /etc/mosquitto/passwd xiaozhi
# 根据提示输入密码

# 修改配置文件
sudo nano /etc/mosquitto/mosquitto.conf
```
添加以下内容：
```conf
# 禁用匿名访问
allow_anonymous false

# 配置监听端口和IP
listener 1883 0.0.0.0

# 配置密码文件
password_file /etc/mosquitto/passwd

# 日志配置
log_dest file
log_file /var/log/mosquitto/mosquitto.log
log_timestamp true
```
```bash
# 重启服务
sudo systemctl restart mosquitto
sudo systemctl enable mosquitto

# 检查状态
sudo systemctl status mosquitto
```

Mac:
```bash
# 使用Homebrew安装
brew install mosquitto

# 创建密码文件
mosquitto_passwd -c /usr/local/etc/mosquitto/passwd xiaozhi
# 根据提示输入密码

# 修改配置文件
nano /usr/local/etc/mosquitto/mosquitto.conf
```
添加以下内容：
```conf
# 禁用匿名访问
allow_anonymous false

# 配置监听端口和IP
listener 1883 0.0.0.0

# 配置密码文件
password_file /usr/local/etc/mosquitto/passwd

# 日志配置
log_dest file
log_file /usr/local/var/log/mosquitto.log
log_timestamp true
```
```bash
# 重启服务
brew services restart mosquitto
```

### 3. 创建并激活 Conda 环境

```bash
# 创建名为 xiaozhi-server 的环境，使用 Python 3.9
conda create -n xiaozhi-server python=3.9
# 激活环境
conda activate xiaozhi-server
```

### 4. 安装依赖

```bash
pip install -r requirements.txt
```

### 5. 运行开发服务器

```bash
cd src
# 监听所有网络接口，允许局域网访问
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

服务器将在以下地址运行：
- 本机访问: http://localhost:8000
- 局域网访问: http://<本机IP>:8000 

注意：
1. 请确保防火墙允许8000端口的入站连接
2. 如果使用Windows，可能需要在防火墙设置中允许Python/uvicorn的网络访问
3. 本机IP可以通过 `ipconfig` (Windows) 或 `ifconfig` (Linux/Mac) 命令查看

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

### MQTT测试

安装完Mosquitto后，可以使用命令行工具测试MQTT连接：

```bash
# 订阅主题（使用用户名和密码）
mosquitto_sub -h localhost -t "test/topic" -u xiaozhi -P your_password

# 发布消息（使用用户名和密码）
mosquitto_pub -h localhost -t "test/topic" -m "hello" -u xiaozhi -P your_password
```

注意：
1. 请将 `your_password` 替换为你设置的实际密码
2. 默认用户名为 `xiaozhi`
3. ESP32设备和服务器端也需要配置相同的用户名和密码 