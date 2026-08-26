import base64
import os
import random
import colorsys
from collections import Counter
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

try:
    from app.sdk.logging import logger
except ImportError:
    from app.log import logger

try:
    from ..utils.color_helper import ColorHelper
except ImportError:
    from app.plugins.mediacovergenerator.utils.color_helper import ColorHelper

# ========== 配置 ==========
canvas_size = (1920, 1080)

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

def adjust_to_macaron(h, s, v, target_saturation_range=(0.2, 0.7), target_value_range=(0.55, 0.85)):
    """将颜色的饱和度和亮度调整到接近马卡龙色系的范围，同时避免颜色过亮。"""
    adjusted_s = min(max(s, target_saturation_range[0]), target_saturation_range[1])
    adjusted_v = min(max(v, target_value_range[0]), target_value_range[1])
    return adjusted_s, adjusted_v

def find_dominant_vibrant_colors(image, num_colors=5):
    """
    从图像中提取出现次数较多的前 N 种非黑非白非灰的颜色，
    并将其调整到接近马卡龙色系。
    """
    img = image.copy()  
    img.thumbnail((100, 100))
    img = img.convert('RGB')
    pixels = list(img.getdata())
    filtered_pixels = [p for p in pixels if is_not_black_white_gray_near(p)]
    if not filtered_pixels:
        return []
    color_counter = Counter(filtered_pixels)
    dominant_colors = color_counter.most_common(num_colors * 3)

    macaron_colors = []
    seen_hues = set()

    for color, count in dominant_colors:
        h, s, v = rgb_to_hsv(color)
        adjusted_s, adjusted_v = adjust_to_macaron(h, s, v)
        adjusted_rgb = hsv_to_rgb(h, adjusted_s, adjusted_v)

        hue_degree = int(h * 360)
        is_similar_hue = any(abs(hue_degree - seen) < 15 for seen in seen_hues)

        if not is_similar_hue and adjusted_rgb not in macaron_colors:
            macaron_colors.append(adjusted_rgb)
            seen_hues.add(hue_degree)
            if len(macaron_colors) >= num_colors:
                break

    return macaron_colors

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

def crop_to_16_9(img):
    """直接将图片裁剪为16:9的比例"""
    target_ratio = 16 / 9
    current_ratio = img.width / img.height
    
    if current_ratio > target_ratio:
        new_width = int(img.height * target_ratio)
        left = (img.width - new_width) // 2
        img = img.crop((left, 0, left + new_width, img.height))
    else:
        new_height = int(img.width / target_ratio)
        top = (img.height - new_height) // 2
        img = img.crop((0, top, img.width, top + new_height))
    
    return img

def align_image_right(img, canvas_size):
    """
    将图片调整为与画布相同高度，裁剪出画布60%宽度的部分，
    然后将裁剪后的图片靠右放置（因为左侧40%会被其他内容遮盖）。
    """
    canvas_width, canvas_height = canvas_size
    target_width = int(canvas_width * 0.675)
    img_width, img_height = img.size

    scale_factor = canvas_height / img_height
    new_img_width = int(img_width * scale_factor)
    resized_img = img.resize((new_img_width, canvas_height), Image.LANCZOS)
    
    if new_img_width < target_width:
        scale_factor = target_width / img_width
        new_img_height = int(img_height * scale_factor)
        resized_img = img.resize((target_width, new_img_height), Image.LANCZOS)
        
        if new_img_height > canvas_height:
            crop_top = (new_img_height - canvas_height) // 2
            resized_img = resized_img.crop((0, crop_top, target_width, crop_top + canvas_height))
        
        final_img = Image.new("RGB", canvas_size)
        final_img.paste(resized_img, (canvas_width - target_width, 0))
        return final_img
    
    resized_img_center_x = new_img_width / 2
    crop_left = max(0, resized_img_center_x - target_width / 2)
    if crop_left + target_width > new_img_width:
        crop_left = new_img_width - target_width
    crop_right = crop_left + target_width
    crop_left = max(0, crop_left)
    crop_right = min(new_img_width, crop_right)
    
    cropped_img = resized_img.crop((int(crop_left), 0, int(crop_right), canvas_height))
    
    final_img = Image.new("RGB", canvas_size)
    paste_x = canvas_width - cropped_img.width + int(canvas_width * 0.075)
    final_img.paste(cropped_img, (paste_x, 0))
    
    return final_img

