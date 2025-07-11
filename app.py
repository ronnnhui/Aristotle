from flask import Flask, render_template, request, jsonify, g
from silicon_flow_api import SiliconFlowAPI
from dida365_api import DidaAPI
from prompts.task_prompts import TASK_ANALYSIS_PROMPT
from logging_config import setup_logging
import os
import tempfile
import base64
from datetime import datetime
import pytz
import json
import time

# 设置日志记录器
logger = setup_logging()

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

def save_config():
    """保存配置到文件"""
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    """处理设置的获取和更新"""
    if request.method == 'GET':
        # 返回当前设置
        return jsonify({
            'llm_model': config.get('llm_model', 'gpt-4')
        })
    else:
        # 更新设置
        try:
            data = request.get_json()
            if 'llm_model' in data:
                config['llm_model'] = data['llm_model']
                save_config()
                # 更新 SiliconFlowAPI 实例的设置
                silicon_api.set_model(data['llm_model'])
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

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
        logger.info("=== 阶段1：语音输入 ===")
        
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
        logger.info("=== 阶段1.1：调用ASR服务 ===")
        result = silicon_api.transcribe_audio(temp_path)
        logger.debug(f"ASR服务返回结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        # 处理ASR结果
        if 'error' in result:
            return jsonify({'error': result['error']}), 500
        
        transcribed_text = result.get('text', '')
        if not transcribed_text.strip():
            return jsonify({'error': '未能识别出有效的语音内容'}), 400
        
        print("语音识别成功")
        return jsonify({'text': transcribed_text})
    
    except Exception as e:
        print("语音识别失败")
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
    try:
        logger.info("=== Executing Task Action ===")
        logger.debug(f"Action data: {json.dumps(action_data, ensure_ascii=False, indent=2)}")
        
        action = action_data.get('action')
        task_data = action_data.get('task_data', {})
        
        if not action:
            error_msg = "缺少操作类型"
            logger.error(f"错误: {error_msg}")
            return False, error_msg
        
        logger.info(f"操作类型: {action}")
        logger.debug(f"任务数据: {json.dumps(task_data, ensure_ascii=False, indent=2)}")
        
        try:
            dida_api = get_dida_api()
        except Exception as e:
            error_msg = f"无法连接到任务管理服务: {str(e)}"
            logger.error(f"错误: {error_msg}")
            return False, error_msg
        
        if action == 'create_task':
            try:
                if not task_data.get('title'):
                    return False, "任务标题不能为空"
                
                # 确保时区正确
                if 'startDate' in task_data or 'dueDate' in task_data:
                    task_data.setdefault('timeZone', 'Asia/Shanghai')
                
                result = dida_api.create_task(**task_data)
                success_msg = f"已成功创建任务：{task_data.get('title')}"
                logger.info(f"成功: {success_msg}")
                logger.debug(f"创建结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
                print("任务创建成功")
                return True, success_msg
                
            except Exception as e:
                error_msg = f"创建任务失败：{str(e)}"
                logger.error(f"错误: {error_msg}")
                print("任务创建失败")
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
                logger.info(f"成功: {success_msg}")
                logger.debug(f"更新结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
                print("任务更新成功")
                return True, success_msg
                
            except Exception as e:
                error_msg = f"更新任务失败：{str(e)}"
                logger.error(f"错误: {error_msg}")
                print("任务更新失败")
                return False, error_msg
                
        elif action == 'get_task':
            try:
                # 检查必填字段
                if not task_data.get('id'):
                    # 如果没有任务ID，但有日期和项目ID，则返回该项目的任务列表
                    if task_data.get('projectId'):
                        tasks = dida_api.get_local_tasks(
                            include_completed=False,
                            project_id=task_data.get('projectId')
                        )
                        if not tasks:
                            return False, "没有找到任何任务"
                            
                        # 如果指定了日期，过滤出该日期的任务
                        if task_data.get('date'):
                            target_date = task_data.get('date')
                            filtered_tasks = []
                            for task in tasks:
                                start_date = task.get('startDate', '').split('T')[0]
                                due_date = task.get('dueDate', '').split('T')[0]
                                if start_date == target_date or due_date == target_date:
                                    filtered_tasks.append(task)
                            tasks = filtered_tasks
                            
                        if not tasks:
                            return False, f"在指定日期没有找到任何任务"
                            
                        task_list = "\n".join([f"- {task.get('title')}" for task in tasks])
                        success_msg = f"找到以下任务：\n{task_list}"
                        logger.info(f"成功: {success_msg}")
                        print("任务查询成功")
                        return True, success_msg
                        
                    return False, "缺少任务ID"
                    
                if not task_data.get('projectId'):
                    return False, "缺少项目ID"
                
                result = dida_api.get_task(task_data['projectId'], task_data['id'])
                success_msg = f"已找到任务：{result.get('title', '未知任务')}"
                logger.info(f"成功: {success_msg}")
                logger.debug(f"任务详情: {json.dumps(result, ensure_ascii=False, indent=2)}")
                print("任务查询成功")
                return True, success_msg
                
            except Exception as e:
                error_msg = f"获取任务失败：{str(e)}"
                logger.error(f"错误: {error_msg}")
                print("任务查询失败")
                return False, error_msg
        else:
            error_msg = f"不支持的操作类型：{action}"
            logger.error(f"错误: {error_msg}")
            print("不支持的操作类型")
            return False, error_msg
            
    except Exception as e:
        error_msg = f"执行操作时发生未知错误：{str(e)}"
        logger.error(f"错误: {error_msg}")
        print("任务执行失败")
        return False, error_msg

@app.route('/api/process-command', methods=['POST'])
def process_command():
    """处理用户指令"""
    try:
        # 验证请求格式
        if not request.is_json or request.json is None:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
        
        logger.info("=== 阶段1：处理用户指令 ===")
        command = request.json.get('command')
        logger.debug(f"收到指令: {command}")
        
        if not command:
            return jsonify({'error': 'No command provided'}), 400
        
        # 获取任务和项目信息
        dida_api = get_dida_api()
        tasks = dida_api.get_local_tasks(include_completed=False)  # 只获取未完成的任务
        projects = dida_api.get_projects()
        
        logger.debug(f"当前任务列表: {json.dumps(tasks, ensure_ascii=False, indent=2)}")
        logger.debug(f"当前项目列表: {json.dumps(projects, ensure_ascii=False, indent=2)}")
        
        # 获取当前时间，包含星期信息
        current_datetime = datetime.now(pytz.timezone('Asia/Shanghai'))
        weekday_map = {
            0: '一',
            1: '二',
            2: '三',
            3: '四',
            4: '五',
            5: '六',
            6: '日'
        }
        current_time = current_datetime.strftime(f"%Y年%m月%d日 星期{weekday_map[current_datetime.weekday()]} %H:%M")
        
        logger.info("=== 阶段2：分析指令 ===")
        llm_response = silicon_api.chat_completion([
            {"role": "user", "content": TASK_ANALYSIS_PROMPT.format(
                current_time=current_time,
                command=command,
                tasks=tasks,
                projects=projects
            )}
        ])
        logger.debug(f"LLM返回结果: {json.dumps(llm_response, ensure_ascii=False, indent=2)}")
        
        if not llm_response or 'choices' not in llm_response:
            print("指令分析失败")
            return jsonify({'error': 'AI服务暂时不可用，请稍后重试'}), 500
        
        print("指令分析成功")
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
            # 如果不是JSON格式，创建一个普通响应
            response_data = {
                "response": cleaned_content
            }
        
        # 如果需要执行任务操作
        if 'action' in response_data and 'task_data' in response_data:
            logger.info("=== 阶段3：执行任务操作 ===")
            success, result_message = execute_task_action(response_data)
            
            if not success:
                try:
                    logger.info("=== 阶段4：生成错误语音回复 ===")
                    error_response = f"抱歉，{result_message}"
                    audio_data = silicon_api.text_to_speech(error_response)
                    print("语音合成成功")
                    return jsonify({
                        'text': error_response,
                        'audio': f'data:audio/wav;base64,{base64.b64encode(audio_data).decode("utf-8")}',
                        'error': result_message
                    }), 500
                except Exception:
                    print("语音合成失败")
                    return jsonify({
                        'text': error_response,
                        'error': result_message
                    }), 500
            
            # 使用LLM返回的友好回复
            response_text = response_data.get('response', f"好的，{result_message}")
        else:
            # 如果只是普通回复，只使用response字段中的内容
            response_text = response_data.get('response', cleaned_content)
        
        # 如果响应文本太长，只取前500个字符
        if len(response_text) > 500:
            response_text = response_text[:497] + "..."
        
        try:
            logger.info("=== 阶段4：生成语音回复 ===")
            audio_data = silicon_api.text_to_speech(response_text)
            print("语音合成成功")
            
            return jsonify({
                'text': response_text,
                'audio': f'data:audio/wav;base64,{base64.b64encode(audio_data).decode("utf-8")}',
                'executed': True
            })
        except Exception:
            print("语音合成失败")
            return jsonify({
                'text': response_text,
                'executed': True
            })
            
    except Exception as e:
        print("指令处理失败")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sync', methods=['POST'])
def sync_tasks():
    """同步任务数据"""
    logger.info("=== 同步数据 ===")
    try:
        get_dida_api().sync_with_server()
        print("数据同步成功")
        return jsonify({'status': 'success'})
    except Exception as e:
        print("数据同步失败")
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
    logger.info("=== 初始化：同步数据 ===")
    try:
        with app.app_context():
            dida_api = get_dida_api()
            dida_api.sync_with_server()
            print("初始数据同步成功")
    except Exception as e:
        print("初始数据同步失败")
        logger.error(f"初始同步失败: {str(e)}")
    
    # 启动服务器
    app.run(
        host=host,
        port=port,
        debug=debug,
        ssl_context=ssl_context
    ) 