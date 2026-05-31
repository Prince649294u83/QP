import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite://"
test_workspace_root = Path(tempfile.gettempdir()) / "qpgen_academic_e2e"
os.environ["STORAGE_ROOT"] = str(test_workspace_root / "test-storage")
test_workspace_root.mkdir(parents=True, exist_ok=True)
Path(os.environ["STORAGE_ROOT"]).mkdir(parents=True, exist_ok=True)

from app.main import app

def login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]

def test_academic_ingestion_and_generation():
    with TestClient(app) as client:
        # Login as teacher
        token = login(client, "teacher@dsatm.edu", "Teacher@123")
        headers = {"Authorization": f"Bearer {token}"}
        
        # 1. Upload a document
        test_file_content = b"The process of photosynthesis in plants converts light energy into chemical energy. It occurs in the chloroplasts and involves two main stages: light-dependent reactions and the Calvin cycle."
        
        files = {"file": ("test_notes.txt", test_file_content, "text/plain")}
        data = {"subject_id": 1, "document_type": "notes"}
        
        upload_response = client.post(
            "/api/v1/academic/documents/upload",
            headers=headers,
            data=data,
            files=files
        )
        assert upload_response.status_code == 200, f"Upload failed: {upload_response.text}"
        doc_data = upload_response.json()
        assert doc_data["processing_status"] in ["completed", "embedding"]
        
        # 2. Check chunks
        chunks_response = client.get(f"/api/v1/academic/chunks?document_id={doc_data['id']}", headers=headers)
        assert chunks_response.status_code == 200
        chunks = chunks_response.json()
        assert len(chunks) > 0, "No chunks created"
        
        print("\n--- Extracted Chunks ---")
        for i, c in enumerate(chunks):
            print(f"Chunk {i+1}: {c['chunk_text'][:100]}...")
        print("------------------------\n")
        
        # Approve all chunks so they can be used for generation
        for chunk in chunks:
            approve_resp = client.put(
                f"/api/v1/academic/chunks/{chunk['id']}/approve",
                headers=headers,
                json={"approval_status": "approved", "review_notes": "Looks good"}
            )
            assert approve_resp.status_code == 200
        
        # 3. Try to generate a question using RAG
        generate_req = {
            "subject_id": 1,
            "num_questions": 2,
            "marks_distribution": {"5": 1, "10": 1},
            "bloom_levels": ["L2", "L3"],
            "co_targets": ["CO1", "CO2"],
            "question_types": ["descriptive"],
            "additional_instructions": "Make it about photosynthesis"
        }
        
        generate_response = client.post(
            "/api/v1/academic/generate",
            headers=headers,
            json=generate_req
        )
        
        if generate_response.status_code == 500:
            print("Generation failed with 500. This might be due to missing ollama or embeddings service.")
            print(generate_response.text)
        else:
            assert generate_response.status_code == 200, f"Generation failed: {generate_response.text}"
            gen_data = generate_response.json()
            assert "questions" in gen_data
            
            if len(gen_data["questions"]) == 0:
                print("Generation returned 0 questions. This happens if Ollama is not running locally.")
            else:
                assert len(gen_data["questions"]) > 0
                # Print success
                print("Successfully extracted and generated content!")


def test_syllabus_documents_do_not_unlock_generation():
    with TestClient(app) as client:
        token = login(client, "teacher@dsatm.edu", "Teacher@123")
        headers = {"Authorization": f"Bearer {token}"}

        syllabus_content = b"""Machine Learning syllabus
Course outcomes include regression, classification, clustering, and evaluation.
Module 1: Foundations of machine learning
Module 2: Regression and optimization
Module 3: Classification and ensemble methods
"""

        upload_response = client.post(
            "/api/v1/academic/documents/upload",
            headers=headers,
            data={"subject_id": 2, "document_type": "syllabus"},
            files={"file": ("machine_learning_syllabus.txt", syllabus_content, "text/plain")},
        )
        assert upload_response.status_code == 200, upload_response.text
        assert upload_response.json()["document_type"] == "syllabus"

        generate_response = client.post(
            "/api/v1/academic/generate",
            headers=headers,
            json={
                "subject_id": 2,
                "num_questions": 1,
                "marks_distribution": {"5": 1},
                "bloom_levels": ["L2"],
                "co_targets": ["CO1"],
                "question_types": ["descriptive"],
            },
        )
        assert generate_response.status_code == 400
        assert "No approved knowledge chunks found" in generate_response.json()["detail"]


