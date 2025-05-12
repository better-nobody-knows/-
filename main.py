import win32gui
import win32ui
import win32con
import cv2
import numpy as np
import time
from PIL import Image
from threading import Thread, Event
from bluetooth import CoyoteBluetoothController
from ocr import FastOCR
import re
import asyncio

class AdvancedWindowDetector:
    def __init__(self, window_title: str, check_interval: float = 1):
        """
        增强型窗口检测器
        
        :param window_title: 目标窗口标题（支持模糊匹配）
        :param check_interval: 检测间隔时间（秒）
        """
        self.window_title = window_title
        self.check_interval = check_interval
        self.hwnd = None
        self._stop_event = Event()
        self._lock = Thread()  # 用于线程安全的伪锁

        # 游戏内数据
        self.life = 999
        self.max_life = 999
        self.load = 0 # 0代表正常，1代表混乱，2代表阻滞
        self.damage = 0 # 暂存关卡内伤害

        # 性能监控数据
        self.frame_count = 0
        self.average_process_time = 0

        self.ocr = FastOCR(lang="ch")
        


    # def _convert_color_space(self, image: np.ndarray, color_space: str) -> np.ndarray:
    #     """颜色空间转换"""
    #     if color_space == 'HSV':
    #         return cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    #     elif color_space == 'LAB':
    #         return cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    #     elif color_space == 'BGR':
    #         return image.copy()
    #     else:
    #         raise ValueError(f"不支持的色彩空间: {color_space}")

    # def remove_template(self, template_name: str):
    #     """移除模板配置"""
    #     if template_name in self.templates:
    #         del self.templates[template_name]

    # def _preprocess_image(self, image: np.ndarray, color_space: str) -> np.ndarray:
    #     """彩色图像预处理管道"""
    #     # 转换颜色空间
    #     processed = self._convert_color_space(image, color_space)
        
    #     # 可选：高斯模糊降噪
    #     processed = cv2.GaussianBlur(processed, (3, 3), 0)
    #     return processed

    def find_window(self):
        """查找目标窗口句柄"""
        def callback(hwnd, hwnd_list):
            if win32gui.IsWindowVisible(hwnd) and self.window_title.lower() in win32gui.GetWindowText(hwnd).lower():
                hwnd_list.append(hwnd)
            return True

        hwnd_list = []
        win32gui.EnumWindows(callback, hwnd_list)
        return hwnd_list  [0] if hwnd_list else None
    
    def capture_window(self) -> np.ndarray:
        """捕获窗口画面"""
        if not self.hwnd:
            self.hwnd = self.find_window()
            if not self.hwnd:
                raise RuntimeError("找不到目标窗口")

        left, top, right, bottom = win32gui.GetClientRect(self.hwnd)
        w = right - left
        h = bottom - top

        hwndDC = win32gui.GetWindowDC(self.hwnd)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()

        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
        saveDC.SelectObject(saveBitMap)

        # 根据窗口的DPI缩放比例调整捕获尺寸
        try:
            import ctypes
            scale_factor = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
        except:
            scale_factor = 1

        # 执行截图
        saveDC.BitBlt((0, 0), (int(w * scale_factor), int(h * scale_factor)), mfcDC, (left, top), win32con.SRCCOPY)

        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)
        img = Image.frombuffer(
            'RGB',
            (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
            bmpstr, 'raw', 'BGRX', 0, 1
        )

        # 资源清理
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(self.hwnd, hwndDC)

        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    
    def _get_area_by_percantage(self,screenshot,region):
        height, width = screenshot.shape[:2]
        def percent_to_pixel(value, max_value):
                return int(round(max_value * value / 100))
        x_start = percent_to_pixel(region[0], width)
        x_end = percent_to_pixel(region[1], width)
        y_start = percent_to_pixel(region[2], height)
        y_end = percent_to_pixel(region[3], height)
        return screenshot[y_start:y_end, x_start:x_end]

    def find_nearby_color(self,image: np.ndarray, center_point: tuple, target_color: tuple):
        """
        在指定点周围搜索近似颜色像素
        
        参数：
        image : 输入图像（HWC格式的RGB数组）
        center_point : 中心坐标 (x, y)
        target_color : 目标颜色 (R, G, B)
        
        返回：
        如果return_positions为False，返回是否存在布尔值
        如果return_positions为True，返回匹配坐标列表
        """
        h, w = image.shape[:2]
        x, y = center_point
        if not (0 <= y < h and 0 <= x < w):
            raise ValueError("中心点坐标超出图像范围")
        
        # 计算颜色容差范围（每个通道±1）
        lower_bound = np.array(target_color) - 1
        upper_bound = np.array(target_color) + 1
        
        # 获取搜索区域（自动处理边界）
        y_start = max(0, y - 1)
        y_end = min(h, y + 2)
        x_start = max(0, x - 1)
        x_end = min(w, x + 2)
        
        # 提取区域
        region = image[y_start:y_end, x_start:x_end]
        # print("检测范围：",region)
        mask = np.ones(region.shape[:2], dtype=bool)
        
        # 创建颜色匹配掩模
        color_mask = np.all(
            (region >= lower_bound) & (region <= upper_bound),
            axis=-1
        )
        
        # 应用位置掩模
        final_mask = color_mask & mask
        return np.any(final_mask)
    
    def _in_battle(self,screenshot):
        height, width = screenshot.shape[:2]
        x = int(round(width * 5.37 / 100))
        y = int(round(height * 9.86 / 100)) # 根据关卡内齿轮按钮是否存在判断是否在关卡内
        # print(f"监测点：{x},{y}")
        return self.find_nearby_color(screenshot,(x,y),(140,140,140))
    
    def _in_rouge(self,screenshot):
        height, width = screenshot.shape[:2]
        x = int(round(width * 1.94 / 100))
        y = int(round(height * 5.88 / 100)) # 根据肉鸽退出按钮是否存在判断是否在肉鸽页面
        # print(f"监测点：{x},{y}")
        return self.find_nearby_color(screenshot,(x,y),(0,0,92))
    
    async def _start_contorller(self):
        self.controller = CoyoteBluetoothController()
        await self.controller.connect()
        await self.controller.set_waveform( 
            [10, 20, 30, 40],  # 输入频率会自动转换
            [20, 40, 60, 80])
        print("蓝牙连接中，成功会电一下")
        await self.controller.set_absolute_strength(20)
    
    async def _refresh_contorller(self):
        strength = 5
        if self.life == 1:
            strength = 20
        else:
            strength += int(10*((self.max_life-self.life)/self.max_life)) # 目标生命影响
        strength += self.damage*2 # 局内漏怪
        strength *= (1 + 0.2*self.load) # 负荷影响
        await self.controller.set_absolute_strength(int(strength))
        print(f"当前状态：目标生命{self.life}/{self.max_life},负荷状态：{self.load},漏怪数：{self.damage}")
        print("当前强度为：",int(strength))

    def _preprocess_for_ocr(self,image):
        gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        target_size = (gray_image.shape[1]*3,gray_image.shape[0]*3)
    
        # 执行缩放（自动处理尺寸顺序）
        resized_image = cv2.resize(
            src=gray_image,
            dsize=target_size,  # (width, height)
            interpolation=cv2.INTER_CUBIC
        )
        cv2.imwrite("test.png",resized_image)
        return resized_image
    

    async def _detection_loop(self):
        """检测主循环"""
        while not self._stop_event.is_set():
            start_time = time.time()
            try:
                screenshot = self.capture_window()
                height, width = screenshot.shape[:2]
                if screenshot is None:
                    continue
                cv2.imwrite('temp.png',screenshot)
                if self._in_battle(screenshot):
                    print("战斗中")
                    x = int(round(width * 66.83 / 100))
                    y = int(round(height * 6.92 / 100)) # 判断是否有漏怪图标
                    if self.find_nearby_color(screenshot,(x,y),(0,0,164)):
                        area = self._get_area_by_percantage(screenshot,(64.45,69.65,5.56,7.90))
                        try:
                            results = self.ocr.recognize(self._preprocess_for_ocr(area))
                            for text,_ in results:
                                if 'X' not in text:
                                    # print("漏怪数为：",text)
                                    self.damage = abs(int(text))
                        except Exception as e:
                            print("OCR检测出错:", e,"异常结果为:",results )
                elif self._in_rouge(screenshot):
                    print("地图中")
                    life_area = self._get_area_by_percantage(screenshot,(12.51,23.34,4.91,11.76))
                    results = self.ocr.recognize(self._preprocess_for_ocr(life_area))
                    for text,_ in results:
                        if '/' in text:
                            nums = re.findall(r'\d+', text)
                            if len(nums) >= 2:
                                n, m = map(int, nums[:2])
                                self.life = min(n,m) # 从目标生命区提取当前生命
                                self.max_life = max(n,m) # 从目标生命区提取生命上限
                    x = int(round(width * 55.88 / 100))
                    y = int(round(height * 93.58 / 100)) # 判断是否有漏怪图标
                    if self.find_nearby_color(screenshot,(x,y),(72,94,24)):
                        self.load = 0
                    elif self.find_nearby_color(screenshot,(x,y),(38,77,100)):
                        self.load = 1
                    elif self.find_nearby_color(screenshot,(x,y),(32,33,98)):
                        self.load = 2
                    else:
                        self.load = 0

                await self._refresh_contorller()
                
                # 性能统计
                process_time = time.time() - start_time
                self.average_process_time = (
                    self.average_process_time * self.frame_count + process_time
                ) / (self.frame_count + 1)
                self.frame_count += 1

                # 动态调整间隔
                adjusted_interval = max(0, self.check_interval - process_time)
                time.sleep(adjusted_interval)
                
            except Exception as e:
                print(f"检测出错: {str(e)}")
                time.sleep(5)

    async def start(self):
        """启动检测线程"""
        self._stop_event.clear()
        await self._start_contorller()
        self.thread = Thread(target=self._detection_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """停止检测"""
        self._stop_event.set()
        if self.thread.is_alive():
            self.thread.join()

    def get_performance_stats(self) -> dict:
        """获取性能统计"""
        return {
            'frame_count': self.frame_count,
            'average_process_time': self.average_process_time,
        }

async def main():
    # 初始化检测器
    detector = AdvancedWindowDetector("MuMu", check_interval = 1)
    # 启动检测
    # await detector.start()
    detector._stop_event.clear()
    await detector._start_contorller()
    await detector._detection_loop()

        # try:
        #     while True:
        #         # 主线程可以执行其他任务
        #         # 示例：每5秒打印性能数据
        #         time.sleep(5)
        #         stats = detector.get_performance_stats()
        #         print(f"性能统计：平均处理时间 {stats['average_process_time']:.3f}s，检测帧数 {stats['frame_count']}")
        # except KeyboardInterrupt:
        #     detector.stop()

# 使用示例
if __name__ == "__main__":
    asyncio.run(main())
    