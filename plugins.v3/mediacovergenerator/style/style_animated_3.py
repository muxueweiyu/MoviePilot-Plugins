import base64
from collections import Counter
import io
from pathlib import Path
from PIL import Image, ImageFilter, ImageDraw, ImageFont, ImageOps
import numpy as np
import os
import math
import random
import colorsys
import subprocess
import tempfile
import shutil

try:
    from app.sdk.logging import logger
except ImportError:
    from app.log import logger

try:
    from ..utils.color_helper import ColorHelper
except ImportError:
    from app.plugins.mediacovergenerator.utils.color_helper import ColorHelper

""" 
代码修改自 https://github.com/HappyQuQu/jellyfin-library-poster/blob/main/gen_poster.py
"""

POSTER_GEN_CONFIG = {
    "ROWS": 3,
    "COLS": 3,
    "MARGIN": 22,
    "CORNER_RADIUS": 46.1,
    "ROTATION_ANGLE": -15.8,
    "START_X": 835,
    "START_Y": -362,
    "COLUMN_SPACING": 100,
    "SAVE_COLUMNS": True,
    "CELL_WIDTH": 410,
    "CELL_HEIGHT": 610,
    "CANVAS_WIDTH": 1920,
    "CANVAS_HEIGHT": 1080,
}

def add_shadow(img, offset=(5, 5), shadow_color=(0, 0, 0, 100), blur_radius=3):
    shadow_width = img.width + offset[0] + blur_radius * 2
    shadow_height = img.height + offset[1] + blur_radius * 2

    shadow = Image.new("RGBA", (shadow_width, shadow_height), (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", img.size, shadow_color)
    shadow.paste(shadow_layer, (blur_radius + offset[0], blur_radius + offset[1]))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur_radius))

    result = Image.new("RGBA", shadow.size, (0, 0, 0, 0))
    result.paste(img, (blur_radius, blur_radius), img if img.mode == "RGBA" else None)
    shadow_img = Image.alpha_composite(shadow, result)
    return shadow_img


def draw_text_on_image(
    image, text, position, font_path, default_font_path, font_size, fill_color=(255, 255, 255, 255),
    shadow=False, shadow_color=None, shadow_offset=10, shadow_alpha=75
):
    position = (int(round(float(position[0]))), int(round(float(position[1]))))
    img_copy = image.copy()
    text_layer = Image.new('RGBA', img_copy.size, (255, 255, 255, 0))
    shadow_layer = Image.new('RGBA', img_copy.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    shadow_draw = ImageDraw.Draw(shadow_layer)
    font = ImageFont.truetype(font_path, font_size)
    
    if shadow:
        fill_color = (fill_color[0], fill_color[1], fill_color[2], 229)
        if shadow_color is None:
            if len(fill_color) >= 3:
                r = max(0, int(fill_color[0] * 0.7))
                g = max(0, int(fill_color[1] * 0.7))
                b = max(0, int(fill_color[2] * 0.7))
                shadow_color_with_alpha = (r, g, b, shadow_alpha)
            else:
                shadow_color_with_alpha = (50, 50, 50, shadow_alpha)
        else:
            if len(shadow_color) == 3:
                shadow_color_with_alpha = shadow_color + (shadow_alpha,)
            elif len(shadow_color) == 4:
                shadow_color_with_alpha = shadow_color[:3] + (shadow_alpha,)
            else:
                raise ValueError("shadow_color 格式不正确")

        for offset in range(3, shadow_offset + 1, 2):
            shadow_draw.text(
                (position[0] + offset, position[1] + offset),
                text,
                font=font,
                fill=shadow_color_with_alpha
            )
    draw.text(position, text, font=font, fill=fill_color)
    blurred_shadow = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_offset))
    combined = Image.alpha_composite(img_copy, blurred_shadow)
    img_copy = Image.alpha_composite(combined, text_layer)
    return img_copy


