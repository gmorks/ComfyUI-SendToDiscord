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
        - Loads the webhook URL and configuration from a configuration file.
        """
        self.output_dir = folder_paths.get_temp_directory() # Ensure this is thread-safe if used in a multithreaded environment
        self.type = "temp"
        self.prefix_append = "_temp_" + ''.join(random.choice("abcdefghijklmnopqrstupvxyz") for x in range(5))
        self.compress_level = 1
        self.config = self.load_config()
        self.webhook_url = self.config.get('Discord', 'webhook_url', fallback='')
        self.batch_size = 5  # Number of images to accumulate before sending
        self.image_queue = []
        self.last_status = "Ready"  # Last send status
        
        # Fallback and compression configurations
        self.enable_fallback = self.config.getboolean('Fallback', 'enable_fallback', fallback=True)
        self.enable_compression = self.config.getboolean('Fallback', 'enable_compression', fallback=True)
        self.compression_quality = self.config.getint('Fallback', 'compression_quality', fallback=80)
        self.max_file_size_mb = self.config.getfloat('Fallback', 'max_file_size_mb', fallback=8.0)

    def load_config(self):
        """
        Loads the complete configuration from a configuration file.
        
        Returns:
            ConfigParser: The configuration object with all settings loaded.
        """
        config = configparser.ConfigParser()
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        config.read(config_path)
        return config

    def get_file_size_mb(self, file_path):
        """
        Gets the size of a file in megabytes.
        
        Args:
            file_path (str): Path to the file.
            
        Returns:
            float: File size in MB.
        """
        return os.path.getsize(file_path) / (1024 * 1024)
    
    def compress_image(self, image_path):
        """
        Compresses an image to WebP format to reduce file size.
        
        Args:
            image_path (str): Path to the original image file.
            
        Returns:
            str: Path to the compressed file.
            
        Raises:
            Exception: If there's an error during compression.
        """
        print("⚠️ Warning: Compressing to WebP will remove workflow metadata from PNG")
        
        try:
            with Image.open(image_path) as img:
                # Convert to appropriate mode for WebP
                if img.mode in ('RGBA', 'LA', 'P'):
                    if img.mode == 'P' and 'transparency' in img.info:
                        img = img.convert('RGBA')
                    elif img.mode == 'LA':
                        img = img.convert('RGBA')
                else:
                    img = img.convert('RGB')
                
                # Generate compressed filename
                base_name = os.path.splitext(os.path.basename(image_path))[0]
                compressed_path = os.path.join(os.path.dirname(image_path), f"{base_name}_compressed.webp")
                
                # Save with WebP compression
                img.save(compressed_path, 'WEBP', quality=self.compression_quality, optimize=True)
                
                return compressed_path
                
        except Exception as e:
            raise Exception(f"Error compressing image: {e}")
    
    def _get_mime_type(self, file_path):
        """
        Determines MIME type based on file extension.
        
        Args:
            file_path (str): Path to the file.
            
        Returns:
            str: MIME type string.
        """
        ext = file_path.lower()
        if ext.endswith('.webp'):
            return 'image/webp'
        elif ext.endswith(('.jpg', '.jpeg')):
            return 'image/jpeg'
        else:
            return 'image/png'
    
    def _cleanup_temp_files(self, current_path, original_path, workflow_path):
        """
        Cleans up temporary files created during processing.
        
        Args:
            current_path (str): Path to the current (possibly compressed) image.
            original_path (str): Path to the original image.
            workflow_path (str): Path to the workflow JSON file.
        """
        for path in [current_path, workflow_path]:
             if path and path != original_path and os.path.exists(path):
                 try:
                     os.remove(path)
                 except OSError:
                     pass

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
                "optional":
                    {"passthrough_image": ("IMAGE", )},
                "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
                }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "preview_images"
    OUTPUT_NODE = True
    CATEGORY = "image"

    def preview_images(self, images, send_to_discord="disable", batch_mode="disable", passthrough_image=None, prompt=None, extra_pnginfo=None):
        """
        Previews images and optionally sends them to Discord.
        
        Args:
            images (list): List of images to preview.
            send_to_discord (str): Whether to send images to Discord ("enable" or "disable").
            batch_mode (str): Whether to send images in batch mode ("enable" or "disable").
            passthrough_image (list, optional): Optional image input for passthrough.
            prompt (str, optional): Prompt text to add as metadata.
            extra_pnginfo (dict, optional): Additional PNG info to add as metadata.
        
        Returns:
            dict: A dictionary containing the UI results with image details and optional image output.
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
                # Extract workflow JSON if available
                workflow_json = None
                if extra_pnginfo and 'workflow' in extra_pnginfo:
                    workflow_json = extra_pnginfo['workflow']
                
                if batch_mode == "enable":
                    # Store both image path and workflow JSON for batch processing
                    self.image_queue.append((full_path, file, workflow_json))
                    if len(self.image_queue) >= self.batch_size:
                        self.send_batch_to_discord()
                else:
                    self.send_to_discord(full_path, file, workflow_json)

            counter += 1

        # Send any remaining images in the queue
        if send_to_discord == "enable" and batch_mode == "enable" and self.image_queue:
            self.send_batch_to_discord()

        # Log workflow JSON if available (useful for debugging and potential future features)
        if extra_pnginfo and 'workflow' in extra_pnginfo:
            print(f"📋 Workflow JSON detected: {len(str(extra_pnginfo['workflow']))} characters")
            # Optionally log the workflow to a file for analysis
            try:
                workflow_log_path = os.path.join(self.output_dir, "workflow_log.json")
                with open(workflow_log_path, 'w') as f:
                    json.dump(extra_pnginfo['workflow'], f, indent=2)
                print(f"📁 Workflow saved to: {workflow_log_path}")
            except Exception as e:
                print(f"⚠️ Could not save workflow: {e}")

        # Return appropriate output based on whether passthrough is used
        output_image = passthrough_image if passthrough_image is not None else images
        return {"ui": {"images": results}, "result": (output_image,)}

    def send_to_discord(self, image_path, filename, workflow_json=None):
        """
        Sends a single image to Discord with intelligent fallback and compression.
        
        Args:
            image_path (str): The path to the image file.
            filename (str): The name of the image file.
            workflow_json (dict, optional): Workflow JSON to send alongside compressed images.
        """
        self.last_status = "📤 Sending..."
        current_path = image_path
        attempts = []
        workflow_path = None
        
        # Check if compression is needed
        if self.enable_compression and self.get_file_size_mb(current_path) > self.max_file_size_mb:
            try:
                current_path = self.compress_image(current_path)
                attempts.append(f"Compressed to {self.get_file_size_mb(current_path):.1f}MB")
                
                # Create workflow JSON file if available
                if workflow_json:
                    base_name = os.path.splitext(filename)[0]
                    workflow_filename = f"{base_name}_workflow.json"
                    workflow_path = os.path.join(os.path.dirname(current_path), workflow_filename)
                    
                    try:
                        with open(workflow_path, 'w') as f:
                            json.dump(workflow_json, f, indent=2)
                        attempts.append("+ workflow JSON")
                        print("📋 Workflow JSON will be sent alongside compressed image")
                    except Exception as e:
                        print(f"⚠️ Could not create workflow file: {e}")
                        workflow_path = None
                        
            except Exception as e:
                print(f"Error compressing image: {e}")
        
        # Attempt sending
        success = self._attempt_send_single(current_path, filename, workflow_path)
        
        if success:
            self.last_status = "✅ Sent"
            if attempts:
                print(f"Image sent successfully: {filename} ({', '.join(attempts)})")
            else:
                print(f"Image sent successfully: {filename}")
        else:
            self.last_status = "❌ Error"
            print(f"Error sending image: {filename}")
        
        # Clean up temporary files
        self._cleanup_temp_files(current_path, image_path, workflow_path)
    
    def _attempt_send_single(self, image_path, filename, workflow_path=None):
        """
        Attempts to send a single image to Discord, optionally with workflow JSON file.
        
        Args:
            image_path (str): Path to the image file.
            filename (str): Name of the file.
            workflow_path (str, optional): Path to the workflow JSON file.
            
        Returns:
            bool: True if sending was successful, False otherwise.
        """
        try:
            # Determine MIME type
            mime_type = self._get_mime_type(image_path)
            
            files = {}
            
            # Add image file
            with open(image_path, 'rb') as img_file:
                files['file'] = (filename, img_file.read(), mime_type)
            
            # Add workflow JSON file if available
            if workflow_path and os.path.exists(workflow_path):
                with open(workflow_path, 'rb') as workflow_file:
                    files['file1'] = (os.path.basename(workflow_path), workflow_file.read(), 'application/json')
            
            response = requests.post(self.webhook_url, files=files, timeout=30)
            return response.status_code == 200
            
        except Exception as e:
            print(f"Error in individual send: {e}")
            return False

    def send_batch_to_discord(self):
        """
        Sends a batch of images to Discord with intelligent fallback.
        """
        if not self.image_queue:
            return
            
        self.last_status = f"📤 Sending batch ({len(self.image_queue)} images)..."
        
        # Try batch sending first
        batch_success = self._attempt_send_batch()
        
        if batch_success:
            self.last_status = f"✅ Batch sent ({len(self.image_queue)} images)"
            print(f"Batch of {len(self.image_queue)} images sent successfully")
        elif self.enable_fallback:
            # Fallback: send one by one
            self.last_status = "🔄 Fallback: sending individually..."
            print("Fallback activated: sending images individually")
            
            success_count = 0
            for image_data in self.image_queue:
                image_path, filename, workflow_json = image_data
                if self._attempt_send_single_for_batch(image_path, filename, workflow_json):
                    success_count += 1
            
            if success_count == len(self.image_queue):
                self.last_status = f"✅ Sent individually ({success_count}/{len(self.image_queue)})"
            else:
                self.last_status = f"⚠️ Partial ({success_count}/{len(self.image_queue)})"
            
            print(f"Fallback completed: {success_count}/{len(self.image_queue)} images sent")
        else:
            self.last_status = "❌ Batch error"
            print("Error sending batch and fallback disabled")
        
        self.image_queue.clear()
    
    def _attempt_send_batch(self):
        """
        Attempts to send a batch of images to Discord.
        
        Returns:
            bool: True if sending was successful, False otherwise.
        """
        try:
            files = {}
            total_size = 0
            
            for i, image_data in enumerate(self.image_queue):
                image_path, filename, workflow_json = image_data
                file_size = self.get_file_size_mb(image_path)
                total_size += file_size
                
                # Check Discord limit (25MB total)
                if total_size > 25:
                    print(f"Batch exceeds 25MB ({total_size:.1f}MB), activating fallback")
                    return False
                
                with open(image_path, 'rb') as img_file:
                    # Determine MIME type
                    mime_type = self._get_mime_type(image_path)
                    files[f'file{i}'] = (filename, img_file.read(), mime_type)
            
            response = requests.post(self.webhook_url, files=files, timeout=60)
            return response.status_code == 200
            
        except Exception as e:
            print(f"Error in batch send: {e}")
            return False
    
    def _attempt_send_single_for_batch(self, image_path, filename, workflow_json=None):
        """
        Attempts to send an individual image as part of batch fallback.
        
        Args:
            image_path (str): Path to the image file.
            filename (str): Name of the file.
            workflow_json (dict, optional): Workflow JSON to send alongside compressed images.
            
        Returns:
            bool: True if sending was successful, False otherwise.
        """
        current_path = image_path
        workflow_path = None
        
        # Apply compression if enabled and necessary
        if self.enable_compression and self.get_file_size_mb(current_path) > self.max_file_size_mb:
            try:
                current_path = self.compress_image(current_path)
                
                # If we compressed and have workflow JSON, create a temporary JSON file
                if workflow_json:
                    base_name = os.path.splitext(filename)[0]
                    workflow_filename = f"{base_name}_workflow.json"
                    workflow_path = os.path.join(os.path.dirname(current_path), workflow_filename)
                    
                    try:
                        with open(workflow_path, 'w') as f:
                            json.dump(workflow_json, f, indent=2)
                    except Exception as e:
                        print(f"⚠️ Could not create workflow file for batch fallback: {e}")
                        workflow_path = None
                        
            except Exception as e:
                print(f"Error compressing {filename}: {e}")
        
        # Attempt sending
        success = self._attempt_send_single(current_path, filename, workflow_path)
        
        # Clean up temporary files
        self._cleanup_temp_files(current_path, image_path, workflow_path)
        
        return success

# Node class mappings
NODE_CLASS_MAPPINGS = {
    "PreviewImageWithDiscord": PreviewImageWithDiscord
}

# Node display name mappings
NODE_DISPLAY_NAME_MAPPINGS = {
    "PreviewImageWithDiscord": "Preview Image (with Discord option)"
}