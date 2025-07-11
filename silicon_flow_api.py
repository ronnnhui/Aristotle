import requests
import json
from typing import Optional
from pathlib import Path
from datetime import datetime

class SiliconFlowAPI:
    def __init__(self, config_path: str = "config.json"):
        """初始化硅基流动API客户端
        
        Args:
            config_path (str): 配置文件路径，默认为'config.json'
        """
        self.config_path = config_path
        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        silicon_config = config['silicon_flow']
        self.api_token = silicon_config['api_token']
        self.base_url = silicon_config['api_base_url']
        self.models = silicon_config['models']
        
        self.headers = {
            "Authorization": f"Bearer {self.api_token}"
        }
    
    def set_model(self, model_name: str) -> None:
        """设置LLM模型
        
        Args:
            model_name (str): 模型名称
        """
        # 更新内存中的模型设置
        self.models['llm'] = model_name
        
        # 更新配置文件
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        config['silicon_flow']['models']['llm'] = model_name
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
    
    def transcribe_audio(self, audio_file_path: str) -> dict:
        """ASR模块：将音频文件转换为文字
        
        Args:
            audio_file_path (str): 音频文件路径
            
        Returns:
            dict: 转录结果，格式为：
                成功: {"text": "转录文本"}
                失败: {"error": "错误信息", "text": ""}
        """
        try:
            # 准备API请求
            url = f"{self.base_url}/audio/transcriptions"
            headers = {
                "Authorization": f"Bearer {self.api_token}"
            }
            
            # 读取音频文件
            with open(audio_file_path, 'rb') as audio_file:
                files = {
                    'file': ('audio.webm', audio_file, 'audio/webm')
                }
                data = {
                    'model': "FunAudioLLM/SenseVoiceSmall"  # 直接使用固定的模型名称
                }
                
                print(f"正在调用硅基流动API: {url}")
                response = requests.post(url, headers=headers, files=files, data=data, timeout=30)
            
            # 检查响应状态
            if response.status_code != 200:
                error_msg = f"API错误 (状态码: {response.status_code})"
                print(f"错误: {error_msg}")
                print(f"响应内容: {response.text}")
                return {"error": error_msg, "text": ""}
            
            # 解析响应
            try:
                result = response.json()
                return result
            except json.JSONDecodeError as e:
                error_msg = f"解析响应失败: {str(e)}"
                print(f"错误: {error_msg}")
                print(f"原始响应: {response.text}")
                return {"error": error_msg, "text": ""}
            
        except Exception as e:
            error_msg = f"语音识别过程发生异常: {str(e)}"
            print(f"错误: {error_msg}")
            return {"error": error_msg, "text": ""}
    
    def chat_completion(self, messages: list) -> dict:
        """LLM模块：调用大语言模型进行对话
        
        Args:
            messages (list): 对话历史消息列表
            
        Returns:
            dict: 模型回复
        """
        url = f"{self.base_url}/chat/completions"
        
        payload = {
            "model": self.models['llm'],
            "messages": messages
        }
        
        headers = self.headers.copy()
        headers["Content-Type"] = "application/json"
        
        response = requests.post(url, json=payload, headers=headers)
        return response.json()
    
    def text_to_speech(self, text: str, voice: Optional[str] = None) -> bytes:
        """TTS模块：将文字转换为语音
        
        Args:
            text (str): 要转换的文字
            voice (str, optional): 语音模型和说话人. 如果不指定，将使用配置文件中的默认值
            
        Returns:
            bytes: 音频数据
            
        Raises:
            Exception: 当API调用失败时抛出异常
        """
        url = f"{self.base_url}/audio/speech"
        
        if voice is None:
            voice = self.models['tts']['default_voice']
            
        payload = {
            "model": self.models['tts']['model'],
            "input": text,
            "voice": voice
        }
        
        headers = self.headers.copy()
        headers["Content-Type"] = "application/json"
        
        print(f"正在调用TTS API: {url}")
        print(f"请求参数: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            # 检查响应状态
            if response.status_code != 200:
                error_msg = f"TTS API错误 (状态码: {response.status_code})"
                print(f"错误: {error_msg}")
                print(f"响应内容: {response.text}")
                raise Exception(error_msg)
            
            # 检查响应内容类型
            content_type = response.headers.get('Content-Type', '')
            if not content_type.startswith('audio/'):
                error_msg = f"TTS API返回了非音频数据: {content_type}"
                print(f"错误: {error_msg}")
                print(f"响应内容: {response.text[:200]}...")
                raise Exception(error_msg)
            
            print(f"TTS API调用成功，返回音频大小: {len(response.content)} 字节")
            print(f"音频类型: {content_type}")
            
            return response.content
            
        except requests.Timeout:
            error_msg = "TTS API请求超时"
            print(f"错误: {error_msg}")
            raise Exception(error_msg)
            
        except requests.RequestException as e:
            error_msg = f"TTS API请求失败: {str(e)}"
            print(f"错误: {error_msg}")
            raise Exception(error_msg)
            
        except Exception as e:
            error_msg = f"TTS处理过程发生异常: {str(e)}"
            print(f"错误: {error_msg}")
            raise

# 使用示例
if __name__ == "__main__":
    # 初始化API客户端
    api = SiliconFlowAPI()
    
    # ASR示例
    # audio_text = api.transcribe_audio("test.wav")
    # print("语音转文字结果:", audio_text)
    
    # LLM对话示例
    chat_response = api.chat_completion([
        {"role": "user", "content": "你好，请问今天天气怎么样？"}
    ])
    print("LLM回复:", chat_response)
    
    # TTS示例
    # speech_data = api.text_to_speech("你好，我是语音助手")
    # with open("output.wav", "wb") as f:
    #     f.write(speech_data) 