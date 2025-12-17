from paddleocr import PaddleOCR
import cv2
import sys

ocr = PaddleOCR(lang="en")
img = cv2.imread("test_img/frame_000001.png")
if img is None:
    print("Image not found")
    sys.exit(1)
res = ocr.ocr(img)
print("Result type:", type(res))
if res:
    print("Result length:", len(res))
    if res[0]:
        print("First element type:", type(res[0]))
        print("First element:", res[0])
        if len(res[0]) > 0:
            print("First detection:", res[0][0])
            print("Detection structure:", res[0][0])
            print("Coordinates:", res[0][0][0])
            print("Text and confidence:", res[0][0][1])