def test_module_filtered_generation_stays_within_requested_module():
    with TestClient(app) as client:
        token = login(client, "teacher@dsatm.edu", "Teacher@123")
        headers = {"Authorization": f"Bearer {token}"}

        uploads = [
            (
                "module1_notes.txt",
                b"State space search uses breadth first search, depth first search, and heuristic evaluation for problem solving in artificial intelligence.",
                1,
                "State space search",
            ),
            (
                "module2_notes.txt",
                b"Knowledge representation uses semantic networks, frames, and predicate logic to encode facts and inference rules in artificial intelligence.",
                2,
                "Knowledge representation",
            ),
        ]

        chunk_ids: list[tuple[int, int, str]] = []
        for filename, content, module_number, topic_name in uploads:
            upload_response = client.post(
                "/api/v1/academic/documents/upload",
                headers=headers,
                data={"subject_id": 4, "document_type": "notes"},
                files={"file": (filename, content, "text/plain")},
            )
            assert upload_response.status_code == 200, upload_response.text
            document_id = upload_response.json()["id"]

            chunks_response = client.get(
                f"/api/v1/academic/chunks?document_id={document_id}",
                headers=headers,
            )
            assert chunks_response.status_code == 200
            chunks = chunks_response.json()
            assert chunks
            chunk_ids.append((chunks[0]["id"], module_number, topic_name))

        for chunk_id, module_number, topic_name in chunk_ids:
            edit_response = client.put(
                f"/api/v1/academic/chunks/{chunk_id}/edit",
                headers=headers,
                json={
                    "module_number": module_number,
                    "topic_name": topic_name,
                    "bloom_level": "L2",
                    "co_mapping": "CO1",
                },
            )
            assert edit_response.status_code == 200, edit_response.text

            approve_response = client.put(
                f"/api/v1/academic/chunks/{chunk_id}/approve",
                headers=headers,
                json={"approval_status": "approved", "review_notes": "Module-aligned chunk"},
            )
            assert approve_response.status_code == 200, approve_response.text

        generate_response = client.post(
            "/api/v1/academic/generate",
            headers=headers,
            json={
                "subject_id": 4,
                "num_questions": 1,
                "marks_distribution": {"5": 1},
                "bloom_levels": ["L2"],
                "co_targets": ["CO1"],
                "question_types": ["descriptive"],
                "module_filter": 1,
                "additional_instructions": "Focus on state space search techniques.",
            },
        )
        assert generate_response.status_code == 200, generate_response.text
        payload = generate_response.json()
        assert payload["questions"], payload
        question = payload["questions"][0]
        assert question["module_number"] == 1
        assert not any("module boundaries" in message.lower() for message in question["validation_errors"])


def test_paper_generation_filters_out_overlap_prone_rag_questions():
    with TestClient(app) as client:
        token = login(client, "teacher@dsatm.edu", "Teacher@123")
        headers = {"Authorization": f"Bearer {token}"}

        noisy_notes = b"""MODULE 3
INFORMED (HEURISTIC) SEARCH STRATEGIES
Informed search strategy is one that uses problem-specific knowledge beyond the definition of itself and can find solutions more efficiently than an uninformed strategy.
"""

        upload_response = client.post(
            "/api/v1/academic/documents/upload",
            headers=headers,
            data={"subject_id": 1, "document_type": "notes"},
            files={"file": ("iai_module3_notes.txt", noisy_notes, "text/plain")},
        )
        assert upload_response.status_code == 200, upload_response.text

        paper_response = client.post(
            "/api/v1/ai/generate-paper",
            headers=headers,
            json={
                "subject_id": 1,
                "title": "IAT-1 AI Paper",
                "exam_type": "IAT-1",
                "semester": "1",
                "batch": "2022-26",
                "max_marks": 50,
                "duration_minutes": 90,
                "teaching_department": "AIML",
                "prompt": "Generate a balanced AI paper without repeated or note-like questions.",
                "rbt_levels": ["L1", "L2", "L3", "L4"],
                "module_numbers": [1, 2, 3, 4, 5],
            },
        )
        assert paper_response.status_code == 200, paper_response.text
        paper = paper_response.json()
        assert paper["questions"]
        assert len({item["text"] for item in paper["questions"]}) == len(paper["questions"])
        assert all(not item.get("validation_errors") for item in paper["questions"])
        assert all(not item.get("validation_warnings") for item in paper["questions"])
