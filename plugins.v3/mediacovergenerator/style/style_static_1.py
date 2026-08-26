import base64
import random
import colorsys
from collections import Counter
from io import BytesIO
from pathlib import Path
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

try:
    from app.sdk.logging import logger
except ImportError:
    from app.log import logger

try:
    from ..utils.image_manager import (
        ResolutionConfig, ImageResourceManager, managed_image, managed_images
    )
    from ..utils.performance_helper import (
        OptimizedImageProcessor, PerformanceMonitor, memory_efficient_operation
    )
    from ..utils.color_helper import ColorHelper
except ImportError:
    from app.plugins.mediacovergenerator.utils.image_manager import (
        ResolutionConfig, ImageResourceManager, managed_image, managed_images
    )
    from app.plugins.mediacovergenerator.utils.performance_helper import (
        OptimizedImageProcessor, PerformanceMonitor, memory_efficient_operation
    )
    from app.plugins.mediacovergenerator.utils.color_helper import ColorHelper


def is_not_black_white_gray_near(color, threshold=20):
    """判断颜色既不是黑、白、灰，也不是接近黑、白。"""
    r, g, b = color
    if (r < threshold and g < threshold and b < threshold) or \
       (r > 255 - threshold and g > 255 - threshold and b > 255 - threshold):
        return False
    gray_diff_threshold = 10
    if abs(r - g) < gray_diff_threshold and abs(g - b) < gray_diff_threshold and abs(r - b) < gray_diff_threshold:
        return False
    return True

def rgb_to_hsv(color):
    """将 RGB 颜色转换为 HSV 颜色。"""
    r, g, b = [x / 255.0 for x in color]
    return colorsys.rgb_to_hsv(r, g, b)

def hsv_to_rgb(h, s, v):
    """将 HSV 颜色转换为 RGB 颜色。"""
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))

def adjust_color_macaron(color):
    """
    调整颜色使其更接近马卡龙风格：
    - 如果颜色太暗，增加亮度
    - 如果颜色太亮，降低亮度
    - 调整饱和度到适当范围
    """
    h, s, v = rgb_to_hsv(color)
    
    # 马卡龙风格的理想范围
    target_saturation_range = (0.3, 0.7)  # 饱和度范围
    target_value_range = (0.6, 0.85)      # 亮度范围
    
    # 调整饱和度
    if s < target_saturation_range[0]:
        s = target_saturation_range[0]
    elif s > target_saturation_range[1]:
        s = target_saturation_range[1]
    
    # 调整亮度
    if v < target_value_range[0]:
        v = target_value_range[0]  # 太暗，加亮
    elif v > target_value_range[1]:
        v = target_value_range[1]  # 太亮，加暗
    
    return hsv_to_rgb(h, s, v)

def color_distance(color1, color2):
    """计算两个颜色在HSV空间中的距离"""
    h1, s1, v1 = rgb_to_hsv(color1)
    h2, s2, v2 = rgb_to_hsv(color2)
    
    # 色调在环形空间中，需要特殊处理
    h_dist = min(abs(h1 - h2), 1 - abs(h1 - h2))
    
    # 综合距离，给予色调更高的权重
    return h_dist * 5 + abs(s1 - s2) + abs(v1 - v2)

def find_dominant_macaron_colors(image, num_colors=5):
    """
    从图像中提取主要颜色并调整为马卡龙风格：
    1. 过滤掉黑白灰颜色
    2. 从剩余颜色中找到出现频率最高的几种
    3. 调整这些颜色使其接近马卡龙风格
    4. 确保提取的颜色之间有足够的差异
    """
    img = image.copy()
    img.thumbnail((150, 150))
    img = img.convert('RGB')
    pixels = list(img.getdata())
    
    filtered_pixels = [p for p in pixels if is_not_black_white_gray_near(p)]
    if not filtered_pixels:
        return []
    
    color_counter = Counter(filtered_pixels)
    candidate_colors = color_counter.most_common(num_colors * 5)
    
    macaron_colors = []
    min_color_distance = 0.15
    
    for color, _ in candidate_colors:
        adjusted_color = adjust_color_macaron(color)
        if not any(color_distance(adjusted_color, existing) < min_color_distance for existing in macaron_colors):
            macaron_colors.append(adjusted_color)
            if len(macaron_colors) >= num_colors:
                break
    
    return macaron_colors

