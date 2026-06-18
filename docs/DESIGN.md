# V2fly-hub

## Context

当前架构：OpenWrt VM (192.168.100.1:1080) 提供 socks 代理，解析机场订阅并转发流量；Xray 通过 3 个配置文件分别提供：
- SS (666) → socks 出站（经订阅节点翻墙）
- VMess+WS (24811) → socks 出站（经订阅节点翻墙）
- SS (704) → freedom 出站（国外回国反向代理）

目标：用 Python Web 工具替代 OpenWrt，管理 V2fly 进程，实现订阅解析、节点选择、可用性检测和自动故障转移。

## 技术栈

- Python 3 + Flask + SQLite
- 前端：纯 HTML/CSS/JS，等宽字体，无外部依赖
- V2fly-core（已放在 bin/ 目录）

## 项目结构

```
Xray-webui/
├── run.py                  # 入口文件
├── app/                    # Python 应用包
│   ├── __init__.py
│   ├── main.py             # Flask 应用（页面路由 + API）
│   ├── db.py               # 数据库操作（SQLite）
│   ├── xray_manager.py    # V2fly 进程管理
│   └── upgrade.py          # GitHub 二进制升级
├── templates/              # Jinja2 HTML 模板
│   ├── base.html           # 共享布局（导航栏、侧边栏、日志面板）
│   ├── dashboard.html      # 仪表盘
│   ├── inbounds.html       # 入站设置
│   ├── outbounds.html      # 出站设置
│   ├── subscriptions.html  # 订阅管理
│   ├── nodes.html          # 节点列表
│   └── settings.html       # 设置 + V2fly 升级
├── bin/                    # V2fly 二进制 + 数据文件（gitignore）
├── config/                 # V2fly 运行时配置（gitignore）
├── data/                   # SQLite 数据库（gitignore）
├── docs/
│   └── DESIGN.md           # 设计文档
├── requirements.txt
└── .gitignore
```

## UI 设计风格

- 等宽字体 Consolas/Monaco，无阴影、无渐变、无动画
- 紧凑布局，信息密度优先
- 配色：#fafafa 背景、#fff 组件、#333 文字、#888 次要文字、#e0e0e0 边框
- 按钮用文字（stop/edit/del/use/check），不用图标库
- 弹窗用自定义 modal，无 Bootstrap

## 核心概念：服务 = 入站 + 出站

用户通过组合入站和出站来创建"服务"，每个服务是一个独立的代理通道。

**入站类型**（4 种）：
- HTTP
- SOCKS
- Shadowsocks
- VMess

**出站类型**（3 种）：
- **Freedom**：直连出站，用于回国代理场景
- **单一代理**：固定使用某个节点
- **自动切换**：节点池 + 优先级排序 + 可用性检测 + 自动故障转移

## 页面结构

### 1. 仪表盘 (`dashboard.html`)

- 顶部状态栏：V2fly 运行状态、活跃服务数、当前节点、当前延迟
- 服务列表：每个服务卡片显示 `入站 → 出站` 流向图
- 操作：添加服务、启停/重启/删除单个服务
- 添加服务弹窗：选择已有入站/出站，或新建

### 2. 入站设置 (`inbounds.html`)

- 表格：名称、协议、监听地址、参数、关联服务
- 添加弹窗：选协议（SS/VMess/HTTP/SOCKS），动态切换参数表单
- SS：加密方式、密码
- VMess：UUID、alterId、传输协议(tcp/ws)、ws path
- HTTP/SOCKS：用户名、密码（可选）

### 3. 出站设置 (`outbounds.html`)

- 出站卡片列表，每种类型显示不同内容：
  - Freedom：名称
  - 单一代理：名称 + 固定节点信息
  - 自动切换：名称 + 节点池列表 + 检测间隔 + 测试 URL
- 节点池内节点用 up/down 按钮调整优先级
- 添加弹窗：选类型，单选切换表单

### 4. 订阅管理 (`subscriptions.html`)

- 每个订阅一个卡片：名称、节点数、更新时间
- **关键字设置**：filter 和 exclude 各占一行，点击弹出 textarea 编辑（每行一个关键字）
- 节点预览表格：名称、协议、地址、是否在节点池中
- 操作：刷新、编辑、删除订阅；节点加入/移除节点池
- 被 exclude 关键字匹配的节点不显示

