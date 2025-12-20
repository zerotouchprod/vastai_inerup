"""
Example usage of ROI Processing System.
Shows how to integrate ROI processing into an AI agent workflow.
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def example_basic_roi():
    """Basic example of ROI processing."""
    print("=== Basic ROI Processing Example ===")
    
    from src.schemas.roi import RegionOfInterest
    from src.services.image_processor import ImageService
    
    # 1. Create ROI for "slightly below center" region
    roi = RegionOfInterest(x=0.1, y=0.6, width=0.8, height=0.3)
    print(f"Created ROI: x={roi.x}, y={roi.y}, width={roi.width}, height={roi.height}")
    
    # 2. Or use the default ROI (same as above)
    default_roi = ImageService.get_default_roi()
    print(f"Default ROI: x={default_roi.x}, y={default_roi.y}")
    
    # 3. Create ROI from string (useful for configuration)
    roi_from_string = RegionOfInterest.from_string("0.1,0.6,0.8,0.3")
    print(f"ROI from string: {roi_from_string}")
    
    # 4. Convert to pixel coordinates for a 1920x1080 image
    left, top, right, bottom = roi.to_pixel_coordinates(1920, 1080)
    print(f"Pixel coordinates for 1920x1080: left={left}, top={top}, right={right}, bottom={bottom}")
    print(f"Crop size: {right-left}x{bottom-top} pixels")
    
    return True

def example_image_processing():
    """Example of actual image processing with ROI."""
    print("\n=== Image Processing Example ===")
    
    try:
        from PIL import Image
        from src.schemas.roi import RegionOfInterest
        from src.services.image_processor import ImageService
        
        # Create a sample image (in real usage, this would come from screen capture or file)
        width, height = 800, 600
        sample_image = Image.new('RGB', (width, height), color='white')
        
        # Define ROI for the region we want to focus on
        roi = RegionOfInterest(x=0.2, y=0.5, width=0.6, height=0.4)
        
        # Crop the image to the ROI
        cropped_image = ImageService.crop_image(sample_image, roi)
        
        print(f"Original image: {width}x{height}")
        print(f"ROI: {roi.width*100:.0f}% width, {roi.height*100:.0f}% height")
        print(f"Cropped image: {cropped_image.size[0]}x{cropped_image.size[1]}")
        print("✓ Image successfully cropped to ROI")
        
        # In a real AI agent, you would now pass cropped_image to your vision model
        # Example: vision_model.process(cropped_image)
        
        return True
        
    except ImportError:
        print("PIL not available, skipping image example")
        return True
    except Exception as e:
        print(f"Error in image processing example: {e}")
        return False

def example_agent_integration():
    """Example of how to integrate ROI processing into an AI agent."""
    print("\n=== AI Agent Integration Example ===")
    
    print("""
Typical AI Agent Workflow with ROI:

1. Capture screen or load image
2. Define ROI based on task (e.g., "slightly below center" for UI elements)
3. Crop image to ROI to remove noise and focus on relevant area
4. Process cropped image with vision model
5. Return results

Example code structure:

class AIAgent:
    def __init__(self):
        from src.services.image_processor import ImageService
        self.image_service = ImageService
        self.default_roi = ImageService.get_default_roi()  # x=0.1, y=0.6, width=0.8, height=0.3
    
    def process_screen(self, screen_image):
        # Crop to ROI to focus on relevant area
        cropped = self.image_service.crop_image(screen_image, self.default_roi)
        
        # Process with vision model
        result = self.vision_model.process(cropped)
        
        return result
    
    def process_with_custom_roi(self, screen_image, roi_string):
        # Parse custom ROI from configuration
        from src.schemas.roi import RegionOfInterest
        roi = RegionOfInterest.from_string(roi_string)
        
        # Crop and process
        cropped = self.image_service.crop_image(screen_image, roi)
        return self.vision_model.process(cropped)
""")
    
    return True

def example_error_handling():
    """Example of error handling in ROI processing."""
    print("\n=== Error Handling Example ===")
    
    from src.schemas.roi import RegionOfInterest
    from src.services.image_processor import ImageService, ImageProcessingError
    
    # 1. Invalid ROI (out of bounds)
    try:
        invalid_roi = RegionOfInterest(x=0.9, y=0.6, width=0.2, height=0.3)
        print("✗ Should have raised ValueError")
        return False
    except ValueError as e:
        print(f"✓ Correctly caught invalid ROI: {e}")
    
    # 2. Invalid image source
    try:
        # Try to crop a non-existent image
        roi = RegionOfInterest(x=0.1, y=0.6, width=0.8, height=0.3)
        ImageService.crop_image("non_existent.jpg", roi)
        print("✗ Should have raised ImageProcessingError")
        return False
    except (ImageProcessingError, FileNotFoundError) as e:
        print(f"✓ Correctly caught invalid image source: {e}")
    
    return True

def main():
    """Run all examples."""
    print("ROI Processing System - Usage Examples")
    print("=" * 60)
    
    examples = [
        ("Basic ROI", example_basic_roi),
        ("Image Processing", example_image_processing),
        ("Agent Integration", example_agent_integration),
        ("Error Handling", example_error_handling)
    ]
    
    for example_name, example_func in examples:
        print(f"\nRunning: {example_name}")
        if not example_func():
            print(f"[ERROR] Example '{example_name}' failed")
            return False
    
    print("\n" + "=" * 60)
    print("✅ All examples completed successfully!")
    print("\nSummary of ROI Processing System:")
    print("1. ✅ Pydantic models with strict validation")
    print("2. ✅ Normalized coordinates (0.0-1.0) for resolution independence")
    print("3. ✅ Image cropping service with error handling")
    print("4. ✅ Default ROI for 'slightly below center' (x=0.1, y=0.6, width=0.8, height=0.3)")
    print("5. ✅ Center-based ROI creation")
    print("6. ✅ String parsing for configuration")
    print("7. ✅ Integration ready for AI agents")
    
    print("\nTo integrate into your AI agent:")
    print("1. Import RegionOfInterest and ImageService")
    print("2. Define ROI for your use case (or use default)")
    print("3. Crop images before passing to vision model")
    print("4. Handle errors appropriately")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
