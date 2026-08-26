import base64
import datetime
import hashlib
import mimetypes
import os
import re
import ast
import threading
import time
import shutil
import random
from pathlib import Path
from urllib.parse import urlparse, quote, unquote
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
import pytz
import yaml

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# MoviePilot V3 SDK imports with legacy V2 fallback
try:
    from app.sdk.logging import logger
except ImportError:
    from app.log import logger

try:
    from app.sdk.config import settings
except ImportError:
    from app.core.config import settings

try:
    from app.sdk.events import eventmanager, Event
except ImportError:
    from app.core.event import eventmanager, Event

try:
    from app.sdk.media import MetaBase
except ImportError:
    from app.core.meta import MetaBase

try:
    from app.sdk.services import MediaServerHelper
except ImportError:
    try:
        from app.helper.mediaserver import MediaServerHelper
    except ImportError:
        MediaServerHelper = None

try:
    from app.chain.mediaserver import MediaServerChain
except ImportError:
    MediaServerChain = None

try:
    from app.sdk.plugins import _PluginBase
except ImportError:
    from app.plugins import _PluginBase

try:
    from app.sdk.schemas import MediaInfo, TransferInfo, ServiceInfo
    from app.sdk.schemas.types import EventType
except ImportError:
    try:
        from app import schemas
        from app.schemas import MediaInfo, TransferInfo, ServiceInfo
        from app.schemas.types import EventType
    except ImportError:
        schemas = None
        MediaInfo = None
        TransferInfo = None
        ServiceInfo = None
        EventType = None

try:
    from app.sdk.network import RequestUtils, UrlUtils
except ImportError:
    try:
        from app.utils.http import RequestUtils
        from app.utils.url import UrlUtils
    except ImportError:
        RequestUtils = None
        UrlUtils = None

# Plugin internal imports
try:
    from .style.style_static_1 import create_style_static_1
    from .style.style_static_2 import create_style_static_2
    from .style.style_static_3 import create_style_static_3
    from .style.style_static_4 import create_style_static_4
    from .style.style_animated_1 import create_style_animated_1
    from .style.style_animated_2 import create_style_animated_2
    from .style.style_animated_3 import create_style_animated_3
    from .style.style_animated_4 import create_style_animated_4
    from .utils.image_manager import ResolutionConfig, ImageResourceManager
    from .utils.network_helper import NetworkHelper, validate_font_file
    from .utils.performance_helper import PerformanceMonitor, ProgressTracker, memory_efficient_operation
    from .utils.color_helper import ColorHelper
except ImportError:
    from app.plugins.mediacovergenerator.style.style_static_1 import create_style_static_1
    from app.plugins.mediacovergenerator.style.style_static_2 import create_style_static_2
    from app.plugins.mediacovergenerator.style.style_static_3 import create_style_static_3
    from app.plugins.mediacovergenerator.style.style_static_4 import create_style_static_4
    from app.plugins.mediacovergenerator.style.style_animated_1 import create_style_animated_1
    from app.plugins.mediacovergenerator.style.style_animated_2 import create_style_animated_2
    from app.plugins.mediacovergenerator.style.style_animated_3 import create_style_animated_3
    from app.plugins.mediacovergenerator.style.style_animated_4 import create_style_animated_4
    from app.plugins.mediacovergenerator.utils.image_manager import ResolutionConfig, ImageResourceManager
    from app.plugins.mediacovergenerator.utils.network_helper import NetworkHelper, validate_font_file
    from app.plugins.mediacovergenerator.utils.performance_helper import PerformanceMonitor, ProgressTracker, memory_efficient_operation
    from app.plugins.mediacovergenerator.utils.color_helper import ColorHelper


from .core.font_manager import FontManagerMixin
from .core.history_manager import HistoryManagerMixin
from .core.media_fetcher import MediaFetcherMixin
from .core.generator import GeneratorMixin
from .core.api import ApiManagerMixin

