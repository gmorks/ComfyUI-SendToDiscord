import os
import json
import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
import requests
import io
import random
import folder_paths
import configparser

class PreviewImageWithDiscord:
    def __init__(self):
        self.output_dir = folder_paths.get_temp_directory()
        self.type = "temp"
        self.prefix_append = "_temp_" + ''.join(random.choice("abcdefghijklmnopqrstupvxyz") for x in range(5))
        self.compress_level = 1
        self.webhook_url = self.load_webhook_url()
        self.batch_size = 5  # Number of images to accumulate before sending
        self.image_queue = []

    def load_webhook_url(self):
        config = configparser.ConfigParser()
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        config.read(config_path)
        return config.get('Discord', 'webhook_url', fallback='')

    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"images": ("IMAGE", ),
                     "send_to_discord": (["enable", "disable"], {"default": "disable"}),
                     "batch_mode": (["enable", "disable"], {"default": "disable"})},
                "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
                }

    RETURN_TYPES = ()
    FUNCTION = "preview_images"
    OUTPUT_NODE = True
    CATEGORY = "image"

    def preview_images(self, images, send_to_discord="disable", batch_mode="disable", prompt=None, extra_pnginfo=None):
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path("ComfyUI", self.output_dir, images[0].shape[1], images[0].shape[0])
        results = list()
        for image in images:
            i = 255. * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
            
            metadata = PngInfo()
            if prompt is not None:
                metadata.add_text("prompt", json.dumps(prompt))
            if extra_pnginfo is not None:
                for x in extra_pnginfo:
                    metadata.add_text(x, json.dumps(extra_pnginfo[x]))

            file = f"{filename}_{counter:05}_.png"
            full_path = os.path.join(full_output_folder, file)
            img.save(full_path, pnginfo=metadata, compress_level=self.compress_level)
            
            results.append({
                "filename": file,
                "subfolder": subfolder,
                "type": self.type
            })

            if send_to_discord == "enable" and self.webhook_url:
                if batch_mode == "enable":
                    self.image_queue.append(full_path)
                    if len(self.image_queue) >= self.batch_size:
                        self.send_batch_to_discord()
                else:
                    self.send_to_discord(full_path, file)

            counter += 1

        # Send any remaining images in the queue
        if send_to_discord == "enable" and batch_mode == "enable" and self.image_queue:
            self.send_batch_to_discord()

        return { "ui": { "images": results } }

    def send_to_discord(self, image_path, filename):
        with open(image_path, 'rb') as img_file:
            files = {
                'file': (filename, img_file, 'image/png')
            }
            
            try:
                response = requests.post(self.webhook_url, files=files)
                if response.status_code == 200:
                    print(f"Successfully sent image to Discord: {filename}")
                else:
                    print(f"Failed to send image to Discord: {filename}. Status: {response.status_code}")
            except Exception as e:
                print(f"Error sending image to Discord: {e}")

    def send_batch_to_discord(self):
        files = {}
        for i, image_path in enumerate(self.image_queue):
            with open(image_path, 'rb') as img_file:
                filename = os.path.basename(image_path)
                files[f'file{i}'] = (filename, img_file.read(), 'image/png')
        
        try:
            response = requests.post(self.webhook_url, files=files)
            if response.status_code == 200:
                print(f"Successfully sent batch of {len(self.image_queue)} images to Discord")
            else:
                print(f"Failed to send batch to Discord. Status: {response.status_code}")
        except Exception as e:
            print(f"Error sending batch to Discord: {e}")
        
        self.image_queue.clear()

# Node class mappings
NODE_CLASS_MAPPINGS = {
    "PreviewImageWithDiscord": PreviewImageWithDiscord
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PreviewImageWithDiscord": "Preview Image (with Discord option)"
}