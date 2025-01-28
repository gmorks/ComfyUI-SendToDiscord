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
    """
    A class to handle the preview image generation and sending it to Discord via webhook.
    
    Attributes:
        output_dir (str): The directory where temporary images are stored.
        type (str): The type of the generated images, default is 'temp'.
        prefix_append (str): A random string appended to image filenames for uniqueness.
        compress_level (int): Compression level for saving images.
        webhook_url (str): URL for Discord webhook to send the image.
        batch_size (int): Number of images to accumulate before sending a batch to Discord.
        image_queue (list): A list to hold paths of images waiting to be sent to Discord.
    """

    def __init__(self):
        """
        Initializes the PreviewImageWithDiscord class with default values and settings.
        
        - Sets the output directory for temporary images using `folder_paths.get_temp_directory()`.
        - Defines a prefix to be appended to image filenames for uniqueness.
        - Loads the webhook URL from a configuration file.
        """
        self.output_dir = folder_paths.get_temp_directory() # Ensure this is thread-safe if used in a multithreaded environment
        self.type = "temp"
        self.prefix_append = "_temp_" + ''.join(random.choice("abcdefghijklmnopqrstupvxyz") for x in range(5))
        self.compress_level = 1
        self.webhook_url = self.load_webhook_url()
        self.batch_size = 5  # Number of images to accumulate before sending
        self.image_queue = []

    def load_webhook_url(self):
        """
        Loads the webhook URL from a configuration file.
        
        Returns:
            str: The webhook URL if found, otherwise an empty string.
        """
        config = configparser.ConfigParser()
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        config.read(config_path)
        # Retrieve the webhook URL from the Discord section in the configuration file
        webhook_url = config.get('Discord', 'webhook_url', fallback='')
        return webhook_url

    @classmethod
    def INPUT_TYPES(s):
        """
        Defines the input types for the node.
        
        Returns:
            dict: A dictionary specifying required and hidden inputs.
        """
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
        """
        Previews images and optionally sends them to Discord.
        
        Args:
            images (list): List of images to preview.
            send_to_discord (str): Whether to send images to Discord ("enable" or "disable").
            batch_mode (str): Whether to send images in batch mode ("enable" or "disable").
            prompt (str, optional): Prompt text to add as metadata.
            extra_pnginfo (dict, optional): Additional PNG info to add as metadata.
        
        Returns:
            dict: A dictionary containing the UI results with image details.
        """
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

            # Send image to Discord if enabled
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
        """
        Sends a single image to Discord.
        
        Args:
            image_path (str): The path to the image file.
            filename (str): The name of the image file.
        """
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
        """
        Sends a batch of images to Discord.
        """
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

# Node display name mappings
NODE_DISPLAY_NAME_MAPPINGS = {
    "PreviewImageWithDiscord": "Preview Image (with Discord option)"
}