class MediaCoverGenerator(ApiManagerMixin, FontManagerMixin, HistoryManagerMixin, MediaFetcherMixin, GeneratorMixin, _PluginBase):
    # 插件名称
    plugin_name = "Emby媒体库封面生成"
    # 插件描述
    plugin_desc = "生成媒体库动态/静态封面，支持 Emby/Jellyfin"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/icons/emby.png"
    # 插件版本
    plugin_version = "1.0.0"
    # 插件作者
    plugin_author = "justzerock (V3适配版)"
    # 作者主页
    author_url = "https://github.com/justzerock/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "mediacovergenerator_"
    # 加载顺序
    plugin_order = 2
    # 可使用的用户级别
    auth_level = 1

    # 退出事件
    _event = threading.Event()

    # 私有属性
    _scheduler = None
    mschain = None
    mediaserver_helper = None
    _enabled = False
    _update_now = False
    _transfer_monitor = True
    _cron = None
    _delay = 60
    _servers = None
    _selected_servers = []
    _all_libraries = []
    _include_libraries = []
    _sort_by = 'Random'
    _monitor_sort = ''
    _current_updating_items = set()
    _covers_output = ''
    _covers_input = ''
    _zh_font_url = ''
    _en_font_url = ''
    _zh_font_path = ''
    _en_font_path = ''
    _title_config = ''
    _current_config = {}
    _cover_style = 'static_1'
    _cover_style_base = 'static_1'
    _cover_style_variant = 'static'
    _font_path = ''
    _covers_path = ''
    _tab = 'style-tab'
    _multi_1_blur = True
    _zh_font_size = None
    _en_font_size = None
    _blur_size = 50
    _color_ratio = 0.8
    _use_primary = False
    _seen_keys = set()
    _zh_font_custom = ''
    _en_font_custom = ''
    _zh_font_preset = 'chaohei'
    _en_font_preset = 'EmblemaOne'
    _zh_font_offset = ''
    _title_spacing = ''
    _en_line_spacing = ''
    _title_scale = 1.0
    _resolution = '480p'
    _custom_width = 1920
    _custom_height = 1080
    _resolution_config = None
    _animation_duration = 8
    _animation_scroll = 'alternate'
    _animation_fps = 24
    _animation_format = 'apng'
    _animation_resolution = '320x180'
    _animation_reduce_colors = 'medium'
    _animated_2_image_count = 6
    _animated_2_departure_type = 'fly'
    _style_naming_v2 = True
    _sanitize_log_cache = set()
    _clean_images = False
    _clean_fonts = False
    _save_recent_covers = True
    _covers_history_limit_per_library = 10
    _covers_page_history_limit = 50
    _page_tab = "generate-tab"

    def __init__(self):
        super().__init__()

    def init_plugin(self, config: dict = None):
        try:
            self.mschain = MediaServerChain() if MediaServerChain else None
        except Exception as e:
            logger.warning(f"MediaServerChain 初始化失败: {e}")
            self.mschain = None

        try:
            self.mediaserver_helper = MediaServerHelper() if MediaServerHelper else None
        except Exception as e:
            logger.warning(f"MediaServerHelper 初始化失败: {e}")
            self.mediaserver_helper = None
        data_path = self.get_data_path()
        (data_path / 'fonts').mkdir(parents=True, exist_ok=True)
        (data_path / 'input').mkdir(parents=True, exist_ok=True)
        self._covers_path = data_path / 'input'
        self._font_path = data_path / 'fonts'
        if config:
            self._enabled = config.get("enabled")
            self._update_now = config.get("update_now")
            self._transfer_monitor = config.get("transfer_monitor")
            self._cron = config.get("cron")
            self._delay = config.get("delay")
            self._selected_servers = config.get("selected_servers")
            self._include_libraries = config.get("include_libraries")
            self._sort_by = config.get("sort_by")
            self._covers_output = config.get("covers_output")
            self._covers_input = config.get("covers_input")
            # self._title_config = self.get_data('title_config')
            self._title_config = config.get("title_config")
            self._zh_font_url = config.get("zh_font_url")
            self._en_font_url = config.get("en_font_url")
            self._zh_font_path = config.get("zh_font_path")
            self._en_font_path = config.get("en_font_path")
            self._cover_style = config.get("cover_style", "static_1")

            # 样式命名升级兼容（仅对旧配置执行一次迁移）
            if not config.get("style_naming_v2"):
                if self._cover_style == 'single_1':
                    self._cover_style = 'static_1'
                elif self._cover_style == 'single_2':
                    self._cover_style = 'static_2'
                elif self._cover_style == 'multi_1':
                    self._cover_style = 'static_3'
            default_base, default_variant = self._resolve_cover_style_ui(self._cover_style)
            self._cover_style_base = config.get("cover_style_base", default_base)
            self._cover_style_variant = config.get("cover_style_variant", default_variant)
            self._cover_style = self._compose_cover_style(self._cover_style_base, self._cover_style_variant)
            self._multi_1_blur = config.get("multi_1_blur", True)
            self._zh_font_size = config.get("zh_font_size", 170)
            self._en_font_size = config.get("en_font_size", 75)
            try:
                self._blur_size = int(config.get("blur_size", 50))
            except (ValueError, TypeError):
                self._blur_size = 50
            try:
                self._color_ratio = float(config.get("color_ratio", 0.8))
            except (ValueError, TypeError):
                self._color_ratio = 0.8
            self._use_primary = config.get("use_primary")
            self._zh_font_custom = config.get("zh_font_custom", "")
            self._en_font_custom = config.get("en_font_custom", "")
            self._zh_font_preset = config.get("zh_font_preset", "chaohei")
            self._en_font_preset = config.get("en_font_preset", "EmblemaOne")
            self._zh_font_offset = config.get("zh_font_offset")
            self._title_spacing = config.get("title_spacing")
            self._en_line_spacing = config.get("en_line_spacing")
            try:
                self._title_scale = float(config.get("title_scale", 1.0))
            except (ValueError, TypeError):
                self._title_scale = 1.0
            self._resolution = config.get("resolution", "480p")
            self._custom_width = config.get("custom_width", 1920)
            self._custom_height = config.get("custom_height", 1080)
            try:
                self._animation_duration = int(config.get("animation_duration", 12))
            except (ValueError, TypeError):
                self._animation_duration = 12
            self._animation_scroll = config.get("animation_scroll", "alternate")
            try:
                self._animation_fps = int(config.get("animation_fps", 12))
            except (ValueError, TypeError):
                self._animation_fps = 12
            self._animation_format = config.get("animation_format", "apng")
            if self._animation_format == "webp":
                self._animation_format = "gif"
            if self._animation_format not in ["apng", "gif"]:
                self._animation_format = "apng"
            self._animation_resolution = config.get("animation_resolution", "320x180")
            animation_reduce_colors = config.get("animation_reduce_colors", "medium")
            if isinstance(animation_reduce_colors, bool):
                self._animation_reduce_colors = "medium" if animation_reduce_colors else "off"
            elif animation_reduce_colors in ["off", "medium", "strong"]:
                self._animation_reduce_colors = animation_reduce_colors
            else:
                self._animation_reduce_colors = "medium"

            self._animated_2_image_count = config.get("animated_2_image_count", 6)
            self._animated_2_departure_type = config.get("animated_2_departure_type", "fly")
            self._clean_images = config.get("clean_images", False)
            self._clean_fonts = config.get("clean_fonts", False)
            self._save_recent_covers = config.get("save_recent_covers", True)
            self._covers_history_limit_per_library = self._clamp_value(
                config.get("covers_history_limit_per_library", 10),
                1,
                100,
                10,
                "covers_history_limit_per_library[init_plugin]",
                int,
            )
            self._covers_page_history_limit = self._clamp_value(
                config.get("covers_page_history_limit", 50),
                1,
                500,
                50,
                "covers_page_history_limit[init_plugin]",
                int,
            )
            self._page_tab = config.get("page_tab", "generate-tab")

            if self._resolution not in ["1080p", "720p", "480p"]:
                self._resolution = "480p"
            self._animation_resolution = "320x180"

        self._animated_2_image_count = self._clamp_value(
            self._animated_2_image_count,
            3,
            9,
            5,
            "animated_2 image_count[init_plugin]",
            int,
        )
        if self._animated_2_departure_type not in ["fly", "fade", "crossfade"]:
            self._animated_2_departure_type = "fly"
        if self._animation_scroll not in ["down", "up", "alternate", "alternate_reverse"]:
            self._animation_scroll = "alternate"
        self._bg_color_mode = (config or {}).get("bg_color_mode", "auto")
        self._custom_bg_color = (config or {}).get("custom_bg_color", "")

        # 初始化分辨率配置（确保安全初始化）
        try:
            self._resolution_config = ResolutionConfig(self._resolution)
        except Exception as e:
            logger.warning(f"分辨率配置初始化失败，使用默认配置: {e}")
            self._resolution_config = ResolutionConfig("480p")

        if self._selected_servers and self.mediaserver_helper:
            try:
                self._servers = self.mediaserver_helper.get_services(
                    name_filters=self._selected_servers
                )
                self._all_libraries = []
                for server, service in (self._servers or {}).items():
                    if not service.instance.is_inactive():
                        self._all_libraries.extend(self._get_all_libraries(server, service))
                    else:
                        logger.info(f"媒体服务器 {server} 未连接")
            except Exception as e:
                logger.warning(f"获取媒体服务器服务失败: {e}")
                self._servers = {}
                self._all_libraries = []
        else:
            if not self._selected_servers:
                logger.info("未选择媒体服务器")
            elif not self.mediaserver_helper:
                logger.warning("MediaServerHelper 不可用，无法获取媒体服务器")
        
        # 停止现有任务
        self.stop_service()

        cleanup_triggered = False
        if self._clean_images:
            self._clean_generated_images()
            self._clean_images = False
            cleanup_triggered = True
        if self._clean_fonts:
            self._clean_downloaded_fonts()
            self._clean_fonts = False
            cleanup_triggered = True
        if cleanup_triggered:
            self._update_config()

        if self._update_now:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(func=self._update_all_libraries, trigger='date',
                                    run_date=datetime.datetime.now(
                                        tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                                    )
            logger.info(f"媒体库封面更新服务启动，立即运行一次")
            # 关闭一次性开关
            self._update_now = False
            # 保存配置
            self._update_config()
            # 启动服务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def _clamp_value(self, value, minimum, maximum, default_value, name, cast_type):
        try:
            parsed = cast_type(value)
        except (ValueError, TypeError):
            logger.warning(f"{name} 配置值非法 ({value})，已回退默认值 {default_value}")
            return default_value

        if parsed < minimum or parsed > maximum:
            clamped = max(minimum, min(maximum, parsed))
            logger.warning(f"{name} 配置值超出范围 ({parsed})，已限制为 {clamped}")
            return clamped

        return parsed

    def _get_animated_2_required_items(self) -> int:
        self._animated_2_image_count = self._clamp_value(
            self._animated_2_image_count,
            3,
            9,
            5,
            "animated_2 image_count[runtime]",
            int,
        )
        return int(self._animated_2_image_count)

    def _compose_cover_style(self, base_style: str, variant: str) -> str:
        base = base_style if base_style in ["static_1", "static_2", "static_3", "static_4"] else "static_1"
        mode = variant if variant in ["static", "animated"] else "static"
        suffix = base.split("_")[-1]
        return base if mode == "static" else f"animated_{suffix}"

    def _resolve_cover_style_ui(self, cover_style: str) -> Tuple[str, str]:
        if cover_style in ["animated_1", "animated_2", "animated_3", "animated_4"]:
            suffix = cover_style.split("_")[-1]
            if suffix == "4":
                return "static_4", "animated"
            return f"static_{suffix}", "animated"
        if cover_style in ["static_1", "static_2", "static_3", "static_4"]:
            return cover_style, "static"
        return "static_1", "static"

    def _is_single_image_style(self) -> bool:
        return self._cover_style in ["static_1", "static_2", "static_4"]

    def _get_required_items(self) -> int:
        if self._cover_style in ["static_3", "animated_3"]:
            return 9
        if self._cover_style in ["animated_1", "animated_2", "animated_4"]:
            return self._get_animated_2_required_items()
        return 1

    def _update_config(self):
        """
        更新配置
        """
        self._cover_style = self._compose_cover_style(self._cover_style_base, self._cover_style_variant)
        self._animated_2_image_count = self._clamp_value(
            self._animated_2_image_count,
            3,
            9,
            5,
            "animated_2 image_count[save]",
            int,
        )
        self.update_config({
            "enabled": self._enabled,
            "update_now": self._update_now,
            "transfer_monitor": self._transfer_monitor,
            "cron": self._cron,
            "delay": self._delay,
            "selected_servers": self._selected_servers,
            "include_libraries": self._include_libraries,
            "all_libraries": self._all_libraries,
            "sort_by": self._sort_by,
            "covers_output": self._covers_output,
            "covers_input": self._covers_input,
            "title_config": self._title_config,
            "zh_font_url": str(self._zh_font_url),
            "en_font_url": str(self._en_font_url),
            "zh_font_path": str(self._zh_font_path),
            "en_font_path": str(self._en_font_path),
            "cover_style": self._cover_style,
            "cover_style_base": self._cover_style_base,
            "cover_style_variant": self._cover_style_variant,
            "multi_1_blur": self._multi_1_blur,
            "zh_font_size": self._zh_font_size,
            "en_font_size": self._en_font_size,
            "blur_size": self._blur_size,
            "color_ratio": self._color_ratio,
            "use_primary": self._use_primary,
            "zh_font_custom": self._zh_font_custom,
            "en_font_custom": self._en_font_custom,
            "zh_font_preset": self._zh_font_preset,
            "en_font_preset": self._en_font_preset,
            "zh_font_offset": self._zh_font_offset,
            "title_spacing": self._title_spacing,
            "en_line_spacing": self._en_line_spacing,
            "title_scale": self._title_scale,
            "resolution": self._resolution,
            "custom_width": self._custom_width,
            "custom_height": self._custom_height,
            "animation_duration": self._animation_duration,
            "animation_scroll": self._animation_scroll,
            "animation_fps": self._animation_fps,
            "animation_format": self._animation_format,
            "animation_resolution": self._animation_resolution,
            "animation_reduce_colors": self._animation_reduce_colors,
            "animated_2_image_count": self._animated_2_image_count,
            "animated_2_departure_type": self._animated_2_departure_type,
            "bg_color_mode": self._bg_color_mode,
            "custom_bg_color": self._custom_bg_color,
            "clean_images": self._clean_images,
            "clean_fonts": self._clean_fonts,
            "save_recent_covers": self._save_recent_covers,
            "covers_history_limit_per_library": self._covers_history_limit_per_library,
            "covers_page_history_limit": self._covers_page_history_limit,
            "page_tab": self._page_tab,
            "style_naming_v2": True,
        })

    def get_state(self) -> bool:
        return self._enabled

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        """
        return ApiManagerMixin.get_api(self)






    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/update_covers",
                "event": EventType.PluginAction,
                "desc": "更新媒体库封面",
                "category": "",
                "data": {"action": "update_covers"},
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        """
        services = []
        if self._enabled and self._cron:
            services.append({
                "id": "MediaCoverGenerator",
                "name": "媒体库封面更新服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self._update_all_libraries,
                "kwargs": {}
            })
        
        # 总是显示停止按钮，以便中断长时间运行的任务
        services.append({
            "id": "StopMediaCoverGenerator",
            "name": "停止当前更新任务",
            "trigger": None,
            "func": self.stop_task,
            "kwargs": {}
        })
        return services

    def stop_task(self):
        """
        手动停止当前正在执行的任务
        """
        if not self._event.is_set():
            logger.info("正在发送停止任务信号...")
            self._event.set()
            return True, "已发送停止停止信号，请等待当前操作清理完成"
        return True, "任务已处于停止状态或正在停止中"

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面
        """
        # 每次用户打开插件设置页面时，强制重置回封面生成页签，满足不记忆页签的需求
        self._page_tab = "generate-tab"
        
        zh_font_items, en_font_items, _, _ = self._get_font_presets()

        server_items = []
        if self.mediaserver_helper:
            try:
                configs = self.mediaserver_helper.get_configs() or {}
                server_items = [
                    {"title": config.name, "value": config.name}
                    for config in configs.values()
                    if getattr(config, "type", None) in ("emby", "jellyfin")
                ]
            except Exception as e:
                logger.warning(f"获取媒体服务器列表失败: {e}")
        # 标题配置
        title_tab = [
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                        },
                        'content': [
                            {
                                'component': 'VAceEditor',
                                'props': {
                                    'modelvalue': 'title_config',
                                    'lang': 'yaml',
                                    'theme': 'monokai',
                                    'style': 'height: 30rem',
                                    'label': '中英标题配置',
                                    'placeholder': '''媒体库名称:
- 主标题
- 副标题
- "#FF5722"  # 可选：背景颜色（必须加引号）'''
                                 }
                             }
                         ]
                     },
                ]
            },
        ]

        # 其他设置标签
        others_tab = [
            
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                        },
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'text': '自定义图片目录：请将图片存于与媒体库同名的子目录下，例如：/mnt/custom_images/华语电影/1.jpg，填写 /mnt/custom_images 即可。多图模式下，文件名须为 1.jpg, 2.jpg, ...9.jpg，不满足的会被重命名，不够的会随机复制填满9张'
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 4
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'covers_input',
                                    'label': '自定义图片目录（可选）',
                                    'prependInnerIcon': 'mdi-file-image',
                                    'hint': '使用你指定的图片生成封面，图片放在与媒体库同名的文件夹下',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },

                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 4
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'covers_output',
                                    'label': '历史封面保存目录（可选）',
                                    'prependInnerIcon': 'mdi-file-image',
                                    'hint': '生成的封面默认保存在本插件数据目录下',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                                        {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 4
                        },
                        'content': [
                            {
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'save_recent_covers',
                                    'label': '保存最近生成的封面',
                                    'hint': '默认开启，保存历史封面',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 4
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'covers_history_limit_per_library',
                                    'label': '媒体库历史封面数量',
                                    'prependInnerIcon': 'mdi-history',
                                    'hint': '单个媒体库封面保留上限，默认 10',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 4
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'covers_page_history_limit',
                                    'label': '历史封面显示数量',
                                    'prependInnerIcon': 'mdi-image-multiple-outline',
                                    'hint': '历史封面「显示数量」，默认 50',
                                    'persistentHint': True
                                },
                            }
                        ]
                    }
                ]
            },
            
        ]
        # 更多参数标签
        single_tab = [
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                        },
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'text': '字体设置为可选项。若字体无法下载，可以手动下载并填写本地路径。主标题和副标题可以使用不同的字体。'
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VSelect',
                                'props': {
                                    'chips': False,
                                    'multiple': False,
                                    'model': 'zh_font_preset',
                                    'label': '主标题字体预设',
                                    'prependInnerIcon': 'mdi-ideogram-cjk',
                                    'items': zh_font_items
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VSelect',
                                'props': {
                                    'chips': False,
                                    'multiple': False,
                                    'model': 'en_font_preset',
                                    'label': '副标题字体预设',
                                    'prependInnerIcon': 'mdi-format-font',
                                    'items': en_font_items
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'zh_font_custom',
                                    'label': '自定义主标题字体',
                                    'prependInnerIcon': 'mdi-ideogram-cjk',
                                    'placeholder': '留空使用预设字体',
                                    'hint': '字体链接 / 路径',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'en_font_custom',
                                    'label': '自定义副标题字体',
                                    'prependInnerIcon': 'mdi-format-font',
                                    'placeholder': '留空使用预设字体',
                                    'hint': '字体链接 / 路径',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'zh_font_size',
                                    'label': '主标题字体大小',
                                    'prependInnerIcon': 'mdi-format-size',
                                    'placeholder': '留空使用预设尺寸',
                                    'hint': '根据自己喜好设置，默认 180',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'en_font_size',
                                    'label': '副标题字体大小',
                                    'prependInnerIcon': 'mdi-format-size',
                                    'placeholder': '留空使用预设尺寸',
                                    'hint': '根据自己喜好设置，默认 75',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'blur_size',
                                    'label': '背景模糊尺寸',
                                    'prependInnerIcon': 'mdi-blur',
                                    'placeholder': '留空使用预设尺寸',
                                    'hint': '数字越大越模糊，默认 50',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'color_ratio',
                                    'label': '背景颜色混合占比',
                                    'prependInnerIcon': 'mdi-format-color-fill',
                                    'placeholder': '留空使用预设占比',
                                    'hint': '颜色所占的比例，0-1，默认 0.8',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'title_scale',
                                    'label': '标题整体缩放',
                                    'prependInnerIcon': 'mdi-arrow-expand-all',
                                    'placeholder': '留空使用预设比例',
                                    'hint': '以 1080p 为基准，1.0 为默认',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 4
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'zh_font_offset',
                                    'label': '主标题偏移量',
                                    'prependInnerIcon': 'mdi-arrow-up-down',
                                    'placeholder': '留空使用预设尺寸',
                                    'hint': '上移为负值，下移为正值',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 4
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'title_spacing',
                                    'label': '主副标题间距',
                                    'prependInnerIcon': 'mdi-arrow-up-down',
                                    'placeholder': '留空使用预设尺寸',
                                    'hint': '大于 0，默认 40',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 4
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'en_line_spacing',
                                    'label': '副标题行间距',
                                    'prependInnerIcon': 'mdi-format-line-height',
                                    'placeholder': '留空使用预设尺寸',
                                    'hint': '大于 0，默认 40',
                                    'persistentHint': True
                                }
                            }
                        ]
                    },
                ]
            },
        ]

        more_tab = single_tab + others_tab

        styles = [
            {
                "value": "static_1",
                "src": self._style_preview_src(1)
            },
            {
                "value": "static_2",
                "src": self._style_preview_src(2)
            },
            {
                "value": "static_3",
                "src": self._style_preview_src(3)
            },
            {
                "value": "static_4",
                "src": self._style_preview_src(4)
            }
        ]

        style_variant_items = [
            {
                'component': 'VBtn',
                'props': {
                    'value': 'static',
                    'variant': 'outlined',
                    'color': 'primary',
                    'prependIcon': 'mdi-image-outline',
                    'class': 'text-none',
                },
                'text': '静态'
            },
            {
                'component': 'VBtn',
                'props': {
                    'value': 'animated',
                    'variant': 'outlined',
                    'color': 'primary',
                    'prependIcon': 'mdi-play-box-multiple-outline',
                    'class': 'text-none',
                },
                'text': '动态'
            }
        ]

        preview_style_content = []

        for style in styles:
            preview_style_content.append(
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'md': 3,
                    },
                    'content': [
                        {
                            'component': 'VLabel',
                            'props': {
                                'class': 'd-block w-100 cursor-pointer'
                            },
                            'content': [
                                {
                                    'component': 'VCard',
                                    'props': {
                                        'variant': 'flat',
                                        'class': 'transition-swing rounded-lg overflow-hidden',
                                        'style': f'position: relative; background-image: linear-gradient(rgba(80,80,80,0.25), rgba(80,80,80,0.25)), url({style.get("src")}); background-size: cover; background-position: center; background-repeat: no-repeat;'
                                    },
                                    'content': [
                                        {
                                            'component': 'VImg',
                                            'props': {
                                                'src': style.get('src'),
                                                'aspect-ratio': '16/9',
                                                'cover': True,
                                            }
                                        },
                                        {
                                            'component': 'VRadio',
                                            'props': {
                                                'value': style.get('value'),
                                                'color': '#FFFFFF',
                                                'baseColor': '#FFFFFF',
                                                'density': 'default',
                                                'hideDetails': True,
                                                'class': 'position-absolute',
                                                'style': 'top: 8px; right: 8px; z-index: 2; margin: 0; transform: scale(1.2); transform-origin: top right;'
                                            }
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            )

        # 封面风格设置标签
        style_tab = [
            {
                'component': 'VAlert',
                'props': {
                    'type': 'info',
                    'variant': 'tonal',
                    'text': '先选基础样式，再选静态或动态。点击整张预览图即可切换。',
                    'class': 'mb-3'
                }
            },
            {
                'component': 'VRadioGroup',
                'props': {
                    'model': 'cover_style_base',
                },
                'content': [
                    {
                        'component': 'VRow',
                        'content': preview_style_content
                    }
                ]
            },
            {
                'component': 'VBtnToggle',
                'props': {
                    'model': 'cover_style_variant',
                    'mandatory': True,
                    'class': 'mt-3',
                    'divided': True
                },
                'content': style_variant_items
            },
            {
                'component': 'VExpansionPanels',
                'props': {
                    'multiple': True,
                    'class': 'mt-3'
                },
                'content': [
                    {
                        'component': 'VExpansionPanel',
                        'props': {
                            'elevation': 0,
                            'class': 'rounded-lg',
                            'style': 'background-color: rgba(var(--v-theme-surface), 0.38); border: 1px solid rgba(var(--v-border-color), 0.35); backdrop-filter: blur(6px);'
                        },
                        'content': [
                            {
                                'component': 'VExpansionPanelTitle',
                                'props': {
                                    'class': 'font-weight-medium'
                                },
                                'text': '基本参数'
                            },
                            {
                                'component': 'VExpansionPanelText',
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 4},
                                                'content': [
                                                    {
                                                        'component': 'VBtnToggle',
                                                        'props': {
                                                            'model': 'use_primary',
                                                            'mandatory': True,
                                                            'divided': True,
                                                            'class': 'w-100'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VBtn',
                                                                'props': {
                                                                    'value': True,
                                                                    'variant': 'outlined',
                                                                    'color': 'primary',
                                                                    'class': 'text-none'
                                                                },
                                                                'text': '海报图'
                                                            },
                                                            {
                                                                'component': 'VBtn',
                                                                'props': {
                                                                    'value': False,
                                                                    'variant': 'outlined',
                                                                    'color': 'primary',
                                                                    'class': 'text-none'
                                                                },
                                                                'text': '背景图'
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        'component': 'VLabel',
                                                        'props': {
                                                            'class': 'text-caption text-medium-emphasis mt-1 d-inline-block'
                                                        }
                                                        ,
                                                        'text': '选图优先来源'
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 4},
                                                'content': [
                                                    {
                                                        'component': 'VBtnToggle',
                                                        'props': {
                                                            'model': 'multi_1_blur',
                                                            'mandatory': True,
                                                            'divided': True,
                                                            'class': 'w-100'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VBtn',
                                                                'props': {
                                                                    'value': True,
                                                                    'variant': 'outlined',
                                                                    'color': 'primary',
                                                                    'class': 'text-none'
                                                                },
                                                                'text': '模糊背景'
                                                            },
                                                            {
                                                                'component': 'VBtn',
                                                                'props': {
                                                                    'value': False,
                                                                    'variant': 'outlined',
                                                                    'color': 'primary',
                                                                    'class': 'text-none'
                                                                },
                                                                'text': '纯色渐变'
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        'component': 'VLabel',
                                                        'props': {
                                                            'class': 'text-caption text-medium-emphasis mt-1 d-inline-block'
                                                        }
                                                        ,
                                                        'text': '针对九宫格海报'
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 4},
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'chips': False,
                                                            'multiple': False,
                                                            'model': 'resolution',
                                                            'label': '静态分辨率',
                                                            'prependInnerIcon': 'mdi-monitor-screenshot',
                                                            'items': [
                                                                {'title': '1080p (1920x1080)', 'value': '1080p'},
                                                                {'title': '720p (1280x720)', 'value': '720p'},
                                                                {'title': '480p (854x480)', 'value': '480p'}
                                                            ],
                                                            'hint': '动态分辨率默认320*180',
                                                            'persistentHint': True
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VExpansionPanels',
                                        'props': {
                                            'multiple': True,
                                            'class': 'mt-2'
                                        },
                                        'content': [
                                            {
                                                'component': 'VExpansionPanel',
                                                'props': {
                                                    'elevation': 0,
                                                    'class': 'rounded-lg',
                                                    'style': 'background-color: rgba(255,255,255,0.55); border: 1px dashed rgba(0,0,0,0.18);'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VExpansionPanelTitle',
                                                        'text': '背景颜色设置（全部风格生效）'
                                                    },
                                                    {
                                                        'component': 'VExpansionPanelText',
                                                        'content': [
                                                            {
                                                                'component': 'VRow',
                                                                'content': [
                                                                    {
                                                                        'component': 'VCol',
                                                                        'props': {'cols': 12, 'md': 4},
                                                                        'content': [
                                                                            {
                                                                                'component': 'VSelect',
                                                                                'props': {
                                                                                    'model': 'bg_color_mode',
                                                                                    'label': '背景颜色来源',
                                                                                    'prependInnerIcon': 'mdi-palette',
                                                                                    'items': [
                                                                                        {'title': '自动从图片提取', 'value': 'auto'},
                                                                                        {'title': '自定义（全局统一）', 'value': 'custom'},
                                                                                        {'title': '从配置获取', 'value': 'config'}
                                                                                    ]
                                                                                }
                                                                            }
                                                                        ]
                                                                    },
                                                                    {
                                                                        'component': 'VCol',
                                                                        'props': {'cols': 12, 'md': 8},
                                                                        'content': [
                                                                            {
                                                                                'component': 'VTextField',
                                                                                'props': {
                                                                                    'model': 'custom_bg_color',
                                                                                    'label': '自定义背景色',
                                                                                    'prependInnerIcon': 'mdi-eyedropper',
                                                                                    'placeholder': '#FF5722',
                                                                                    'hint': '支持 #十六进制、rgb(...)、颜色英文名',
                                                                                    'persistentHint': True
                                                                                }
                                                                            },
                                                                            {
                                                                                'component': 'VColorPicker',
                                                                                'props': {
                                                                                    'model': 'custom_bg_color',
                                                                                    'mode': 'hexa',
                                                                                    'showSwatches': True,
                                                                                    'hideCanvas': False,
                                                                                    'hideInputs': True,
                                                                                    'elevation': 0,
                                                                                    'class': 'mt-2'
                                                                                }
                                                                            }
                                                                        ]
                                                                    }
                                                                ]
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VExpansionPanel',
                        'props': {
                            'elevation': 0,
                            'class': 'rounded-lg',
                            'style': 'background-color: rgba(var(--v-theme-surface), 0.32); border: 1px solid rgba(var(--v-border-color), 0.32); backdrop-filter: blur(6px);'
                        },
                        'content': [
                            {
                                'component': 'VExpansionPanelTitle',
                                'props': {
                                    'class': 'font-weight-medium'
                                },
                                'text': '动态图参数'
                            },
                            {
                                'component': 'VExpansionPanelText',
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {'class': 'mt-1'},
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 3},
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'animation_duration',
                                                            'label': '动画循环周期 (秒)',
                                                            'type': 'number',
                                                            'prependInnerIcon': 'mdi-clock-outline'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 3},
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'animation_fps',
                                                            'label': '帧率 (FPS)',
                                                            'type': 'number',
                                                            'prependInnerIcon': 'mdi-speedometer'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 3},
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'animation_format',
                                                            'label': '输出格式',
                                                            'items': [
                                                                {'title': 'APNG', 'value': 'apng'},
                                                                {'title': 'GIF', 'value': 'gif'}
                                                            ],
                                                            'prependInnerIcon': 'mdi-file-video'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 3},
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'animation_reduce_colors',
                                                            'label': '颜色压缩等级',
                                                            'items': [
                                                                {'title': '关闭（保真优先）', 'value': 'off'},
                                                                {'title': '中等压缩', 'value': 'medium'},
                                                                {'title': '强压缩（体积最小）', 'value': 'strong'}
                                                            ],
                                                            'prependInnerIcon': 'mdi-palette-outline'
                                                        }
                                                    }
                                                ]
                                            },
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'props': {'class': 'mt-2'},
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 4},
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'animated_2_image_count',
                                                            'label': '样式1/2 图片数量 (3~9)',
                                                            'type': 'number',
                                                            'min': 3,
                                                            'max': 9,
                                                            'hint': '仅样式1/2有效',
                                                            'persistentHint': True,
                                                            'prependInnerIcon': 'mdi-image-multiple'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 4},
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'animated_2_departure_type',
                                                            'label': '样式1动画风格',
                                                            'hint': '仅样式1有效',
                                                            'persistentHint': True,
                                                            'items': [
                                                                {'title': '旋转-飞出', 'value': 'fly'},
                                                                {'title': '旋转-渐隐', 'value': 'fade'},
                                                                {'title': '渐变', 'value': 'crossfade'}
                                                            ],
                                                            'prependInnerIcon': 'mdi-transition'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 4},
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'animation_scroll',
                                                            'label': '样式3滚动方向',
                                                            'hint': '仅样式3有效',
                                                            'persistentHint': True,
                                                            'items': [
                                                                {'title': '向下', 'value': 'down'},
                                                                {'title': '向上', 'value': 'up'},
                                                                {'title': '交替 (两边下/中间上)', 'value': 'alternate'},
                                                                {'title': '交替反向 (两边上/中间下)', 'value': 'alternate_reverse'}
                                                            ],
                                                            'prependInnerIcon': 'mdi-swap-vertical'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
 
                                ]
                            }
                        ]
                    }
                ]
            }
        ]


        return [
            {
                "component": "VCard",
                "props": {"variant": "outlined", "class": "transition-swing rounded-lg mb-3"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "props": {"class": "d-flex align-center"},
                        "content": [
                            {
                                "component": "VIcon",
                                "props": {
                                    "icon": "mdi-cog",
                                    "color": "primary",
                                    "class": "mr-2",
                                },
                            },
                            {"component": "span", "text": "基础设置"},
                        ],
                    },
                    {"component": "VDivider"},
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                'component': 'VForm',
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'enabled',
                                                            'label': '启用插件',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'update_now',
                                                            'label': '立即更新封面',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'transfer_monitor',
                                                            'label': '入库监控',
                                                            'hint': '自动更新入库媒体所在媒体库封面',
                                                            'persistentHint': True
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'delay',
                                                            'label': '入库延迟（秒）',
                                                            'placeholder': '60',
                                                            'hint': '根据实际情况调整延迟时间',
                                                            'persistentHint': True
                                                        }
                                                    }
                                                ]
                                            },
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 6
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'multiple': True,
                                                            'chips': True,
                                                            'clearable': True,
                                                            'model': 'selected_servers',
                                                            'label': '媒体服务器',
                                                            'items': server_items
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'chips': False,
                                                            'multiple': False,
                                                            'model': 'sort_by',
                                                            'label': '封面来源排序，默认随机',
                                                            'items': [
                                                                {"title": "随机", "value": "Random"},
                                                                {"title": "最新入库", "value": "DateCreated"},
                                                                {"title": "最新发行", "value": "PremiereDate"}
                                                                ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VCronField',
                                                        'props': {
                                                            'model': 'cron',
                                                            'label': '定时更新封面',
                                                            'placeholder': '5位cron表达式'
                                                        }
                                                    }
                                                ]
                                            },
                                            
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'multiple': True,
                                                            'chips': True,
                                                            'clearable': True,
                                                            'model': 'include_libraries',
                                                            'label': '更新媒体库',
                                                            'items': [
                                                                {"title": config['name'], "value": config['value']}
                                                                    for config in self._all_libraries
                                                            ],
                                                            'hint': '默认更新全部，或只更新勾选的媒体库',
                                                            'persistentHint': True
                                                        }
                                                    }
                                                ]
                                            },
                                        ]
                                    }
                                    
                                ]
                            },
                        ]
                    }
                ]
            },
            {
                "component": "VCard",
                "props": {"variant": "outlined", "class": "transition-swing rounded-lg"},
                "content": [
                    {
                        "component": "VTabs",
                        "props": {"model": "tab", "grow": True, "color": "primary"},
                        "content": [
                            {
                                "component": "VTab",
                                "props": {"value": "style-tab"},
                                "content": [
                                    {
                                        "component": "VIcon",
                                        "props": {
                                            "icon": "mdi-palette-swatch",
                                            "start": True,
                                            "color": "#cc76d1",
                                        },
                                    },
                                    {"component": "span", "text": "封面风格"},
                                ],
                            },
                            {
                                "component": "VTab",
                                "props": {"value": "title-tab"},
                                "content": [
                                    {
                                        "component": "VIcon",
                                        "props": {
                                            "icon": "mdi-text-box-edit",
                                            "start": True,
                                            "color": "#1976D2",
                                        },
                                    },
                                    {"component": "span", "text": "封面标题"},
                                ],
                            },
                            {
                                "component": "VTab",
                                "props": {"value": "more-tab"},
                                "content": [
                                    {
                                        "component": "VIcon",
                                        "props": {
                                            "icon": "mdi-palette-swatch-variant",
                                            "start": True,
                                            "color": "#f3afe4",
                                        },
                                    },
                                    {"component": "span", "text": "更多参数"},
                                ],
                            },
                        ],
                    },
                    {"component": "VDivider"},
                    {
                        "component": "VWindow",
                        "props": {"model": "tab"},
                        "content": [
                            {
                                "component": "VWindowItem",
                                "props": {"value": "style-tab"},
                                "content": [
                                    {"component": "VCardText", "content": style_tab}
                                ],
                            },
                            {
                                "component": "VWindowItem",
                                "props": {"value": "title-tab"},
                                "content": [
                                    {
                                        "component": "VCardText",
                                        "content": title_tab,
                                    }
                                ],
                            },
                            {
                                "component": "VWindowItem",
                                "props": {"value": "more-tab"},
                                "content": [
                                    {"component": "VCardText", "content": more_tab}
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": True,
            "update_now": False,
            "transfer_monitor": True,
            "cron": "",
            "delay": 60,
            "selected_servers": [],
            "include_libraries": [],
            "sort_by": "Random",
            "title_config": '''# 配置封面标题（按媒体库名称对应）
# 支持两种格式：
#
# 格式1 - 两行配置（主标题+副标题）：
# 媒体库名称:
#   - 主标题
#   - 副标题
#
# 格式2 - 三行配置（主标题+副标题+背景颜色）：
# 媒体库名称:
#   - 主标题
#   - 副标题
#   - "#FF5722"  # 背景颜色（可选，必须加引号）
#
''',
            "tab": "style-tab",
            "cover_style": "static_1",
            "cover_style_base": "static_1",
            "cover_style_variant": "static",
            "multi_1_blur": True,
            "zh_font_preset": "chaohei",
            "en_font_preset": "EmblemaOne",
            "zh_font_custom": "",
            "en_font_custom": "",
            "zh_font_size": None,
            "en_font_size": None,
            "blur_size": 50,
            "color_ratio": 0.8,
            "title_scale": 1.0,
            "use_primary": False,
            "resolution": "480p",
            "custom_width": 1920,
            "custom_height": 1080,
            "bg_color_mode": "auto",
            "custom_bg_color": "",
            "animation_duration": 8,
            "animation_scroll": "alternate",
            "animation_fps": 24,
            "animation_format": "apng",
            "animation_resolution": "320x180",
            "animation_reduce_colors": "medium",
            "animated_2_image_count": 6,
            "animated_2_departure_type": "fly",
            "clean_images": False,
            "clean_fonts": False,
            "save_recent_covers": True,
            "covers_history_limit_per_library": 10,
            "covers_page_history_limit": 50,
            "page_tab": "generate-tab",
            "style_naming_v2": True,
        }

    def get_page(self) -> List[dict]:
        limit = self._clamp_value(
            self._covers_page_history_limit,
            1,
            500,
            50,
            "covers_page_history_limit[get_page]",
            int,
        )
        style_variant, style_index = self._get_cover_style_parts()
        style_preview_cards = self._build_page_style_cards(style_variant=style_variant, selected_index=style_index)
        setup_warnings: List[str] = []
        if not self._enabled:
            setup_warnings.append("插件未启用，请先在设置页启用插件并保存。")
        if not self._selected_servers:
            setup_warnings.append("未勾选媒体服务器，请先在设置页勾选服务器并保存。")
        elif not self._servers:
            setup_warnings.append("服务器配置尚未生效，请在设置页保存后重试。")

        # 历史封面
        cover_rows = []
        recent_covers = self._get_recent_generated_covers(limit=limit)
        if recent_covers:
            for item in recent_covers:
                delete_api = f"plugin/MediaCoverGenerator/delete_saved_cover?file={quote(item['path'])}&apikey={settings.API_TOKEN}"
                cover_rows.append(
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "sm": 6, "md": 3},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {
                                    "variant": "flat",
                                    "elevation": 2,
                                    "class": "transition-swing rounded-lg",
                                },
                                "content": [
                                    {
                                        "component": "VImg",
                                        "props": {
                                            "src": item["src"],
                                            "aspect-ratio": "16/9",
                                            "cover": True,
                                        },
                                    },
                                    {
                                        "component": "VCardText",
                                        "props": {"class": "py-2"},
                                        "content": [
                                            {
                                                "component": "VRow",
                                                "props": {"class": "align-center", "noGutters": True},
                                                "content": [
                                                    {
                                                        "component": "VCol",
                                                        "props": {"cols": 9},
                                                        "content": [
                                                            {
                                                                "component": "div",
                                                                "props": {
                                                                    "class": "text-body-2",
                                                                    "style": "display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.2rem; min-height: 2.4rem;"
                                                                },
                                                                "text": item["name"],
                                                            },
                                                            {
                                                                "component": "div",
                                                                "props": {"class": "text-caption text-medium-emphasis mt-1"},
                                                                "text": item["size"],
                                                            },
                                                        ],
                                                    },
                                                    {
                                                        "component": "VCol",
                                                        "props": {"cols": 3, "class": "text-right"},
                                                        "content": [
                                                            {
                                                                "component": "VBtn",
                                                                "props": {
                                                                    "color": "error",
                                                                    "variant": "text",
                                                                    "size": "small",
                                                                    "title": "删除",
                                                                    "class": "text-none",
                                                                },
                                                                "text": "删除",
                                                                "events": {
                                                                    "click": {
                                                                        "api": delete_api,
                                                                        "method": "post",
                                                                        "params": {"apikey": settings.API_TOKEN},
                                                                    }
                                                                },
                                                            }
                                                        ],
                                                    },
                                                ],
                                            }
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                )
        else:
            cover_rows.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "density": "compact",
                    },
                    "text": "暂无生成的历史封面文件。点击上方“立即生成当前风格”可自动生成。",
                }
            )

        cards = []
        
        # 1. 封面生成与风格配置卡片
        generate_card_content = []
        if setup_warnings:
            generate_card_content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "warning",
                        "variant": "tonal",
                        "density": "compact",
                        "class": "mb-3",
                    },
                    "text": "首次运行请先完成设置",
                }
            )
            generate_card_content.append(
                {
                    "component": "div",
                    "props": {"class": "text-caption text-medium-emphasis mb-2"},
                    "text": "；".join(setup_warnings),
                }
            )

        generate_card_content.append(
            {
                "component": "VRow",
                "props": {"class": "mb-2"},
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "variant": "flat",
                                    "color": "primary",
                                    "class": "text-none mr-2 mb-2",
                                    "prepend-icon": "mdi-swap-horizontal",
                                },
                                "text": f"切换到{'动态' if style_variant == 'static' else '静态'}",
                                "events": {"click": {"api": f"plugin/MediaCoverGenerator/toggle_style_variant?apikey={settings.API_TOKEN}", "method": "get"}},
                            },
                            {
                                "component": "VBtn",
                                "props": {
                                    "variant": "flat",
                                    "color": "primary",
                                    "class": "text-none mb-2 mr-2",
                                    "prepend-icon": "mdi-play-circle-outline",
                                },
                                "text": "立即生成当前风格",
                                "events": {"click": {"api": f"plugin/MediaCoverGenerator/generate_now?apikey={settings.API_TOKEN}", "method": "get"}},
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-caption text-medium-emphasis ml-2 mb-2 d-inline-block"},
                                "text": "更多参数请点击右下角齿轮设置",
                            },
                        ],
                    }
                ],
            }
        )
        generate_card_content.append(
            {
                "component": "VRow",
                "content": style_preview_cards,
            }
        )

        cards.append(
            {
                "component": "VCard",
                "props": {"variant": "outlined", "class": "transition-swing rounded-lg mb-4"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "props": {"class": "text-subtitle-1 font-weight-bold"},
                        "text": "🎨 封面风格选择与生成",
                    },
                    {"component": "VDivider"},
                    {
                        "component": "VCardText",
                        "content": generate_card_content,
                    },
                ],
            }
        )

        # 2. 历史封面卡片
        cards.append(
            {
                "component": "VCard",
                "props": {"variant": "outlined", "class": "transition-swing rounded-lg mb-4"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "props": {"class": "text-subtitle-1 font-weight-bold"},
                        "text": f"🖼️ 历史封面预览（最多显示 {limit} 条）",
                    },
                    {"component": "VDivider"},
                    {
                        "component": "VCardText",
                        "content": [{"component": "VRow", "content": cover_rows}],
                    },
                ],
            }
        )

        # 3. 维护与清理工具卡片
        cards.append(
            {
                "component": "VCard",
                "props": {"variant": "outlined", "class": "transition-swing rounded-lg mb-4"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "props": {"class": "text-subtitle-1 font-weight-bold"},
                        "text": "🧹 缓存维护工具",
                    },
                    {"component": "VDivider"},
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-4 d-flex align-center flex-wrap"},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "error",
                                    "variant": "flat",
                                    "prepend-icon": "mdi-image-remove",
                                    "class": "mr-3 mb-2 text-none",
                                },
                                "text": "立即清理图片缓存",
                                "events": {"click": {"api": f"plugin/MediaCoverGenerator/clean_images?apikey={settings.API_TOKEN}", "method": "get"}},
                            },
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "error",
                                    "variant": "flat",
                                    "prepend-icon": "mdi-format-font",
                                    "class": "mr-3 mb-2 text-none",
                                },
                                "text": "立即清理字体缓存",
                                "events": {"click": {"api": f"plugin/MediaCoverGenerator/clean_fonts?apikey={settings.API_TOKEN}", "method": "get"}},
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-caption text-medium-emphasis mb-2"},
                                "text": "点击后立即清理本地临时缓存，无需重启或重新保存设置。",
                            },
                        ],
                    },
                ],
            }
        )

        return cards
    def _build_page_style_cards(self, style_variant: str, selected_index: int) -> List[Dict[str, Any]]:
        styles = [
            {"name": "风格1", "index": 1, "src": self._style_preview_src(1)},
            {"name": "风格2", "index": 2, "src": self._style_preview_src(2)},
            {"name": "风格3", "index": 3, "src": self._style_preview_src(3)},
            {"name": "风格4", "index": 4, "src": self._style_preview_src(4)},
        ]
        cards: List[Dict[str, Any]] = []
        for style in styles:
            cards.append(
                {
                    "component": "VCol",
                    "props": {"cols": 12, "sm": 6, "md": 3},
                    "content": [
                        {
                            "component": "VCard",
                            "props": {
                                "variant": "flat",
                                "elevation": 3 if style["index"] == selected_index else 1,
                                "color": "primary" if style["index"] == selected_index else None,
                                "class": "cursor-pointer transition-swing rounded-lg",
                            },
                            "events": {
                                "click": {
                                    "api": f"plugin/MediaCoverGenerator/select_style_{style['index']}?apikey={settings.API_TOKEN}",
                                    "method": "get",
                                }
                            },
                            "content": [
                                {
                                    "component": "VImg",
                                    "props": {
                                        "src": style["src"],
                                        "aspect-ratio": "16/9",
                                        "cover": True,
                                    },
                                },
                                {
                                    "component": "VCardText",
                                    "props": {"class": "py-2 text-center"},
                                    "text": f"{style['name']}（{'静态' if style_variant == 'static' else '动态'}{style['index']}）" if style["index"] == selected_index else style["name"],
                                },
                            ],
                        }
                    ],
                }
            )
        return cards

    @staticmethod
    def _style_preview_src(index: int) -> str:
        safe_index = max(1, min(4, int(index)))
        return f"https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/images/style_{safe_index}.jpeg"






    @eventmanager.register(EventType.PluginAction)
    def update_covers(self, event: Event):
        """
        远程全量同步
        """
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "update_covers":
                return
            self.post_message(
                channel=event.event_data.get("channel"),
                title="开始更新媒体库封面 ...",
                userid=event.event_data.get("user"),
            )
        tips = self._update_all_libraries()
        if event:
            self.post_message(
                channel=event.event_data.get("channel"),
                title=tips,
                userid=event.event_data.get("user"),
            )

    @eventmanager.register(EventType.TransferComplete)
    def update_library_cover(self, event: Event):
        """
        媒体整理完成后，更新所在库封面
        """
        if not self._enabled:
            return
        if not self._transfer_monitor:
            return
        
        event_data = event.event_data    
        if not event_data:
            return
        
        # transfer: TransferInfo = event_data.get("transferinfo")        
        # Event data
        mediainfo: MediaInfo = event_data.get("mediainfo")

        # logger.info(f"转移信息：{transfer}")
        # logger.info(f"元数据：{meta}")
        # logger.info(f"媒体信息：{mediainfo}")
        # logger.info(f"监控到的媒体信息：{mediainfo}")
        if not mediainfo:
            return
            
        # 开始前清理可能遗留的停止信号，防止阻塞监控
        self._event.clear()

        # Delay
        if self._delay:
            logger.info(f"延迟 {self._delay} 秒后开始更新封面")
            time.sleep(int(self._delay))
            
        # Query the item in media server
        if not self.mschain:
            logger.warning("MediaServerChain 不可用，跳过更新封面")
            return

        existsinfo = self.mschain.media_exists(mediainfo=mediainfo)
        if not existsinfo or not existsinfo.itemid:
            self.mschain.sync()
            existsinfo = self.mschain.media_exists(mediainfo=mediainfo)
            if not existsinfo:
                logger.warning(f"{mediainfo.title_year} 不存在媒体库中，可能服务器还未扫描完成，建议设置合适的延迟时间")
                return
        
        # Get item details including backdrop
        iteminfo = self.mschain.iteminfo(server=existsinfo.server, item_id=existsinfo.itemid)
        # logger.info(f"获取到媒体项 {mediainfo.title_year} 详情：{iteminfo}")
        if not iteminfo:
            logger.warning(f"获取 {mediainfo.title_year} 详情失败")
            return
            
        # Try to get library ID
        library_id = None
        library = {}
        item_id = existsinfo.itemid
        server = existsinfo.server
        service = self._servers.get(server) if self._servers else None
        libraries = []
        if service:
            libraries = self._get_server_libraries(service) or []
        if libraries and not library_id:
            library = next(
                (library
                 for library in libraries if library.get('Locations', []) 
                 and any(iteminfo.path.startswith(path) for path in library.get('Locations', []))),
                None
            )
        
        if not library or not service:
            logger.warning(f"找不到 {mediainfo.title_year} 所在媒体库")
            return
        if service.type == 'emby':
            library_id = library.get("Id")
        else:
            library_id = library.get("ItemId")
        if self._include_libraries and f"{server}-{library_id}" not in self._include_libraries:
            logger.info(f"{server}：{library['Name']} 不在列表中，跳过更新封面")
            return

        update_key = (server, item_id)
        if update_key in self._current_updating_items:
            logger.info(f"媒体库 {server}：{library['Name']} 的项目 {mediainfo.title_year} 正在更新中，跳过此次更新")
            return
        # self.clean_cover_history(save=True)
        old_history = self.get_data('cover_history') or []
        # 新增去重判断逻辑
        latest_item = max(
            (item for item in old_history if str(item.get("library_id")) == str(library_id)),
            key=lambda x: x["timestamp"],
            default=None
        )
        if latest_item and str(latest_item.get("item_id")) == str(item_id):
            logger.info(f"媒体 {mediainfo.title_year} 在库中是最新记录，不更新封面图")
            return
        
        # 安全地获取字体和翻译
        try:
            self._get_fonts()
        except Exception as e:
            logger.error(f"初始化字体或翻译时出错: {e}")
            # 继续执行，但可能会影响封面生成质量
        new_history = self.update_cover_history(
            server=server, 
            library_id=library_id, 
            item_id=item_id
        )
        # logger.info(f"最新数据： {new_history}")
        self._monitor_sort = 'DateCreated'
        self._current_updating_items.add(update_key)
        if self._update_library(service, library):
            self._monitor_sort = ''
            self._current_updating_items.remove(update_key)
            logger.info(f"媒体库 {server}：{library['Name']} 封面更新成功")

    
                 



    
        
        
        
        




    
    
    

    
    
        
            




        











        

    def stop_service(self):
        """
        停止服务
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            logger.error(f"停止服务失败: {str(e)}")