def draw_multiline_text_on_image(
    image,
    text,
    position,
    font_path,
    default_font_path,
    font_size,
    line_spacing=10,
    fill_color=(255, 255, 255, 255),
    shadow=False,
    shadow_color=None,
    shadow_offset=4,
    shadow_alpha=100,
    is_multiline=False,
):
    position = (int(round(float(position[0]))), int(round(float(position[1]))))
    img_copy = image.copy()
    text_layer = Image.new('RGBA', img_copy.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(text_layer)
    font = ImageFont.truetype(font_path, font_size)

    lines = text.split(" ")

    if shadow:
        fill_color = (fill_color[0], fill_color[1], fill_color[2], 229)
        if shadow_color is None:
            if len(fill_color) >= 3:
                r = max(0, int(fill_color[0] * 0.7))
                g = max(0, int(fill_color[1] * 0.7))
                b = max(0, int(fill_color[2] * 0.7))
                shadow_color_with_alpha = (r, g, b, shadow_alpha)
            else:
                shadow_color_with_alpha = (50, 50, 50, shadow_alpha)
        else:
            if len(shadow_color) == 3:
                shadow_color_with_alpha = shadow_color + (shadow_alpha,)
            elif len(shadow_color) == 4:
                shadow_color_with_alpha = shadow_color[:3] + (shadow_alpha,)
            else:
                raise ValueError("shadow_color 格式不正确")

    if len(lines) <= 1 or not is_multiline:
        if shadow:
            for offset in range(3, shadow_offset + 1, 2):
                draw.text(
                    (position[0] + offset, position[1] + offset),
                    text,
                    font=font,
                    fill=shadow_color_with_alpha
                )
        draw.text(position, text, font=font, fill=fill_color)
        img_copy = Image.alpha_composite(img_copy, text_layer)
        return img_copy, 1

    x, y = position
    for i, line in enumerate(lines):
        current_y = y + i * (font_size + line_spacing)

        if shadow:
            for offset in range(3, shadow_offset + 1, 2):
                draw.text(
                    (x + offset, current_y + offset),
                    line,
                    font=font,
                    fill=shadow_color_with_alpha
                )
        draw.text((x, current_y), line, font=font, fill=fill_color)
    img_copy = Image.alpha_composite(img_copy, text_layer)
    return img_copy, len(lines)


def get_random_color(image_path):
    try:
        img = Image.open(image_path)
        width, height = img.size
        random_x = random.randint(int(width * 0.5), int(width * 0.8))
        random_y = random.randint(int(height * 0.5), int(height * 0.8))

        if img.mode == "RGBA":
            r, g, b, a = img.getpixel((random_x, random_y))
            return (r, g, b, a)
        elif img.mode == "RGB":
            r, g, b = img.getpixel((random_x, random_y))
            return (r + 100, g + 50, b, 255)
        else:
            img = img.convert("RGBA")
            r, g, b, a = img.getpixel((random_x, random_y))
            return (r, g, b, a)
    except Exception:
        return (
            random.randint(50, 200),
            random.randint(50, 200),
            random.randint(50, 200),
            255,
        )


def draw_color_block(image, position, size, color):
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)
    draw.rectangle(
        [position, (position[0] + size[0], position[1] + size[1])], fill=color
    )
    return img_copy


