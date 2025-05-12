from paddleocr import PaddleOCR
import numpy as np
import cv2

class FastOCR:
    def __init__(self, use_gpu=True, lang='en'):
        """
        初始化OCR识别器
        :param use_gpu: 是否使用GPU加速（需要安装对应版本的PaddlePaddle）
        :param lang: 语言类型 en/ch/...
        """
        # 配置轻量模型（默认使用PP-OCRv4）
        self.ocr = PaddleOCR(
            use_angle_cls=False,  # 关闭方向分类（提升速度）
            lang=lang,
            det_model_dir='paddleocr/server_det',  # 服务器级检测模型
            rec_model_dir='paddleocr/server_rec',  # 服务器级识别模型
            use_gpu=use_gpu,
            det_db_thresh=0.3,
        )

    def recognize(self, image: np.ndarray) -> list:
        """
        从ndarray图像中识别文字
        :param image: 输入图像（支持BGR/RGB格式）
        :return: 识别结果列表，每个元素为 (文字内容, 置信度)
        """
        # 自动转换颜色空间（PaddleOCR需要RGB格式）
        if image.shape[-1] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        # 执行OCR
        result = self.ocr.ocr(image, cls=False)  # 关闭方向分类
        
        # 提取有效结果
        return [
            (line  [1]  [0], float(line  [1]  [1])) 
            for line in result  [0] 
            if len(line) >= 2
        ]

# 使用示例
if __name__ == "__main__":
    # 初始化识别器（首次运行会自动下载模型）
    ocr = FastOCR(lang='en')
    
    # 示例1：直接生成测试图像
    test_image = np.zeros((100, 200, 3), dtype=np.uint8)
    cv2.putText(test_image, "Hello PaddleOCR", (10, 50), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    
    # 执行识别
    results = ocr.recognize(test_image)
    print("识别结果：", results)
    
    # 示例2：读取真实图像
    # real_image = cv2.imread("test_image.png")
    # if real_image is not None:
    #     real_results = ocr.recognize(real_image)
    #     print("真实图像识别结果：", real_results)