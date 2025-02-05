from __future__ import annotations
import os

import math
import sys

import numpy as np
from PIL import Image, ImageDraw
from PIL.ImageFilter import Kernel


def saturation(image) -> np.ndarray:
    r, g, b = image.split()
    r, g, b = np.array(r), np.array(g), np.array(b)
    r, g, b = r.astype(float), g.astype(float), b.astype(float)
    maximum = np.maximum(np.maximum(r, g), b)  # [0; 255]
    minimum = np.minimum(np.minimum(r, g), b)  # [0; 255]
    s = (maximum + minimum) / 255  # [0.0; 1.0] pylint:disable=invalid-name
    d = (maximum - minimum) / 255  # [0.0; 1.0] pylint:disable=invalid-name
    d[maximum == minimum] = 0  # if maximum == minimum:
    s[maximum == minimum] = 1  # -> saturation = 0 / 1 = 0
    mask = s > 1
    s[mask] = 2 - d[mask]
    return d / s  # [0.0; 1.0]


def thirds(x):
    """gets value in the range of [0, 1] where 0 is the center of the pictures
    returns weight of rule of thirds [0, 1]"""
    x = ((x + 2 / 3) % 2 * 0.5 - 0.5) * 16
    return max(1 - x * x, 0)


class SmartCrop(object):  # pylint:disable=too-many-instance-attributes

    DEFAULT_SKIN_COLOR: tuple[float, float, float] = (0.78, 0.57, 0.44)

    def __init__(  # pylint:disable=too-many-arguments,too-many-locals
        self,
        detail_weight: float = 0.2,
        edge_radius: float = 0.4,
        edge_weight: float = -20,
        outside_importance: float = -0.5,
        rule_of_thirds: bool = True,
        saturation_bias: float = 0.2,
        saturation_brightness_max: float = 0.9,
        saturation_brightness_min: float = 0.05,
        saturation_threshold: float = 0.4,
        saturation_weight: float = 0.3,
        boost_weight: float = 100,
        score_down_sample: int = 8,
        skin_bias: float = 0.01,
        skin_brightness_max: float = 1,
        skin_brightness_min: float = 0.2,
        skin_color: tuple[float, float, float] | None = None,
        skin_threshold: float = 0.8,
        skin_weight: float = 1.8,
        debug=False
    ):
        self.detail_weight = detail_weight
        self.edge_radius = edge_radius
        self.edge_weight = edge_weight
        self.outside_importance = outside_importance
        self.rule_of_thirds = rule_of_thirds
        self.saturation_bias = saturation_bias
        self.saturation_brightness_max = saturation_brightness_max
        self.saturation_brightness_min = saturation_brightness_min
        self.saturation_threshold = saturation_threshold
        self.saturation_weight = saturation_weight
        self.boost_weight = boost_weight
        self.score_down_sample = score_down_sample
        self.skin_bias = skin_bias
        self.skin_brightness_max = skin_brightness_max
        self.skin_brightness_min = skin_brightness_min
        self.skin_color = skin_color or self.DEFAULT_SKIN_COLOR
        self.skin_threshold = skin_threshold
        self.skin_weight = skin_weight
        self.boosts = None
        self.debug = debug

    def analyse(  # pylint:disable=too-many-arguments,too-many-locals
        self,
        image,
        crop_width: int,
        crop_height: int,
        max_scale: float = 1,
        min_scale: float = 0.9,
        scale_step: float = 0.1,
        step: int = 8
    ) -> dict:
        """
        Analyze image and return some suggestions of crops (coordinates).
        This implementation / algorithm is really slow for large images.
        Use `crop()` which is pre-scaling the image before analyzing it.
        """
        cie_image = image.convert('L', (0.2126, 0.7152, 0.0722, 0))
        cie_array = np.array(cie_image)  # [0; 255]

        # R=skin G=edge B=saturation A=boost
        edge_image = self.detect_edge(cie_image)
        skin_image = self.detect_skin(cie_array, image)
        saturation_image = self.detect_saturation(cie_array, image)
        boost_image = self.applyBoosts(image)
        analyse_image = Image.merge('RGBA', [skin_image, edge_image, saturation_image, boost_image])

        del edge_image
        del skin_image
        del saturation_image
        del boost_image

        score_image = analyse_image.copy()
        score_image.thumbnail(
            (
                int(math.ceil(image.size[0] / self.score_down_sample)),
                int(math.ceil(image.size[1] / self.score_down_sample))
            ),
            Image.Resampling.LANCZOS)

        top_crop = None
        top_score = -sys.maxsize

        crops = self.crops(
            image,
            crop_width,
            crop_height,
            max_scale=max_scale,
            min_scale=min_scale,
            scale_step=scale_step,
            step=step)

        for i, crop in enumerate(crops):
            crop['score'] = self.score(score_image, crop)
            if crop['score']['total'] > top_score:
                top_crop = crop
                top_score = crop['score']['total']
                if self.debug:
                    self.debug_crop(analyse_image, crop).save('smartcrop_dbg_crop_%d.png' % i)
        return {'analyse_image': analyse_image, 'crops': crops, 'top_crop': top_crop}

    def crop(  # pylint:disable=too-many-arguments,too-many-locals
        self,
        image,
        width: int,
        height: int,
        prescale: bool = True,
        max_scale: float = 1,
        min_scale: float = 0.9,
        scale_step: float = 0.1,
        step: int = 8,
        boosts=None
    ) -> dict:
        self.boosts = boosts
        """Not yet fully cleaned from https://github.com/hhatto/smartcrop.py."""
        scale = min(image.size[0] / width, image.size[1] / height)
        crop_width = int(math.floor(width * scale))
        crop_height = int(math.floor(height * scale))
        # img = 100x100, width = 95x95, scale = 100/95, 1/scale > min
        # don't set minscale smaller than 1/scale
        # -> don't pick crops that need upscaling
        min_scale = min(max_scale, max(1 / scale, min_scale))

        prescale_size = 1
        if prescale:
            prescale_size = 1 / scale / min_scale
            if prescale_size < 1:
                image = image.copy()
                image.thumbnail(
                    (int(image.size[0] * prescale_size), int(image.size[1] * prescale_size)),
                    Image.Resampling.LANCZOS)
                crop_width = int(math.floor(crop_width * prescale_size))
                crop_height = int(math.floor(crop_height * prescale_size))
                if self.boosts is not None:
                    self.boosts = [
                        {'x': boost['x'] * prescale_size,
                         'y': boost['y'] * prescale_size,
                         'width': boost['width'] * prescale_size,
                         'height': boost['height'] * prescale_size,
                         'weight': boost['weight']
                         } for boost in self.boosts
                    ]
            else:
                prescale_size = 1

        result = self.analyse(
            image,
            crop_width=crop_width,
            crop_height=crop_height,
            min_scale=min_scale,
            max_scale=max_scale,
            scale_step=scale_step,
            step=step)

        for i in range(len(result['crops'])):
            crop = result['crops'][i]
            crop['x'] = int(math.floor(crop['x'] / prescale_size))
            crop['y'] = int(math.floor(crop['y'] / prescale_size))
            crop['width'] = int(math.floor(crop['width'] / prescale_size))
            crop['height'] = int(math.floor(crop['height'] / prescale_size))
            result['crops'][i] = crop
        return result

    def crops(  # pylint:disable=too-many-arguments
        self,
        image,
        crop_width: int,
        crop_height: int,
        max_scale: float = 1,
        min_scale: float = 0.9,
        scale_step: float = 0.1,
        step: int = 8
    ) -> list[dict]:
        image_width, image_height = image.size
        crops = []
        for scale in (
            i / 100 for i in range(
                int(max_scale * 100),
                int((min_scale - scale_step) * 100),
                -int(scale_step * 100))
        ):
            for y in range(0, image_height, step):
                if y + crop_height * scale > image_height:
                    break
                for x in range(0, image_width, step):
                    if x + crop_width * scale > image_width:
                        break
                    crops.append({
                        'x': x,
                        'y': y,
                        'width': crop_width * scale,
                        'height': crop_height * scale,
                    })
        if not crops:
            raise ValueError(locals())
        return crops

    def debug_crop(self, analyse_image, crop: dict):
        debug_image = analyse_image.copy()
        debug_pixels = debug_image.getdata()
        boost_pixels = debug_pixels.copy()
        debug_boost_image = Image.new(
            'RGBA',
            (
                debug_image.size[0],
                debug_image.size[1]
            ),
            (0, 0, 0, 0)
        )
        debug_boost_pixels = debug_boost_image.getdata()
        debug_crop_image = Image.new(
            'RGBA',
            (
                int(math.floor(crop['width'])),
                int(math.floor(crop['height']))
            ),
            (255, 0, 0, 25)
        )
        ImageDraw.Draw(debug_crop_image).rectangle(
            (
                (0, 0),
                (crop['width'], crop['height'])
            ),
            outline=(255, 0, 0))

        for y in range(analyse_image.size[1]):        # height
            for x in range(analyse_image.size[0]):    # width
                index = y * analyse_image.size[0] + x
                importance = self.importance(crop, x, y)
                if importance > 0:
                    debug_pixels.putpixel(
                        (x, y),
                        (
                            debug_pixels[index][0],
                            int(debug_pixels[index][1] + importance * 32),
                            debug_pixels[index][2],
                        ))
                elif importance < 0:
                    debug_pixels.putpixel(
                        (x, y),
                        (
                            int(debug_pixels[index][0] + importance * -64),
                            debug_pixels[index][1],
                            debug_pixels[index][2],
                        ))
                boost_value = boost_pixels[index][3]//2
                debug_boost_pixels.putpixel(
                    (x, y),
                    (
                        boost_value,
                        boost_value,
                        boost_value,
                        boost_value,
                    ))

        debug_image.paste(debug_crop_image, (crop['x'], crop['y']), debug_crop_image.split()[3])
        debug_image.alpha_composite(debug_boost_image)
        return debug_image.convert('RGB')

    def detect_edge(self, cie_image):
        return cie_image.filter(Kernel((3, 3), (0, -1, 0, -1, 4, -1, 0, -1, 0), 1, 1))

    def detect_saturation(self, cie_array: np.ndarray, source_image):
        threshold = self.saturation_threshold
        saturation_data = saturation(source_image)
        mask = (
            (saturation_data > threshold) &
            (cie_array >= self.saturation_brightness_min * 255) &
            (cie_array <= self.saturation_brightness_max * 255))

        saturation_data[~mask] = 0
        saturation_data[mask] = (saturation_data[mask] - threshold) * (255 / (1 - threshold))

        return Image.fromarray(saturation_data.astype('uint8'))

    def detect_skin(self, cie_array: np.ndarray, source_image):
        r, g, b = source_image.split()
        r, g, b = np.array(r), np.array(g), np.array(b)
        r, g, b = r.astype(float), g.astype(float), b.astype(float)
        rd = np.ones_like(r) * -self.skin_color[0]  # pylint:disable=invalid-name
        gd = np.ones_like(g) * -self.skin_color[1]  # pylint:disable=invalid-name
        bd = np.ones_like(b) * -self.skin_color[2]  # pylint:disable=invalid-name

        mag = np.sqrt(r * r + g * g + b * b)
        mask = ~(abs(mag) < 1e-6)
        rd[mask] = r[mask] / mag[mask] - self.skin_color[0]
        gd[mask] = g[mask] / mag[mask] - self.skin_color[1]
        bd[mask] = b[mask] / mag[mask] - self.skin_color[2]

        skin = 1 - np.sqrt(rd * rd + gd * gd + bd * bd)
        mask = (
            (skin > self.skin_threshold) &
            (cie_array >= self.skin_brightness_min * 255) &
            (cie_array <= self.skin_brightness_max * 255))

        skin_data = (skin - self.skin_threshold) * (255 / (1 - self.skin_threshold))
        skin_data[~mask] = 0

        return Image.fromarray(skin_data.astype('uint8'))

    def applyBoosts(self, image):
        w, h = image.size
        od = np.zeros((h, w))
        if self.boosts is not None:
            for boost in self.boosts:
                self.applyBoost(boost, od)
        return Image.fromarray(od.astype('uint8'))

    def applyBoost(self, boost, image):
        x0 = int(boost['x'])
        x1 = int(boost['x'] + boost['width'])
        y0 = int(boost['y'])
        y1 = int(boost['y'] + boost['height'])
        weight = boost['weight'] * 255
        image[y0:y1, x0:x1] += weight

    def importance(self, crop: dict, x: int, y: int) -> float:
        if (
            crop['x'] > x or x >= crop['x'] + crop['width'] or
            crop['y'] > y or y >= crop['y'] + crop['height']
        ):
            return self.outside_importance

        x = (x - crop['x']) / crop['width']
        y = (y - crop['y']) / crop['height']
        px, py = abs(0.5 - x) * 2, abs(0.5 - y) * 2  # pylint:disable=invalid-name

        # distance from edge
        dx = max(px - 1 + self.edge_radius, 0)      # pylint:disable=invalid-name
        dy = max(py - 1 + self.edge_radius, 0)      # pylint:disable=invalid-name
        d = (dx * dx + dy * dy) * self.edge_weight  # pylint:disable=invalid-name
        s = 1.41 - math.sqrt(px * px + py * py)     # pylint:disable=invalid-name

        if self.rule_of_thirds:
            # pylint:disable=invalid-name
            s += (max(0, s + d + 0.5) * 1.2) * (thirds(px) + thirds(py))

        return s + d

    def score(self, target_image, crop: dict) -> dict:  # pylint:disable=too-many-locals
        score = {
            'detail': 0,
            'saturation': 0,
            'skin': 0,
            'boost': 0,
            'total': 0,
        }
        target_data = target_image.getdata()
        target_width, target_height = target_image.size

        down_sample = self.score_down_sample
        inv_down_sample = 1 / down_sample
        target_width_down_sample = target_width * down_sample
        target_height_down_sample = target_height * down_sample

        for y in range(0, target_height_down_sample, down_sample):
            for x in range(0, target_width_down_sample, down_sample):
                index = int(
                    math.floor(y * inv_down_sample) * target_width +
                    math.floor(x * inv_down_sample)
                )
                importance = self.importance(crop, x, y)
                detail = target_data[index][1] / 255
                score['skin'] += (
                    target_data[index][0] / 255 * (detail + self.skin_bias) * importance
                )
                score['detail'] += detail * importance
                score['saturation'] += (
                    target_data[index][2] / 255 * (detail + self.saturation_bias) * importance
                )
                score['boost'] += (
                    target_data[index][3] / 255 * importance
                )
        score['total'] = (
            score['detail'] * self.detail_weight +
            score['skin'] * self.skin_weight +
            score['saturation'] * self.saturation_weight +
            score['boost'] * self.boost_weight
        ) / (crop['width'] * crop['height'])

        return score