def create_gradient_background(width, height, color=None):
    def _normalize_rgb(input_rgb):
        if isinstance(input_rgb, tuple):
            if len(input_rgb) == 2 and isinstance(input_rgb[0], tuple):
                return _normalize_rgb(input_rgb[0])
            if len(input_rgb) == 4 and all(isinstance(v, (int, float)) for v in input_rgb):
                return input_rgb[:3]
            if len(input_rgb) == 3 and all(isinstance(v, (int, float)) for v in input_rgb):
                return input_rgb
        raise ValueError(f"无法识别的颜色格式: {input_rgb!r}")

    def _is_mid_bright_hsl(input_rgb, min_l=0.3, max_l=0.7):
        r, g, b = _normalize_rgb(input_rgb)
        r1, g1, b1 = r/255.0, g/255.0, b/255.0
        h, l, s = colorsys.rgb_to_hls(r1, g1, b1)
        return min_l <= l <= max_l
    
    selected_color = None
    
    if isinstance(color, list) and len(color) > 0:
        for i in range(min(10, len(color))):
            if _is_mid_bright_hsl(color[i]):
                if isinstance(color[i], tuple) and len(color[i]) == 2 and isinstance(color[i][0], tuple):
                    selected_color = color[i][0]
                else:
                    selected_color = color[i]
                break
    
    if selected_color is None:
        def random_hsl_to_rgb(
            hue_range=(0, 360),
            sat_range=(0.5, 1.0),
            light_range=(0.5, 0.8)
        ):
            h = random.uniform(hue_range[0]/360.0, hue_range[1]/360.0)
            s = random.uniform(sat_range[0], sat_range[1])
            l = random.uniform(light_range[0], light_range[1])
            r, g, b = colorsys.hls_to_rgb(h, l, s)
            return (int(r*255), int(g*255), int(b*255))

        selected_color = random_hsl_to_rgb()

    r = int(selected_color[0] * 0.65)
    g = int(selected_color[1] * 0.65)
    b = int(selected_color[2] * 0.65)
    
    r = max(0, r)
    g = max(0, g)
    b = max(0, b)
    
    selected_color = (r, g, b, selected_color[3] if len(selected_color) > 3 else 255)
    if len(selected_color) == 3:
        selected_color = (selected_color[0], selected_color[1], selected_color[2], 255)
    
    r = min(255, int(selected_color[0] * 1.9))
    g = min(255, int(selected_color[1] * 1.9))
    b = min(255, int(selected_color[2] * 1.9))
    
    r = max(r, selected_color[0] + 80)
    g = max(g, selected_color[1] + 80)
    b = max(b, selected_color[2] + 80)
    
    r = min(r, 230)
    g = min(g, 230)
    b = min(b, 230)
    
    color2 = (r, g, b, selected_color[3])
    
    left_image = Image.new("RGBA", (width, height), selected_color)
    right_image = Image.new("RGBA", (width, height), color2)
    
    mask = Image.new("L", (width, height), 0)
    mask_data = []
    
    for y in range(height):
        for x in range(width):
            mask_value = int(255.0 * (x / width) ** 0.7)
            mask_data.append(mask_value)
    
    mask.putdata(mask_data)
    gradient = Image.composite(right_image, left_image, mask)
    return gradient


def get_poster_primary_color(image_path):
    try:
        from collections import Counter
        img = Image.open(image_path)
        img = img.resize((100, 150), Image.LANCZOS)
        
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        pixels = list(img.getdata())
        filtered_pixels = []
        for pixel in pixels:
            r, g, b, a = pixel
            if a < 200:
                continue
            brightness = (r + g + b) / 3
            if brightness < 30 or brightness > 220:
                continue
            filtered_pixels.append((r, g, b, 255))
            
        if not filtered_pixels:
            filtered_pixels = [(p[0], p[1], p[2], 255) for p in pixels if p[3] > 100]
            
        if not filtered_pixels:
            return (150, 100, 50, 255)
            
        color_counter = Counter(filtered_pixels)
        common_colors = color_counter.most_common(10)
        
        if common_colors:
            return common_colors
        
        r_avg = sum(p[0] for p in filtered_pixels) // len(filtered_pixels)
        g_avg = sum(p[1] for p in filtered_pixels) // len(filtered_pixels)
        b_avg = sum(p[2] for p in filtered_pixels) // len(filtered_pixels)
        
        return [(r_avg, g_avg, b_avg, 255)]
    except Exception:
        return [(150, 100, 50, 255)]


