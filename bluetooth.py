import asyncio
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
import time

class CoyoteBluetoothController:
    BASE_UUID = "0000xxxx-0000-1000-8000-00805f9b34fb"
    
    def __init__(self, device_name="47L121000"):
        self._service_uuid = self._uuid(0x180C)
        self._write_uuid = self._uuid(0x150A)
        self._notify_uuid = self._uuid(0x150B)
        self._battery_uuid = self._uuid(0x1500)
        
        self.device_name = device_name
        self.client = None
        self._seq = 0 #不用回复
        self._response_event = asyncio.Event()
        self._pending_commands = {}
        self._connected = False
        self.B0_state = {'a_strength':5,'b_strength':5,
                         'a_frequencies':[10,10,10,10],'a_intensities':[5,5,5,5],
                         'b_frequencies':[10,10,10,10],'b_intensities':[5,5,5,5]}

    def _uuid(self, short_uuid):
        return self.BASE_UUID.replace("xxxx", f"{short_uuid:04X}")

    async def connect(self, timeout=10.0):
        device = await BleakScanner.find_device_by_name(self.device_name, timeout=timeout)
        if not device:
            raise BleakError(f"Device {self.device_name} not found")
        
        self.client = BleakClient(device)
        await self.client.connect()
        self._connected = True

    def _notification_handler(self, sender, data):
        try:
            if len(data) < 4:  # B1响应最小长度检查
                return
                
            if data[0] == 0xB1:
                seq = (data[1] & 0xF0) >> 4  # 更安全的位运算
                if 0 <= seq <= 15:  # 序列号有效性检查
                    self._current_strength['A'] = data[2]
                    self._current_strength['B'] = data[3]
                    
                    if seq in self._pending_commands:
                        del self._pending_commands[seq]
                        self._response_event.set()
                else:
                    print(f"无效序列号: {seq}")        
        except Exception as e:
            print(f"通知处理错误: {str(e)}")
            # 可添加异常日志记录

    async def _send_command(self, command, wait_response=False):
        if not self._connected:
            raise BleakError("Not connected to device")
        
        await self.client.write_gatt_char(self._write_uuid, command)
        if wait_response:
            self._response_event.wait()
            self._response_event.clear()

    def _convert_frequency(self, input_freq):
        if 10 <= input_freq <= 100:
            return input_freq
        elif 101 <= input_freq <= 600:
            return (input_freq - 100) // 5 + 100
        elif 601 <= input_freq <= 1000:
            return (input_freq - 600) // 10 + 200
        return 10

    # 该函数是周期执行还是每次更改后调用？
    async def send_b0_command(self, 
                            a_strength_mode, a_strength_value,
                            b_strength_mode, b_strength_value,
                            a_frequencies, a_intensities,
                            b_frequencies, b_intensities,
                            wait_response=False): 
        # 验证输入参数
        if len(a_frequencies) != 4 or len(a_intensities) != 4:
            raise ValueError("A通道需要4组频率和强度数据")
        if len(b_frequencies) != 4 or len(b_intensities) != 4:
            raise ValueError("B通道需要4组频率和强度数据")

        # 构造指令头
        command = bytearray()
        command.append(0xB0)
        
        # 序列号和强度模式
        seq = self._seq % 16
        strength_mode = (a_strength_mode << 2) | b_strength_mode
        command.append((seq << 4) | strength_mode)
        
        # 通道强度值
        command.append(max(0, min(a_strength_value, 200)))
        command.append(max(0, min(b_strength_value, 200)))

        # 处理波形数据
        for i in range(4):
            command.append(a_frequencies[i])
        for i in range(4):
            command.append(a_intensities[i])
        for i in range(4):
            command.append(b_frequencies[i])
        for i in range(4):
            command.append(b_intensities[i])
        
        # 发送指令
        await self._send_command(bytes(command), wait_response)

    async def set_absolute_strength(self,value):
        mode = 0b11
        a_val = value
        b_val = value
        
        await self.send_b0_command(
            a_strength_mode=mode,
            a_strength_value=a_val,
            b_strength_mode=mode,
            b_strength_value=b_val,
            a_frequencies=self.B0_state['a_frequencies'],
            a_intensities=self.B0_state['a_intensities'],
            b_frequencies=self.B0_state['b_frequencies'],
            b_intensities=self.B0_state['b_intensities'],
            wait_response=False)
        self.B0_state['a_strength'] = value
        self.B0_state['b_strength'] = value

    async def adjust_strength(self, delta):
        mode = 0b01 if delta > 0 else 0b10
        value = abs(delta)
        
        await self.send_b0_command(
            a_strength_mode=mode,
            a_strength_value=value,
            b_strength_mode=mode,
            b_strength_value=value,
            a_frequencies=self.B0_state['a_frequencies'],
            a_intensities=self.B0_state['a_intensities'],
            b_frequencies=self.B0_state['b_frequencies'],
            b_intensities=self.B0_state['b_intensities'],
            wait_response=False)
        self.B0_state['a_strength'] += delta
        self.B0_state['b_strength'] += delta

    async def set_waveform(self,frequencies, intensities):
        a_freq = frequencies
        a_int = intensities
        b_freq = frequencies
        b_int = intensities

        await self.send_b0_command(
            a_strength_mode=0b00,
            a_strength_value=0,
            b_strength_mode=0b00,
            b_strength_value=0,
            a_frequencies=a_freq,
            a_intensities=a_int,
            b_frequencies=b_freq,
            b_intensities=b_int,
            wait_response=False)
        self.B0_state['a_frequencies'] = frequencies
        self.B0_state['b_frequencies'] = frequencies
        self.B0_state['a_intensities'] = intensities
        self.B0_state['b_intensities'] = intensities

    def get_current_strength(self):
        return self.B0_state['a_strength']
    
    def print_current_state(self):
        print(self.B0_state)

    async def disconnect(self):
        if self.client and self._connected:
            await self.client.disconnect()
            self._connected = False

# 使用示例
async def main():
    controller = CoyoteBluetoothController()
    try:
        await controller.connect()

        # 设置A通道波形
        await controller.set_waveform( 
            [10, 20, 30, 40],  # 输入频率会自动转换
            [20, 40, 60, 80])
        
        # 设置A通道强度到20
        await controller.set_absolute_strength(20)
        print("当前A通道强度:20")
        time.sleep(5)
        
        # 设置A通道强度到30
        await controller.adjust_strength(30)
        print("当前A通道强度:30")
        
        
    except Exception as e:
        print(f"发生错误: {str(e)}")
    finally:
        await controller.disconnect()

if __name__ == "__main__":
    asyncio.run(main())