import sys
import logging
from opuslib import Decoder
from opuslib.constants import OPUS_APPLICATION_VOIP

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

try:
    print("Testing imports...")
    import sounddevice as sd
    print("sounddevice imported successfully")
    
    import numpy as np
    print("numpy imported successfully")
    
    print("Testing opuslib import...")
    decoder = Decoder(OPUS_APPLICATION_VOIP, 16000, 1)
    print("opuslib imported and decoder created successfully")
    
    print("\nTesting audio devices...")
    devices = sd.query_devices()
    print("\nAvailable audio devices:")
    for i, dev in enumerate(devices):
        print(f"[{i}] {dev['name']} (输出通道: {dev['max_output_channels']})")
    
    default_device = sd.query_devices(kind='output')
    print(f"\nDefault output device: {default_device['name']}")
    
    print("\nAll tests passed!")
    
except Exception as e:
    print(f"\nError occurred: {type(e).__name__}: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1) 