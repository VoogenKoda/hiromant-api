import cv2
import numpy as np
from PIL import Image
from google import genai
import os
import json
from models import HandAnalysis
from services.database import get_valid_attributes

try:
    valid_attributes = get_valid_attributes()
    concept_list = list(valid_attributes.keys())
    valid_attributes_json = json.dumps(valid_attributes, ensure_ascii=False)
except Exception as e:
    print(f"Warning: could not load attributes: {e}")
    concept_list = ['life_line', 'head_line']
    valid_attributes_json = "{}"

def enhance_hand_image(img: Image.Image):
    open_cv_image = np.array(img)
    if len(open_cv_image.shape) == 3 and open_cv_image.shape[2] == 3:
        open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    elif len(open_cv_image.shape) == 3 and open_cv_image.shape[2] == 4:
        open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_RGBA2BGR)
        
    hsv = cv2.cvtColor(open_cv_image, cv2.COLOR_BGR2HSV)
    lower_skin = np.array([0, 15, 0], dtype=np.uint8)
    upper_skin = np.array([17, 170, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower_skin, upper_skin)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.GaussianBlur(mask, (5,5), 0)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    final_mask = np.zeros_like(mask)
    if contours:
        c = max(contours, key=cv2.contourArea)
        cv2.drawContours(final_mask, [c], -1, 255, -1)
        
    gray = cv2.cvtColor(open_cv_image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=5.0, tileGridSize=(8,8))
    contrast_img = clahe.apply(gray)
    
    # Blur = 0, CLAHE = 5.0, Canny Min = 179, Canny Max = 158
    edges = cv2.Canny(contrast_img, 179, 158)
    
    clean_edges = cv2.bitwise_and(edges, edges, mask=final_mask)
    
    enhanced_pil = Image.fromarray(cv2.cvtColor(contrast_img, cv2.COLOR_GRAY2RGB))
    edges_pil = Image.fromarray(cv2.cvtColor(clean_edges, cv2.COLOR_GRAY2RGB))
    
    return enhanced_pil, edges_pil

def analyze_image(client: genai.Client, img: Image.Image, enhanced_img: Image.Image, edges_img: Image.Image) -> HandAnalysis | None:
    valid_concepts_str = ", ".join(concept_list)
    prompt = f"""
    You are an expert palmist and computer vision specialist.
    Carefully analyze the provided images of a hand (original, contrast-enhanced, and edge-detected) and identify the main lines, finger proportions, thumb shape, etc.
    The second image has enhanced contrast to help you see faint lines. The third image uses Canny edge detection to highlight structural lines.
    I have also included a reference diagram ("The Map of the Hand") as the last image. Use this reference diagram as a visual guide to correctly identify where the mounts (Jupiter, Saturn, Apollo/Sun, Mercury, Venus, Moon/Luna) and the major lines (Life, Head, Heart, Destiny/Fate) are typically located.
    Output the results strictly in JSON format according to the requested schema.
    Use English snake_case format for feature names and values (concept_canonical_name, attribute_name, attribute_value) so they map correctly to a database ontology.
    CRITICAL: For concept_canonical_name, you MUST strictly use ONLY names from this exact list: [{valid_concepts_str}]. Do not invent new names.
    CRITICAL: For attribute_value, you MUST strictly select an exact matching value from the following JSON schema which maps each concept to its allowed values. Do not invent new attribute values or modify the strings.
    VALID ATTRIBUTES SCHEMA:
    {valid_attributes_json}
    
    Focus strictly on features that are clearly distinguishable and visible in the images.
    CRITICAL: For lines (e.g. line_of_life, line_of_head, line_of_heart), you must provide a list of 3 to 6 points that physically trace the line on the image. BE VERY PRECISE with coordinates (0-100%). Do not place points outside the hand or the visible line.
    """
    
    try:
        ref_map_path = os.path.join(os.path.dirname(__file__), '..', '..', '_archive', 'Palmistry for All', 'images', 'fig001.jpg')
        contents = [img, enhanced_img, edges_img]
        
        if os.path.exists(ref_map_path):
            ref_map = Image.open(ref_map_path)
            contents.append(ref_map)
            
        contents.append(prompt)

        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=contents,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=HandAnalysis,
                temperature=0.0
            ),
        )
        if hasattr(response, 'parsed') and response.parsed:
            return response.parsed
        else:
            return HandAnalysis.model_validate_json(response.text)
    except Exception as e:
        print(f"Vision API error: {e}")
        return None