def create_blur_background(image_path, template_width, template_height, background_color, blur_size, color_ratio, lighten_gradient_strength=0.6):
    original_img = Image.open(image_path)
    if original_img.mode != 'RGBA':
        original_img = original_img.convert('RGBA')
    
    canvas_size = (template_width, template_height)
    bg_img = original_img.copy()
    bg_img = ImageOps.fit(bg_img, canvas_size, method=Image.LANCZOS)
    bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=int(blur_size)))

    actual_color = darken_color(background_color, 0.85)
    if len(actual_color) >= 3:
        bg_color = (int(actual_color[0]), int(actual_color[1]), int(actual_color[2]))
    else:
        bg_color = (0, 0, 0)

    bg_img_array = np.array(bg_img, dtype=float)
    height, width, channels = bg_img_array.shape
    
    bg_color_array = np.zeros_like(bg_img_array)
    for i in range(min(3, channels)):  
        bg_color_array[:, :, i] = float(bg_color[i])
    
    if channels == 4:
        bg_color_array[:, :, 3] = 255.0
    
    blended_bg_array = bg_img_array * (1 - float(color_ratio)) + bg_color_array * float(color_ratio)
    blended_bg_array = np.clip(blended_bg_array, 0, 255).astype(np.uint8)

    mode = 'RGBA' if channels == 4 else 'RGB'
    blended_bg_img = Image.fromarray(blended_bg_array, mode)

    if blended_bg_img.mode != 'RGBA':
        blended_bg_img = blended_bg_img.convert('RGBA')

    if lighten_gradient_strength > 0:
        gradient_mask = Image.new("L", canvas_size, 0)  
        draw_mask = ImageDraw.Draw(gradient_mask)

        for x in range(template_width):
            max_alpha_for_gradient = int(255 * np.clip(lighten_gradient_strength, 0.0, 1.0))
            alpha_value = int((x / template_width) * max_alpha_for_gradient)
            draw_mask.line([(x, 0), (x, template_height)], fill=alpha_value)

        lighten_layer = Image.new("RGBA", canvas_size, (255, 255, 255, 0))
        lighten_layer.putalpha(gradient_mask)
        blended_bg_img = Image.alpha_composite(blended_bg_img, lighten_layer)

    final_bg_img = add_film_grain(blended_bg_img, intensity=0.03)
    return final_bg_img


def add_film_grain(image, intensity=0.05):
    mode = image.mode
    img_array = np.array(image, dtype=np.float32)
    if mode == 'RGBA':
        channels = img_array.shape[2]
        for i in range(min(3, channels)):
            channel = img_array[:, :, i]
            noise = np.random.normal(0, 255 * intensity, channel.shape)
            img_array[:, :, i] = np.clip(channel + noise, 0, 255)
    else:
        noise = np.random.normal(0, 255 * intensity, img_array.shape)
        img_array = np.clip(img_array + noise, 0, 255)
    
    grainy_image = Image.fromarray(img_array.astype(np.uint8), mode)
    return grainy_image


def is_not_black_white_gray_near(color, threshold=20):
    r, g, b = color
    if (r < threshold and g < threshold and b < threshold) or \
       (r > 255 - threshold and g > 255 - threshold and b > 255 - threshold):
        return False
    gray_diff_threshold = 10
    if abs(r - g) < gray_diff_threshold and abs(g - b) < gray_diff_threshold and abs(r - b) < gray_diff_threshold:
        return False
    return True


def rgb_to_hsv(color):
    r, g, b = [x / 255.0 for x in color]
    return colorsys.rgb_to_hsv(r, g, b)


