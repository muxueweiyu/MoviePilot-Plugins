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



class GeneratorMixin:
    def __update_all_libraries(self):
        """
        更新所有媒体库封面
        """
        if not self._enabled:
            return
        # 所有媒体服务器
        if not self._servers:
            return
        logger.info("开始检查字体 ...")
        try:
            self.__get_fonts()
        except Exception as e:
            logger.error(f"初始化过程中出错: {e}")
            logger.warning("将尝试继续执行，但可能影响封面生成质量")
        logger.info("开始更新媒体库封面 ...")
        # 开始前确保停止信号已清除
        self._event.clear()
        for server, service in self._servers.items():
            # 扫描所有媒体库
            logger.info(f"当前服务器 {server}")
            cover_style = {
                "static_1": "静态 1",
                "static_2": "静态 2",
                "static_3": "静态 3",
                "static_4": "静态 4（全屏模糊）",
                "animated_1": "卡片翻转动画",
                "animated_2": "帷幕切换动画",
                "animated_3": "斜向滚动动画",
                "animated_4": "全屏模糊渐变"
            }.get(self._cover_style, "静态 1")
            logger.info(f"当前风格 {cover_style}")
            # 获取媒体库列表
            libraries = self.__get_server_libraries(service)
            if not libraries:
                logger.warning(f"服务器 {server} 的媒体库列表获取失败")
                continue
            success_count = 0
            fail_count = 0
            for library in libraries:
                if self._event.is_set():
                    logger.info("媒体库封面更新服务停止")
                    self._event.clear()
                    return
                if service.type == 'emby':
                    library_id = library.get("Id")
                else:
                    library_id = library.get("ItemId")
                if self._include_libraries and f"{server}-{library_id}" not in self._include_libraries:
                    logger.info(f"{server}：{library['Name']} 不在列表中，跳过更新封面")
                    continue
                if self.__update_library(service, library):
                    logger.info(f"媒体库 {server}：{library['Name']} 封面更新成功")
                    success_count += 1
                else:
                    logger.warning(f"媒体库 {server}：{library['Name']} 封面更新失败")
                    fail_count += 1
        tips = f"媒体库封面更新任务结束，成功 {success_count} 个，失败 {fail_count} 个"
        logger.info(tips)
        return tips

    def __update_library(self, service, library):
        library_name = library['Name']
        logger.info(f"媒体库 {service.name}：{library_name} 开始准备更新封面")
        # 自定义图像路径
        image_path = self.__check_custom_image(library_name)
        # 从配置获取标题和背景颜色
        title_result = self.__get_title_from_config(library_name)
        if len(title_result) == 3:
            title = (title_result[0], title_result[1])
            config_bg_color = title_result[2]
        else:
            title = title_result
            config_bg_color = None
        if image_path:
            logger.info(f"媒体库 {service.name}：{library_name} 从自定义路径获取封面")
            image_data = self.__generate_image_from_path(service.name, library_name, title, image_path[0], config_bg_color)
        else:
            image_data = self.__generate_from_server(service, library, title)

        if image_data:
            return self.__set_library_image(service, library, image_data)

    def __check_custom_image(self, library_name):
        if not self._covers_input:
            return None

        # 使用安全的文件名
        safe_library_name = self.__sanitize_filename(library_name)
        library_dir = os.path.join(self._covers_input, safe_library_name)
        if not os.path.isdir(library_dir):
            return None

        images = sorted([
            os.path.join(library_dir, f)
            for f in os.listdir(library_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"))
        ])
        
        return images if images else None  # 或改为 return images if images else False

    @memory_efficient_operation
    def __generate_image_from_path(self, server, library_name, title, image_path=None, config_bg_color=None):
        logger.info(f"媒体库 {server}：{library_name} 正在生成封面图 ...")

        # 执行健康检查
        if not self.health_check():
            logger.error("插件健康检查失败，无法生成封面")
            return False

        # 确保分辨率配置已初始化
        if not hasattr(self, '_resolution_config') or self._resolution_config is None:
            logger.warning("分辨率配置未初始化，重新初始化")
            # 使用用户设置的分辨率，而不是硬编码的1080p
            if self._resolution == "custom":
                try:
                    custom_w = int(self._custom_width)
                    custom_h = int(self._custom_height)
                    self._resolution_config = ResolutionConfig((custom_w, custom_h))
                except ValueError:
                    logger.warning(f"自定义分辨率参数无效: {self._custom_width}x{self._custom_height}, 使用默认1080p")
                    self._resolution_config = ResolutionConfig("1080p")
            else:
                self._resolution_config = ResolutionConfig(self._resolution)

        # 使用分辨率配置计算字体大小
        try:
            base_zh_font_size = float(self._zh_font_size) if self._zh_font_size else 170
        except ValueError:
            base_zh_font_size = 170
            
        try:
            base_en_font_size = float(self._en_font_size) if self._en_font_size else 75
        except ValueError:
            base_en_font_size = 75

        try:
            title_scale = float(self._title_scale) if self._title_scale else 1.0
        except (ValueError, TypeError):
            title_scale = 1.0
        if title_scale <= 0:
            title_scale = 1.0
        if self._cover_style.startswith("animated"):
            zh_font_size = float(base_zh_font_size) * title_scale
            en_font_size = float(base_en_font_size) * title_scale
        else:
            # 静态风格按当前分辨率缩放
            zh_font_size = self._resolution_config.get_font_size(base_zh_font_size) * title_scale
            en_font_size = self._resolution_config.get_font_size(base_en_font_size) * title_scale

        blur_size = self._blur_size or 50
        color_ratio = self._color_ratio or 0.8

        # 检查字体路径是否有效
        if not self._zh_font_path or not self._en_font_path:
            logger.error("字体路径未设置或无效，无法生成封面")
            return False

        # 验证字体文件是否存在
        if not validate_font_file(Path(self._zh_font_path)):
            logger.error(f"主标题字体文件无效: {self._zh_font_path}")
            return False

        if not validate_font_file(Path(self._en_font_path)):
            logger.error(f"副标题字体文件无效: {self._en_font_path}")
            return False

        font_path = (str(self._zh_font_path), str(self._en_font_path))
        font_size = (float(zh_font_size), float(en_font_size))

        zh_font_offset = float(self._zh_font_offset or 0)
        title_spacing = float(self._title_spacing or 40) * title_scale
        en_line_spacing = float(self._en_line_spacing or 40) * title_scale
        font_offset = (float(zh_font_offset), float(title_spacing), float(en_line_spacing))

        # 记录分辨率配置信息
        logger.info(f"当前分辨率配置: {self._resolution_config}")

        # 准备背景颜色配置
        bg_color_config = {
            'mode': self._bg_color_mode,
            'custom_color': self._custom_bg_color,
            'config_color': config_bg_color
        }

        # 传递分辨率配置给图像生成函数
        if self._cover_style == 'static_1':
            image_data = create_style_static_1(image_path, title, font_path,
                                                font_size=font_size,
                                                font_offset=font_offset,
                                                blur_size=blur_size,
                                                color_ratio=color_ratio,
                                                resolution_config=self._resolution_config,
                                                bg_color_config=bg_color_config)
        elif self._cover_style == 'static_2':
            image_data = create_style_static_2(image_path, title, font_path,
                                                font_size=font_size,
                                                font_offset=font_offset,
                                                blur_size=blur_size,
                                                color_ratio=color_ratio,
                                                resolution_config=self._resolution_config,
                                                bg_color_config=bg_color_config)
        elif self._cover_style == 'static_4':
            image_data = create_style_static_4(image_path, title, font_path,
                                                font_size=font_size,
                                                font_offset=font_offset,
                                                blur_size=blur_size,
                                                color_ratio=color_ratio,
                                                resolution_config=self._resolution_config,
                                                bg_color_config=bg_color_config)
        elif self._cover_style == 'static_3':
            # 使用安全的文件名
            safe_library_name = self.__sanitize_filename(library_name)
            if image_path:
                library_dir = Path(self._covers_input) / safe_library_name
            else:
                library_dir = Path(self._covers_path) / safe_library_name
            logger.info(f"static_3: 准备图片目录 {library_dir}")
            if self.prepare_library_images(library_dir, required_items=9):
                logger.info("static_3: 图片目录准备完成，开始生成封面")
                image_data = create_style_static_3(library_dir, title, font_path,
                                                    font_size=font_size,
                                                    font_offset=font_offset,
                                                    is_blur=self._multi_1_blur,
                                                    blur_size=blur_size,
                                                    color_ratio=color_ratio,
                                                    resolution_config=self._resolution_config,
                                                    bg_color_config=bg_color_config)
            else:
                logger.warning(f"static_3: 图片目录准备失败 {library_dir}")
        elif self._cover_style == 'animated_3':
            # 动态封面强制使用 320x180 分辨率以保证性能
            anim_res = '320x180'
            logger.info(f"强制动图生成分辨率为: {anim_res}")
            
            # 动态封面逻辑，类似于 multi_1
            safe_library_name = self.__sanitize_filename(library_name)
            if image_path:
                library_dir = Path(self._covers_input) / safe_library_name
            else:
                library_dir = Path(self._covers_path) / safe_library_name
            
            logger.info(f"正在准备库图片目录: {library_dir}")
            if self.prepare_library_images(library_dir, required_items=9):
                logger.info("库图片准备完成，开始调用 create_style_animated_3")
                image_data = create_style_animated_3(library_dir, title, font_path,
                                                    font_size=font_size,
                                                    font_offset=font_offset,
                                                    is_blur=self._multi_1_blur,
                                                    blur_size=blur_size,
                                                    color_ratio=color_ratio,
                                                    resolution_config=self._resolution_config,
                                                    bg_color_config=bg_color_config,
                                                    animation_duration=self._animation_duration,
                                                    animation_scroll=self._animation_scroll,
                                                    animation_fps=self._animation_fps,
                                                    animation_format=self._animation_format,
                                                    animation_resolution=anim_res,
                                                    animation_reduce_colors=self._animation_reduce_colors,
                                                    stop_event=self._event)
        elif self._cover_style == 'animated_1':
            # 动态封面强制使用 320x180 分辨率以保证性能
            anim_res = '320x180'
            logger.info(f"强制动图生成分辨率为: {anim_res}")

            animated_2_image_count = self.__get_animated_2_required_items()

            # 动态封面逻辑，类似于 multi_1
            safe_library_name = self.__sanitize_filename(library_name)
            if image_path:
                library_dir = Path(self._covers_input) / safe_library_name
            else:
                library_dir = Path(self._covers_path) / safe_library_name

            logger.info(f"正在准备库图片目录: {library_dir}")
            if self.prepare_library_images(library_dir, required_items=animated_2_image_count):
                logger.info("库图片准备完成，开始调用 create_style_animated_1")
                image_data = create_style_animated_1(library_dir, title, font_path,
                                                    font_size=font_size,
                                                    font_offset=font_offset,
                                                    is_blur=self._multi_1_blur,
                                                    blur_size=blur_size,
                                                    color_ratio=color_ratio,
                                                    resolution_config=self._resolution_config,
                                                    bg_color_config=bg_color_config,
                                                    animation_duration=self._animation_duration,
                                                    animation_fps=self._animation_fps,
                                                    animation_format=self._animation_format,
                                                    animation_resolution=anim_res,
                                                    animation_reduce_colors=self._animation_reduce_colors,
                                                    image_count=animated_2_image_count,
                                                    departure_type=self._animated_2_departure_type,
                                                    stop_event=self._event)
        elif self._cover_style == 'animated_2':
            # 动态封面强制使用 320x180 分辨率以保证性能
            anim_res = '320x180'
            logger.info(f"强制动图生成分辨率为: {anim_res}")

            safe_library_name = self.__sanitize_filename(library_name)
            if image_path:
                library_dir = Path(self._covers_input) / safe_library_name
            else:
                library_dir = Path(self._covers_path) / safe_library_name

            logger.info(f"正在准备库图片目录: {library_dir}")
            if self.prepare_library_images(library_dir, required_items=9):
                logger.info("库图片准备完成，开始调用 create_style_animated_2")
                image_data = create_style_animated_2(library_dir, title, font_path,
                                                    font_size=font_size,
                                                    font_offset=font_offset,
                                                    is_blur=self._multi_1_blur,
                                                    blur_size=blur_size,
                                                    color_ratio=color_ratio,
                                                    resolution_config=self._resolution_config,
                                                    bg_color_config=bg_color_config,
                                                    animation_duration=self._animation_duration,
                                                    animation_fps=self._animation_fps,
                                                    animation_format=self._animation_format,
                                                    animation_resolution=anim_res,
                                                    animation_reduce_colors=self._animation_reduce_colors,
                                                    image_count=self.__get_animated_2_required_items(),
                                                    stop_event=self._event)
        elif self._cover_style == 'animated_4':
            anim_res = '320x180'
            logger.info(f"强制动图生成分辨率为: {anim_res}")

            animated_2_image_count = self.__get_animated_2_required_items()

            safe_library_name = self.__sanitize_filename(library_name)
            if image_path:
                library_dir = Path(self._covers_input) / safe_library_name
            else:
                library_dir = Path(self._covers_path) / safe_library_name

            logger.info(f"正在准备库图片目录: {library_dir}")
            if self.prepare_library_images(library_dir, required_items=animated_2_image_count):
                logger.info("库图片准备完成，开始调用 create_style_animated_4")
                image_data = create_style_animated_4(library_dir, title, font_path,
                                                    font_size=font_size,
                                                    font_offset=font_offset,
                                                    is_blur=self._multi_1_blur,
                                                    blur_size=blur_size,
                                                    color_ratio=color_ratio,
                                                    resolution_config=self._resolution_config,
                                                    bg_color_config=bg_color_config,
                                                    animation_duration=self._animation_duration,
                                                    animation_fps=self._animation_fps,
                                                    animation_format=self._animation_format,
                                                    animation_resolution=anim_res,
                                                    animation_reduce_colors=self._animation_reduce_colors,
                                                    image_count=animated_2_image_count,
                                                    stop_event=self._event)
        return image_data

    def __generate_from_server(self, service, library, title):

        logger.info(f"媒体库 {service.name}：{library['Name']} 开始筛选媒体项")
        required_items = self.__get_required_items()
        
        # 获取项目集合
        items = []
        offset = 0
        batch_size = 50  # 每次获取的项目数量
        max_attempts = 20  # 最大尝试次数，防止无限循环
        
        library_type = library.get('CollectionType')
        if service.type == 'emby':
            library_id = library.get("Id")
        else:
            library_id = library.get("ItemId")
        parent_id = library_id
        
        # 处理合集类型的特殊情况
        if library_type == "boxsets":
            return self.__handle_boxset_library(service, library, title)
        elif library_type == "playlists":
            return self.__handle_playlist_library(service, library, title)
        elif library_type == "music":
            include_types = 'MusicAlbum,Audio'
        else:
            # 基础类型映射
            if self.__is_single_image_style():
                include_types = {
                    "PremiereDate": "Movie,Series",
                    "DateCreated": "Movie,Episode",
                    "Random": "Movie,Series"
                }.get(self._sort_by, "Movie,Series")
            else:
                # 对于多图样式，如果按最新入库排序（DateCreated），也要包含 Episode 以展示剧集的最新动态
                if self._sort_by == "DateCreated":
                    include_types = "Movie,Episode"
                else:
                    # 其他排序方式默认使用 Series 获取海报
                    include_types = "Movie,Series"
            logger.debug(f"媒体库筛选类型: {include_types}, 排序方式: {self._sort_by}")
        self._seen_keys = set()
        for attempt in range(max_attempts):
            if self._event.is_set():
                logger.info("检测到停止信号，中断媒体项获取 ...")
                return False
                
            batch_items = self.__get_items_batch(service, parent_id,
                                              offset=offset, limit=batch_size,
                                              include_types=include_types)
            
            if not batch_items:
                break  # 没有更多项目可获取
                
            # 筛选有效项目（有所需图片的项目）
            valid_items = self.__filter_valid_items(batch_items)
            items.extend(valid_items)
            
            # 如果已经有足够的有效项目，则停止获取
            if len(items) >= required_items:
                break
                
            offset += batch_size
        
        # 使用获取到的有效项目更新封面
        if len(items) > 0:
            logger.info(f"媒体库 {service.name}：{library['Name']} 找到 {len(items)} 个有效项目")
            if self.__is_single_image_style():
                return self.__update_single_image(service, library, title, items[0])
            else:
                return self.__update_grid_image(service, library, title, items[:required_items])
        else:
            logger.warning(f"媒体库 {service.name}：{library['Name']} 无法找到有效的图片项目 (筛选类型: {include_types})")
            return False

    def __handle_boxset_library(self, service, library, title):

        include_types = 'BoxSet,Movie'
        if service.type == 'emby':
            library_id = library.get("Id")
        else:
            library_id = library.get("ItemId")
        parent_id = library_id
        boxsets = self.__get_items_batch(service, parent_id,
                                      include_types=include_types)
        
        required_items = self.__get_required_items()
        valid_items = []
        
        # 首先检查BoxSet本身是否有合适的图片
        self._seen_keys = set()

        valid_boxsets = self.__filter_valid_items(boxsets)
        valid_items.extend(valid_boxsets)
        
        # 如果BoxSet本身没有足够的图片，则获取其中的电影
        if len(valid_items) < required_items:
            for boxset in boxsets:
                if len(valid_items) >= required_items:
                    break
                    
                # 获取此BoxSet中的电影
                movies = self.__get_items_batch(service,
                                             parent_id=boxset['Id'], 
                                             include_types=include_types)
                
                valid_movies = self.__filter_valid_items(movies)
                valid_items.extend(valid_movies)
                
                if len(valid_items) >= required_items:
                    break
        
        # 使用获取到的有效项目更新封面
        if len(valid_items) > 0:
            if self.__is_single_image_style():
                return self.__update_single_image(service, library, title, valid_items[0])
            else:
                return self.__update_grid_image(service, library, title, valid_items[:required_items])
        else:
            print(f"媒体库 {service.name}：{library['Name']} 无法找到有效的图片项目")
            return False

    def __handle_playlist_library(self, service, library, title):
        """ 
        播放列表图片获取 
        """
        include_types = 'Playlist,Movie,Series,Episode,Audio'
        if service.type == 'emby':
            library_id = library.get("Id")
        else:
            library_id = library.get("ItemId")
        parent_id = library_id
        playlists = self.__get_items_batch(service, parent_id,
                                      include_types=include_types)
        
        required_items = self.__get_required_items()
        valid_items = []
        
        # 首先检查 playlist 本身是否有合适的图片
        self._seen_keys = set()

        valid_playlists = self.__filter_valid_items(playlists)
        valid_items.extend(valid_playlists)
        
        # 如果 playlist 本身没有足够的图片，则获取其中的电影
        if len(valid_items) < required_items:
            for playlist in playlists:
                if len(valid_items) >= required_items:
                    break
                    
                # 获取此 playlist 中的电影
                movies = self.__get_items_batch(service,
                                             parent_id=playlist['Id'], 
                                             include_types=include_types)
                
                valid_movies = self.__filter_valid_items(movies)
                valid_items.extend(valid_movies)
                
                if len(valid_items) >= required_items:
                    break
        
        # 使用获取到的有效项目更新封面
        if len(valid_items) > 0:
            if self.__is_single_image_style():
                return self.__update_single_image(service, library, title, valid_items[0])
            else:
                return self.__update_grid_image(service, library, title, valid_items[:required_items])
        else:
            print(f"警告: 无法为播放列表 {service.name}：{library['Name']} 找到有效的图片项目")
            return False

    def __build_content_key(self, item: dict) -> Optional[str]:
        """构建内容去重Key，尽量让同一来源内容只入选一次。"""
        item_type = item.get("Type")

        if item_type == "Episode":
            if item.get("SeriesId"):
                return f"series:{item.get('SeriesId')}"
            if item.get("ParentBackdropItemId"):
                return f"parent:{item.get('ParentBackdropItemId')}"

        if item_type in ["MusicAlbum", "Audio"]:
            if item.get("AlbumId"):
                return f"album:{item.get('AlbumId')}"
            if item.get("ParentBackdropItemId"):
                return f"parent:{item.get('ParentBackdropItemId')}"

        if item.get("Id"):
            return f"item:{item.get('Id')}"

        return None

    def __build_image_key(self, image_url: str) -> Optional[str]:
        """构建图片去重Key，忽略api_key，避免同图重复。"""
        if not image_url:
            return None

        try:
            # 统一移除 api_key 参数，避免同图不同密钥导致重复
            normalized = re.sub(r"([?&])api_key=[^&]*", "", image_url).rstrip("?&")

            # 优先用路径 + tag 作为去重关键字（能精准区分图像版本）
            # 例如: /Items/{id}/Images/Backdrop/0?tag=xxx
            tag_match = re.search(r"[?&]tag=([^&]+)", image_url)
            tag = tag_match.group(1) if tag_match else ""

            parsed = urlparse(normalized)
            path = parsed.path if parsed.path else normalized
            return f"img:{path}|tag:{tag}"
        except Exception:
            return f"img:{image_url}"

    def __update_single_image(self, service, library, title, item):
        """更新单图封面"""
        logger.info(f"媒体库 {service.name}：{library['Name']} 从媒体项获取图片")
        updated_item_id = ''
        image_url = self.__get_image_url(item)
        if not image_url:
            return False
            
        image_path = self.__download_image(service, image_url, library['Name'], count=1)
        if not image_path:
            return False
        updated_item_id = self.__get_item_id(item)
        # 从配置获取背景颜色
        title_result = self.__get_title_from_config(library['Name'])
        config_bg_color = title_result[2] if len(title_result) == 3 else None
        image_data = self.__generate_image_from_path(service.name, library['Name'], title, image_path, config_bg_color)
            
        if not image_data:
            return False
        if service.type == 'emby':
            library_id = library.get("Id")
        else:
            library_id = library.get("ItemId")
        # 更新id
        self.update_cover_history(
            server=service.name, 
            library_id=library_id, 
            item_id=updated_item_id
        )

        return image_data

    def __update_grid_image(self, service, library, title, items):
        """更新九宫格封面"""
        logger.info(f"媒体库 {service.name}：{library['Name']} 从媒体项获取图片")

        image_paths = []
        
        updated_item_ids = []
        for i, item in enumerate(items):
            if self._event.is_set():
                logger.info("检测到停止信号，中断图片下载 ...")
                return False
            image_url = self.__get_image_url(item)
            if image_url:
                image_path = self.__download_image(service, image_url, library['Name'], count=i+1)
                if image_path:
                    image_paths.append(image_path)
                    updated_item_ids.append(self.__get_item_id(item))
        
        if len(image_paths) < 1:
            return False
            
        # 生成九宫格图片
        # 从配置获取背景颜色
        title_result = self.__get_title_from_config(library['Name'])
        config_bg_color = title_result[2] if len(title_result) == 3 else None
        image_data = self.__generate_image_from_path(service.name, library['Name'], title, None, config_bg_color)
        if not image_data:
            return False
        if service.type == 'emby':
            library_id = library.get("Id")
        else:
            library_id = library.get("ItemId")
        # 更新ids
        for item_id in reversed(updated_item_ids):
            self.update_cover_history(
                server=service.name, 
                library_id=library_id, 
                item_id=item_id
            )
            
        return image_data

    def __load_title_config(self, yaml_str: str) -> dict:
        try:
            # 替换全角冒号为半角
            yaml_str = yaml_str.replace("：", ":")
            # 替换制表符为两个空格，统一缩进
            yaml_str = yaml_str.replace("\t", "  ")

            # 处理数字或字母开头的媒体库名，确保它们被正确解析为字符串键
            # 在YAML中，数字开头的键可能被解析为数字，需要加引号
            lines = yaml_str.split('\n')
            processed_lines = []
            for line in lines:
                # 检查是否是键值对行（包含冒号且不是注释）
                if ':' in line and not line.strip().startswith('#'):
                    # 分割键和值
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key_part = parts[0].strip()
                        value_part = parts[1]

                        # 如果键不是以引号开头，且包含数字或特殊字符，则添加引号
                        if key_part and not (key_part.startswith('"') or key_part.startswith("'")):
                            # 检查是否需要加引号（数字开头、包含特殊字符等）
                            if (key_part[0].isdigit() or
                                any(char in key_part for char in [' ', '-', '.', '(', ')', '[', ']'])):
                                key_part = f'"{key_part}"'

                        processed_lines.append(f"{key_part}:{value_part}")
                    else:
                        processed_lines.append(line)
                else:
                    processed_lines.append(line)

            processed_yaml = '\n'.join(processed_lines)
            preview_limit = 800
            flat_yaml = " ".join(part.strip() for part in processed_yaml.splitlines() if part.strip())
            if len(flat_yaml) > preview_limit:
                logger.debug(f"处理后的YAML(扁平, 前{preview_limit}字): {flat_yaml[:preview_limit]}... (已截断)")
            else:
                logger.debug(f"处理后的YAML(扁平): {flat_yaml}")

            title_config = yaml.safe_load(processed_yaml) or {}
            if not isinstance(title_config, dict):
                return {}
            filtered = {}
            for key, value in title_config.items():
                if isinstance(value, list) and len(value) >= 2 and isinstance(value[0], str) and isinstance(value[1], str):
                    # 支持两行或三行配置（第三行可选）
                    if len(value) >= 3 and isinstance(value[2], str):
                        filtered[str(key)] = [value[0], value[1], value[2]]
                    else:
                        filtered[str(key)] = [value[0], value[1]]
                    if len(value) > 3:
                        logger.info(f"配置项 {key} 包含多行，只使用前三行")
                else:
                    # 忽略格式不正确的项
                    logger.warning(f"标题配置项格式不正确，已忽略: {key} -> {value}")
                    continue

            logger.debug(f"解析后的配置: {filtered}")
            return filtered
        except Exception as e:
            # 整体 YAML 无法解析（比如语法错误），返回空配置
            logger.warning(f"YAML 解析失败，使用空配置: {e}")
            return {}

    def __get_title_from_config(self, library_name):
        """
        从 yaml 配置中获取媒体库的主副标题和背景颜色
        """
        zh_title = library_name
        en_title = ''
        bg_color = None
        title_config = {}
        if self._current_config:
            title_config = self._current_config
        elif self._title_config:
            title_config = self.__load_title_config(self._title_config)

        # 添加调试信息
        logger.debug(f"查找媒体库名称: '{library_name}' (类型: {type(library_name)})")
        logger.debug(f"可用的配置键: {list(title_config.keys())}")

        # 多种匹配策略，确保数字或字母开头的媒体库名能够正确匹配
        for lib_name, config_values in title_config.items():
            # 策略1: 直接字符串比较
            if str(lib_name) == str(library_name):
                zh_title = config_values[0]
                en_title = config_values[1] if len(config_values) > 1 else ''
                bg_color = config_values[2] if len(config_values) > 2 else None
                logger.debug(f"找到匹配的配置(直接匹配): {lib_name} -> {zh_title}, {en_title}, {bg_color}")
                break

            # 策略2: 去除空格后比较
            if str(lib_name).strip() == str(library_name).strip():
                zh_title = config_values[0]
                en_title = config_values[1] if len(config_values) > 1 else ''
                bg_color = config_values[2] if len(config_values) > 2 else None
                logger.debug(f"找到匹配的配置(去空格匹配): {lib_name} -> {zh_title}, {en_title}, {bg_color}")
                break

            # 策略3: 忽略大小写比较
            if str(lib_name).lower() == str(library_name).lower():
                zh_title = config_values[0]
                en_title = config_values[1] if len(config_values) > 1 else ''
                bg_color = config_values[2] if len(config_values) > 2 else None
                logger.debug(f"找到匹配的配置(忽略大小写匹配): {lib_name} -> {zh_title}, {en_title}, {bg_color}")
                break
        else:
            logger.debug(f"未找到媒体库 '{library_name}' 的配置，使用默认标题")
            # 如果没有找到配置，检查是否是数字开头的媒体库名导致的问题
            if library_name and (library_name[0].isdigit() or library_name[0].isalpha()):
                logger.info(f"媒体库名 '{library_name}' 以数字或字母开头，如果需要自定义标题，请在配置中使用引号包围媒体库名，例如: \"{library_name}\":")

        return (zh_title, en_title, bg_color)

    def __clean_generated_images(self):
        removed = 0
        cache_dirs: List[Path] = []
        if self._covers_path:
            cache_dirs.append(Path(self._covers_path))
        data_path = self.get_data_path()
        legacy_covers_dir = data_path / "covers"
        cache_dirs.append(legacy_covers_dir)

        handled = set()
        for cache_dir in cache_dirs:
            if not cache_dir.exists() or not cache_dir.is_dir():
                continue
            cache_key = str(cache_dir.resolve())
            if cache_key in handled:
                continue
            handled.add(cache_key)
            for entry in cache_dir.iterdir():
                if not entry.exists():
                    continue
                try:
                    if entry.is_dir():
                        shutil.rmtree(entry)
                        removed += 1
                    elif entry.is_file():
                        entry.unlink(missing_ok=True)
                        removed += 1
                except Exception as e:
                    logger.warning(f"清理图片失败 {entry}: {e}")
        logger.info(f"清理图片完成（含旧版 covers 兼容目录），共清理 {removed} 项")

    def __clean_downloaded_fonts(self):
        if not self._font_path or not Path(self._font_path).exists():
            logger.info("清理字体：未找到字体目录，跳过")
            return
        removed = 0
        for entry in Path(self._font_path).iterdir():
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_file():
                    entry.unlink(missing_ok=True)
                    removed += 1
                elif entry.is_dir():
                    shutil.rmtree(entry)
                    removed += 1
            except Exception as e:
                logger.warning(f"清理字体失败 {entry}: {e}")
        self._zh_font_path = ""
        self._en_font_path = ""
        logger.info(f"清理字体完成，共清理 {removed} 项")

    def health_check(self) -> bool:
        """
        插件健康检查，确保关键组件正常
        """
        try:
            # 检查分辨率配置
            if not hasattr(self, '_resolution_config') or self._resolution_config is None:
                logger.warning("分辨率配置缺失，重新初始化")
                # 使用用户设置的分辨率，而不是硬编码的1080p
                if self._resolution == "custom":
                    self._resolution_config = ResolutionConfig((self._custom_width, self._custom_height))
                else:
                    self._resolution_config = ResolutionConfig(self._resolution)

            # 检查字体文件
            if not self._zh_font_path or not self._en_font_path:
                logger.warning("字体文件缺失，尝试重新获取")
                self.__get_fonts()

            # 验证字体文件有效性
            if self._zh_font_path and not validate_font_file(Path(self._zh_font_path)):
                logger.warning("主标题字体文件无效，尝试重新下载")
                return False

            if self._en_font_path and not validate_font_file(Path(self._en_font_path)):
                logger.warning("副标题字体文件无效，尝试重新下载")
                return False

            logger.info("插件健康检查通过")
            return True

        except Exception as e:
            logger.error(f"健康检查失败: {e}")
            return False

    def __sanitize_filename(self, filename: str) -> str:
        """
        将媒体库名称转换为安全的文件名，特别处理数字或字母开头的名称
        """
        if not filename:
            return "unknown"

        # 移除或替换不安全的字符
        import re
        # 替换Windows和Unix系统中不允许的字符
        unsafe_chars = r'[<>:"/\\|?*]'
        safe_name = re.sub(unsafe_chars, '_', filename)

        # 移除前后空格
        safe_name = safe_name.strip()

        # 如果名称为空，使用默认名称
        if not safe_name:
            return "unknown"

        # 确保不以点开头（在某些系统中是隐藏文件）
        if safe_name.startswith('.'):
            safe_name = '_' + safe_name[1:]

        # 限制长度（避免路径过长）
        if len(safe_name) > 100:
            safe_name = safe_name[:100]

        if safe_name != filename and filename not in self._sanitize_log_cache:
            self._sanitize_log_cache.add(filename)
            logger.debug(f"文件名安全化: '{filename}' -> '{safe_name}'")
        return safe_name

