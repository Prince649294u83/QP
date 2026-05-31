import os
import json
import asyncio
from pathlib import Path

# Add backend to path if run from scripts folder
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.academic.content_extractor import PDFExtractor
from app.llm_pipeline import VisionExtractor, LLMCall

import base64

DATASET_EXTRACTION_PROMPT = """
You are an expert academic parser building a multi-modal fine-tuning dataset.
Extract all exam questions from the provided text and images. For each question, carefully infer its true academic properties.

If a question refers to or relies on one of the provided images (like a circuit diagram, graph, or flowchart), set "has_image" to true and include an "<image>" token in the question text where the image belongs.

Return STRICT JSON format with NO extra text or markdown blocks:
{
  "questions": [
    {
      "text": "...",
      "marks": number,
      "topic": "...",
      "bloom_level": "L1 Remember" | "L2 Understand" | "L3 Apply" | "L4 Analyze" | "L5 Evaluate" | "L6 Create",
      "difficulty": "Easy" | "Medium" | "Hard",
      "course_outcome": "CO1" | "CO2" | "CO3" | "CO4" | "CO5",
      "module": number,
      "has_image": true | false
    }
  ]
}
"""

def get_base64_image(image_path: str) -> str:
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode('utf-8')

async def process_pdf(pdf_path: str, llm: LLMCall) -> list[dict]:
    print(f"Extracting text and images from {pdf_path}...")
    pdf_extractor = PDFExtractor(output_dir="/tmp/pdf_out")
    result = pdf_extractor.extract(pdf_path)
    
    full_text = "\n".join([tb.text for tb in result.text_blocks])
    
    # Process extracted images
    base64_images = []
    image_paths = []
    if hasattr(result, 'images') and result.images:
        for img in result.images:
            if hasattr(img, 'image_path') and os.path.exists(img.image_path):
                base64_images.append(get_base64_image(img.image_path))
                image_paths.append(img.image_path)
                
    if not full_text and not base64_images:
        print(f"No content extracted from {pdf_path}")
        return []
        
    print(f"Extracting enriched multi-modal questions via LLM for {pdf_path} (Images: {len(base64_images)})...")
    
    prompt = DATASET_EXTRACTION_PROMPT + f"\n\nInput text:\n{full_text[:8000]}"
    
    # Pass images to LLM if available
    llm_kwargs = {}
    if base64_images:
        llm_kwargs["images"] = base64_images
        
    llm_result = llm(
        prompt, 
        "You are a specialized parser for creating high-quality, multi-modal instruction-tuning datasets.",
        **llm_kwargs
    )
    
    questions = []
    if isinstance(llm_result, dict) and "questions" in llm_result:
        questions = llm_result["questions"]
    
    dataset_entries = []
    for q in questions:
        topic = q.get("topic", "General")
        marks = q.get("marks", 5)
        bloom = q.get("bloom_level", "L2 Understand")
        difficulty = q.get("difficulty", "Medium")
        co = q.get("course_outcome", "CO2")
        module = q.get("module", 1)
        has_image = q.get("has_image", False)
        
        instruction = (
            f"Generate a unique and high-quality academic question for a University Examination.\n\n"
            f"Constraints:\n"
            f"- Module: {module}\n"
            f"- Topic: {topic}\n"
            f"- Course Outcome: {co}\n"
            f"- Bloom's Level: {bloom}\n"
            f"- Difficulty: {difficulty}\n"
            f"- Marks: {marks}\n"
        )
        
        if has_image:
            instruction += "- Modality: Includes an image diagram/reference.\n"
            
        instruction += "\nEnsure the question is academically rigorous, tests true comprehension, and avoids robotic phrasing."
        
        entry = {
            "instruction": instruction,
            "output": q.get("text", "")
        }
        
        # Attach image paths to the dataset entry if it requires an image
        if has_image and image_paths:
            entry["images"] = image_paths
            
        dataset_entries.append(entry)
        
    return dataset_entries

async def main():
    dataset_path = "dataset.jsonl"
    pdf_dir = "data/pdfs"
    
    if not os.path.exists(pdf_dir):
        print(f"Directory {pdf_dir} not found. Please create it and add PDF question papers.")
        # Create directory to help user
        os.makedirs(pdf_dir, exist_ok=True)
        return
        
    llm = LLMCall(model="phi4-mini")
    
    extracted_data = []
    
    print(f"Searching for PDFs in {pdf_dir}...")
    with open(dataset_path, "w", encoding="utf-8") as f:
        for filename in os.listdir(pdf_dir):
            if filename.endswith(".pdf"):
                pdf_path = os.path.join(pdf_dir, filename)
                entries = await process_pdf(pdf_path, llm)
                
                for entry in entries:
                    f.write(json.dumps(entry) + "\n")
                    
                print(f"Added {len(entries)} entries from {filename}")
                
    print(f"Dataset generated at {dataset_path}")

if __name__ == "__main__":
    asyncio.run(main())
                