### 5. 节点列表 (`nodes.html`)

- 按订阅折叠分组，点击展开/收起
- 表格：名称、协议、地址、tcp 延迟、curl 延迟、状态
- 当前使用的节点高亮标记 `[current]`
- 操作：use（切换为当前节点）、enable/disable、移除
- **检测按钮**：
  - 每个分组标题有 check 按钮（检测该组所有节点）
  - navbar 有 check all 按钮（检测全部）
  - 节点 ≤20 个时串行检测，>20 个时并行检测
  - 检测结果实时填入 tcp 和 curl 列

### 6. 设置 (`settings.html`)

- **V2fly 升级/下载**：
  - 显示当前版本、平台（自动检测 linux-x86_64 / windows-x86_64）
  - check update 按钮：从 GitHub releases API 获取最新版本
  - download latest 按钮：选择平台后下载对应 zip，解压到 bin/ 目录
  - 下载源：`https://github.com/Xray/Xray-core/releases`
  - 下载后自动重启 V2fly 进程
  - 显示下载进度条
- V2fly 可执行文件路径、配置目录
- 节点检测参数：正常间隔（可达时 3-5min）、故障间隔（不可达时 30s）、tcp 超时、curl 超时、测试 URL、自动故障转移开关
- Web UI 参数：监听地址、端口、密码
- 系统信息：版本、PID、运行时长、数据库大小、平台
- 危险操作区：清空节点、重置设置、清空数据库

### 7. 日志面板（全局）

每个页面底部都有一个可折叠的日志面板：
- 点击 LOG 标题栏展开/收起（默认收起）
- 日志格式：`HH:MM:SS [module] message`
- 日志级别：info（黑）、ok（绿）、warn（橙）、error（红）
- 模块标识：system、V2fly、check、failover、upgrade、subscription 等
- 所有操作（启停服务、切换节点、检测结果、故障转移、升级下载）都写入日志
- 自动滚动到最新日志

## 数据模型

```
subscriptions:
  id, name, url, filter_keywords(text), exclude_keywords(text), updated_at

nodes:
  id, sub_id, name, protocol(vmess/ss), address, port, config_json,
  is_active(bool), priority(int),
  tcp_latency(int nullable), curl_latency(int nullable),
  last_check_at, last_check_status(ok/fail/unchecked)

inbounds:
  id, name, protocol(http/socks/ss/vmess), listen_addr, port, params_json

outbounds:
  id, name, type(freedom/single/auto), config_json

outbound_nodes:  (自动切换出站的节点池)
  id, outbound_id, node_id, priority(int)

services:
  id, name, inbound_id, outbound_id, is_running(bool)

settings:
  key, value
```

## 自动切换机制

### 故障转移逻辑

自动切换出站的节点按 priority 排序（越小优先级越高），后台线程定期检测：

1. **当前节点可达时**：
   - 检查是否有更高优先级的节点也可达
   - 如果有，切换到更高优先级的节点（优选）
   - 如果没有，继续使用当前节点

2. **当前节点不可达时**：
   - 从 priority 最小（最高优先级）的节点开始遍历
   - 找到第一个可达节点，切换并使用
   - 更新 V2fly 配置，重启出站

### 自适应检测间隔

- **当前节点可达**：检测间隔较长（默认 3-5 分钟），只做优选检查
- **当前节点不可达**：
  - 遍历阶段：间隔较短（默认 30 秒），快速找到可用节点
  - 完整遍历无可用节点后：间隔逐渐增大（指数退避，如 30s → 60s → 120s → 300s 上限）
  - 一旦找到可用节点，恢复为正常检测间隔

### 手动检测

在节点列表页面，用户可手动触发检测：
- 节点数 ≤20：串行逐个检测，结果逐行更新
- 节点数 >20：并行检测（ThreadPoolExecutor），批量更新结果
- 每个节点先测 tcp（socket 连接），再测 curl（通过代理 HTTP 请求测试 URL）
- 结果实时更新到页面的 tcp 和 curl 列
- 检测过程写入日志面板：`[check] node HK-01: tcp 12ms, curl 86ms` / `[check] node US-01: tcp timeout`

