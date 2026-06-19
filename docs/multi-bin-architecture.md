# 多二进制架构设计方案

## 背景

当前 v2ray-webui 只使用 Xray 作为代理后端，但 Xray 不支持：
- SS 插件（obfs-local, v2ray-plugin）
- Hysteria2 出站
- TUIC 出站

参考 passwall2 的架构，采用多二进制方案解决。

## 目标

支持所有主流协议的完整功能：

| 协议 | 功能 |
|------|------|
| VMess | 全功能 |
| VLESS | 全功能 |
| Trojan | 全功能 |
| SS | 全功能（包括插件） |
| Hysteria2 | 全功能 |
| TUIC | 全功能 |

## 架构设计

### 1. 二进制文件

```
bin/
├── xray.exe          # VMess/VLESS/Trojan
├── sslocal.exe       # SS（支持插件）
├── obfs-local.exe    # SS obfs 插件
├── v2ray-plugin.exe  # SS v2ray 插件（可选）
└── sing-box.exe      # Hysteria2/TUIC
```

### 2. 协议分配

```python
# 二进制选择规则
BINARY_MAP = {
    'vmess': 'xray',
    'vless': 'xray',
    'trojan': 'xray',
    'ss': 'sslocal',      # 有插件时
    'ss': 'xray',         # 无插件时（可选）
    'hysteria2': 'sing-box',
    'tuic': 'sing-box',
}
```

### 3. 数据库修改

nodes 表新增字段：
```sql
ALTER TABLE nodes ADD COLUMN bin_type TEXT DEFAULT 'xray';
```

bin_type 值：
- `xray` - 使用 Xray
- `sslocal` - 使用 sslocal
- `sing-box` - 使用 sing-box

### 4. 配置生成器

```
app/
├── config/
│   ├── __init__.py
│   ├── xray.py       # Xray 配置生成
│   ├── sslocal.py    # sslocal 配置生成
│   └── singbox.py    # sing-box 配置生成
├── checker.py        # 节点检测
└── ...
```

### 5. 配置格式

#### Xray (VMess/VLESS/Trojan)
```json
{
  "inbounds": [{"protocol": "socks", "port": 10808, "listen": "127.0.0.1"}],
  "outbounds": [{"protocol": "vmess", "settings": {...}}]
}
```

#### sslocal (SS)
```json
{
  "server": "example.com",
  "server_port": 8388,
  "password": "password",
  "method": "aes-256-gcm",
  "plugin": "obfs-local",
  "plugin_opts": "obfs=http;obfs-host=example.com"
}
```

#### sing-box (Hysteria2/TUIC)
```json
{
  "inbounds": [{"type": "socks", "listen_port": 10808, "listen": "127.0.0.1"}],
  "outbounds": [{"type": "hysteria2", "server": "example.com", ...}]
}
```

## 实现步骤

### 第一阶段：基础设施

1. **下载二进制文件**
   - xray.exe（已有）
   - sslocal.exe（从 GitHub 下载）
   - sing-box.exe（从 GitHub 下载）
   - obfs-local.exe（已下载）

2. **修改数据库**
   - nodes 表新增 bin_type 字段
   - 订阅解析时自动设置 bin_type

3. **创建配置生成器**
   - app/config/xray.py
   - app/config/sslocal.py
   - app/config/singbox.py

### 第二阶段：检测功能

4. **重写 checker.py**
   - 根据 bin_type 选择二进制
   - 生成对应配置
   - 启动临时进程测试
   - 统一的结果格式

### 第三阶段：运行功能

5. **重写 xray_manager.py**
   - 支持多二进制管理
   - 统一的启动/停止/重启接口
   - 进程状态监控

6. **修改 main.py**
   - 更新 API 接口
   - 支持多二进制状态查询

### 第四阶段：前端适配

7. **修改前端**
   - 节点编辑支持选择二进制
   - 状态栏显示当前使用的二进制
   - 设置页面管理二进制路径

## 文件清单

### 新增文件
- `bin/sslocal.exe` - SS 客户端
- `bin/sing-box.exe` - sing-box 客户端
- `app/config/__init__.py`
- `app/config/xray.py`
- `app/config/sslocal.py`
- `app/config/singbox.py`
- `docs/multi-bin-architecture.md`

### 修改文件
- `app/db.py` - 新增 bin_type 字段
- `app/subscription.py` - 自动设置 bin_type
- `app/checker.py` - 支持多二进制检测
- `app/xray_manager.py` - 支持多二进制管理
- `app/main.py` - 更新 API
- `templates/nodes.html` - 前端适配
- `templates/settings.html` - 二进制路径设置

## 注意事项

1. **端口管理** - 每个临时进程使用随机端口，避免冲突
2. **进程清理** - 确保临时进程被正确杀掉
3. **并发控制** - 限制同时运行的临时进程数
4. **错误处理** - 每个二进制的错误格式不同，需要统一处理
5. **日志格式** - 不同二进制的日志格式不同，需要解析

## 测试计划

1. **单元测试** - 每个配置生成器
2. **集成测试** - 完整的检测流程
3. **性能测试** - 批量检测的并发性能
4. **兼容性测试** - 各协议的各种配置

## 时间估算

- 第一阶段：2-3 小时
- 第二阶段：2-3 小时
- 第三阶段：3-4 小时
- 第四阶段：2-3 小时

总计：约 10-13 小时
