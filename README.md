# CodeMind — 从零自建的 AI Coding Agent

**一个有自己 IDE 的 AI 编程助手。** 不是 CLI 命令行工具，而是像 Trae/Cursor 一样的沉浸式编码体验。

从零用 Python 构建 —— Agent Loop、工具调度、权限管线、记忆系统、多智能体协作，以及一个基于 Monaco 的 Web IDE。

![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-active-brightgreen)

## 为什么叫 CodeMind？

> Code + Mind = 不只是写代码，而是理解你的代码上下文，像一个有记忆、会思考的编程伙伴。

## 架构总览

```
浏览器 (Monaco 编辑器 + 聊天 + 文件树 + 终端)
    ↕ WebSocket + HTTP
FastAPI 服务 (web/server.py)
    ↕
CodeMind Agent 核心 (codemind/)
    ↕ Anthropic SDK 兼容
DeepSeek API (api.deepseek.com/anthropic)
```

### Agent Loop 核心流程

```
用户输入 → Hooks 钩子 → Context 压缩 → System Prompt 组装
    → LLM 调用 → Tool Use 检测 → 权限门禁 → 工具执行
    → PostToolUse 钩子 → 追加结果 → 循环
```

简单说就是：**用户说一句话，Agent 自主决定要用什么工具、怎么用、用完之后下一步干什么，直到任务完成。**

## 核心能力

### Agent 引擎（27 个内置工具）

| 类别 | 功能 |
|------|------|
| **文件操作** | bash 执行、读文件、写文件、编辑替换、glob 搜索 |
| **任务管理** | todo_write 待办清单、Task 持久化任务图（带依赖关系） |
| **智能体委托** | Subagent 子任务隔离执行、Teammate 自主后台协作者 |
| **记忆系统** | 持久化 .memory/*.md 存储、LLM 驱动的相关性筛选 |
| **技能加载** | 按需加载 Skill 文件、系统提示词中注入目录 |
| **上下文压缩** | 4 层管线：budget → snip → micro → summarize |
| **容错恢复** | 429 重试、529 模型降级、max_tokens 升级、prompt-too-long 响应式压缩 |
| **后台任务** | 耗时操作放入守护线程异步执行 |
| **定时调度** | 5 字段 Cron，持久化，跨会话存活 |
| **工作区隔离** | git worktree，每个任务独立分支 |
| **MCP 协议** | 延迟绑定外部工具（mcp__server__tool 命名） |
| **权限管线** | 3 道门禁：拒绝列表 → 模式匹配 → 工作区边界 |
| **Hook 系统** | UserPromptSubmit、PreToolUse、PostToolUse、Stop |

### Web IDE

- **Monaco 编辑器**：VS Code 同款编辑引擎，语法高亮，多语言支持
- **聊天面板**：WebSocket 实时对话，流式输出
- **文件树**：浏览工作区，点击打开文件，自动识别语言
- **终端面板**：工具执行日志实时输出
- **工作区切换**：支持原生文件夹选择器，随时切换项目

## 快速开始

### 环境要求

- Python 3.11+
- DeepSeek API Key（[platform.deepseek.com](https://platform.deepseek.com) 注册即可）

### 安装

```bash
git clone https://github.com/HJGisfh/codemind.git
cd codemind

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装
pip install -e .

# 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key
```

### 终端模式

```bash
codemind
# 或者: python -m codemind.cli

CodeMind >> 列出这个项目里的所有 Python 文件
CodeMind >> 为重构创建一个待办清单
CodeMind >> 写一个 Flask API 的单元测试
```

### Web IDE 模式

```bash
codemind-web
# 或者: python web/server.py

# 浏览器打开 http://localhost:8080
```

## 项目结构

```
codemind/
├── codemind/                  # Agent 核心包
│   ├── cli.py                 # 命令行入口
│   ├── loop.py                # Agent Loop（while True → LLM → tools）
│   ├── dispatch.py            # 工具调度 + 文本提取
│   ├── context.py             # 全局共享状态
│   ├── prompt.py              # 系统提示词组装
│   ├── hooks.py               # Hook 注册 / 触发
│   ├── permission.py          # 3 道门禁权限管线
│   ├── memory.py              # 记忆存储 + LLM 相关性筛选
│   ├── compact.py             # 4 层上下文压缩
│   ├── recovery.py            # 容错恢复
│   ├── subagent.py            # 子代理 + 协作者 + 消息总线
│   ├── background.py          # 后台任务分发
│   └── tools/                 # 27 个内置工具
│       ├── bash.py            # Shell 执行
│       ├── file_ops.py        # 文件读写编辑 + 安全路径
│       ├── todo.py            # 会话待办清单
│       ├── task_crud.py       # 持久化任务图
│       ├── skill.py           # 技能加载
│       ├── mcp.py             # MCP 客户端
│       ├── cron.py            # Cron 定时调度
│       └── worktree.py        # Git 工作区隔离
├── web/                       # Web IDE 前端
│   ├── server.py              # FastAPI + WebSocket 服务
│   └── static/
│       ├── index.html         # IDE 外壳
│       ├── css/style.css      # VS Code 风格暗色主题
│       └── js/app.js          # Monaco + 聊天 + 文件树控制器
├── docs/                      # 设计文档
├── tests/                     # 测试
├── pyproject.toml             # 项目元数据
└── README.md
```

## 关键设计决策

**为什么不用 LangChain？** Agent Loop 核心只有 ~60 行 Python。加框架反而会隐藏控制流，使得 hooks、permission、compaction 这些模块难以独立理解和测试。**自己做一遍，才能真正理解 Agent 的原理。**

**为什么选 DeepSeek？** DeepSeek 提供 Anthropic 兼容的 API 端点（`/anthropic`），可以直接用 Anthropic SDK，同时成本远低于 Claude。修改 `ANTHROPIC_BASE_URL` 和 `MODEL_ID` 两个环境变量就能切换到任何兼容服务。

**为什么 Monaco + 原生 JS？** 没有 React/Vue 构建工具链。Monaco 从 CDN 加载，前端 ~400 行原生 JavaScript——够做一个能用的 IDE，也短到可以一口气读完。

**为什么文件即数据库？** Task、Memory、Cron Jobs、Transcripts 全都是文件。没有数据库依赖，用任何文本编辑器就能查看 Agent 状态，重启不丢数据。

## License

MIT
