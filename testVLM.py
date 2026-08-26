import requests
import base64
import json

def get_vlm_decision(image_path, model_name="llava-phi3"):
    # 1. 将截图转换为 base64
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')

    # 2. 构造符合你 PRD 要求的 Prompt
    prompt = """你是一个聪明的网页自动操作助手。请仔细观察截图，寻找屏幕上的可点击按钮（如“继续”、“下一页”、“上一页”、“确认”或题目选项）。

请严格按照以下 JSON 格式输出你的决策，不要输出任何其他内容。

字段要求：
- "action": 必须是 "click" 或 "wait" 或 "terminate"。
- "target_text": 如果是 click，请原样输出你要点击的按钮上的文字（例如 "继续"）。如果不点击，填空字符串 ""。
- "reason": 用一句话解释为什么这么做（例如 "看到了继续按钮，需要进入下一步"）。
- "confidence": 0.0 到 1.0 的数字。

【示例】
如果图中右下角有一个“下一页”按钮，你必须输出：
{
  "action": "click",
  "target_text": "下一页",
  "reason": "需要点击下一页继续学习",
  "confidence": 0.95
}"""

    # 3. 构造请求 Payload
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [base64_image]
            }
        ],
        "stream": False,
        "format": "json", # 🔥 关键参数：强制 Ollama 输出合法 JSON
        "options": {
            "temperature": 0.1,  # 保持稳定输出
            "num_predict": 256   # 限制输出长度，加快速度
        }
    }

    print("请求已发送，等待 VLM 推理 (因显存限制，可能需要 5-15 秒)...")
    
    # 4. 发送请求
    try:
        response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=60)
        response.raise_for_status()
        
        # 5. 解析并返回
        result_text = response.json()["message"]["content"]
        decision = json.loads(result_text)
        return decision
        
    except Exception as e:
        print(f"请求失败或解析出错: {e}")
        return None

# 测试运行
if __name__ == "__main__":
    # 你可以截一张带题目的课程页面保存为 test_page.png 进行测试
    decision = get_vlm_decision("test1.png")
    print(json.dumps(decision, indent=2, ensure_ascii=False))
    pass


