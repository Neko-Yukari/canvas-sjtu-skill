# Canvas@SJTU Skill 🎓

一个命令行工具，让你不用打开浏览器就能管理上海交通大学 Canvas（oc.sjtu.edu.cn）课程。

## 我能做什么

| 能力 | 说明 |
|------|------|
| 📊 **课程仪表盘** | 一眼看完待办作业、截止时间、剩余天数 |
| 📁 **文件下载** | 按关键词一键下载课件/教材，自动分类到课程文件夹 |
| 📝 **作业管理** | 查看作业列表、提交状态、已得分 |
| 📤 **作业提交** | 三步上传（预检→S3云端→确认），提交前需手动确认 |
| 🔑 **自动登录** | jAccount 登录后保存 session，后续免验证码直连 |
| 🌐 **可扩展** | 基于 Canvas REST API，新增功能只需添加 API 调用 |

## 为什么不用浏览器

- **批处理**：一口气下载所有课件 → 自动按课程分好文件夹
- **脚本化**：配合定时任务做截止日期提醒
- **快**：API 直接交互，不用等页面加载
- **省心**：只输入关键词，不用手动翻几十门课程

## 快速上手

```bash
# 1. 安装依赖
pip install playwright
playwright install chromium

# 2. 创建运行目录
mkdir local

# 3. 首次登录（会弹出浏览器窗口，登录一次即可）
python scripts/login.py

# 4. 开始使用
python scripts/canvas.py dashboard          # 查看首页
python scripts/canvas.py courses            # 列课程
python scripts/canvas.py assignments 电子线路  # 查作业
python scripts/canvas.py download 电子线路 教材 # 下载课件
python scripts/canvas.py submit 无线通信 lab5 report.pdf  # 提交作业
```

## 所有命令

```bash
python scripts/canvas.py <命令>
```

| 命令 | 参数 | 示例 |
|------|------|------|
| `dashboard` | — | 首页概览（待办 + 截止时间） |
| `courses` | — | 列出所有活跃课程 |
| `files` | \<课程名或ID\> | `files 无线通信` |
| `download` | \<课程\> \<关键词\> | `download 电子线路 教材` |
| `assignments` | \<课程\> | `assignments 光纤通信` |
| `submit` | \<课程\> \<作业\> \<文件\> | `submit 无线通信 lab5 report.pdf` |
| `open` | — | 在可见浏览器打开 Canvas |
| `login` | — | 重新登录（刷新 session） |

课程名支持中文关键词（如 `光纤`、`电子`）或数字 ID（如 `87954`）。

## 安全设计

- **本地运行**：所有数据（cookie、下载文件）存在 `local/` 目录，已加入 `.gitignore`
- **提交确认**：`submit` 命令显示预览后必须输入大写 `SUBMIT` 才会执行
- **不存密码**：只保存 Playwright session cookie，不记录 jAccount 密码

## 技术架构

```
用户命令 → canvas.py → Canvas REST API → Playwright session → oc.sjtu.edu.cn
                                                              ↓
                        S3 presigned URL ← 文件上传预检 ←── 作业提交
```

- **API 优先**：直接调用 `/api/v1/`，不做 HTML 页面抓取
- **Playwright 复用**：`request.new_context(storage_state=…)` 共享 session cookie，绕开 CORS
- **课程缓存**：1 小时本地缓存，关键词模糊匹配

## 平台说明

- 仅在 **Windows** 测试过（PowerShell 7+）
- Python 3.11+，依赖 Playwright
- session 约半天过期（jAccount captcha 周期），过期后重新运行 `login.py`
