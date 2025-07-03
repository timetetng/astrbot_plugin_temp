# 导入 astrbot API 和 asyncio
import asyncio
from typing import Dict, Any, Deque
from collections import deque # 导入 deque 用于存储有限历史数据
from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from datetime import datetime, timezone
import re
import psutil
# 插件元数据注册
@register(
    "astrbot_plugin_temp",  # 插件名称
    "timetetng",    # 作者名
    "查询和告警服务器硬件温度、系统状态及Docker容器管理",  # 插件描述
    "2.3.0",        # 版本号 (更新为2.3.0)
    "your_repo_url" #
)
class ServerTempPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        self.monitor_task = None
        
        self.device_name_map = {
            "CPU": "CPU",
            "Motherboard": "主板",
            "WIFI": "网卡",
            "NVMe": "硬盘"
        }
        # 存储每个设备的温度历史，使用 deque 限制长度
        # deque 的最大长度为 (趋势计算时间窗口 / 检查间隔) + 1，以确保至少有2个点用于计算变化率
        # 假设 check_interval_minutes 默认为5分钟，半小时是30分钟，则 30/5 + 1 = 7个点
        self.history_length = (self.config.get("trend_window_minutes", 30) // self.config.get("check_interval_minutes", 5)) + 1
        self._temperature_history: Dict[str, Deque[float]] = {
            "CPU": deque(maxlen=self.history_length),
            "主板": deque(maxlen=self.history_length),
            "网卡": deque(maxlen=self.history_length),
            "硬盘": deque(maxlen=self.history_length)
        }

        if self.config.get("enabled", False):
            self.monitor_task = asyncio.create_task(self._temperature_monitor())
            logger.info("服务器温度监控任务已启动。")

    async def _get_sensor_data_structured(self) -> Dict[str, float]:
        data_dict = {}
        try:
            process = await asyncio.create_subprocess_exec(
                'sensors', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                logger.error(f"执行 'sensors' 命令失败: {stderr.decode('utf-8').strip()}")
                return {}
            output = stdout.decode('utf-8')
        except FileNotFoundError:
            logger.error("错误: 'sensors' 命令未找到。请在服务器上安装 lm-sensors。")
            return {}
        except Exception as e:
            logger.error(f"获取传感器数据时发生未知错误: {e}")
            return {}

        lines = output.splitlines()
        current_section_map = {
            "coretemp-isa": "CPU",
            "acpitz-acpi": "主板",
            "iwlwifi": "网卡",
            "nvme-pci": "硬盘"
        }
        current_section_name = None

        for line in lines:
            line_stripped = line.strip()
            # 检查是否为新设备的开始
            for key, name in current_section_map.items():
                if line_stripped.startswith(key):
                    current_section_name = name
                    break
            
            temp_str = ""
            if current_section_name == "CPU" and "Package id 0:" in line_stripped:
                temp_str = line_stripped.split(":")[1].strip().split(" ")[0]
            elif current_section_name == "主板" and "temp1:" in line_stripped:
                temp_str = line_stripped.split(":")[1].strip().split(" ")[0]
            elif current_section_name == "网卡" and "temp1:" in line_stripped:
                temp_str = line_stripped.split(":")[1].strip().split(" ")[0]
            elif current_section_name == "硬盘" and "Composite:" in line_stripped:
                temp_str = line_stripped.split(":")[1].strip().split(" ")[0]
            
            if temp_str:
                try:
                    temp_value = float(temp_str.lstrip('+').replace("°C", ""))
                    data_dict[current_section_name] = temp_value
                    # 重置 current_section_name，因为我们已经找到了这个设备的关键温度
                    current_section_name = None 
                except (ValueError, IndexError):
                    continue
        return data_dict

    def _get_temperature_trend(self, device_name: str) -> str:
        """
        根据历史温度数据计算并返回温度趋势。
        使用历史数据的平均变化率判断。
        """
        history = self._temperature_history.get(device_name)
        if not history or len(history) < 2:
            return "" # 数据不足以判断趋势

        # 计算平均变化率
        diff_sum = 0
        count = 0
        for i in range(1, len(history)):
            diff_sum += history[i] - history[i-1]
            count += 1
        
        if count > 0:
            avg_diff = diff_sum / count
            if avg_diff > 0.1: # 设定一个微小的阈值，避免微小波动显示趋势
                return "↑"
            elif avg_diff < -0.1:
                return "↓"
        return "" # 变化不明显或数据不足

    async def _temperature_monitor(self):
        logger.info("温度监控后台任务正在运行...")
        while True:
            try:
                interval_minutes = self.config.get("check_interval_minutes", 5)
                await asyncio.sleep(interval_minutes * 60)

                logger.info("正在执行定时温度检查...")
                current_temps = await self._get_sensor_data_structured()
                if not current_temps:
                    logger.warning("定时检查无法获取到温度数据，跳过本次检查。")
                    continue

                # 更新温度历史
                for device_key, temp in current_temps.items():
                    # 确保设备名称在 device_name_map 中是中文显示名
                    display_name = self.device_name_map.get(device_key, device_key)
                    if display_name not in self._temperature_history:
                        self._temperature_history[display_name] = deque(maxlen=self.history_length)
                    self._temperature_history[display_name].append(temp)

                thresholds = self.config.get("thresholds", {})
                alert_messages = []

                for device_key, temp in current_temps.items():
                    if device_key in thresholds and temp > thresholds[device_key]:
                        display_name = self.device_name_map.get(device_key, device_key)
                        msg = f"检测到 {display_name} 温度异常，当前: {temp}°C, 阈值: {thresholds[device_key]}°C"
                        alert_messages.append(msg)
                
                if alert_messages:
                    full_alert_message = "⚠️ 服务器高温告警 ⚠️\n" + "\n".join(alert_messages)
                    alert_groups = self.config.get("alert_groups", [])
                    
                    if not alert_groups:
                        logger.warning("温度达到阈值，但未配置告警群聊 (alert_groups)。")
                        continue

                    for group_umo in alert_groups:
                        logger.info(f"向群聊 {group_umo} 发送高温告警。")
                        await self.context.send_message(group_umo, [Comp.Plain(full_alert_message)])
            
            except asyncio.CancelledError:
                logger.info("温度监控任务被取消，正在停止...")
                break
            except Exception as e:
                logger.error(f"温度监控任务出现错误: {e}", exc_info=True)
                await asyncio.sleep(300)

    @filter.command("servertemp", alias={"温度", "temp"})
    async def get_server_temp_command(self, event: AstrMessageEvent):
        logger.info(f"用户 {event.get_sender_name()} 触发了温度查询指令")
        structured_data = await self._get_sensor_data_structured()

        if not structured_data:
            yield event.plain_result("无法获取服务器温度信息，请检查后台日志。")
            return

        output_parts = []
        for device_key, temp in structured_data.items():
            display_name = self.device_name_map.get(device_key, device_key)
            # 在这里将当前温度加入历史记录，以便后续计算趋势
            if display_name not in self._temperature_history:
                self._temperature_history[display_name] = deque(maxlen=self.history_length)
            self._temperature_history[display_name].append(temp)
            
            trend = self._get_temperature_trend(display_name)
            output_parts.append(f"{display_name}温度: {temp}°C {trend}".strip()) # strip 避免趋势为空时多余空格
        
        yield event.plain_result("--- 温度信息 ---\n" + "\n".join(output_parts))

    @filter.command("status", alias={"状态"})
    async def get_server_status_command(self, event: AstrMessageEvent):
        logger.info(f"用户 {event.get_sender_name()} 触发了服务器状态查询指令")
        
        output_message_parts = []

        # 获取温度信息
        structured_data = await self._get_sensor_data_structured()
        if structured_data:
            output_message_parts.append("--- 温度信息 ---")
            for device_key, temp in structured_data.items():
                display_name = self.device_name_map.get(device_key, device_key)
                # 在这里将当前温度加入历史记录，以便后续计算趋势
                if display_name not in self._temperature_history:
                    self._temperature_history[display_name] = deque(maxlen=self.history_length)
                self._temperature_history[display_name].append(temp)

                trend = self._get_temperature_trend(display_name)
                output_message_parts.append(f"{display_name}温度: {temp}°C {trend}".strip())
        else:
            output_message_parts.append("--- 温度信息 (无法获取) ---")

        # 获取CPU和内存信息
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            
            mem = psutil.virtual_memory()
            mem_total_gb = round(mem.total / (1024**3), 2)
            mem_used_gb = round(mem.used / (1024**3), 2)
            mem_percent = mem.percent

            output_message_parts.append("\n--- 系统状态 ---")
            output_message_parts.append(f"CPU使用率: {cpu_percent}%")
            output_message_parts.append(f"内存使用率: {mem_percent}% ({mem_used_gb}GB/{mem_total_gb}GB)")

        except Exception as e:
            logger.error(f"获取服务器状态时发生错误: {e}", exc_info=True)
            output_message_parts.append("\n--- 系统状态 (无法获取) ---")
            output_message_parts.append("获取服务器CPU/内存状态失败，请检查后台日志。")

        yield event.plain_result("\n".join(output_message_parts))

    @filter.command("containers", alias={"容器", "docker"})
    async def get_docker_containers_command(self, event: AstrMessageEvent):
        logger.info(f"用户 {event.get_sender_name()} 触发了Docker容器查询指令")
        
        try:
            client = docker.from_env()
            containers = client.containers.list(all=True)

            if not containers:
                yield event.plain_result("当前没有运行的 Docker 容器。")
                return

            container_data = []
            for container in containers:
                name = container.name
                status = container.status
                
                cpu_percent = "N/A"
                mem_usage = "N/A"

                try:
                    stats = container.stats(stream=False)
                    if stats:
                        # CPU使用率计算
                        if 'cpu_stats' in stats and 'precpu_stats' in stats and \
                           'cpu_usage' in stats['cpu_stats'] and 'total_usage' in stats['cpu_stats']['cpu_usage'] and \
                           'cpu_usage' in stats['precpu_stats'] and 'total_usage' in stats['precpu_stats']['cpu_usage'] and \
                           'system_cpu_usage' in stats['cpu_stats'] and 'system_cpu_usage' in stats['precpu_stats']:

                            cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
                            system_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
                            
                            num_cpus = len(stats['cpu_stats'].get('online_cpus', [])) if isinstance(stats['cpu_stats'].get('online_cpus'), list) else 1

                            if system_delta > 0 and cpu_delta > 0 and num_cpus > 0:
                                cpu_percent = f"{round((cpu_delta / system_delta) * num_cpus * 100.0, 2)}%"
                            else:
                                   cpu_percent = "0.00%"
                        else:
                            cpu_percent = "数据不完整"

                        # 内存使用率
                        if 'memory_stats' in stats and 'usage' in stats['memory_stats']:
                            mem_usage_bytes = stats['memory_stats']['usage']
                            mem_limit_bytes = stats['memory_stats'].get('limit', 0)

                            if mem_limit_bytes > 0:
                                mem_usage = f"{round(mem_usage_bytes / (1024**2), 2)}MB ({round((mem_usage_bytes / mem_limit_bytes) * 100, 2)}%)"
                            else:
                                mem_usage = f"{round(mem_usage_bytes / (1024**2), 2)}MB"
                        else:
                            mem_usage = "数据不完整"

                except Exception as stats_e:
                    logger.warning(f"无法获取容器 {name} 的统计信息: {stats_e}")
                
                container_data.append({
                    "name": name,
                    "cpu_percent": cpu_percent,
                    "mem_usage": mem_usage,
                    "status": status,
                })
            
            # HTML 模板，包含基本样式，并移除运行时间列
            HTML_TEMPLATE = '''
            <div style="font-family: Arial, sans-serif; padding: 10px; background-color: #f0f2f5; border-radius: 8px;">
                <h2 style="color: #333; text-align: center; margin-bottom: 15px;">Docker 容器状态</h2>
                <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                    <thead style="background-color: #4CAF50; color: white;">
                        <tr>
                            <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">容器名</th>
                            <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">CPU占用</th>
                            <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">内存占用</th>
                            <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">运行状态</th>
                            </tr>
                    </thead>
                    <tbody>
                        {% for container in containers %}
                        <tr style="background-color: {% if loop.index % 2 == 0 %}#f9f9f9{% else %}#ffffff{% endif %};">
                            <td style="padding: 8px; border: 1px solid #ddd;">{{ container.name }}</td>
                            <td style="padding: 8px; border: 1px solid #ddd;">{{ container.cpu_percent }}</td>
                            <td style="padding: 8px; border: 1px solid #ddd;">{{ container.mem_usage }}</td>
                            <td style="padding: 8px; border: 1px solid #ddd;">{{ container.status }}</td>
                            </tr>
                        {% endfor %}
                    </tbody>
                </table>
                <p style="font-size: 12px; color: #666; text-align: right; margin-top: 15px;">数据更新时间: {{ current_time }}</p>
            </div>
            '''
            
            # 渲染 HTML 并获取图片 URL
            render_data = {
                "containers": container_data,
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            url = await self.html_render(HTML_TEMPLATE, render_data)
            
            yield event.image_result(url)

        except docker.errors.DockerException as e:
            logger.error(f"连接Docker守护进程失败或Docker环境问题: {e}", exc_info=True)
            yield event.plain_result("无法连接到 Docker 守护进程，请检查 Docker 服务是否正在运行。")
        except Exception as e:
            logger.error(f"获取Docker容器信息或图片渲染时发生错误: {e}", exc_info=True)
            # 如果 HTML 渲染失败，则回退到文本输出
            fallback_message = "获取 Docker 容器信息或图片渲染失败，请检查后台日志。\n"
            fallback_message += "--- 回退到文本输出 ---\n"
            
            text_lines = ["容器名          | 容器CPU占用 | 容器内存占用 | 容器运行状态"]
            for data in container_data: 
                text_lines.append(f"{data['name']:<15} | {data['cpu_percent']:<12} | {data['mem_usage']:<12} | {data['status']:<12}")
            
            yield event.plain_result(fallback_message + "\n".join(text_lines))

    @filter.command("启动容器", alias={"start_container"})
    async def start_container_command(self, event: AstrMessageEvent, container_name: str):
        logger.info(f"用户 {event.get_sender_name()} 触发了启动容器指令: {container_name}")
        try:
            client = docker.from_env()
            container = client.containers.get(container_name)
            if container.status == "running":
                yield event.plain_result(f"容器 {container_name} 已经在运行中。")
                return
            
            container.start()
            yield event.plain_result(f"容器 {container_name} 启动成功。")
        except docker.errors.NotFound:
            yield event.plain_result(f"错误：未找到名为 '{container_name}' 的容器。")
        except docker.errors.APIError as e:
            logger.error(f"启动容器 {container_name} 失败: {e}", exc_info=True)
            yield event.plain_result(f"启动容器 {container_name} 失败：{e}")
        except Exception as e:
            logger.error(f"启动容器 {container_name} 时发生未知错误: {e}", exc_info=True)
            yield event.plain_result(f"启动容器 {container_name} 时发生未知错误。")

    @filter.command("关闭容器", alias={"stop_container"})
    async def stop_container_command(self, event: AstrMessageEvent, container_name: str):
        logger.info(f"用户 {event.get_sender_name()} 触发了关闭容器指令: {container_name}")
        try:
            client = docker.from_env()
            container = client.containers.get(container_name)
            if container.status != "running":
                yield event.plain_result(f"容器 {container_name} 没有在运行中。")
                return
            
            container.stop()
            yield event.plain_result(f"容器 {container_name} 关闭成功。")
        except docker.errors.NotFound:
            yield event.plain_result(f"错误：未找到名为 '{container_name}' 的容器。")
        except docker.errors.APIError as e:
            logger.error(f"关闭容器 {container_name} 失败: {e}", exc_info=True)
            yield event.plain_result(f"关闭容器 {container_name} 失败：{e}")
        except Exception as e:
            logger.error(f"关闭容器 {container_name} 时发生未知错误: {e}", exc_info=True)
            yield event.plain_result(f"关闭容器 {container_name} 时发生未知错误。")

    @filter.command("删除容器", alias={"remove_container"})
    async def remove_container_command(self, event: AstrMessageEvent, container_name: str):
        logger.info(f"用户 {event.get_sender_name()} 触发了删除容器指令: {container_name}")
        try:
            client = docker.from_env()
            # remove 之前最好先 stop，或者使用 force=True
            container = client.containers.get(container_name)
            if container.status == "running":
                yield event.plain_result(f"容器 {container_name} 正在运行中，请先关闭后再尝试删除。")
                return

            container.remove()
            yield event.plain_result(f"容器 {container_name} 删除成功。")
        except docker.errors.NotFound:
            yield event.plain_result(f"错误：未找到名为 '{container_name}' 的容器。")
        except docker.errors.APIError as e:
            logger.error(f"删除容器 {container_name} 失败: {e}", exc_info=True)
            yield event.plain_result(f"删除容器 {container_name} 失败：{e}")
        except Exception as e:
            logger.error(f"删除容器 {container_name} 时发生未知错误: {e}", exc_info=True)
            yield event.plain_result(f"删除容器 {container_name} 时发生未知错误。")

    @filter.command("重启容器", alias={"restart_container"})
    async def restart_container_command(self, event: AstrMessageEvent, container_name: str):
        logger.info(f"用户 {event.get_sender_name()} 触发了重启容器指令: {container_name}")
        try:
            client = docker.from_env()
            container = client.containers.get(container_name)
            
            # 容器不一定在运行才能重启，但如果已经停止，重启会尝试启动它
            container.restart()
            yield event.plain_result(f"容器 {container_name} 重启成功。")
        except docker.errors.NotFound:
            yield event.plain_result(f"错误：未找到名为 '{container_name}' 的容器。")
        except docker.errors.APIError as e:
            logger.error(f"重启容器 {container_name} 失败: {e}", exc_info=True)
            yield event.plain_result(f"重启容器 {container_name} 失败：{e}")
        except Exception as e:
            logger.error(f"重启容器 {container_name} 时发生未知错误: {e}", exc_info=True)
            yield event.plain_result(f"重启容器 {container_name} 时发生未知错误。")


    async def terminate(self):
        if self.monitor_task:
            self.monitor_task.cancel()
            await asyncio.gather(self.monitor_task, return_exceptions=True)
            logger.info("服务器温度监控任务已成功停止。")