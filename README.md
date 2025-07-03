
# AstrBot 服务器状态监控与 Docker 管理插件

## 🚀 简介

`astrbot_plugin_temp` 是一个功能强大的 AstrBot 插件，旨在帮助您实时监控服务器的**硬件温度**、**系统资源使用情况（CPU/内存）**，并提供便捷的 **Docker 容器管理**功能。此外，它还支持**温度异常告警**和**温度趋势显示**，让您对服务器健康状况了如指掌。


## ✨ 主要功能

  * **实时温度查询**：
      * 支持查询 CPU、主板、网卡、硬盘等硬件设备的当前温度。
      * 显示温度趋势（上升 `↑` / 下降 `↓`），根据一段时间内的平均变化率判断。
  * **系统状态查询**：
      * 一键获取服务器的 CPU 使用率和内存使用率（已用/总量）。
      * 此命令会合并显示所有温度信息及其趋势。
  * **Docker 容器管理**：
      * 列出所有 Docker 容器的状态，包括容器名、CPU 占用、内存占用和运行状态。
      * 支持通过命令**启动**、**停止**、**重启**和**删除**指定容器。
      * 提供 HTML 渲染的表格输出，更直观易读。
  * **温度异常告警**：
      * 可配置各个硬件的温度阈值。
      * 当温度超过阈值时，自动向指定群聊发送告警消息。
  * **配置灵活**：所有功能均可通过配置文件轻松开启/关闭或调整参数。


## 🛠️ 安装与依赖

### 1\. 安装系统依赖

本插件需要您的 Linux 服务器安装 `lm-sensors` 工具来获取硬件温度。

```bash
# Debian/Ubuntu 系统
sudo apt update
sudo apt install lm-sensors
sudo sensors-detect 

# CentOS/RHEL 系统
sudo yum install lm_sensors
sudo sensors-detect
```

### 2\. 安装 Python 依赖

进入您的 AstrBot 项目根目录，确保 AstrBot 的虚拟环境已激活，然后安装以下 Python 库：

```bash
pip install psutil
pip install docker
```

### 3\. 插件部署

将 `main.py` 文件放置到 AstrBot 的插件目录中，例如 `data/plugins/astrbot_plugin_temp/main.py`。



## ⚙️ 配置

在您的 AstrBot 配置目录中（通常是 `config.yaml` 所在的目录），找到或创建此插件的配置文件，例如 `config/astrbot_plugin_temp.json`。

以下是配置文件的示例内容：

```json
{
  "enabled": {
    "type": "bool",
    "description": "是否启用定时温度告警功能。",
    "default": true
  },
  "check_interval_minutes": {
    "type": "int",
    "description": "定时检查硬件温度的周期（单位：分钟）。",
    "hint": "设置每隔多少分钟检查一次温度。建议不要设置得太频繁，例如 5 分钟或以上。",
    "default": 5
  },
  "trend_window_minutes": {
    "type": "int",
    "description": "计算温度变化趋势的时间窗口（单位：分钟）。",
    "hint": "系统会分析此时间窗口内的温度数据来判断上升或下降趋势。建议设置为 check_interval_minutes 的倍数，例如 30 分钟。",
    "default": 30
  },
  "alert_groups": {
    "type": "list",
    "description": "接收告警消息的群聊列表。",
    "hint": "填写群聊的 `unified_msg_origin`。您可以创建一个临时指令，在群内触发后打印 event.unified_msg_origin 来获取此值。",
    "default": []
  },
  "thresholds": {
    "type": "object",
    "description": "各硬件的温度告警阈值（单位：°C）。当实际温度超过设定值时会发送告警。",
    "items": {
      "CPU": {
        "type": "float",
        "description": "CPU 温度阈值",
        "default": 85.0
      },
      "Motherboard": {
        "type": "float",
        "description": "主板温度阈值",
        "default": 60.0
      },
      "WIFI": {
        "type": "float",
        "description": "网卡温度阈值",
        "default": 80.0
      },
      "NVMe": {
        "type": "float",
        "description": "硬盘温度阈值",
        "default": 70.0
      }
    }
  }
}
```