def create_diagonal_mask(size, split_top=0.5, split_bottom=0.33):
    """创建斜线分割的蒙版。左侧为背景 (255)，右侧为前景 (0)。"""
    mask = Image.new('L', size, 255)
    draw = ImageDraw.Draw(mask)
    width, height = size
    top_x = int(width * split_top)
    bottom_x = int(width * split_bottom)

    draw.polygon(
        [
            (top_x, 0),
            (width, 0),
            (width, height),
            (bottom_x, height)
        ],
        fill=0
    )

    draw.polygon(
        [
            (0, 0),
            (top_x, 0),
            (bottom_x, height),
            (0, height)
        ],
        fill=255
    )
    return mask

def create_shadow_mask(size, split_top=0.5, split_bottom=0.33, feather_size=40):
    """创建一个阴影蒙版，用于左侧图片向右侧图片投射阴影"""
    width, height = size
    top_x = int(width * split_top)
    bottom_x = int(width * split_bottom)
    
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    shadow_width = feather_size // 3
    
    draw.polygon(
        [
            (top_x - 5, 0),
            (top_x - 5 + shadow_width, 0),
            (bottom_x - 5 + shadow_width, height),
            (bottom_x - 5, height)
        ],
        fill=255
    )
    
    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather_size//3))
    return mask

def create_style_static_2(image_path, title, font_path, font_size=(170,75), font_offset=(0,40,40), blur_size=50, color_ratio=0.8, resolution_config=None, bg_color_config=None):
    try:
        zh_font_path, en_font_path = font_path
        title_zh, title_en = title
        zh_font_size, en_font_size = font_size
        zh_font_offset, title_spacing, en_line_spacing = font_offset

        if int(blur_size) < 0:
            blur_size = 50

        if float(color_ratio) < 0 or float(color_ratio) > 1:
            color_ratio = 0.8

        if not float(zh_font_size) > 0:
            zh_font_size = 170
        if not float(en_font_size) > 0:
            en_font_size = 75
        style_font_scale = 1.1
        zh_font_size = float(zh_font_size) * style_font_scale
        en_font_size = float(en_font_size) * style_font_scale

        if resolution_config:
            canvas_size = resolution_config.size
        else:
            canvas_size = (1920, 1080)

        split_top = 0.55
        split_bottom = 0.4
        
        fg_img_original = Image.open(image_path).convert("RGB")
        fg_img = align_image_right(fg_img_original, canvas_size)
        
        vibrant_colors = find_dominant_vibrant_colors(fg_img)
        
        soft_colors = [
            (237, 159, 77),
            (255, 183, 197),
            (186, 225, 255),
            (255, 223, 186),
            (202, 231, 200),
            (245, 203, 255),
        ]
        if bg_color_config:
            bg_color = ColorHelper.get_background_color(
                fg_img,
                color_mode=bg_color_config.get('mode', 'auto'),
                custom_color=bg_color_config.get('custom_color'),
                config_color=bg_color_config.get('config_color')
            )
        elif vibrant_colors:
            bg_color = vibrant_colors[0]
        else:
            bg_color = random.choice(soft_colors)
        shadow_color = darken_color(bg_color, 0.5)
        
        bg_img_original = Image.open(image_path).convert("RGB")
        bg_img = ImageOps.fit(bg_img_original, canvas_size, method=Image.LANCZOS)
        bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=int(blur_size)))

        bg_color = darken_color(bg_color, 0.85)
        bg_img_array = np.array(bg_img, dtype=float)
        bg_color_array = np.array([[bg_color]], dtype=float)
        
        blended_bg = bg_img_array * (1 - float(color_ratio)) + bg_color_array * float(color_ratio)
        blended_bg = np.clip(blended_bg, 0, 255).astype(np.uint8)
        blended_bg_img = Image.fromarray(blended_bg)
        blended_bg_img = add_film_grain(blended_bg_img, intensity=0.05)
        
        diagonal_mask = create_diagonal_mask(canvas_size, split_top, split_bottom)
        canvas = fg_img.copy()
        shadow_mask = create_shadow_mask(canvas_size, split_top, split_bottom, feather_size=30)
        shadow_layer = Image.new('RGB', canvas_size, shadow_color)
        
        temp_canvas = Image.new('RGB', canvas_size)
        temp_canvas.paste(canvas)
        temp_canvas.paste(shadow_layer, mask=shadow_mask)
        canvas = Image.composite(blended_bg_img, temp_canvas, diagonal_mask)
        
        canvas = canvas.convert('RGBA')
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


def create_style_single_2(*args, **kwargs):
    """兼容旧命名"""
    return create_style_static_2(*args, **kwargs)
