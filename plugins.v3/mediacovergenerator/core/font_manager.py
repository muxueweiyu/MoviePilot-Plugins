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



class FontManagerMixin:
    def _font_search_dirs(self) -> List[Path]:
        dirs: List[Path] = []
        if self._font_path:
            dirs.append(Path(self._font_path))
        repo_font_dir = Path(__file__).resolve().parents[2] / "fonts"
        dirs.append(repo_font_dir)
        unique_dirs: List[Path] = []
        seen = set()
        for directory in dirs:
            key = str(directory)
            if key in seen:
                continue
            seen.add(key)
            if directory.exists() and directory.is_dir():
                unique_dirs.append(directory)
        return unique_dirs

    def _find_font_file(self, aliases: List[str], exts: List[str]) -> Optional[str]:
        normalized_aliases = [item.lower() for item in aliases if item]
        normalized_aliases_compact = [re.sub(r'[\s_\-]+', '', item) for item in normalized_aliases]
        normalized_exts = [item.lower() for item in exts]
        for directory in self._font_search_dirs():
            candidates = sorted(directory.iterdir(), key=lambda p: p.name.lower())
            for font_file in candidates:
                if not font_file.is_file():
                    continue
                suffix = font_file.suffix.lower()
                if suffix not in normalized_exts:
                    continue
                stem = font_file.stem.lower()
                name = font_file.name.lower()
                stem_compact = re.sub(r'[\s_\-]+', '', stem)
                name_compact = re.sub(r'[\s_\-]+', '', name)
                if any(
                    alias in stem or alias in name or compact in stem_compact or compact in name_compact
                    for alias, compact in zip(normalized_aliases, normalized_aliases_compact)
                ):
                    return str(font_file)
        return None

    def _get_font_presets(self) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], Dict[str, Optional[str]], Dict[str, Optional[str]]]:
        zh_specs = [
            {"title": "潮黑", "value": "chaohei", "aliases": ["chaohei", "wendao", "潮黑", "chao_hei"]},
            {"title": "粗雅宋", "value": "yasong", "aliases": ["yasong", "粗雅宋", "multi_1_zh", "ya_song"]},
        ]
        en_specs = [
            {"title": "EmblemaOne", "value": "EmblemaOne", "aliases": ["emblemaone", "emblema_one"]},
            {"title": "Melete", "value": "Melete", "aliases": ["melete", "multi_1_en"]},
            {"title": "Phosphate", "value": "Phosphate", "aliases": ["phosphate", "phosphat"]},
            {"title": "JosefinSans", "value": "JosefinSans", "aliases": ["josefinsans", "josefin_sans"]},
            {"title": "LilitaOne", "value": "LilitaOne", "aliases": ["lilitaone", "lilita_one"]},
            {"title": "Monoton", "value": "Monoton", "aliases": ["monoton"]},
            {"title": "Plaster", "value": "Plaster", "aliases": ["plaster"]},
        ]
        all_specs = []
        seen_values = set()
        for spec in zh_specs + en_specs:
            if spec["value"] in seen_values:
                continue
            seen_values.add(spec["value"])
            value_alias = spec["value"].lower()
            compact_value_alias = re.sub(r'[\s_\-]+', '', value_alias)
            if value_alias not in spec["aliases"]:
                spec["aliases"].append(value_alias)
            if compact_value_alias and compact_value_alias not in spec["aliases"]:
                spec["aliases"].append(compact_value_alias)
            title_alias = spec["title"].lower()
            compact_title_alias = re.sub(r'[\s_\-]+', '', title_alias)
            if title_alias not in spec["aliases"]:
                spec["aliases"].append(title_alias)
            if compact_title_alias and compact_title_alias not in spec["aliases"]:
                spec["aliases"].append(compact_title_alias)
            all_specs.append(spec)
        zh_paths: Dict[str, Optional[str]] = {}
        en_paths: Dict[str, Optional[str]] = {}
        zh_items: List[Dict[str, str]] = []
        en_items: List[Dict[str, str]] = []
        zh_exts = [".ttf", ".otf", ".woff2", ".woff"]
        en_exts = [".ttf", ".otf", ".woff2", ".woff"]

        for spec in all_specs:
            found = self._find_font_file(spec["aliases"], zh_exts)
            zh_paths[spec["value"]] = found
            zh_items.append({"title": spec["title"], "value": spec["value"]})
        for spec in all_specs:
            found = self._find_font_file(spec["aliases"], en_exts)
            en_paths[spec["value"]] = found
            en_items.append({"title": spec["title"], "value": spec["value"]})
        return zh_items, en_items, zh_paths, en_paths

    def _get_fonts(self):
        def detect_string_type(s: str):
            if not s:
                return None
            s = s.strip()

            # 判断是否是 HTTP(S) 链接
            if re.match(r'^https?://[^\s]+$', s, re.IGNORECASE):
                return 'url'

            # 判断是否像路径（包含 / 或 \，或以 ~、.、/ 开头）
            if os.path.isabs(s) or s.startswith(('.', '~', '/')) or re.search(r'[\\/]', s):
                return 'path'

            return None
        
        font_dir_path = self._font_path
        Path(font_dir_path).mkdir(parents=True, exist_ok=True)

        _, _, zh_preset_paths, en_preset_paths = self._get_font_presets()

        if not self._zh_font_preset:
            self._zh_font_preset = "chaohei"

        default_font_url = {
            "chaohei": "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/chaohei.ttf",
            "yasong": "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/yasong.ttf",
            "EmblemaOne": "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/EmblemaOne.woff2",
            "Melete": "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/Melete.otf",
            "Phosphate": "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/phosphate.ttf",
            "JosefinSans": "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/josefinsans.woff2",
            "LilitaOne": "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/lilitaone.woff2",
            "Monoton": "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/Monoton.woff2",
            "Plaster": "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/Plaster.woff2",
        }
        default_zh_url = default_font_url.get(self._zh_font_preset, "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/chaohei.ttf")

        if not self._en_font_preset:
            self._en_font_preset = "EmblemaOne"

        default_en_url = default_font_url.get(self._en_font_preset, "https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/fonts/EmblemaOne.woff2")
        
        log_prefix = "默认"
        zh_custom_type = detect_string_type(self._zh_font_custom)
        en_custom_type = detect_string_type(self._en_font_custom)
        current_zh_font_url = self._zh_font_custom if zh_custom_type == 'url' else default_zh_url
        current_en_font_url = self._en_font_custom if en_custom_type == 'url' else default_en_url
        zh_local_path_config = self._zh_font_custom if zh_custom_type == 'path' else zh_preset_paths.get(self._zh_font_preset)
        en_local_path_config = self._en_font_custom if en_custom_type == 'path' else en_preset_paths.get(self._en_font_preset)

        downloaded_zh_font_base = f"{self._zh_font_preset}_custom" if zh_custom_type == 'url' else self._zh_font_preset
        downloaded_en_font_base = f"{self._en_font_preset}_custom" if en_custom_type == 'url' else self._en_font_preset
        hash_zh_file_name = f"{downloaded_zh_font_base}_url.hash"
        hash_en_file_name = f"{downloaded_en_font_base}_url.hash"
        final_zh_font_path_attr = "_zh_font_path"
        final_en_font_path_attr = "_en_font_path"

        logger.info(f"当前主标题字体URL: {current_zh_font_url} (本地路径: {zh_local_path_config})")

        active_fonts_to_process = [
            {
                "lang": "主标题",
                "url": current_zh_font_url,
                "local_path_config": zh_local_path_config,
                "download_base_name": downloaded_zh_font_base,
                "hash_file_name": hash_zh_file_name,
                "final_attr_name": final_zh_font_path_attr,
                "fallback_ext": ".ttf"
            },
            {
                "lang": "副标题",
                "url": current_en_font_url,
                "local_path_config": en_local_path_config,
                "download_base_name": downloaded_en_font_base,
                "hash_file_name": hash_en_file_name,
                "final_attr_name": final_en_font_path_attr,
                "fallback_ext": ".ttf"
            }
        ]


        for font_info in active_fonts_to_process:
            lang = font_info["lang"]
            url = font_info["url"]
            local_path_cfg = font_info["local_path_config"]
            download_base = font_info["download_base_name"]
            hash_filename = font_info["hash_file_name"]
            final_attr = font_info["final_attr_name"]
            fallback_ext = font_info["fallback_ext"]


            extension = self.get_file_extension_from_url(url, fallback_ext=fallback_ext)
            downloaded_font_file_path = Path(font_dir_path) / f"{download_base}{extension}"
            hash_file_path = Path(font_dir_path) / hash_filename
            
            current_font_path = None
            using_local_font = False
            if local_path_cfg:
                local_font_p = Path(local_path_cfg)
                if validate_font_file(local_font_p):
                    logger.info(f"{lang}字体: 使用本地指定路径 {local_font_p}")
                    current_font_path = local_font_p
                    using_local_font = True
                else:
                    logger.warning(f"{log_prefix}{lang}字体: 本地指定路径 {local_font_p} 无效或文件不存在。")

            if not using_local_font:
                url_hash = hashlib.md5(url.encode()).hexdigest()
                url_has_changed = True
                if hash_file_path.exists():
                    try:
                        if hash_file_path.read_text() == url_hash:
                            url_has_changed = False
                    except Exception as e:
                        logger.warning(f"读取哈希文件失败 {hash_file_path}: {e}。将重新下载。")
                
                font_file_is_valid = validate_font_file(downloaded_font_file_path)

                if url_has_changed or not font_file_is_valid:
                    if url_has_changed:
                        logger.info(f"{log_prefix}{lang}字体URL已更改或首次下载。")
                    if not font_file_is_valid and downloaded_font_file_path.exists():
                         logger.info(f"{log_prefix}{lang}字体文件 {downloaded_font_file_path} 无效或损坏，将重新下载。")
                    elif not downloaded_font_file_path.exists():
                         logger.info(f"{log_prefix}{lang}字体文件 {downloaded_font_file_path} 不存在，将下载。")

                    # 使用安全的字体下载方法
                    if self.download_font_safely_with_timeout(url, downloaded_font_file_path):
                        try:
                            hash_file_path.write_text(url_hash)
                        except Exception as e:
                            logger.error(f"写入哈希文件失败 {hash_file_path}: {e}")
                        current_font_path = downloaded_font_file_path
                    else:
                        logger.critical(f"无法获取必要的{log_prefix}{lang}支持字体: {url}")
                        if font_file_is_valid :
                             logger.warning(f"下载失败，但找到一个已存在的（可能旧版本）有效字体文件 {downloaded_font_file_path}，将尝试使用。")
                             current_font_path = downloaded_font_file_path
                        else:
                             current_font_path = None
                else:
                    logger.info(f"{log_prefix}{lang}字体: 使用已下载/缓存的有效字体 {downloaded_font_file_path}")
                    current_font_path = downloaded_font_file_path
            
            # 安全设置字体路径
            if current_font_path and current_font_path.exists():
                setattr(self, final_attr, current_font_path)
                status_log = '(本地路径)' if using_local_font else '(已下载/缓存)'
                logger.info(f"{log_prefix}{lang}字体最终路径: {getattr(self,final_attr)} {status_log}")
            else:
                # 字体获取失败，设置为None并记录错误
                setattr(self, final_attr, None)
                logger.error(f"{log_prefix}{lang}字体获取失败，这可能导致封面生成失败")

        # 检查是否所有必要的字体都已获取
        if not self._zh_font_path or not self._en_font_path:
            logger.critical("关键字体文件缺失，插件可能无法正常工作。请检查网络连接或手动下载字体文件。")

    def download_font_safely_with_timeout(self, font_url: str, font_path: Path, timeout: int = 60) -> bool:
        """
        带超时的安全字体下载方法，避免首次下载时阻塞过久
        """
        try:
            logger.info(f"开始下载字体（超时限制: {timeout}秒）: {font_url}")
            return self.download_font_safely(font_url, font_path, retries=1, timeout=timeout)

        except Exception as e:
            logger.error(f"字体下载过程中出现异常: {e}")
            return False

    def download_font_safely(self, font_url: str, font_path: Path, retries: int = 2, timeout: int = 30):
        """
        从链接下载字体文件到指定目录，使用优化的网络助手
        :param font_url: 字体文件URL
        :param font_path: 保存路径
        :param retries: 每种策略的最大重试次数（减少重试次数）
        :param timeout: 下载超时时间
        :return: 是否下载成功
        """
        logger.info(f"准备下载字体: {font_url} -> {font_path}")

        # 确保在开始下载前删除任何可能存在的损坏文件
        if font_path.exists():
            try:
                font_path.unlink()
                logger.info(f"删除之前的字体文件以便重新下载: {font_path}")
            except OSError as unlink_error:
                logger.error(f"无法删除现有字体文件 {font_path}: {unlink_error}")
                return False
        
        # 使用优化的网络助手进行下载
        network_helper = NetworkHelper(timeout=timeout, max_retries=retries)

        # 准备下载策略
        strategies = []

        # 判断是否为GitHub链接
        is_github_url = "github.com" in font_url or "raw.githubusercontent.com" in font_url

        # 对于GitHub链接，优先使用GitHub镜像站
        if is_github_url and settings.GITHUB_PROXY:
            github_proxy_url = f"{UrlUtils.standardize_base_url(settings.GITHUB_PROXY)}{font_url}"
            strategies.append(("GitHub镜像站", github_proxy_url))

        # 直接使用原始URL
        strategies.append(("直连", font_url))

        # 遍历所有策略
        for strategy_name, target_url in strategies:
            logger.info(f"尝试使用策略：{strategy_name} 下载字体: {target_url}")

            # 创建临时文件路径
            temp_path = font_path.with_suffix('.temp')

            try:
                # 使用网络助手下载
                if network_helper.download_file_sync(target_url, temp_path):
                    # 验证下载的字体文件
                    if validate_font_file(temp_path):
                        # 验证通过后，将临时文件移动到正确位置
                        temp_path.replace(font_path)
                        logger.info(f"字体下载成功: 使用策略 {strategy_name}")
                        return True
                    else:
                        logger.warning(f"下载的字体文件验证失败，可能已损坏")
                        if temp_path.exists():
                            temp_path.unlink()
                else:
                    logger.warning(f"策略 {strategy_name} 下载失败")

            except Exception as e:
                logger.warning(f"策略 {strategy_name} 下载出错: {e}")
                # 清理可能的临时文件
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
        
        # 所有策略都失败
        logger.error(f"所有下载策略均失败，无法下载字体，建议手动下载字体: {font_url}")
        # 确保目标路径没有损坏的文件
        if font_path.exists():
            try:
                font_path.unlink()
                logger.info(f"已删除部分下载的文件: {font_path}")
            except OSError as unlink_error:
                logger.error(f"无法删除部分下载的文件 {font_path}: {unlink_error}")
        
        return False

    def get_file_extension_from_url(self, url: str, fallback_ext: str = ".ttf") -> str:
        """
        从链接获取字体扩展名扩展名
        """
        try:
            parsed_url = urlparse(url)
            path_part = parsed_url.path
            if path_part:
                filename = os.path.basename(path_part)
                _ , ext = os.path.splitext(filename)
                return ext if ext else fallback_ext
            else:
                logger.warning(f"无法从URL中提取路径部分: {url}. 使用备用扩展名: {fallback_ext}")
                return fallback_ext
        except Exception as e:
            logger.error(f"解析URL时出错 '{url}': {e}. 使用备用扩展名: {fallback_ext}")
            return fallback_ext

    def _validate_font_file(self, font_path: Path):
        if not font_path or not font_path.exists() or not font_path.is_file():
            return False
        
        try:
            with open(font_path, "rb") as f:
                header = f.read(4) 
                if (header.startswith(b'\x00\x01\x00\x00') or
                    header.startswith(b'OTTO') or
                    header.startswith(b'true') or
                    header.startswith(b'wOFF') or
                    header.startswith(b'wOF2')):
                    return True
                if font_path.suffix.lower() == ".svg":
                    f.seek(0)
                    sample = f.read(100).decode(errors='ignore').strip()
                    if sample.startswith('<svg') or sample.startswith('<?xml'):
                        return True
                if font_path.suffix.lower() == ".bdf":
                    f.seek(0)
                    sample = f.read(9).decode(errors='ignore')
                    if sample == "STARTFONT":
                        return True
            logger.warning(f"字体文件存在但可能已损坏或格式无法识别: {font_path}")
            return False
        except Exception as e:
            logger.warning(f"验证字体文件时出错 {font_path}: {e}")
            return False