def adjust_background_color(color, darken_factor=0.85):
    """
    调整背景色，使其适合作为背景：
    - 降低亮度以减少对比度
    - 略微降低饱和度
    """
    h, s, v = rgb_to_hsv(color)
    v = v * darken_factor
    s = s * 0.9
    return hsv_to_rgb(h, s, v)

def darken_color(color, factor=0.7):
    """将颜色加深。"""
    r, g, b = color
    return (int(r * factor), int(g * factor), int(b * factor))

def add_film_grain(image, intensity=0.05):
    """添加胶片颗粒效果"""
    img_array = np.array(image)
    noise = np.random.normal(0, intensity * 255, img_array.shape)
    img_array = img_array + noise
    img_array = np.clip(img_array, 0, 255).astype(np.uint8)
    return Image.fromarray(img_array)

def crop_to_square(img):
    """将图片裁剪为正方形"""
    width, height = img.size
    size = min(width, height)
    left = (width - size) // 2
    top = (height - size) // 2
    right = left + size
    bottom = top + size
    return img.crop((left, top, right, bottom))
    
def add_rounded_corners(img, radius=30):
    """给图片添加圆角，通过超采样技术消除锯齿"""
    factor = 2
    width, height = img.size
    enlarged_img = img.resize((width * factor, height * factor), Image.Resampling.LANCZOS)
    enlarged_img = enlarged_img.convert("RGBA")
    
    mask = Image.new('L', (width * factor, height * factor), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (width * factor, height * factor)], 
                            radius=radius * factor, fill=255)
    
    background = Image.new("RGBA", (width * factor, height * factor), (255, 255, 255, 0))
    high_res_result = Image.composite(enlarged_img, background, mask)
    result = high_res_result.resize((width, height), Image.Resampling.LANCZOS)
    return result

def add_card_shadow(img, offset=(10, 10), radius=10, opacity=0.5):
    """给卡片添加更真实的阴影效果"""
    width, height = img.size
    padding = max(width, height) // 2
    shadow = Image.new("RGBA", (width + padding * 2, height + padding * 2), (0, 0, 0, 0))
    
    orig_mask = Image.new("L", (width, height), 255)
    rounded_mask = add_rounded_corners(orig_mask, radius).convert("L")
    
    shadow_x = padding + offset[0]
    shadow_y = padding + offset[1]
    shadow.paste((0, 0, 0, int(255 * opacity)), 
                (shadow_x, shadow_y, width + shadow_x, height + shadow_y), 
                rounded_mask)
    
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius))
    result = Image.new("RGBA", shadow.size, (0, 0, 0, 0))
    result.paste(shadow, (0, 0), shadow)
    result.paste(img, (padding, padding), img if img.mode == "RGBA" else None)
    return result

def add_shadow_and_rotate(canvas, img, angle, offset=(10, 10), radius=10, opacity=0.5, center_pos=None):
    """先创建阴影并旋转放置，然后旋转图像并放置"""
    width, height = img.size
    if center_pos is None:
        center_pos = (canvas.width // 2, canvas.height // 2)
    
    padding = max(radius * 4, 100)
    shadow_size = (width + padding * 2, height + padding * 2)
    shadow = Image.new("RGBA", shadow_size, (0, 0, 0, 0))
    
    mask_size = (width, height)
    shadow_mask = Image.new("L", mask_size, 255)
    
    if img.mode == "RGBA":
        shadow_mask = img.split()[3]
    
    shadow_center = (padding, padding)
    shadow.paste((0, 0, 0, int(255 * opacity)), 
                (shadow_center[0], shadow_center[1], 
                 shadow_center[0] + width, shadow_center[1] + height), 
                shadow_mask)
    
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius))
    rotated_shadow = rotate_image(shadow, angle)
    shadow_width, shadow_height = rotated_shadow.size
    
    shadow_x = center_pos[0] - shadow_width // 2 + offset[0]
    shadow_y = center_pos[1] - shadow_height // 2 + offset[1]
    canvas.paste(rotated_shadow, (shadow_x, shadow_y), rotated_shadow)
    
    rotated_img = rotate_image(img, angle)
    img_width, img_height = rotated_img.size
    
    img_x = center_pos[0] - img_width // 2
    img_y = center_pos[1] - img_height // 2
    canvas.paste(rotated_img, (img_x, img_y), rotated_img)
    return canvas