class SmartCropWithFace(SmartCrop):
    def __init__(self, detail_weight: float = 0.2, edge_radius: float = 0.4, edge_weight: float = -20,
                 outside_importance: float = -0.5, rule_of_thirds: bool = True, saturation_bias: float = 0.2,
                 saturation_brightness_max: float = 0.9, saturation_brightness_min: float = 0.05, saturation_threshold: float = 0.4, saturation_weight: float = 0.3,
                 boost_weight: float = 100, score_down_sample: int = 8, skin_bias: float = 0.01, skin_brightness_max: float = 1, skin_brightness_min: float = 0.2, skin_color: tuple[float, float, float] | None = None, skin_threshold: float = 0.8, skin_weight: float = 1.8, debug=False):
        super().__init__(detail_weight, edge_radius, edge_weight, outside_importance, rule_of_thirds, saturation_bias, saturation_brightness_max, saturation_brightness_min,
                         saturation_threshold, saturation_weight, boost_weight, score_down_sample, skin_bias, skin_brightness_max, skin_brightness_min, skin_color, skin_threshold, skin_weight, debug)
        from .facedet import FaceDetector
        self.faceDtr = FaceDetector()

    def crop(self, image, width: int, height: int, prescale: bool = True, max_scale: float = 1, min_scale: float = 0.9, scale_step: float = 0.1, step: int = 8) -> dict:
        boosts = []
        for faceCoord in self.faceDtr.detect(image):
            x, y, w, h = faceCoord[0:4]
            boosts.append({
                'x': x,
                'y': y,
                'width': w,
                'height': h,
                'weight': 1
            })
        return super().crop(image, width, height, prescale, max_scale, min_scale, scale_step, step, boosts)


if __name__ == '__main__':

    here = os.path.abspath(os.path.dirname(__file__))
    imgPath = os.path.join(here, '../tests/images', 'business-work-1.jpg')
    img = Image.open(imgPath)

    cropper = SmartCropWithFace(debug=True)

    ret = cropper.crop(img.copy(), 80, 80)

    box = (ret['top_crop']['x'],
           ret['top_crop']['y'],
           ret['top_crop']['width'] + ret['top_crop']['x'],
           ret['top_crop']['height'] + ret['top_crop']['y'])

    print(box)

    # if box != crop:
    img = img.crop(box)
    # img.thumbnail((500, 500), Image.Resampling.LANCZOS)
    img.save('thumb.jpg')

    # assert box == crop
