# 亚里士多德 (Aristotle)

亚里士多德是一个智能任务管理助手,它可以通过语音或文字交互来帮助你管理日常任务。项目基于 Flask 框架开发,集成了语音识别、自然语言处理和任务管理功能。

## 主要功能

- 语音/文字交互界面
- 智能任务分析和处理
- 任务创建、更新和查询
- 实时语音反馈
- 滴答清单(TickTick/Dida365)集成

## 技术栈

- Python 3.x
- Flask
- SQLite
- WebRTC (语音录制)
- TailwindCSS (UI设计)

## 安装要求

1. Python 3.x
2. pip 包管理器
3. SSL 证书 (用于 HTTPS)
4. 滴答清单账号

## 安装步骤

1. 克隆仓库:
```bash
git clone https://github.com/[your-username]/aristotle.git
cd aristotle
```

2. 安装依赖:
```bash
pip install -r requirements.txt
```

3. 配置文件:
   - 复制 `config.json.example` 为 `config.json`
   - 填入必要的配置信息

4. SSL证书:
   - 在 `ssl` 目录中放入你的 SSL 证书文件

5. 运行服务:
```bash
python app.py
```

## 使用说明

1. 访问 `https://[your-domain]:1005`
2. 使用语音按钮或文字输入框与亚里士多德交互
3. 按照提示确认或修改任务

## 注意事项

- 请确保有可用的麦克风设备
- 需要现代浏览器支持 (推荐 Chrome/Firefox)
- 必须使用 HTTPS 协议访问

## 许可证

MIT License

## 贡献指南

欢迎提交 Issue 和 Pull Request 来帮助改进项目。 