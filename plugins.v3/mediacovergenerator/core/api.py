import mimetypes
from typing import Any, Dict, List, Optional, Tuple

try:
    from app.sdk.logging import logger
except ImportError:
    from app.log import logger

class ApiManagerMixin:
    @staticmethod
    def _api_response(code: int, msg: str, data: Any = None) -> Dict[str, Any]:
        return {
            "success": code == 0,
            "message": msg or "",
            "data": data,
        }

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        """
        return [
            {"path": "/clean_images", "endpoint": self.api_clean_images, "methods": ["POST", "GET"], "summary": "立即清理封面图片缓存"},
            {"path": "clean_images", "endpoint": self.api_clean_images, "methods": ["POST", "GET"], "summary": "立即清理封面图片缓存(兼容)"},
            {"path": "/clean_fonts", "endpoint": self.api_clean_fonts, "methods": ["POST", "GET"], "summary": "立即清理字体缓存"},
            {"path": "clean_fonts", "endpoint": self.api_clean_fonts, "methods": ["POST", "GET"], "summary": "立即清理字体缓存(兼容)"},
            {"path": "/delete_saved_cover", "endpoint": self.api_delete_saved_cover, "methods": ["POST", "GET"], "summary": "删除一张已保存封面"},
            {"path": "delete_saved_cover", "endpoint": self.api_delete_saved_cover, "methods": ["POST", "GET"], "summary": "删除一张已保存封面(兼容)"},
            {"path": "/generate_now", "endpoint": self.api_generate_now, "methods": ["POST", "GET"], "summary": "立即生成媒体库封面"},
            {"path": "generate_now", "endpoint": self.api_generate_now, "methods": ["POST", "GET"], "summary": "立即生成媒体库封面(兼容)"},
            {"path": "/set_cover_style", "endpoint": self.api_set_cover_style, "methods": ["POST", "GET"], "summary": "保存封面风格选择"},
            {"path": "set_cover_style", "endpoint": self.api_set_cover_style, "methods": ["POST", "GET"], "summary": "保存封面风格选择(兼容)"},
            {"path": "/toggle_style_variant", "endpoint": self.api_toggle_style_variant, "methods": ["POST", "GET"], "summary": "切换静态/动态"},
            {"path": "toggle_style_variant", "endpoint": self.api_toggle_style_variant, "methods": ["POST", "GET"], "summary": "切换静态/动态(兼容)"},
            {"path": "/select_style_1", "endpoint": self.api_select_style_1, "methods": ["POST", "GET"], "summary": "选择风格1"},
            {"path": "/select_style_2", "endpoint": self.api_select_style_2, "methods": ["POST", "GET"], "summary": "选择风格2"},
            {"path": "/select_style_3", "endpoint": self.api_select_style_3, "methods": ["POST", "GET"], "summary": "选择风格3"},
            {"path": "/select_style_4", "endpoint": self.api_select_style_4, "methods": ["POST", "GET"], "summary": "选择风格4"},
            {"path": "select_style_1", "endpoint": self.api_select_style_1, "methods": ["POST", "GET"], "summary": "选择风格1(兼容)"},
            {"path": "select_style_2", "endpoint": self.api_select_style_2, "methods": ["POST", "GET"], "summary": "选择风格2(兼容)"},
            {"path": "select_style_3", "endpoint": self.api_select_style_3, "methods": ["POST", "GET"], "summary": "选择风格3(兼容)"},
            {"path": "select_style_4", "endpoint": self.api_select_style_4, "methods": ["POST", "GET"], "summary": "选择风格4(兼容)"},
            {"path": "/set_page_tab_generate", "endpoint": self.api_set_page_tab_generate, "methods": ["POST", "GET"], "summary": "切换到生成页"},
            {"path": "/set_page_tab_history", "endpoint": self.api_set_page_tab_history, "methods": ["POST", "GET"], "summary": "切换到历史页"},
            {"path": "/set_page_tab_clean", "endpoint": self.api_set_page_tab_clean, "methods": ["POST", "GET"], "summary": "切换到清理页"},
            {"path": "set_page_tab_generate", "endpoint": self.api_set_page_tab_generate, "methods": ["POST", "GET"], "summary": "切换到生成页(兼容)"},
            {"path": "set_page_tab_history", "endpoint": self.api_set_page_tab_history, "methods": ["POST", "GET"], "summary": "切换到历史页(兼容)"},
            {"path": "set_page_tab_clean", "endpoint": self.api_set_page_tab_clean, "methods": ["POST", "GET"], "summary": "切换到清理页(兼容)"},
            {"path": "/saved_cover_image", "endpoint": self.api_saved_cover_image, "methods": ["GET"], "summary": "获取已保存封面图片"},
            {"path": "saved_cover_image", "endpoint": self.api_saved_cover_image, "methods": ["GET"], "summary": "获取已保存封面图片(兼容)"},
        ]

    def api_clean_images(self, apikey: Optional[str] = None):
        try:
            logger.info("【MediaCoverGenerator】收到立即清理图片缓存请求")
            self._clean_generated_images()
            self._clean_images = False
            self._update_config()
            return self._api_response(0, "图片缓存清理完成")
        except Exception as e:
            logger.error(f"【MediaCoverGenerator】立即清理图片失败: {e}", exc_info=True)
            return self._api_response(1, f"图片缓存清理失败: {e}")

    def api_clean_fonts(self, apikey: Optional[str] = None):
        try:
            logger.info("【MediaCoverGenerator】收到立即清理字体缓存请求")
            self._clean_downloaded_fonts()
            self._clean_fonts = False
            self._update_config()
            return self._api_response(0, "字体缓存清理完成")
        except Exception as e:
            logger.error(f"【MediaCoverGenerator】立即清理字体失败: {e}", exc_info=True)
            return self._api_response(1, f"字体缓存清理失败: {e}")

    def api_delete_saved_cover(self, file: Optional[str] = None, apikey: Optional[str] = None):
        try:
            target_file = self._resolve_saved_cover_path(file)
            if not target_file:
                return self._api_response(1, "无效文件路径")
            if not target_file.exists() or not target_file.is_file():
                return self._api_response(1, "文件不存在")
            target_file.unlink(missing_ok=True)
            logger.info(f"【MediaCoverGenerator】已删除封面文件: {target_file}")
            return self._api_response(0, "封面文件删除成功")
        except Exception as e:
            logger.error(f"【MediaCoverGenerator】删除封面文件失败: {e}", exc_info=True)
            return self._api_response(1, f"封面文件删除失败: {e}")

    def api_generate_now(self, style: Optional[str] = None, apikey: Optional[str] = None):
        old_style = self._cover_style
        try:
            if not self._enabled:
                logger.warning("【MediaCoverGenerator】立即生成失败：插件未启用，请先在设置页启用插件并保存")
                return self._api_response(1, "插件未启用，请先在设置页启用插件并保存")
            if not self._selected_servers:
                logger.warning("【MediaCoverGenerator】立即生成失败：未勾选媒体服务器，请先在设置页勾选服务器并保存")
                return self._api_response(1, "未勾选媒体服务器，请先在设置页勾选服务器并保存")
            if not self._servers:
                logger.warning("【MediaCoverGenerator】立即生成失败：服务器连接信息为空，请检查设置并保存后重试")
                return self._api_response(1, "服务器连接信息为空，请检查设置并保存后重试")

            target_style = (style or "").strip()
            allowed_styles = {
                "static_1", "static_2", "static_3", "static_4",
                "animated_1", "animated_2", "animated_3", "animated_4",
            }
            if target_style:
                if target_style not in allowed_styles:
                    return self._api_response(1, f"不支持的风格: {target_style}")
                self._cover_style = target_style
            logger.info(f"【MediaCoverGenerator】收到立即生成请求，风格: {self._cover_style}")
            tips = self._update_all_libraries()
            return self._api_response(0, tips or "封面生成任务已完成")
        except Exception as e:
            logger.error(f"【MediaCoverGenerator】立即生成失败: {e}", exc_info=True)
            return self._api_response(1, f"封面生成失败: {e}")
        finally:
            self._cover_style = old_style

    def api_set_cover_style(self, style: Optional[str] = None, apikey: Optional[str] = None):
        try:
            target_style = (style or "").strip()
            allowed_styles = {
                "static_1", "static_2", "static_3", "static_4",
                "animated_1", "animated_2", "animated_3", "animated_4",
            }
            if target_style not in allowed_styles:
                return self._api_response(1, f"不支持的风格: {target_style}")
            self._cover_style = target_style
            base, variant = self._resolve_cover_style_ui(target_style)
            self._cover_style_base = base
            self._cover_style_variant = variant
            self._update_config()
            logger.info(f"【MediaCoverGenerator】已保存封面风格: {target_style}")
            return self._api_response(0, f"已保存风格: {target_style}")
        except Exception as e:
            logger.error(f"【MediaCoverGenerator】保存封面风格失败: {e}", exc_info=True)
            return self._api_response(1, f"保存风格失败: {e}")

    def _get_cover_style_parts(self) -> Tuple[str, int]:
        style = (self._cover_style or "static_1").strip()
        variant = "animated" if style.startswith("animated_") else "static"
        try:
            index = int(style.split("_")[-1])
        except Exception:
            index = 1
        index = max(1, min(4, index))
        return variant, index

    def _set_cover_style_parts(self, variant: str, index: int):
        safe_variant = "animated" if variant == "animated" else "static"
        safe_index = max(1, min(4, int(index)))
        target_style = f"{safe_variant}_{safe_index}"
        self._cover_style = target_style
        self._cover_style_base = f"static_{safe_index}"
        self._cover_style_variant = safe_variant
        self._update_config()
        logger.info(f"【MediaCoverGenerator】已保存封面风格: {target_style}")

    def api_toggle_style_variant(self, apikey: Optional[str] = None):
        try:
            variant, index = self._get_cover_style_parts()
            new_variant = "animated" if variant == "static" else "static"
            self._set_cover_style_parts(new_variant, index)
            return self._api_response(0, f"已切换为{new_variant}风格{index}")
        except Exception as e:
            logger.error(f"【MediaCoverGenerator】切换静态/动态失败: {e}", exc_info=True)
            return self._api_response(1, f"切换失败: {e}")

    def _api_select_style(self, index: int):
        try:
            variant, _ = self._get_cover_style_parts()
            self._set_cover_style_parts(variant, index)
            return self._api_response(0, f"已选择{variant}风格{index}")
        except Exception as e:
            logger.error(f"【MediaCoverGenerator】选择风格失败: {e}", exc_info=True)
            return self._api_response(1, f"选择风格失败: {e}")

    def api_select_style_1(self, apikey: Optional[str] = None):
        return self._api_select_style(1)

    def api_select_style_2(self, apikey: Optional[str] = None):
        return self._api_select_style(2)

    def api_select_style_3(self, apikey: Optional[str] = None):
        return self._api_select_style(3)

    def api_select_style_4(self, apikey: Optional[str] = None):
        return self._api_select_style(4)

    def _set_page_tab(self, tab: str):
        self._page_tab = tab if tab in ["generate-tab", "history-tab", "clean-tab"] else "generate-tab"
        logger.info(f"【MediaCoverGenerator】已切换页面Tab: {self._page_tab}")

    def api_set_page_tab_generate(self, apikey: Optional[str] = None):
        self._set_page_tab("generate-tab")
        return self._api_response(0, "已切换到封面生成")

    def api_set_page_tab_history(self, apikey: Optional[str] = None):
        self._set_page_tab("history-tab")
        return self._api_response(0, "已切换到历史封面")

    def api_set_page_tab_clean(self, apikey: Optional[str] = None):
        self._set_page_tab("clean-tab")
        return self._api_response(0, "已切换到清理缓存")

    def api_saved_cover_image(self, file: Optional[str] = None, apikey: Optional[str] = None):
        target_file = self._resolve_saved_cover_path(file)
        if not target_file or not target_file.exists() or not target_file.is_file():
            return self._api_response(1, "图片不存在")
        mime_type, _ = mimetypes.guess_type(str(target_file))
        if not mime_type:
            mime_type = "image/jpeg"
        try:
            from fastapi.responses import FileResponse
            return FileResponse(path=str(target_file), media_type=mime_type)
        except Exception:
            try:
                from starlette.responses import FileResponse
                return FileResponse(path=str(target_file), media_type=mime_type)
            except Exception as e:
                logger.error(f"【MediaCoverGenerator】返回图片失败: {e}")
                return self._api_response(1, "返回图片失败")
