from flask import Flask, render_template, request, jsonify, g
from silicon_flow_api import SiliconFlowAPI
from dida365_api import DidaAPI
from prompts.task_prompts import TASK_ANALYSIS_PROMPT, CONFIRMATION_ANALYSIS_PROMPT
import os
import tempfile
import base64
from datetime import datetime
import pytz
import json
import time

# 用于格式化时间的辅助函数
def format_time_cost(start_time):
    """计算并格式化耗时
    
    Args:
        start_time: 开始时间戳
    
    Returns:
        str: 格式化的耗时字符串
    """
    cost = time.time() - start_time
    return f"{cost:.2f}秒"

# 加载配置文件
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

app = Flask(__name__)

# 初始化API客户端
silicon_api = SiliconFlowAPI()

# 存储会话状态
session_state = {}

def get_dida_api():
    """获取当前请求的DidaAPI实例"""
    if 'dida_api' not in g:
        g.dida_api = DidaAPI()
    return g.dida_api

@app.teardown_appcontext
def close_dida_api(error):
    """在请求结束时关闭数据库连接"""
    dida_api = g.pop('dida_api', None)
    if dida_api is not None:
        dida_api.close()

@app.route('/')
def index():
    """渲染主页"""
    return render_template('index.html')

@app.route('/api/speech-to-text', methods=['POST'])
def speech_to_text():
    """处理语音转文字请求"""
    total_start_time = time.time()
    temp_path = None
    
    try:
        print("\n=== 阶段1：语音输入 ===")
        
        # 验证请求格式
        if not request.is_json or request.json is None:
            return jsonify({'error': '请求必须是JSON格式'}), 400
        
        # 获取音频数据
        audio_data = request.json.get('audio')
        if not audio_data:
            return jsonify({'error': '未提供音频数据'}), 400
        
        # 处理音频格式
        if ',' in audio_data:
            header, encoded = audio_data.split(',', 1)
            if 'audio/webm' not in header:
                return jsonify({'error': '不支持的音频格式，仅支持WEBM格式'}), 400
        else:
            encoded = audio_data
        
        # 解码音频数据
        audio_bytes = base64.b64decode(encoded)
        if len(audio_bytes) > 50 * 1024 * 1024:
            return jsonify({'error': '音频文件过大（超过50MB）'}), 400
        
        # 保存临时文件并处理
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name
            temp_file.flush()
            os.fsync(temp_file.fileno())
        
        # 调用ASR服务
        print("\n=== 阶段1.1：调用ASR服务 ===")
        asr_start_time = time.time()
        result = silicon_api.transcribe_audio(temp_path)
        print(f"语音识别耗时: {format_time_cost(asr_start_time)}")
        print(f"ASR服务返回结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        # 处理ASR结果
        if 'error' in result:
            return jsonify({'error': result['error']}), 500
        
        transcribed_text = result.get('text', '')
        if not transcribed_text.strip():
            return jsonify({'error': '未能识别出有效的语音内容'}), 400
        
        print(f"\n阶段1总耗时: {format_time_cost(total_start_time)}")
        return jsonify({'text': transcribed_text})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        # 清理临时文件
        if temp_path:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

def execute_task_action(action_data):
    """执行任务操作"""
    start_time = time.time()
    try:
        print(f"=== Executing Task Action ===")
        print(f"Action data: {json.dumps(action_data, ensure_ascii=False, indent=2)}")
        
        action = action_data.get('action')
        task_data = action_data.get('task_data', {})
        
        if not action:
            error_msg = "缺少操作类型"
            print(f"错误: {error_msg}")
            return False, error_msg
        
        print(f"操作类型: {action}")
        print(f"任务数据: {json.dumps(task_data, ensure_ascii=False, indent=2)}")
        
        try:
            dida_api = get_dida_api()
        except Exception as e:
            error_msg = f"无法连接到任务管理服务: {str(e)}"
            print(f"错误: {error_msg}")
            return False, error_msg
        
        action_start_time = time.time()
        if action == 'create_task':
            try:
                if not task_data.get('title'):
                    return False, "任务标题不能为空"
                
                # 确保时区正确
                if 'startDate' in task_data or 'dueDate' in task_data:
                    task_data.setdefault('timeZone', 'Asia/Shanghai')
                
                result = dida_api.create_task(**task_data)
                success_msg = f"已成功创建任务：{task_data.get('title')}"
                print(f"成功: {success_msg}")
                print(f"创建结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
                print(f"创建任务耗时: {format_time_cost(action_start_time)}")
                return True, success_msg
                
            except Exception as e:
                error_msg = f"创建任务失败：{str(e)}"
                print(f"错误: {error_msg}")
                return False, error_msg
                
        elif action == 'update_task':
            try:
                # 检查必填字段
                if not task_data.get('id'):
                    return False, "缺少任务ID"
                if not task_data.get('projectId'):
                    return False, "缺少项目ID"
                
                # 确保时区正确
                if 'startDate' in task_data or 'dueDate' in task_data:
                    task_data.setdefault('timeZone', 'Asia/Shanghai')
                
                # 从task_data中提取id和projectId，其余作为更新数据
                task_id = task_data.pop('id')
                project_id = task_data.pop('projectId')
                
                result = dida_api.update_task(task_id, project_id, **task_data)
                success_msg = f"已更新任务：{result.get('title', '未知任务')}"
                print(f"成功: {success_msg}")
                print(f"更新结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
                print(f"更新任务耗时: {format_time_cost(action_start_time)}")
                return True, success_msg
                
            except Exception as e:
                error_msg = f"更新任务失败：{str(e)}"
                print(f"错误: {error_msg}")
                return False, error_msg
                
        elif action == 'get_task':
            try:
                # 检查必填字段
                if not task_data.get('id'):
                    return False, "缺少任务ID"
                if not task_data.get('projectId'):
                    return False, "缺少项目ID"
                
                result = dida_api.get_task(task_data['projectId'], task_data['id'])
                success_msg = f"已找到任务：{result.get('title', '未知任务')}"
                print(f"成功: {success_msg}")
                print(f"任务详情: {json.dumps(result, ensure_ascii=False, indent=2)}")
                print(f"获取任务耗时: {format_time_cost(action_start_time)}")
                return True, success_msg
                
            except Exception as e:
                error_msg = f"获取任务失败：{str(e)}"
                print(f"错误: {error_msg}")
                return False, error_msg
        else:
            error_msg = f"不支持的操作类型：{action}"
            print(f"错误: {error_msg}")
            return False, error_msg
            
    except Exception as e:
        error_msg = f"执行操作时发生未知错误：{str(e)}"
        print(f"错误: {error_msg}")
        return False, error_msg
    finally:
        print(f"任务操作总耗时: {format_time_cost(start_time)}")
        print("=== Task Action Completed ===")

@app.route('/api/process-command', methods=['POST'])
def process_command():
    """处理用户指令"""
    total_start_time = time.time()
    
    try:
        # 验证请求格式
        if not request.is_json or request.json is None:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
        
        print("\n=== 阶段2：处理用户指令 ===")
        command = request.json.get('command')
        session_id = request.json.get('session_id')
        is_confirmation = request.json.get('is_confirmation', False)
        
        if not command:
            return jsonify({'error': 'No command provided'}), 400
        
        # 处理确认请求
        if is_confirmation:
            return handle_confirmation(command, session_id, total_start_time)
        
        # 处理初始指令
        return handle_initial_command(command, session_id, total_start_time)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def handle_confirmation(command, session_id, total_start_time):
    """处理用户确认"""
    print("\n=== 阶段4：处理用户确认 ===")
    confirm_start_time = time.time()
    
    if session_id not in session_state:
        return jsonify({'error': 'Session expired'}), 400
    
    print("\n=== 阶段4.1：分析确认回复 ===")
    llm_start_time = time.time()
    confirm_response = silicon_api.chat_completion([
        {"role": "user", "content": CONFIRMATION_ANALYSIS_PROMPT.format(command=command)}
    ])
    print(f"确认分析耗时: {format_time_cost(llm_start_time)}")
    print(f"LLM返回结果: {json.dumps(confirm_response, ensure_ascii=False, indent=2)}")
    
    if not confirm_response or 'choices' not in confirm_response:
        return jsonify({'error': 'AI服务暂时不可用，请稍后重试'}), 500
    
    response_content = confirm_response['choices'][0]['message']['content']
    cleaned_content = response_content.strip()
    if cleaned_content.startswith('```json'):
        cleaned_content = cleaned_content[7:]
    if cleaned_content.endswith('```'):
        cleaned_content = cleaned_content[:-3]
    confirm_result = json.loads(cleaned_content.strip())
    
    if confirm_result.get('confirmed'):
        return handle_task_execution(session_id, total_start_time)
    else:
        return handle_retry_suggestion(confirm_result, session_id, total_start_time)

def handle_task_execution(session_id, total_start_time):
    """执行任务"""
    print("\n=== 阶段5：执行任务 ===")
    action_start_time = time.time()
    success, result_message = execute_task_action(session_state[session_id])
    print(f"任务执行耗时: {format_time_cost(action_start_time)}")
    
    session_state.pop(session_id, None)
    
    if not success:
        try:
            print("\n=== 阶段6：生成错误语音回复 ===")
            error_response = f"抱歉，{result_message}"
            tts_start_time = time.time()
            audio_data = silicon_api.text_to_speech(error_response)
            print(f"语音合成耗时: {format_time_cost(tts_start_time)}")
            return jsonify({
                'text': error_response,
                'audio': f'data:audio/wav;base64,{base64.b64encode(audio_data).decode("utf-8")}',
                'error': result_message
            }), 500
        except Exception:
            return jsonify({
                'text': error_response,
                'error': result_message
            }), 500
    
    try:
        print("\n=== 阶段6：生成成功语音回复 ===")
        tts_start_time = time.time()
        response_text = f"好的，{result_message}"
        audio_data = silicon_api.text_to_speech(response_text)
        print(f"语音合成耗时: {format_time_cost(tts_start_time)}")
        
        print(f"\n总耗时: {format_time_cost(total_start_time)}")
        return jsonify({
            'text': response_text,
            'audio': f'data:audio/wav;base64,{base64.b64encode(audio_data).decode("utf-8")}',
            'executed': True
        })
    except Exception:
        return jsonify({
            'text': f"好的，{result_message}",
            'executed': True
        })

def handle_retry_suggestion(confirm_result, session_id, total_start_time):
    """处理重试建议"""
    print("\n=== 阶段3：重新生成建议 ===")
    try:
        response_text = confirm_result.get('response', '好的，让我重新给出建议。')
        tts_start_time = time.time()
        audio_data = silicon_api.text_to_speech(response_text)
        print(f"语音合成耗时: {format_time_cost(tts_start_time)}")
        
        print(f"\n总耗时: {format_time_cost(total_start_time)}")
        return jsonify({
            'text': response_text,
            'audio': f'data:audio/wav;base64,{base64.b64encode(audio_data).decode("utf-8")}',
            'needs_confirmation': True,
            'session_id': session_id,
            'retry_suggestion': True
        })
    except Exception:
        return jsonify({
            'text': response_text,
            'needs_confirmation': True,
            'session_id': session_id,
            'retry_suggestion': True
        })

def handle_initial_command(command, session_id, total_start_time):
    """处理初始指令"""
    print("\n=== 阶段2：分析用户指令 ===")
    dida_api = get_dida_api()
    tasks = dida_api.get_local_tasks()
    projects = dida_api.get_projects()
    
    current_time = datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y年%m月%d日 %H:%M")
    
    print("\n=== 阶段3：生成建议 ===")
    llm_start_time = time.time()
    llm_response = silicon_api.chat_completion([
        {"role": "user", "content": TASK_ANALYSIS_PROMPT.format(
            current_time=current_time,
            command=command,
            tasks=tasks,
            projects=projects
        )}
    ])
    print(f"指令分析耗时: {format_time_cost(llm_start_time)}")
    print(f"LLM返回结果: {json.dumps(llm_response, ensure_ascii=False, indent=2)}")
    
    if not llm_response or 'choices' not in llm_response:
        return jsonify({'error': 'AI服务暂时不可用，请稍后重试'}), 500
    
    response_content = llm_response['choices'][0]['message']['content']
    cleaned_content = response_content.strip()
    
    try:
        # 尝试解析JSON响应
        if cleaned_content.startswith('```json'):
            cleaned_content = cleaned_content[7:]
        if cleaned_content.endswith('```'):
            cleaned_content = cleaned_content[:-3]
        response_data = json.loads(cleaned_content.strip())
    except json.JSONDecodeError:
        # 如果不是JSON格式，创建一个查询响应
        response_data = {
            "action": "query_task",
            "response": cleaned_content
        }
    
    # 判断是否是查询任务
    if response_data.get('action') in ['get_task', 'query_task'] or 'task_data' not in response_data:
        try:
            print("\n=== 阶段3.1：生成查询结果语音回复 ===")
            tts_start_time = time.time()
            response_text = response_data.get('response', cleaned_content)
            # 如果响应文本太长，只取前500个字符
            if len(response_text) > 500:
                response_text = response_text[:497] + "..."
            audio_data = silicon_api.text_to_speech(response_text)
            print(f"语音合成耗时: {format_time_cost(tts_start_time)}")
            
            print(f"\n总耗时: {format_time_cost(total_start_time)}")
            return jsonify({
                'text': response_text,
                'audio': f'data:audio/wav;base64,{base64.b64encode(audio_data).decode("utf-8")}',
                'needs_confirmation': False,
                'executed': True
            })
        except Exception as e:
            print(f"处理查询任务时出错: {str(e)}")
            return jsonify({
                'text': response_text if 'response_text' in locals() else response_data.get('response', cleaned_content),
                'needs_confirmation': False,
                'executed': True
            })
    
    # 如果不是查询任务，则需要确认
    if not session_id:
        session_id = str(datetime.now().timestamp())
    session_state[session_id] = response_data
    
    try:
        print("\n=== 阶段3.1：生成确认语音回复 ===")
        tts_start_time = time.time()
        response_text = response_data['response']
        # 如果响应文本太长，只取前500个字符
        if len(response_text) > 500:
            response_text = response_text[:497] + "..."
        audio_data = silicon_api.text_to_speech(response_text)
        print(f"语音合成耗时: {format_time_cost(tts_start_time)}")
        
        print(f"\n总耗时: {format_time_cost(total_start_time)}")
        return jsonify({
            'text': response_text,
            'audio': f'data:audio/wav;base64,{base64.b64encode(audio_data).decode("utf-8")}',
            'needs_confirmation': True,
            'session_id': session_id
        })
    except Exception:
        return jsonify({
            'text': response_data['response'],
            'needs_confirmation': True,
            'session_id': session_id
        })

@app.route('/api/sync', methods=['POST'])
def sync_tasks():
    """同步任务数据"""
    print("\n=== 阶段1：同步数据 ===")
    start_time = time.time()
    try:
        get_dida_api().sync_with_server()
        print(f"同步耗时: {format_time_cost(start_time)}")
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # 使用配置文件中的服务器设置
    server_config = config.get('server', {})
    host = server_config.get('host', '0.0.0.0')
    port = server_config.get('port', 1005)
    debug = server_config.get('debug', False)
    
    ssl_context = (
        r'ssl\cr8z.me_public.crt',
        r'ssl\cr8z.me.key'
    )
    
    # 程序启动时同步数据库
    print("\n=== 初始化：同步数据 ===")
    start_time = time.time()
    try:
        with app.app_context():
            dida_api = get_dida_api()
            dida_api.sync_with_server()
            print(f"初始同步耗时: {format_time_cost(start_time)}")
    except Exception as e:
        print(f"初始同步失败: {str(e)}")
    
    # 启动服务器
    app.run(
        host=host,
        port=port,
        debug=debug,
        ssl_context=ssl_context
    ) 