def rotate_image(img, angle, bg_color=(0, 0, 0, 0)):
    """旋转图片并确保不会截断图片内容"""
    return img.rotate(angle, Image.BICUBIC, expand=True, fillcolor=bg_color)


@memory_efficient_operation
def create_style_static_1(image_path, title, font_path, font_size=(170,75), font_offset=(0,40,40), blur_size=50, color_ratio=0.8, resolution_config=None, bg_color_config=None):
    try:
        logger.info("开始创建单图封面...")

        if resolution_config is None:
            resolution_config = ResolutionConfig("1080p")

        canvas_size = resolution_config.size
        logger.info(f"图像生成使用的画布尺寸: {canvas_size} (分辨率配置: {resolution_config})")

        zh_font_path, en_font_path = font_path
        title_zh, title_en = title
        zh_font_size = float(font_size[0])
        en_font_size = float(font_size[1])
        zh_font_offset, title_spacing, en_line_spacing = font_offset

        if int(blur_size) < 0:
            blur_size = 50

        if float(color_ratio) < 0 or float(color_ratio) > 1:
            color_ratio = 0.8

        if not float(zh_font_size) > 0:
            zh_font_size = resolution_config.get_font_size(170)
        if not float(en_font_size) > 0:
            en_font_size = resolution_config.get_font_size(75)

        num_colors = 6

        with managed_image(image_path, "RGB") as original_img:
            if bg_color_config:
                bg_color = ColorHelper.get_background_color(
                    original_img,
                    color_mode=bg_color_config.get('mode', 'auto'),
                    custom_color=bg_color_config.get('custom_color'),
                    config_color=bg_color_config.get('config_color')
                )
                logger.info(f"使用背景颜色: {bg_color} (模式: {bg_color_config.get('mode', 'auto')})")
            else:
                candidate_colors = OptimizedImageProcessor.optimized_color_analysis(original_img, num_colors)
                random.shuffle(candidate_colors)
                extracted_colors = candidate_colors[:num_colors]

                soft_macaron_colors = [
                    (237, 159, 77),
                    (186, 225, 255),
                    (255, 223, 186),
                    (202, 231, 200),
                ]

                while len(extracted_colors) < num_colors:
                    if not extracted_colors:
                        extracted_colors.append(random.choice(soft_macaron_colors))
                    else:
                        max_diff = 0
                        best_color = None
                        for color in soft_macaron_colors:
                            min_dist = min(color_distance(color, existing) for existing in extracted_colors)
                            if min_dist > max_diff:
                                max_diff = min_dist
                                best_color = color
                        extracted_colors.append(best_color or random.choice(soft_macaron_colors))

                bg_color = darken_color(extracted_colors[0], 0.85)

            card_colors_extracted = ColorHelper.extract_dominant_colors(original_img, num_colors=3, style="macaron")
            card_colors = [card_colors_extracted[1] if len(card_colors_extracted) > 1 else (186, 225, 255),
                          card_colors_extracted[2] if len(card_colors_extracted) > 2 else (255, 223, 186)]

            bg_img = original_img.copy()
            bg_img = ImageOps.fit(bg_img, canvas_size, method=Image.LANCZOS)
            bg_img = OptimizedImageProcessor.optimized_gaussian_blur(bg_img, int(blur_size))
        
            bg_img_array = np.array(bg_img, dtype=float)
            bg_color_array = np.array([[bg_color]], dtype=float)

            blended_bg = bg_img_array * (1 - float(color_ratio)) + bg_color_array * float(color_ratio)
            blended_bg = np.clip(blended_bg, 0, 255).astype(np.uint8)
            blended_bg_img = Image.fromarray(blended_bg)
            blended_bg_img = add_film_grain(blended_bg_img, intensity=0.03)

            canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            canvas.paste(blended_bg_img)

            square_img = crop_to_square(original_img)
            card_size = int(canvas_size[1] * 0.7)
            square_img = square_img.resize((card_size, card_size), Image.LANCZOS)

            main_card = add_rounded_corners(square_img, radius=card_size//8)
            main_card = main_card.convert("RGBA")

            aux_card1 = square_img.copy().filter(ImageFilter.GaussianBlur(radius=8))
            aux_card1_array = np.array(aux_card1, dtype=float)
            card_color1_array = np.array([[card_colors[0]]], dtype=float)
            blended_card1 = aux_card1_array * 0.5 + card_color1_array * 0.5
            blended_card1 = np.clip(blended_card1, 0, 255).astype(np.uint8)
            aux_card1 = Image.fromarray(blended_card1)
            aux_card1 = add_rounded_corners(aux_card1, radius=card_size//8)
            aux_card1 = aux_card1.convert("RGBA")

            aux_card2 = square_img.copy().filter(ImageFilter.GaussianBlur(radius=16))
            aux_card2_array = np.array(aux_card2, dtype=float)
            card_color2_array = np.array([[card_colors[1]]], dtype=float)
            blended_card2 = aux_card2_array * 0.4 + card_color2_array * 0.6
            blended_card2 = np.clip(blended_card2, 0, 255).astype(np.uint8)
            aux_card2 = Image.fromarray(blended_card2)
            aux_card2 = add_rounded_corners(aux_card2, radius=card_size//8)
            aux_card2 = aux_card2.convert("RGBA")

            center_x = int(canvas_size[0] - canvas_size[1] * 0.5)
            center_y = int(canvas_size[1] * 0.5)
            center_pos = (center_x, center_y)
        
            rotation_angles = [36, 18, 0]

            shadow_configs = [
                {'offset': (10, 16), 'radius': 12, 'opacity': 0.4},
                {'offset': (15, 22), 'radius': 15, 'opacity': 0.5},
                {'offset': (20, 26), 'radius': 18, 'opacity': 0.6},
            ]

            cards_canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            cards = [aux_card2, aux_card1, main_card]

            for i, (card, angle, shadow_config) in enumerate(zip(cards, rotation_angles, shadow_configs)):
                cards_canvas = add_shadow_and_rotate(
                    cards_canvas,
                    card,
                    angle,
                    offset=shadow_config['offset'],
                    radius=shadow_config['radius'],
                    opacity=shadow_config['opacity'],
                    center_pos=center_pos
                )

            canvas = Image.alpha_composite(canvas.convert("RGBA"), cards_canvas)

            text_layer = Image.new('RGBA', canvas_size, (255, 255, 255, 0))
            shadow_layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))

            shadow_draw = ImageDraw.Draw(shadow_layer)
            draw = ImageDraw.Draw(text_layer)

            left_area_center_x = int(canvas_size[0] * 0.25)
            left_area_center_y = canvas_size[1] // 2

            zh_font = ImageFont.truetype(zh_font_path, int(zh_font_size))
            en_font = ImageFont.truetype(en_font_path, int(en_font_size))

            text_color = (255, 255, 255, 229)
            shadow_color = darken_color(bg_color, 0.8) + (75,)
            shadow_offset = 12
            shadow_alpha = 75
        
        zh_bbox = draw.textbbox((0, 0), title_zh, font=zh_font)
        zh_text_w = zh_bbox[2] - zh_bbox[0]
        zh_text_h = zh_bbox[3] - zh_bbox[1]
        
        en_line_spacing = int(en_font_size * 0.3)
        
        en_lines = []
        en_text_w = 0
        en_text_h = 0
        total_en_height = 0
        
        if title_en:
            en_bbox = draw.textbbox((0, 0), title_en, font=en_font)
            en_full_width = en_bbox[2] - en_bbox[0]
            
            if en_full_width > zh_text_w and " " in title_en:
                words = title_en.split(" ")
                current_line = words[0]
                
                for word in words[1:]:
                    test_line = current_line + " " + word
                    test_bbox = draw.textbbox((0, 0), test_line, font=en_font)
                    test_width = test_bbox[2] - test_bbox[0]
                    
                    if test_width > zh_text_w:
                        en_lines.append(current_line)
                        current_line = word
                    else:
                        current_line = test_line
                
                if current_line:
                    en_lines.append(current_line)
                
                for line in en_lines:
                    line_bbox = draw.textbbox((0, 0), line, font=en_font)
                    line_width = line_bbox[2] - line_bbox[0]
                    line_height = line_bbox[3] - line_bbox[1]
                    en_text_w = max(en_text_w, line_width)
                    total_en_height += line_height + en_line_spacing
                
                if en_lines:
                    total_en_height -= en_line_spacing
                    
                en_text_h = total_en_height
            else:
                en_lines = [title_en]
                en_text_w = en_full_width
                en_text_h = en_bbox[3] - en_bbox[1]
                total_en_height = en_text_h
        
        title_spacing = float(title_spacing) if title_en else 0
        total_text_height = zh_text_h + total_en_height + title_spacing
        total_text_y = left_area_center_y - total_text_height // 2

        zh_x = left_area_center_x - zh_text_w // 2
        zh_y = total_text_y + float(zh_font_offset)

        for offset in range(3, shadow_offset + 1, 2):
            current_shadow_color = shadow_color[:3] + (shadow_alpha,)
            shadow_draw.text((zh_x + offset, zh_y + offset), title_zh, font=zh_font, fill=current_shadow_color)
        
            draw.text((zh_x, zh_y), title_zh, font=zh_font, fill=text_color)

            if en_lines:
                en_y = zh_y + zh_text_h + title_spacing

                for i, line in enumerate(en_lines):
                    line_bbox = draw.textbbox((0, 0), line, font=en_font)
                    line_width = line_bbox[2] - line_bbox[0]
                    line_height = line_bbox[3] - line_bbox[1]

                    en_x = left_area_center_x - line_width // 2
                    current_y = en_y + i * (line_height + en_line_spacing)

                    for offset in range(2, shadow_offset // 2 + 1):
                        current_shadow_color = shadow_color[:3] + (shadow_alpha,)
                        shadow_draw.text((en_x + offset, current_y + offset), line, font=en_font, fill=current_shadow_color)

                    draw.text((en_x, current_y), line, font=en_font, fill=text_color)

            blurred_shadow = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_offset))
            combined = Image.alpha_composite(canvas, blurred_shadow)
            combined = Image.alpha_composite(combined, text_layer)

            def image_to_base64(image, format="auto", quality=85):
                buffer = BytesIO()
                if format.lower() == "auto":
                    if image.mode == "RGBA" or (image.info.get('transparency') is not None):
                        format = "PNG"
                    else:
                        try:
                            image.save(buffer, format="WEBP", quality=quality, optimize=True)
                            base64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
                            return base64_str
                        except Exception:
                            format = "JPEG"
                if format.lower() == "png":
                    image.save(buffer, format="PNG", optimize=True)
                    base64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    return base64_str
                elif format.lower() == "jpeg":
                    image = image.convert("RGB")
                    image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
                    base64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    return base64_str
                else:
                    raise ValueError(f"Unsupported format: {format}")

            return image_to_base64(combined)
        
    except Exception as e:
        logger.error(f"创建单图封面时出错: {e}")
        return False


def create_style_single_1(*args, **kwargs):
    """兼容旧命名"""
    return create_style_static_1(*args, **kwargs)