def hsv_to_rgb(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def adjust_to_macaron(h, s, v, target_saturation_range=(0.2, 0.7), target_value_range=(0.55, 0.85)):
    adjusted_s = min(max(s, target_saturation_range[0]), target_saturation_range[1])
    adjusted_v = min(max(v, target_value_range[0]), target_value_range[1])
    return adjusted_s, adjusted_v


def find_dominant_vibrant_colors(image, num_colors=5):
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
    r, g, b = color
    return (int(r * factor), int(g * factor), int(b * factor))


def create_style_animated_3(library_dir, title, font_path, font_size=(170,75), font_offset=(0,40,40), 
                           is_blur=False, blur_size=50, color_ratio=0.8, resolution_config=None, 
                           bg_color_config=None, animation_duration=12, animation_scroll='down', 
                           animation_fps=15, animation_format='apng', animation_resolution='300x200', 
                           animation_reduce_colors='strong', stop_event=None):
    try:
        zh_font_size, en_font_size = font_size
        zh_font_offset, title_spacing, en_line_spacing = font_offset

        try:
            target_w, target_h = map(int, animation_resolution.lower().split('x'))
        except:
            target_w, target_h = 320, 180 

        scale = target_h / 1080.0
        def s(val): return val * scale

        if int(blur_size) < 0: blur_size = 50
        if float(color_ratio) < 0 or float(color_ratio) > 1: color_ratio = 0.8
            
        zh_font_size_s = int(zh_font_size * scale)
        en_font_size_s = int(en_font_size * scale)

        zh_font_path, en_font_path = font_path
        title_zh, title_en = title
        poster_folder = Path(library_dir)
        first_image_path = poster_folder / "1.jpg"

        rows = POSTER_GEN_CONFIG["ROWS"]
        cols = POSTER_GEN_CONFIG["COLS"]
        margin = s(POSTER_GEN_CONFIG["MARGIN"])
        corner_radius = s(POSTER_GEN_CONFIG["CORNER_RADIUS"])
        rotation_angle = POSTER_GEN_CONFIG["ROTATION_ANGLE"]

        start_x = s(POSTER_GEN_CONFIG["START_X"])
        start_y = s(POSTER_GEN_CONFIG["START_Y"])
        column_spacing = s(POSTER_GEN_CONFIG["COLUMN_SPACING"])

        cell_width = s(POSTER_GEN_CONFIG["CELL_WIDTH"])
        cell_height = s(POSTER_GEN_CONFIG["CELL_HEIGHT"])

        color_img = Image.open(first_image_path).convert("RGB")        
        vibrant_colors = find_dominant_vibrant_colors(color_img)
        selected_bg_color = None
        if bg_color_config:
            selected_bg_color = ColorHelper.get_background_color(
                color_img,
                color_mode=bg_color_config.get('mode', 'auto'),
                custom_color=bg_color_config.get('custom_color'),
                config_color=bg_color_config.get('config_color')
            )

        if selected_bg_color:
            blur_color = selected_bg_color
            gradient_color = selected_bg_color
        else:
            blur_color = vibrant_colors[0] if vibrant_colors else (237, 159, 77)
            gradient_color = get_poster_primary_color(first_image_path)

        if is_blur:
            bg_img = create_blur_background(first_image_path, target_w, target_h, blur_color, blur_size * scale, color_ratio)
        else:
            bg_img = create_gradient_background(target_w, target_h, gradient_color)

        text_overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
        text_shadow_color = darken_color(blur_color, 0.8)
        random_color = vibrant_colors[1] if len(vibrant_colors) > 1 else (random.randint(50, 200), random.randint(50, 200), random.randint(50, 200), 255)
        
        text_overlay = draw_text_on_image(
            text_overlay, title_zh, (s(73.32), s(427.34) + zh_font_size_s * zh_font_offset), zh_font_path, "ch.ttf", zh_font_size_s,
            shadow=is_blur, shadow_color=text_shadow_color
        )
        if title_en:
            text_overlay, line_count = draw_multiline_text_on_image(
                text_overlay, title_en, (s(124.68), s(624.55) + s(title_spacing)),
                en_font_path, "en.otf", en_font_size_s, s(en_line_spacing),
                shadow=is_blur, shadow_color=text_shadow_color, is_multiline=True
            )
            cb_h = int(en_font_size_s + s(en_line_spacing) + (line_count - 1) * (en_font_size_s + s(en_line_spacing)))
            text_overlay = draw_color_block(text_overlay, (s(84.38), s(620.06) + s(title_spacing)), (s(21.51), cb_h), random_color)

        base_frame = Image.alpha_composite(bg_img, text_overlay)

        supported_formats = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
        custom_order = "315426987"
        order_map = {num: index for index, num in enumerate(custom_order)}

        all_posters = sorted(
            [os.path.join(poster_folder, f) for f in os.listdir(poster_folder)
             if os.path.isfile(os.path.join(poster_folder, f)) and f.lower().endswith(supported_formats)
             and os.path.splitext(f)[0] in order_map],
            key=lambda x: order_map[os.path.splitext(os.path.basename(x))[0]]
        )
        if not all_posters: return None
        
        processed_images = []
        extended_posters = []
        while len(extended_posters) < rows * cols: extended_posters.extend(all_posters)
        extended_posters = extended_posters[:rows * cols]
        
        for p_path in extended_posters:
            try:
                img = Image.open(p_path).convert("RGBA")
                img = ImageOps.fit(img, (int(cell_width), int(cell_height)), method=Image.Resampling.BILINEAR)
                if corner_radius > 0:
                    mask = Image.new("L", (int(cell_width), int(cell_height)), 0)
                    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (int(cell_width), int(cell_height))], radius=corner_radius, fill=255)
                    img.putalpha(mask)
                img_with_shadow = add_shadow(img, offset=(int(s(15)), int(s(15))), shadow_color=(0, 0, 0, 200), blur_radius=int(s(10)))
                processed_images.append(img_with_shadow)
            except Exception as e:
                logger.error(f"图片预处理异常: {e}")
                continue
                
        if not processed_images: return None

        column_posters = [processed_images[i::cols] for i in range(cols)]
        scroll_dist = rows * (cell_height + margin) 
        
        cos_val = max(1e-6, math.cos(math.radians(abs(rotation_angle))))
        view_h = int(target_h / cos_val * 1.6)
        view_w = int(cell_width + s(60))
        
        rendered_strips = []
        for col_index, current_col_imgs in enumerate(column_posters):
            loop_posters = current_col_imgs * 2 + [current_col_imgs[0]]
            shadow_extra = int(s(60))
            col_strip_h = len(loop_posters) * cell_height + (len(loop_posters) - 1) * margin
            col_strip = Image.new("RGBA", (int(cell_width) + shadow_extra, int(col_strip_h) + shadow_extra), (0, 0, 0, 0))
            
            for row_index, p_img in enumerate(loop_posters):
                col_strip.paste(p_img, (0, int(row_index * (cell_height + margin))), p_img)
            
            rendered_strips.append(col_strip)

        try: fps = max(1, int(animation_fps))
        except: fps = 15
        n_frames = int(float(animation_duration) * fps)
        col_phases = [0, scroll_dist // 4, scroll_dist // 2]

        base_centers = []
        col_x_step = cell_width - s(50)
        third_col_extra_x = s(30)
        for col_index in range(cols):
            base_cx = start_x + col_index * column_spacing
            base_cy = start_y + (rows * cell_height + (rows - 1) * margin) // 2
            if col_index == 1: 
                base_cx += col_x_step
            elif col_index == 2:
                base_cy += -s(155)
                base_cx += col_x_step * 2 + third_col_extra_x
            base_centers.append((base_cx, base_cy))

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            logger.info(f"正在进行帧合成 (共 {n_frames} 帧, 目标 {target_w}x{target_h})...")
            
            try:
                safe_fps = int(animation_fps)
                safe_duration = int(animation_duration)
            except (ValueError, TypeError):
                safe_fps = 15
                safe_duration = 12
                
            n_frames = safe_fps * safe_duration
            if n_frames > 500:
                logger.warning(f"检测到异常帧数 {n_frames}，已强制限制为 500 帧")
                n_frames = 500
            
            logger.info(f"开始生成动画帧: {n_frames} 帧, 格式: {animation_format}, 分辨率: {animation_resolution}")
            
            for i in range(n_frames):
                if stop_event and stop_event.is_set():
                    logger.info("检测到停止信号，中断动图生成 ...")
                    return False
                
                if i % 10 == 0:
                    logger.info(f"正在生成第 {i}/{n_frames} 帧...")
                
                frame = base_frame.copy()
                progress = i / n_frames

                for col_index, strip in enumerate(rendered_strips):
                    total_scroll = progress * scroll_dist
                    phase_offset = col_phases[col_index % len(col_phases)]

                    if animation_scroll == 'up':
                        dy_float = total_scroll % scroll_dist
                    elif animation_scroll == 'down':
                        dy_float = (scroll_dist - total_scroll) % scroll_dist
                    elif animation_scroll == 'alternate':
                        if col_index == 1:
                            dy_float = (total_scroll + phase_offset) % scroll_dist
                        else:
                            dy_float = (scroll_dist - total_scroll + phase_offset) % scroll_dist
                    elif animation_scroll == 'alternate_reverse':
                        if col_index == 1:
                            dy_float = (scroll_dist - total_scroll + phase_offset) % scroll_dist
                        else:
                            dy_float = (total_scroll + phase_offset) % scroll_dist
                    else:
                        dy_float = (scroll_dist - total_scroll) % scroll_dist

                    dy_int = int(dy_float)
                    sub_strip = strip.crop((0, dy_int, view_w, dy_int + view_h))
                    rotated_piece = sub_strip.rotate(rotation_angle, resample=Image.Resampling.BILINEAR, expand=True)
                    
                    bcx, bcy = base_centers[col_index]
                    pos_x = int(bcx - rotated_piece.width // 2 + cell_width // 2)
                    pos_y = int(bcy - rotated_piece.height // 2)
                    frame.paste(rotated_piece, (pos_x, pos_y), rotated_piece)

                frame_file = tmp_path / f"frame_{i:04d}.bmp"
                frame.convert("RGB").save(frame_file, format="BMP")

            output_ext = ".gif" if animation_format == 'gif' else ".png"
            output_file = tmp_path / f"output{output_ext}"
            
            ffmpeg_common = ['ffmpeg', '-hide_banner', '-y', '-framerate', str(fps), '-i', str(tmp_path / 'frame_%04d.bmp'), '-threads', '2']
            
            reduce_mode = animation_reduce_colors
            if isinstance(reduce_mode, bool): reduce_mode = 'strong' if reduce_mode else 'off'
            
            if animation_format == 'gif':
                p_colors = '64' if reduce_mode == 'strong' else ('128' if reduce_mode == 'medium' else '256')
                p_dither = 'none' if reduce_mode == 'strong' else ('bayer:bayer_scale=3' if reduce_mode == 'medium' else 'floyd_steinberg')
                ffmpeg_cmd = ffmpeg_common + ['-filter_complex', f'[0:v] split [a][b]; [a] palettegen=max_colors={p_colors} [p]; [b][p] paletteuse=dither={p_dither}', '-loop', '0', '-f', 'gif', str(output_file)]
            else:
                if reduce_mode == 'off':
                    ffmpeg_cmd = ffmpeg_common + ['-vcodec', 'apng', '-pix_fmt', 'rgba', '-plays', '0', '-f', 'apng', str(output_file)]
                else:
                    p_colors = '64' if reduce_mode == 'strong' else '128'
                    p_dither = 'none' if reduce_mode == 'strong' else 'bayer:bayer_scale=3'
                    ffmpeg_cmd = ffmpeg_common + ['-filter_complex', f'[0:v] split [a][b]; [a] palettegen=max_colors={p_colors}:reserve_transparent=on [p]; [b][p] paletteuse=dither={p_dither}', '-vcodec', 'apng', '-pix_fmt', 'rgba', '-plays', '0', '-f', 'apng', str(output_file)]

            logger.debug("正在启动 ffmpeg...")
            try:
                result = subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if result.stderr:
                    result.stderr = b""
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode('utf-8', 'ignore') if e.stderr else "无详细错误信息"
                logger.error(f"ffmpeg 执行失败 (状态码 {e.returncode})")
                raise
            
            with open(output_file, 'rb') as f:
                final_data = f.read()
            logger.info(f"ffmpeg 导出成功! 最终大小: {len(final_data)/1024/1024:.2f} MB")
            return base64.b64encode(final_data).decode('utf-8')

    except Exception as e:
        logger.error(f"创建 style_animated_3 失败: {e}")
        return False
