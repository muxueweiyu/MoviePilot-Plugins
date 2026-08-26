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



class MediaFetcherMixin:
    def __get_items_batch(self, service, parent_id, offset=0, limit=20, include_types=None):
        # 调用API获取项目
        try:
            if not service:
                return []
            
            try:
                if not self._sort_by:
                    sort_by = 'Random'
                else:
                    sort_by = self._sort_by
                if self._monitor_sort:
                    sort_by = 'DateCreated'
                    # 转移监控模式下强制包含 Episode 以获取最新入库的内容
                    include_types = 'Movie,Episode'
                if not include_types:
                    include_types = 'Movie,Series'

                url = f'[HOST]emby/Items/?api_key=[APIKEY]' \
                      f'&ParentId={parent_id}&SortBy={sort_by}&Limit={limit}' \
                      f'&StartIndex={offset}&IncludeItemTypes={include_types}' \
                      f'&Recursive=True&SortOrder=Descending'

                res = service.instance.get_data(url=url)
                if res:
                    data = res.json()
                    return data.get("Items", [])
            except Exception as err:
                logger.error(f"获取媒体项失败：{str(err)}")
            return []
                
        except Exception as err:
            logger.error(f"Failed to get latest items: {str(err)}")
            return []

    def __filter_valid_items(self, items):
        """筛选有效的项目（包含所需图片的项目），并按图片标签去重"""
        valid_items = []

        for item in items:
            # 1) 根据当前样式计算真实会使用的图片URL
            image_url = self.__get_image_url(item)
            if not image_url:
                continue

            # 2) 两层去重：
            #    - content_key: 内容层（如同一剧集的多集使用同一Series图）
            #    - image_key:   图片层（同一图片tag或同一路径）
            content_key = self.__build_content_key(item)
            image_key = self.__build_image_key(image_url)

            if not content_key and not image_key:
                continue

            if (content_key and content_key in self._seen_keys) or (image_key and image_key in self._seen_keys):
                continue

            # 3) 加入有效列表并记录已处理的 Key
            valid_items.append(item)
            if content_key:
                self._seen_keys.add(content_key)
            if image_key:
                self._seen_keys.add(image_key)

        return valid_items

    def __get_server_libraries(self, service):
        try:
            if not service:
                return []
            try:
                if service.type == 'emby':
                    url = f'[HOST]emby/Library/VirtualFolders/Query?api_key=[APIKEY]'
                else:
                    url = f'[HOST]emby/Library/VirtualFolders/?api_key=[APIKEY]'
                res = service.instance.get_data(url=url)
                if res:
                    data = res.json()
                    if service.type == 'emby':
                        return data.get("Items", [])
                    else:
                        return data
            except Exception as err:
                logger.error(f"获取媒体库列表失败：{str(err)}")
            return []
        except Exception as err:
            logger.error(f"获取媒体库列表失败：{str(err)}")
            return []

    def __get_all_libraries(self, server, service):
        try:
            lib_items = []
            libraries = self.__get_server_libraries(service)
            for library in libraries:
                if service.type == 'emby':
                    library_id = library.get("Id")
                else:
                    library_id = library.get("ItemId")
                if library['Name'] and library_id:
                    lib_item = {
                        "name": f"{server}: {library['Name']}",
                        "value": f"{server}-{library_id}"
                    }
                    lib_items.append(lib_item)
            return lib_items
        except Exception as err:
            logger.error(f"获取所有媒体库失败：{str(err)}")
            return []

    def __get_image_url(self, item):
        """
        从媒体项信息中获取图片URL
        """
        # Emby/Jellyfin
        if item['Type'] in 'MusicAlbum,Audio':
            if item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                item_id = item.get("ParentBackdropItemId")
                tag = item["ParentBackdropImageTags"][0]
                return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
            elif item.get("PrimaryImageTag"):
                item_id = item.get("PrimaryImageItemId")
                tag = item.get("PrimaryImageTag")
                return f'[HOST]emby/Items/{item_id}/Images/Primary?tag={tag}&api_key=[APIKEY]'
            elif item.get("AlbumPrimaryImageTag"):
                item_id = item.get("AlbumId")
                tag = item.get("AlbumPrimaryImageTag")
                return f'[HOST]emby/Items/{item_id}/Images/Primary?tag={tag}&api_key=[APIKEY]'

        elif self._cover_style == 'static_3' or self._cover_style in ['animated_1', 'animated_2', 'animated_3', 'animated_4']:
            if self._use_primary:
                if item.get("Type") == 'Episode':
                    if item.get("SeriesPrimaryImageTag"):
                        item_id = item.get("SeriesId")
                        tag = item.get("SeriesPrimaryImageTag")
                        return f'[HOST]emby/Items/{item_id}/Images/Primary?tag={tag}&api_key=[APIKEY]'
                    elif item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                        item_id = item.get("ParentBackdropItemId")
                        tag = item["ParentBackdropImageTags"][0]
                        return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
                elif item.get("ImageTags") and item.get("ImageTags").get("Primary"):
                    item_id = item.get("Id")
                    tag = item.get("ImageTags").get("Primary")
                    return f'[HOST]emby/Items/{item_id}/Images/Primary?tag={tag}&api_key=[APIKEY]'
                elif item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                    item_id = item.get("ParentBackdropItemId")
                    tag = item["ParentBackdropImageTags"][0]
                    return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
                elif item.get("BackdropImageTags") and len(item["BackdropImageTags"]) > 0:
                    item_id = item.get("Id")
                    tag = item["BackdropImageTags"][0]
                    return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
            else:
                if item.get("Type") == 'Episode':
                    if item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                        item_id = item.get("ParentBackdropItemId")
                        tag = item["ParentBackdropImageTags"][0]
                        return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
                    elif item.get("SeriesPrimaryImageTag"):
                        item_id = item.get("SeriesId")
                        tag = item.get("SeriesPrimaryImageTag")
                        return f'[HOST]emby/Items/{item_id}/Images/Primary?tag={tag}&api_key=[APIKEY]'
                if item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                    item_id = item.get("ParentBackdropItemId")
                    tag = item["ParentBackdropImageTags"][0]
                    return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
                elif item.get("BackdropImageTags") and len(item["BackdropImageTags"]) > 0:
                    item_id = item.get("Id")
                    tag = item["BackdropImageTags"][0]
                    return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
                elif item.get("ImageTags") and item.get("ImageTags").get("Primary"):
                    item_id = item.get("Id")
                    tag = item.get("ImageTags").get("Primary")
                    return f'[HOST]emby/Items/{item_id}/Images/Primary?tag={tag}&api_key=[APIKEY]'

        elif self._cover_style.startswith('static'):
            if self._use_primary:
                if item.get("Type") == 'Episode':
                    if item.get("SeriesPrimaryImageTag"):
                        item_id = item.get("SeriesId")
                        tag = item.get("SeriesPrimaryImageTag")
                        return f'[HOST]emby/Items/{item_id}/Images/Primary?tag={tag}&api_key=[APIKEY]'
                    elif item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                        item_id = item.get("ParentBackdropItemId")
                        tag = item["ParentBackdropImageTags"][0]
                        return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
                elif item.get("ImageTags") and item.get("ImageTags").get("Primary"):
                    item_id = item.get("Id")
                    tag = item.get("ImageTags").get("Primary")
                    return f'[HOST]emby/Items/{item_id}/Images/Primary?tag={tag}&api_key=[APIKEY]'
                elif item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                    item_id = item.get("ParentBackdropItemId")
                    tag = item["ParentBackdropImageTags"][0]
                    return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
                elif item.get("BackdropImageTags") and len(item["BackdropImageTags"]) > 0:
                    item_id = item.get("Id")
                    tag = item["BackdropImageTags"][0]
                    return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
            else:
                if item.get("Type") == 'Episode':
                    if item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                        item_id = item.get("ParentBackdropItemId")
                        tag = item["ParentBackdropImageTags"][0]
                        return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
                    elif item.get("SeriesPrimaryImageTag"):
                        item_id = item.get("SeriesId")
                        tag = item.get("SeriesPrimaryImageTag")
                        return f'[HOST]emby/Items/{item_id}/Images/Primary?tag={tag}&api_key=[APIKEY]'
                elif item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                    item_id = item.get("ParentBackdropItemId")
                    tag = item["ParentBackdropImageTags"][0]
                    return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
                elif item.get("BackdropImageTags") and len(item["BackdropImageTags"]) > 0:
                    item_id = item.get("Id")
                    tag = item["BackdropImageTags"][0]
                    return f'[HOST]emby/Items/{item_id}/Images/Backdrop/0?tag={tag}&api_key=[APIKEY]'
                elif item.get("ImageTags") and item.get("ImageTags").get("Primary"):
                    item_id = item.get("Id")
                    tag = item.get("ImageTags").get("Primary")
                    return f'[HOST]emby/Items/{item_id}/Images/Primary?tag={tag}&api_key=[APIKEY]'

    def __get_item_id(self, item):
        """
        从媒体项信息中获取项目ID
        """
        # Emby/Jellyfin
        if item['Type'] in 'MusicAlbum,Audio':
            if item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                item_id = item.get("ParentBackdropItemId")
            elif item.get("PrimaryImageTag"):
                item_id = item.get("PrimaryImageItemId")
            elif item.get("AlbumPrimaryImageTag"):
                item_id = item.get("AlbumId")

        elif self._cover_style == 'static_3' or self._cover_style in ['animated_1', 'animated_2', 'animated_3', 'animated_4']:
            if self._use_primary:
                if (item.get("ImageTags") and item.get("ImageTags").get("Primary")) \
                    or (item.get("BackdropImageTags") and len(item["BackdropImageTags"]) > 0):
                    item_id = item.get("Id")
                elif item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                    item_id = item.get("ParentBackdropItemId")
            else:
                if item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                    item_id = item.get("ParentBackdropItemId")
                elif (item.get("ImageTags") and item.get("ImageTags").get("Primary")) \
                    or (item.get("BackdropImageTags") and len(item["BackdropImageTags"]) > 0):
                    item_id = item.get("Id")

        elif self._cover_style.startswith('static'):
            if self._use_primary:
                if (item.get("BackdropImageTags") and len(item["BackdropImageTags"]) > 0) \
                    or (item.get("ImageTags") and item.get("ImageTags").get("Primary")):
                    item_id = item.get("Id")
                elif item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                    item_id = item.get("ParentBackdropItemId")
            else:
                if item.get("ParentBackdropImageTags") and len(item["ParentBackdropImageTags"]) > 0:
                    item_id = item.get("ParentBackdropItemId")
                elif (item.get("BackdropImageTags") and len(item["BackdropImageTags"]) > 0) \
                    or (item.get("ImageTags") and item.get("ImageTags").get("Primary")):
                    item_id = item.get("Id")

        return item_id

    def __download_image(self, service, imageurl, library_name, count=None, retries=3, delay=1):
        """
        下载图片，保存到本地目录 self._covers_path/library_name/ 下，文件名为 1-9.jpg
        若已存在则跳过下载，直接返回图片路径。
        下载失败时重试若干次。
        """
        try:
            # 确保媒体库名称是安全的文件名（处理数字或字母开头的名称）
            safe_library_name = self.__sanitize_filename(library_name)

            # 创建目标子目录
            subdir = os.path.join(self._covers_path, safe_library_name)
            os.makedirs(subdir, exist_ok=True)

            # 文件命名：item_id 为主，适合排序
            if count is not None:
                filename = f"{count}.jpg"
            else:
                filename = f"img_{int(time.time())}.jpg"

            filepath = os.path.join(subdir, filename)

            # 如果文件已存在，直接返回路径
            # if os.path.exists(filepath):
            #     return filepath

            # 重试机制
            for attempt in range(1, retries + 1):
                image_content = None

                if '[HOST]' in imageurl:
                    if not service:
                        return None

                    r = service.instance.get_data(url=imageurl)
                    if r and r.status_code == 200:
                        image_content = r.content
                else:
                    r = RequestUtils().get_res(url=imageurl)
                    if r and r.status_code == 200:
                        image_content = r.content

                # 如果成功，保存并返回
                if image_content:
                    with open(filepath, 'wb') as f:
                        f.write(image_content)
                    return filepath

                # 如果失败，记录并等待后重试
                logger.warning(f"第 {attempt} 次尝试下载失败：{imageurl}")
                if attempt < retries:
                    time.sleep(delay)

            logger.error(f"图片下载失败（重试 {retries} 次）：{imageurl}")
            return None

        except Exception as err:
            logger.error(f"下载图片异常：{str(err)}")
            return None

    def __set_library_image(self, service, library, image_base64):
        """
        设置媒体库封面
        """

        """设置Emby媒体库封面"""
        try:
            if service.type == 'emby':
                library_id = library.get("Id")
            else:
                library_id = library.get("ItemId")
            
            url = f'[HOST]emby/Items/{library_id}/Images/Primary?api_key=[APIKEY]'
            # 根据 base64 前几个字节简单判断格式
            content_type = "image/png"
            extension = "png"
            if image_base64.startswith("R0lG"):
                content_type = "image/gif"
                extension = "gif"
            elif image_base64.startswith("UklG"):
                content_type = "image/webp"
                extension = "webp"
            elif image_base64.startswith("iVBOR"):
                content_type = "image/png"
                extension = "png"
            elif image_base64.startswith("/9j/"):
                content_type = "image/jpeg"
                extension = "jpg"

            # 在发送前保存一份图片到本地
            if self._save_recent_covers:
                try:
                    image_bytes = base64.b64decode(image_base64)
                    self.__save_image_to_local(image_bytes, service.name, library['Name'], extension)
                except Exception as save_err:
                    logger.error(f"保存发送前图片失败: {str(save_err)}")
            
            res = service.instance.post_data(
                url=url,
                data=image_base64,
                headers={
                    "Content-Type": content_type
                }
            )
            
            if res and res.status_code in [200, 204]:
                return True
            else:
                logger.error(f"设置「{library['Name']}」封面失败，错误码：{res.status_code if res else 'No response'}")
                return False
        except Exception as err:
            logger.error(f"设置「{library['Name']}」封面失败：{str(err)}")
        return False

    def prepare_library_images(self, library_dir: str, required_items: int = 9):
        """
        准备目录下的 1~required_items.jpg 图片文件:
        1. 检查已有的目标编号文件
        2. 保留已有的文件，只补足缺失的编号
        3. 补充文件时尽量避免连续使用相同的源图片
        """
        os.makedirs(library_dir, exist_ok=True)

        required_items = max(1, int(required_items))

        # 检查哪些编号的文件已存在，哪些缺失
        existing_numbers = []
        missing_numbers = []
        for i in range(1, required_items + 1):
            target_file_path = os.path.join(library_dir, f"{i}.jpg")
            if os.path.exists(target_file_path):
                existing_numbers.append(i)
            else:
                missing_numbers.append(i)

        # 如果已经存在所有文件，直接返回
        if not missing_numbers:
            return True

        logger.info(f"信息: {library_dir} 中缺少以下编号的图片: {missing_numbers}，将进行补充。")

        target_name_pattern = rf"^[1-9][0-9]*\.jpg$"

        # 获取可用作源的图片（排除已有的目标编号文件）
        # 使用 scandir 并限制采样数量，避免超大目录扫描导致长时间无日志
        source_image_filenames = []
        max_source_scan = 512
        scanned_entries = 0
        for entry in os.scandir(library_dir):
            scanned_entries += 1
            if not entry.is_file():
                continue

            f = entry.name
            # 排除 N.jpg（N 为正整数）作为源
            if re.match(target_name_pattern, f, re.IGNORECASE):
                continue
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                source_image_filenames.append(f)
                if len(source_image_filenames) >= max_source_scan:
                    break

        if scanned_entries > 2000:
            logger.info(f"信息: {library_dir} 文件较多，已快速采样 {len(source_image_filenames)} 张作为补图源")

        # 如果没有源图片可用
        if not source_image_filenames:
            # 如果已经有部分目标编号图片，可以从这些现有文件中选择
            if existing_numbers:
                logger.info(f"信息: {library_dir} 中没有其他图片可用，将从现有目标编号图片中随机选择进行复制。")
                existing_file_paths = [os.path.join(library_dir, f"{i}.jpg") for i in existing_numbers]
                source_image_paths = existing_file_paths
            else:
                logger.info(f"警告: {library_dir} 中没有任何可用的图片来生成 1-{required_items}.jpg。")
                return False
        else:
            # 将文件名转换为完整路径
            source_image_paths = [os.path.join(library_dir, f) for f in sorted(source_image_filenames)]

        # 如果源图片数量不足，需要重复使用
        if len(source_image_paths) < len(missing_numbers):
            logger.info(f"信息: 源图片数量({len(source_image_paths)})小于缺失数量({len(missing_numbers)})，某些图片将被重复使用。")
        
        # 为每个缺失的编号选择一个源图片，尽量避免连续重复
        last_used_source = None
        for missing_num in missing_numbers:
            target_path = os.path.join(library_dir, f"{missing_num}.jpg")
            
            # 如果只有一个源文件，没有选择，直接使用
            if len(source_image_paths) == 1:
                selected_source = source_image_paths[0]
            else:
                # 尝试选择一个与上次不同的源文件
                available_sources = [s for s in source_image_paths if s != last_used_source]
                
                # 如果没有其他选择（可能上次用了唯一的源文件），则使用所有源
                if not available_sources:
                    available_sources = source_image_paths
                    
                # 随机选择一个源文件
                selected_source = random.choice(available_sources)
                
            # 记录本次使用的源文件，用于下次比较
            last_used_source = selected_source
            
            try:
                if not os.path.exists(selected_source):
                    logger.info(f"错误: 源文件 {selected_source} 在尝试复制前找不到了！")
                    return False
                    
                shutil.copy(selected_source, target_path)
                logger.info(f"信息: 已创建 {missing_num}.jpg (源自: {os.path.basename(selected_source)})")
                
            except Exception as e:
                logger.info(f"错误: 复制文件 {selected_source} 到 {target_path} 时发生错误: {e}")
                return False

        logger.info(f"信息: {library_dir} 已成功补充所有缺失的图片，现在包含完整的 1-{required_items}.jpg")
        return True

