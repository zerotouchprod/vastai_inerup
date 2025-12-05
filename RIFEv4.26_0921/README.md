# RIFEv4.26_0921

This directory contains the RIFE v4.26 model files downloaded from the pre-trained weights.

## Structure

- `train_log/` - Contains the trained model weights (.pkl files) and model architecture files
  - `RIFE_HDv3.py` - Main model class definition  
  - `IFNet_HDv3.py` - IFNet architecture
  - `refine.py` - Refinement network
  - `flownet.pkl` - Pre-trained model weights

- `model/` - Contains supporting modules required by train_log files
  - `warplayer.py` - Optical flow warping utilities
  - `loss.py` - Loss function implementations (EPE, SOBEL, etc.)
  - `RIFE.py`, `IFNet.py` - Additional model architectures
  - Other utility modules

## Note

The `model/` directory files are copied from the original RIFE repository to satisfy
imports in the model architecture files. These are needed for both training and inference.

