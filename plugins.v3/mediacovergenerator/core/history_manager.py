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



class HistoryManagerMixin:
    def _get_recent_generated_covers(self, limit: int = 20) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        cover_dirs: List[Path] = []

        if self._covers_output:
            cover_dirs.append(Path(self._covers_output))
        data_path = self.get_data_path()
        default_output = data_path / "output"
        if default_output.exists():
            cover_dirs.append(default_output)

        allowed_ext = {".jpg", ".jpeg", ".png", ".gif", ".apng", ".webp"}
        seen = set()
        for directory in cover_dirs:
            key = str(directory)
            if key in seen:
                continue
            seen.add(key)
            if not directory.exists() or not directory.is_dir():
                continue
            for file_path in directory.iterdir():
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in allowed_ext:
                    continue
                try:
                    stat = file_path.stat()
                    
                    try:
                        from PIL import Image
                        from io import BytesIO
                        import base64
                        
                        # 动态生成缩略图进行 Base64 传输
                        # 1. 彻底绕开 /api/v1/plugin 外部接口存在的 401 鉴权问题
                        # 2. 将几十 MB 的动图压缩为了几十 KB 的缩略图，解决前端加载卡死问题
                        with Image.open(file_path) as img:
                            if hasattr(img, 'is_animated') and img.is_animated:
                                img.seek(0)
                                
                            thumb = img.copy()
                            if thumb.mode != 'RGB':
                                thumb = thumb.convert('RGB')
                                
                            thumb.thumbnail((480, 270))
                            buf = BytesIO()
                            thumb.save(buf, format="JPEG", quality=75)
                            image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                            image_src = f"data:image/jpeg;base64,{image_b64}"
                            
                    except Exception as img_err:
                        logger.debug(f"生成缩略图失败 {file_path}: {img_err}")
                        continue

                    items.append(
                        {
                            "name": file_path.name,
                            "path": str(file_path),
                            "mtime_ts": float(stat.st_mtime),
                            "mtime": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                            "size": self._format_size(stat.st_size),
                            "src": image_src,
                        }
                    )
                except Exception as e:
                    logger.debug(f"读取封面文件信息失败: {file_path} -> {e}")

        items.sort(key=lambda x: x.get("mtime_ts", 0.0), reverse=True)
        return items[:max(1, int(limit))]

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        try:
            size = float(size_bytes)
        except (TypeError, ValueError):
            return "0 B"
        units = ["B", "KB", "MB", "GB"]
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
            size /= 1024
        return f"{int(size_bytes)} B"

    def _get_saved_cover_dirs(self) -> List[Path]:
        result: List[Path] = []
        if self._covers_output:
            result.append(Path(self._covers_output))
        data_path = self.get_data_path()
        default_output = data_path / "output"
        result.append(default_output)
        unique: List[Path] = []
        seen = set()
        for directory in result:
            key = str(directory)
            if key in seen:
                continue
            seen.add(key)
            unique.append(directory)
        return unique

    def _resolve_saved_cover_path(self, raw_path: str) -> Optional[Path]:
        if not raw_path:
            return None
        decoded = unquote(str(raw_path)).strip()
        target = Path(decoded).expanduser()
        if not target.is_absolute():
            return None
        allowed_dirs = self._get_saved_cover_dirs()
        for directory in allowed_dirs:
            try:
                root = directory.resolve()
                file_path = target.resolve()
                if str(file_path).startswith(str(root) + os.sep) or file_path == root:
                    return file_path
            except Exception:
                continue
        return None

    def _get_recent_cover_output_dir(self) -> Path:
        if self._covers_output:
            return Path(self._covers_output).expanduser()
        return self.get_data_path() / "output"

    def _save_image_to_local(self, image_content, server_name: str, library_name: str, extension: str):
        """
        保存图片到本地路径
        """
        try:
            if not self._save_recent_covers:
                return
            # 确保目录存在
            local_path = str(self._get_recent_cover_output_dir())
            os.makedirs(local_path, exist_ok=True)

            safe_server = self._sanitize_filename(server_name) or "server"
            safe_library = self._sanitize_filename(library_name) or "library"
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = extension.strip(".").lower() if extension else "jpg"
            filename = f"{safe_server}_{safe_library}_{timestamp}.{ext}"

            file_path = os.path.join(local_path, filename)
            with open(file_path, "wb") as f:
                f.write(image_content)
            logger.info(f"图片已保存到本地: {file_path}")
            self._trim_saved_cover_history(local_path, safe_server, safe_library)
        except Exception as err:
            logger.error(f"保存图片到本地失败: {str(err)}")

    def _trim_saved_cover_history(self, local_path: str, safe_server: str, safe_library: str):
        limit = self._clamp_value(
            self._covers_history_limit_per_library,
            1,
            100,
            10,
            "covers_history_limit_per_library[trim]",
            int,
        )
        pattern = f"{safe_server}_{safe_library}_"
        candidate_files: List[Path] = []
        try:
            for file_name in os.listdir(local_path):
                lower_name = file_name.lower()
                if not lower_name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".apng")):
                    continue
                if not file_name.startswith(pattern):
                    continue
                file_path = Path(local_path) / file_name
                if file_path.is_file():
                    candidate_files.append(file_path)
            if len(candidate_files) <= limit:
                return
            candidate_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for old_file in candidate_files[limit:]:
                old_file.unlink(missing_ok=True)
                logger.info(f"已按历史数量限制删除旧封面: {old_file}")
        except Exception as e:
            logger.warning(f"清理历史封面失败: {e}")

    def clean_cover_history(self, save=True):
        history = self.get_data('cover_history') or []
        cleaned = []

        for item in history:
            try:
                cleaned_item = {
                    "server": item["server"],
                    "library_id": str(item["library_id"]),
                    "item_id": str(item["item_id"]),
                    "timestamp": float(item["timestamp"])
                }
                cleaned.append(cleaned_item)
            except (KeyError, ValueError, TypeError):
                # 如果字段缺失或格式错误则跳过该项
                continue

        if save:
            self.save_data('cover_history', cleaned)

        return cleaned

    def update_cover_history(self, server, library_id, item_id):
        now = time.time()
        item_id = str(item_id)
        library_id = str(library_id)

        history_item = {
            "server": server,
            "library_id": library_id,
            "item_id": item_id,
            "timestamp": now
        }

        # 原始数据
        history = self.get_data('cover_history') or []

        # 用于分组管理：(server, library_id) => list of items
        grouped = defaultdict(list)
        for item in history:
            key = (item["server"], str(item["library_id"]))
            grouped[key].append(item)

        key = (server, library_id)
        items = grouped[key]

        # 查找是否已有该 item_id
        existing = next((i for i in items if str(i["item_id"]) == item_id), None)

        if existing:
            # 若已存在且是最新的，跳过
            if existing["timestamp"] >= max(i["timestamp"] for i in items):
                return
            else:
                existing["timestamp"] = now
        else:
            items.append(history_item)

        # 排序 + 截取前9
        grouped[key] = sorted(items, key=lambda x: x["timestamp"], reverse=True)[:9]

        # 重新整合所有分组的数据
        new_history = []
        for item_list in grouped.values():
            new_history.extend(item_list)

        self.save_data('cover_history', new_history)
        return [ 
            item for item in new_history
            if str(item.get("library_id")) == str(library_id)
        ]

