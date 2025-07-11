# -*- coding: utf-8 -*-
import json
import sqlite3
import requests
import base64
from typing import Optional, List, Dict
from pathlib import Path
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import urllib.parse
import time

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """OAuth callback handler"""
    code: Optional[str] = None
    
    def do_GET(self):   
        """Handle GET request to get authorization code"""
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        
        if 'code' in params:
            OAuthCallbackHandler.code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Authorization successful! You can close this window.")
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Authorization failed! Please try again.")

    def log_message(self, format, *args):
        """禁用HTTP服务器的日志输出"""
        pass

class DidaAPI:
    _local = threading.local()
    
    def __init__(self, config_path: str = "config.json"):
        """Initialize Dida365 API client
        
        Args:
            config_path (str): Path to configuration file
        """
        # Load configuration
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        self.config = config['dida365']
        self.access_token = None
        
        # Initialize database for the current thread
        self._init_database()
        
        # Try to load token from database
        self._load_token()
        
        # If no valid token, perform authorization
        if not self.access_token:
            self._authorize()
    
    @property
    def conn(self):
        """Get thread-local database connection"""
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(self.config['db_path'])
        return self._local.conn
    
    @property
    def cursor(self):
        """Get thread-local database cursor"""
        if not hasattr(self._local, 'cursor'):
            self._local.cursor = self.conn.cursor()
        return self._local.cursor
    
    def _init_database(self):
        """Initialize SQLite database"""
        # Create auth table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS auth (
            id INTEGER PRIMARY KEY,
            access_token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create tasks table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            title TEXT,
            content TEXT,
            status INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create projects table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT,
            color TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        self.conn.commit()
    
    def _load_token(self):
        """Load access token from database"""
        self.cursor.execute('SELECT access_token FROM auth ORDER BY created_at DESC LIMIT 1')
        result = self.cursor.fetchone()
        if result:
            self.access_token = result[0]
    
    def _save_token(self, access_token: str):
        """Save access token to database
        
        Args:
            access_token (str): Access token to save
        """
        self.cursor.execute('INSERT INTO auth (access_token) VALUES (?)', (access_token,))
        self.conn.commit()
        self.access_token = access_token
    
    def _authorize(self):
        """执行OAuth认证流程"""
        # 构建认证URL，确保scope格式正确
        auth_params = {
            'client_id': self.config['client_id'],
            'scope': 'tasks:write tasks:read',  # 按照文档格式修正
            'state': 'state',
            'redirect_uri': self.config['redirect_uri'],
            'response_type': 'code'
        }
        auth_url = f"{self.config['auth_url']}?{urllib.parse.urlencode(auth_params)}"
        
        print("\n=== 滴答清单认证 ===")
        print("1. 自动认证：系统将打开浏览器并等待回调")
        print("2. 手动认证：您需要手动复制认证code")
        choice = input("请选择认证方式 (1/2): ").strip()
        
        auth_code = None
        if choice == "1":
            # 启动本地服务器接收回调
            server = HTTPServer(('localhost', 8080), OAuthCallbackHandler)
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.daemon = True
            server_thread.start()
            
            # 打开浏览器进行认证
            print(f"\n正在打开浏览器进行授权...")
            webbrowser.open(auth_url)
            
            # 等待认证完成
            print("等待认证完成...")
            try:
                timeout = 20  # 20秒超时
                start_time = time.time()
                while not OAuthCallbackHandler.code:
                    time.sleep(0.1)
                    if time.time() - start_time > timeout:
                        print("\n自动认证超时！切换到手动模式...")
                        break
                
                if OAuthCallbackHandler.code:
                    auth_code = OAuthCallbackHandler.code
                
            except KeyboardInterrupt:
                print("\n认证被中断！切换到手动模式...")
            finally:
                # 关闭服务器
                server.shutdown()
                server.server_close()
                OAuthCallbackHandler.code = None
        
        if not auth_code:
            # 手动认证模式
            print("\n=== 手动认证步骤 ===")
            print("1. 请访问以下链接进行授权：")
            print(f"{auth_url}")
            print("\n2. 在浏览器中完成授权后，您会被重定向到一个无法访问的地址")
            print("3. 从该地址的URL中复制code参数的值")
            print("\n重定向URL示例: http://cr8z.me:8080/callback?code=YOUR_CODE&state=state")
            auth_code = input("\n请输入code值: ").strip()
        
        if not auth_code:
            raise Exception("未能获取认证码")
            
        # 使用认证码获取访问令牌
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # 准备请求数据
        data = {
            'client_id': self.config['client_id'],
            'client_secret': self.config['client_secret'],
            'code': auth_code,
            'grant_type': 'authorization_code',
            'redirect_uri': self.config['redirect_uri']
        }
        
        try:
            print(f"\n=== 获取访问令牌 ===")
            print(f"请求URL: {self.config['token_url']}")
            print(f"请求头: {headers}")
            print(f"请求数据: {data}")
            
            response = requests.post(
                self.config['token_url'],
                headers=headers,
                data=data,
                timeout=30,
                verify=True
            )
            
            if response.status_code == 200:
                response_data = response.json()
                if 'access_token' in response_data:
                    access_token = response_data['access_token']
                    self._save_token(access_token)
                    print("\n认证成功！")
                else:
                    raise Exception("响应中未包含access_token")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = f"{error_msg}: {json.dumps(error_data, ensure_ascii=False)}"
                except:
                    if response.text:
                        error_msg = f"{error_msg}: {response.text}"
                    else:
                        error_msg = f"{error_msg}: 服务器未返回错误信息"
                print("\n=== 错误信息 ===")
                print(f"响应状态码: {response.status_code}")
                print(f"响应头: {dict(response.headers)}")
                print(f"响应内容: {response.text}")
                raise Exception(f"获取访问令牌失败 - {error_msg}")
                
        except requests.exceptions.RequestException as e:
            raise Exception(f"请求失败: {str(e)}")
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make API request with better error handling
        
        Args:
            method (str): HTTP method
            endpoint (str): API endpoint
            **kwargs: Request parameters
        
        Returns:
            dict: API response
        
        Raises:
            Exception: When API request fails
        """
        # 确保请求头符合API要求
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        url = f"{self.config['api_base_url']}/{endpoint.lstrip('/')}"
        
        try:
            # 打印完整的请求信息用于调试
            print(f"\n=== API请求调试信息 ===")
            print(f"请求URL: {url}")
            print(f"请求方法: {method}")
            print(f"请求头: {headers}")
            if 'json' in kwargs:
                print(f"请求数据: {kwargs['json']}")
            
            response = requests.request(method, url, headers=headers, **kwargs)
            
            print(f"响应状态码: {response.status_code}")
            print(f"响应头: {dict(response.headers)}")
            print(f"响应内容: {response.text[:500]}...")  # 只打印前500个字符
            
            if response.status_code == 401:
                print("Token已过期，重新认证...")
                self._authorize()
                headers['Authorization'] = f'Bearer {self.access_token}'
                response = requests.request(method, url, headers=headers, **kwargs)
                
            response.raise_for_status()  # 对非2xx状态码抛出异常
            
            if not response.text:  # 检查响应是否为空
                return {}
                
            try:
                return response.json()
            except ValueError as e:
                raise Exception(f"无效的JSON响应: {str(e)}\n响应内容: {response.text[:500]}...")
                
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error_msg = f"{error_msg} - {json.dumps(error_data, ensure_ascii=False)}"
                except:
                    if e.response.text:
                        error_msg = f"{error_msg} - {e.response.text}"
            raise Exception(f"API请求失败: {error_msg}")
    
    def get_project_with_data(self, project_id: str) -> Dict:
        """Get project details including tasks and columns
        
        Args:
            project_id (str): Project ID
        
        Returns:
            Dict: Project information with format:
            {
                "project": {
                    "id": "project_id",
                    "name": "project name",
                    "color": "#F18181",
                    ...
                },
                "tasks": [{
                    "id": "task_id",
                    "projectId": "project_id",
                    "title": "Task Title",
                    "content": "Task Content",
                    ...
                }],
                "columns": [{
                    "id": "column_id",
                    "projectId": "project_id",
                    "name": "Column Name",
                    "sortOrder": 0
                }]
            }
        """
        return self._make_request('GET', f'project/{project_id}/data')

    def sync_with_server(self):
        """Synchronize local database with server data
        
        现在使用新的 API 接口同步项目及其任务数据
        """
        # Get all projects first
        projects = self._make_request('GET', 'project')
        
        total_tasks = 0
        
        # Update local project data and sync tasks for each project
        for project in projects:
            project_id = project['id']
            
            # Get detailed project data including tasks
            try:
                project_data = self.get_project_with_data(project_id)
                
                # Update project info
                self.cursor.execute('''
                INSERT OR REPLACE INTO projects (id, name, color, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ''', (project['id'], project['name'], project.get('color')))
                
                print(f"\n正在同步项目: {project['name']} (ID: {project['id']})")
                
                # Update tasks for this project
                if 'tasks' in project_data:
                    for task in project_data['tasks']:
                        self.cursor.execute('''
                        INSERT OR REPLACE INTO tasks (
                            id, project_id, title, content, status, updated_at
                        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ''', (
                            task['id'],
                            task['projectId'],
                            task['title'],
                            task.get('content'),
                            task.get('status', 0)
                        ))
                        total_tasks += 1
                
            except Exception as e:
                print(f"同步项目 {project['name']} 时出错: {str(e)}")
                continue
        
        self.conn.commit()
        print(f"\n同步完成！共同步了 {len(projects)} 个项目，{total_tasks} 个任务")
    
    def get_local_tasks(self, project_id: Optional[str] = None) -> List[Dict]:
        """Get tasks from local database
        
        Args:
            project_id (str, optional): Project ID to filter tasks
            
        Returns:
            List[Dict]: List of tasks
        """
        if project_id:
            self.cursor.execute('''
            SELECT id, project_id, title, content, status
            FROM tasks
            WHERE project_id = ?
            ORDER BY updated_at DESC
            ''', (project_id,))
        else:
            self.cursor.execute('''
            SELECT id, project_id, title, content, status
            FROM tasks
            ORDER BY updated_at DESC
            ''')
        
        tasks = []
        for row in self.cursor.fetchall():
            tasks.append({
                'id': row[0],
                'projectId': row[1],
                'title': row[2],
                'content': row[3],
                'status': row[4]
            })
        return tasks
    
    def get_projects(self) -> List[Dict]:
        """Get all projects
        
        Returns:
            List[Dict]: List of projects with format:
            [{
                "id": "project_id",
                "name": "project name",
                "color": "#F18181",
                "closed": false,
                "groupId": "group_id",
                "viewMode": "list",
                "permission": "write",
                "kind": "TASK"
            }]
        """
        response = self._make_request('GET', 'project')
        if isinstance(response, dict):
            return [response]
        return response
    
    def get_task(self, project_id: str, task_id: str) -> Dict:
        """Get task details by project ID and task ID
        
        注意：这是滴答清单API提供的唯一获取任务信息的方法。
        你必须已知task_id才能获取任务详情。
        
        Args:
            project_id (str): Project ID  
            task_id (str): Task ID (必须已知)
        
        Returns:
            Dict: Task information with format:
            {
                "id": "task_id",
                "projectId": "project_id", 
                "title": "Task Title",
                "content": "Task Content",
                "desc": "Task Description",
                "isAllDay": true,
                "startDate": "2019-11-13T03:00:00+0000",
                "dueDate": "2019-11-14T03:00:00+0000",
                "timeZone": "America/Los_Angeles",
                ...
            }
        """
        return self._make_request('GET', f'project/{project_id}/task/{task_id}')

    def create_task(self, title: str, project_id: Optional[str] = None, **kwargs) -> dict:
        """Create new task
        
        Args:
            title (str): Task title (required)
            project_id (str, optional): Project ID. If None, will be created in default project
            **kwargs: Additional task parameters:
                - content (str): Task content  
                - desc (str): Task description
                - isAllDay (bool): Whether it's an all-day task
                - startDate (str): Start date in "yyyy-MM-dd'T'HH:mm:ssZ" format
                - dueDate (str): Due date in "yyyy-MM-dd'T'HH:mm:ssZ" format
                - timeZone (str): Time zone
                - priority (int): Task priority (default 0)
                - reminders (list): List of reminders
                - repeatFlag (str): Recurring rules
                - items (list): List of subtasks
        
        Returns:
            dict: Created task information
        """
        task_data = {
            'title': title,
            **kwargs
        }
        
        if project_id:
            task_data['projectId'] = project_id
        
        # Create task via API
        new_task = self._make_request('POST', 'task', json=task_data)
        
        # 同步新任务到本地数据库
        try:
            self.cursor.execute('''
            INSERT OR REPLACE INTO tasks (
                id, project_id, title, content, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (
                new_task['id'],
                new_task.get('projectId'),
                new_task['title'],
                new_task.get('content'),
                new_task.get('status', 0)
            ))
            self.conn.commit()
            print(f"任务已创建并同步到本地: {new_task['title']}")
        except Exception as e:
            print(f"任务创建成功，但同步到本地数据库失败: {str(e)}")
        
        return new_task

    def update_task(self, task_id: str, project_id: str, **kwargs) -> dict:
        """Update existing task
        
        Args:
            task_id (str): Task ID to update
            project_id (str): Project ID that the task belongs to
            **kwargs: Task parameters to update:
                - title (str): Task title
                - content (str): Task content
                - desc (str): Task description
                - isAllDay (bool): Whether it's an all-day task
                - startDate (str): Start date in "yyyy-MM-dd'T'HH:mm:ssZ" format
                - dueDate (str): Due date in "yyyy-MM-dd'T'HH:mm:ssZ" format
                - timeZone (str): Time zone
                - priority (int): Task priority (0=normal, 1=medium, 2=high, 3=urgent)
                - status (int): Task status (0=pending, 1=completed)
                - reminders (list): List of reminders
                - repeatFlag (str): Recurring rules
                - sortOrder (int): The order of task
                - items (list): List of subtasks with format:
                    [{
                        "id": "subtask_id",  # Only needed for existing subtasks
                        "title": "Subtask title",
                        "status": 0/1,
                        "isAllDay": true/false,
                        "startDate": "yyyy-MM-dd'T'HH:mm:ssZ",
                        "timeZone": "timezone",
                        "sortOrder": 12345,
                        "completedTime": "yyyy-MM-dd'T'HH:mm:ssZ"  # Only for completed subtasks
                    }]
                - completedTime (str): Completed time in "yyyy-MM-dd'T'HH:mm:ssZ" format
        
        Returns:
            dict: Updated task information
            
        Note:
            When updating a task, you must provide both task_id and project_id.
            The API requires these fields in both the URL and request body.
        """
        # 确保必填字段存在
        task_data = {
            'id': task_id,  # API要求在body中也包含id
            'projectId': project_id,  # API要求在body中也包含projectId
            **kwargs
        }
        
        # Update task via API
        try:
            updated_task = self._make_request('POST', f'task/{task_id}', json=task_data)
            
            # 同步更新后的任务到本地数据库
            try:
                self.cursor.execute('''
                UPDATE tasks SET
                    title = ?,
                    content = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND project_id = ?
                ''', (
                    updated_task.get('title'),
                    updated_task.get('content'),
                    updated_task.get('status', 0),
                    task_id,
                    project_id
                ))
                self.conn.commit()
                print(f"任务已更新并同步到本地: {updated_task.get('title')}")
            except Exception as e:
                print(f"任务更新成功，但同步到本地数据库失败: {str(e)}")
            
            return updated_task
            
        except Exception as e:
            print(f"更新任务失败: {str(e)}")
            raise

    def close(self):
        """Close database connection for current thread"""
        if hasattr(self._local, 'cursor'):
            self._local.cursor.close()
            delattr(self._local, 'cursor')
        if hasattr(self._local, 'conn'):
            self._local.conn.close()
            delattr(self._local, 'conn')
    
    def __del__(self):
        """Cleanup when object is deleted"""
        try:
            self.close()
        except:
            pass

# Usage example
if __name__ == "__main__":
    # Initialize API client
    api = DidaAPI()
    
    # Sync data
    api.sync_with_server()
    
    # Get all projects
    tasks = api.get_local_tasks()
    print("Tasks:", tasks)
    
    # Create new task
    # new_task = api.create_task(
    #     title="Test Task",
    #     content="This is a test task",
    #     desc="Task description"
    # )
    # print("New task:", new_task) 