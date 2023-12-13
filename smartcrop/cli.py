import argparse
import json
import sys

from PIL import Image
import piexif

from .library import SmartCrop


def parse_argument() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    arg = parser.add_argument
    arg('inputfile', metavar='INPUT_FILE', help='Input image file')
    arg('outputfile', metavar='OUTPUT_FILE', help='Output image file')
    arg('--debug-file', metavar='DEBUG_FILE', help='Debugging image file')
    arg('--width', type=int, default=100, help='Crop width')
    arg('--height', type=int, default=100, help='Crop height')
    arg('--facedet',action="store_true",help='Whether use face detection')
    return parser.parse_args()


def main() -> None:
    options = parse_argument()

    image = Image.open(options.inputfile)

    # Apply orientation from EXIF metadata
    if "exif" in image.info:
        exif_dict = piexif.load(image.info["exif"])

        if piexif.ImageIFD.Orientation in exif_dict["0th"]:
            orientation = exif_dict["0th"].pop(piexif.ImageIFD.Orientation)
            exif_bytes = piexif.dump(exif_dict)
            if orientation == 2:
                image = image.transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 3:
                image = image.rotate(180)
            elif orientation == 4:
                image = image.rotate(180).transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 5:
                image = image.rotate(-90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 6:
                image = image.rotate(-90, expand=True)
            elif orientation == 7:
                image = image.rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 8:
                image = image.rotate(90, expand=True)

    # Ensure image is in RGB (convert it otherwise)
    if image.mode not in ('RGB', 'RGBA'):
        sys.stderr.write(f"{image.mode} convert from mode='{options.inputfile}' to mode='RGB'\n")
        new_image = Image.new('RGB', image.size)
        new_image.paste(image)
        image = new_image

    if options.facedet:
        from .library import SmartCropWithFace
        cropper = SmartCropWithFace()
    else:
        cropper = SmartCrop()
    result = cropper.crop(image, width=100, height=int(options.height / options.width * 100))

    box = (
        result['top_crop']['x'],
        result['top_crop']['y'],
        result['top_crop']['width'] + result['top_crop']['x'],
        result['top_crop']['height'] + result['top_crop']['y']
    )

    if options.debug_file:
        analyse_image = result.pop('analyse_image')
        cropper.debug_crop(analyse_image, result['top_crop']).save(options.debug_file)
        print(json.dumps(result))

    cropped_image = image.crop(box)
    cropped_image.thumbnail((options.width, options.height), Image.Resampling.LANCZOS)
    cropped_image.save(options.outputfile, 'JPEG', quality=90)