## API 设计

```
# 页面
GET  /                          # 仪表盘
GET  /inbounds                  # 入站设置
GET  /outbounds                 # 出站设置
GET  /subscriptions             # 订阅管理
GET  /nodes                     # 节点列表
GET  /settings                  # 设置

# 服务
POST /api/services              # 创建服务
PUT  /api/services/<id>         # 更新服务
DELETE /api/services/<id>       # 删除服务
POST /api/services/<id>/start   # 启动服务
POST /api/services/<id>/stop    # 停止服务
POST /api/services/<id>/restart # 重启服务

# 入站
POST /api/inbounds              # 创建入站
PUT  /api/inbounds/<id>         # 更新入站
DELETE /api/inbounds/<id>       # 删除入站

# 出站
POST /api/outbounds             # 创建出站
PUT  /api/outbounds/<id>        # 更新出站
DELETE /api/outbounds/<id>      # 删除出站

# 订阅
POST /api/subscriptions              # 添加订阅
PUT  /api/subscriptions/<id>         # 更新订阅
DELETE /api/subscriptions/<id>       # 删除订阅
POST /api/subscriptions/<id>/refresh # 刷新订阅

# 节点
POST /api/nodes/<id>/activate    # 加入节点池
POST /api/nodes/<id>/deactivate  # 从节点池移除
POST /api/nodes/<id>/select      # 手动选择为当前节点
POST /api/nodes/check            # 手动检测（body: {node_ids: [...]} 或 {all: true}）
POST /api/outbound-nodes/reorder # 更新节点优先级

# Xray
GET  /api/Xray/status           # V2fly 状态
POST /api/Xray/start            # 启动 V2fly
POST /api/Xray/stop             # 停止 V2fly
POST /api/Xray/restart          # 重启 V2fly

# 设置
GET  /api/settings               # 获取设置
POST /api/settings               # 更新设置

# 升级
GET  /api/upgrade/check          # 检查最新版本（返回 tag_name, published_at, assets）
GET  /api/upgrade/download       # 下载指定平台二进制（query: platform=linux-64|windows-64）
                                 # 流式返回进度，下载后解压到 bin/，重启 V2fly
```

## V2fly 配置模板

```json
{
  "inbounds": [
    {"port": 666, "protocol": "shadowsocks", "settings": {"method": "aes-256-gcm", "password": "xxx"}},
    {"port": 24811, "listen": "127.0.0.1", "protocol": "vmess", "settings": {"clients": [{"id": "xxx", "alterId": 64}]}, "streamSettings": {"network": "ws", "wsSettings": {"path": "/xxx/"}}},
    {"port": 704, "protocol": "shadowsocks", "settings": {"method": "aes-256-gcm", "password": "xxx"}}
  ],
  "outbounds": [
    {"protocol": "socks", "settings": {"servers": [{"address": "当前选中节点地址", "port": "端口"}]}},
    {"protocol": "freedom", "tag": "direct"}
  ],
  "routing": {
    "rules": [{"type": "field", "inboundTag": ["ss-home"], "outboundTag": "direct"}]
  }
}
```

## 实施步骤

1. **基础框架**：Flask 应用 + 数据库模型 + 页面模板（6 个页面）
2. **入站/出站管理**：CRUD 接口 + 配置存储
3. **服务管理**：服务 = 入站 + 出站组合，启停控制
4. **订阅解析**：vmess/ss 链接解析，关键字筛选/排除
5. **节点管理**：节点池、优先级排序、手动切换
6. **V2fly 管理**：配置生成（Jinja2）、进程管理（subprocess）
7. **节点检测**：TCP + curl 双重检测、手动触发、串行/并行
8. **自动故障转移**：自适应间隔、优先级优选、指数退避

## 验证方式

1. 添加订阅 → 节点正确解析，关键字筛选/排除生效
2. 创建入站+出站+服务 → V2fly 配置正确生成
3. 客户端通过 SS/VMess 连接 → 代理可用
4. 手动 check 节点 → tcp/curl 延迟正确显示
5. 断开当前节点 → 自动切换到下一优先级可用节点
6. 高优先级节点恢复 → 自动切回
7. SS 回国代理 (704) → 国外可连回国内
