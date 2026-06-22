# ProxyHub

自托管的代理服务管理面板。通过 Web UI 统一管理多种代理引擎的入站、出站、订阅和节点，支持节点健康检测与自动故障切换。

## 快速开始

```bash
pip install -r requirements.txt
python run.py
```

打开 http://localhost:8080，默认用户名 `admin`，无密码。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3 + Flask + SQLite |
| 前端 | 纯 HTML/CSS/JS（无框架依赖） |
| 代理引擎 | Xray · sslocal · sing-box（多二进制架构） |

依赖仅 `flask>=3.0` 和 `pyyaml>=6.0`。

## 核心概念

### Service = Inbound + Outbound

每个 Service 是一条独立的代理通道，由一个入站和一个出站组合而成。

**入站类型：**
- HTTP 代理
- SOCKS5 代理
- Shadowsocks
- VMess

**出站类型：**
- Freedom（直连）
- 单代理节点
- 自动切换（节点池 + 优先级故障切换）

### 多二进制架构

ProxyHub 同时管理多个代理二进制，按协议自动选择：

| 引擎 | 支持协议 | 二进制文件 |
|------|----------|-----------|
| Xray | VMess / VLESS / Trojan | `bin/xray.exe` |
| sslocal | Shadowsocks（含 obfs/v2ray-plugin） | `bin/sslocal.exe` + `bin/obfs-local.exe` |
| sing-box | Hysteria2 / TUIC | `bin/sing-box.exe` |

## 功能特性

- **订阅管理** — 解析 `vmess://` 和 `ss://` 链接，支持关键词过滤/排除
- **节点管理** — 批量检测（TCP + HTTP 延迟），优先级分组
- **自动故障切换** — 基于优先级的节点切换，自适应检测间隔（正常 3-5 分钟，故障 30 秒指数退避）
- **服务管理** — 入站/出站/服务 CRUD，支持开机自启
- **二进制升级** — 从 GitHub Releases 检查并下载最新版本
- **日志面板** — 每页可折叠的实时日志，按级别着色（info/ok/warn/error）
- **登录认证** — 基于 session 的用户名/密码认证

## 目录结构

```
v2ray-webui/
├── run.py                      # 入口 — Flask 应用（默认端口 8080）
├── requirements.txt            # flask, pyyaml
├── app/                        # Python 应用包
│   ├── main.py                 # Flask 路由 + REST API + 认证 + 自启
│   ├── db.py                   # SQLite 数据库操作
│   ├── bin_manager.py          # 多二进制进程管理（启动/停止/重启/版本查询）
│   ├── config_generator.py     # 服务配置生成
│   ├── checker.py              # 节点健康检测（TCP + curl）
│   ├── subscription.py         # 订阅解析 + 关键词过滤
│   ├── upgrade.py              # GitHub 二进制升级
│   ├── logger.py               # 内存日志面板
│   └── config/                 # 各引擎配置生成器
│       ├── xray.py             # Xray JSON 配置
│       ├── sslocal.py          # sslocal 配置
│       └── singbox.py          # sing-box 配置
├── templates/                  # Jinja2 模板（等宽字体 UI）
│   ├── base.html               # 公共布局（导航栏、侧边栏、日志面板）
│   ├── dashboard.html          # 仪表盘 — 服务状态卡片
│   ├── inbounds.html           # 入站管理
│   ├── outbounds.html          # 出站管理
│   ├── subscriptions.html      # 订阅管理
│   ├── nodes.html              # 节点列表
│   ├── settings.html           # 设置 + 二进制升级
│   └── login.html              # 登录页
├── bin/                        # 代理二进制文件（gitignored）
├── config/                     # 运行时配置（gitignored）
├── data/                       # SQLite 数据库 + PID 文件（gitignored）
└── scripts/                    # 测试脚本
```

## 默认配置

| 项目 | 默认值 |
|------|--------|
| Web 端口 | 8080 |
| 用户名 | admin |
| 密码 | （空） |
| 检测间隔 | 240 秒 |
| 故障切换间隔 | 30 秒 |
| TCP 超时 | 3 秒 |
| curl 超时 | 5 秒 |
| 测试 URL | `http://www.gstatic.com/generate_204` |

## License

MIT
