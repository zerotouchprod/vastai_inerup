import sys
sys.path.insert(0, '.')

from src.application.factories import ProcessorFactory

def test_factory():
    print("Testing ROI parameter flow...")
    factory = ProcessorFactory()
    print("Factory created successfully")
    
    # Test with different ROI values
    test_cases = [
        'bottom',
        'full',
        '0.35',
        '0.1,0.7,0.8,0.2'
    ]
    
    for roi in test_cases:
        print(f"\nTesting with roi='{roi}':")
        try:
            remover = factory.create_subtitle_remover(lang='en', roi=roi)
            print(f"  ✓ Subtitle remover created successfully")
            # Check if roi was passed
            if hasattr(remover, '_roi'):
                print(f"  - Wrapper ROI attribute: {remover._roi}")
            elif hasattr(remover, 'roi_height_factor'):
                print(f"  - Service ROI factor: {remover.roi_height_factor}")
        except Exception as e:
            print(f"  ✗ Error: {e}")

if __name__ == '__main__':
    test_factory()
