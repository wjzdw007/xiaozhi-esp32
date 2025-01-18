from pydantic import BaseModel, Field
from config import MQTT_HOST

class MQTTConfig(BaseModel):
    endpoint: str = Field(default_factory=lambda: MQTT_HOST)
    client_id: str = "esp32_client"
    username: str = "mqtt_user"
    password: str = "mqtt_password"
    subscribe_topic: str = "esp32/device/in"
    publish_topic: str = "esp32/device/out" 