请根据您的实际需求修改 `alert_groups` 和 `thresholds` 中的值。


## 🚀 使用方法

以下是您可以在聊天中使用的命令：

  * **查询硬件温度**：

      * `/servertemp`
      * `/温度`
      * `/temp`
      * **示例输出**：
        ```
        --- 温度信息 ---
        CPU温度: 46.0°C ↑
        主板温度: 27.8°C →
        网卡温度: 51.0°C ↓
        硬盘温度: 48.9°C ↑
        ```
        （箭头 `↑` 表示温度上升，`↓` 表示下降，没有箭头或 `→` 表示变化不明显）

  * **查询服务器综合状态（包含温度、CPU、内存）**：

      * `/status`
      * `/状态`
      * **示例输出**：
        ```
        --- 温度信息 ---
        CPU温度: 46.0°C ↑
        主板温度: 27.8°C →
        网卡温度: 51.0°C ↓
        硬盘温度: 48.9°C ↑

        --- 系统状态 ---
        CPU使用率: 15.2%
        内存使用率: 35.7% (4.5GB/12.6GB)
        ```

  * **查询 Docker 容器状态**：

      * `/containers`
      * `/容器`
      * `/docker`
      * **示例输出**（HTML 图片形式，提供容器名、CPU、内存、运行状态）：
        一张包含以下表格内容的图片：
        | 容器名        | CPU占用      | 内存占用      | 运行状态   |
        | :------------ | :----------- | :------------ | :--------- |
        | my\_web\_app    | 0.5%         | 50.2MB (10%)  | running    |
        | database      | 1.2%         | 200.5MB (25%) | running    |
        | stopped\_nginx | 0.00%        | 0.00MB (0%)   | exited     |
        | ...           | ...          | ...           | ...        |

  * **启动 Docker 容器**：

      * `/启动容器 <容器名>`
      * `/start_container <容器名>`
      * **示例**：`/启动容器 my_web_app`

  * **关闭 Docker 容器**：

      * `/关闭容器 <容器名>`
      * `/stop_container <容器名>`
      * **示例**：`/关闭容器 my_web_app`

  * **删除 Docker 容器**：

      * `/删除容器 <容器名>`
      * `/remove_container <容器名>`
      * **注意**：容器必须是停止状态才能删除。
      * **示例**：`/删除容器 old_container`

  * **重启 Docker 容器**：

      * `/重启容器 <容器名>`
      * `/restart_container <容器名>`
      * **示例**：`/重启容器 database`


## ⚠️ 注意事项

  * **`lm-sensors` 安装**：确保您的 Linux 服务器上已正确安装 `lm-sensors` 工具，并且运行 `sudo sensors-detect` 进行了设备检测，否则插件将无法获取硬件温度。
  * **Docker 权限**：确保运行 AstrBot 的用户拥有访问 Docker Daemon 的权限。通常，将用户添加到 `docker` 用户组即可：
    ```bash
    sudo usermod -aG docker $USER
    # 然后需要重启会话或重新登录才能生效
    ```
  * **温度趋势判断**：温度趋势的箭头（`↑` / `↓`）是基于一段时间内的平均变化率。如果温度波动较小，可能不会显示箭头。默认的判断阈值是 `0.1°C`，你可以在代码中微调 `_get_temperature_trend` 方法中的 `0.1` 来改变灵敏度。
  * **配置更新**：修改配置文件后，需要重启 AstrBot 才能使新配置生效。

-----

## 🤝 贡献

如果您有任何改进建议或发现 Bug，欢迎提交 Pull Request 或 Issue。

-----

**作者**：timetetng

**版本**：2.3.0

**仓库地址**：[astrbot_plugin_temp](https://github.com/timetetng/astrbot_plugin_temp) 

-----
