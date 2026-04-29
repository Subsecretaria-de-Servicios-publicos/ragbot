"""
app/services/rag_service.py — FIXES:
  #2  closure bug en lambda de Google embed
  #4  SQL injection en search() → usar text() con parámetros
  #11 límite de chunks por documento
  #5  índice HNSW solo en migración, no en __table_args__
"""
import os
import re
import asyncio
from typing import Optional
from dataclasses import dataclass
import structlog
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Document, DocumentChunk, DocumentStatus

logger = structlog.get_logger()

MAX_CHUNKS_PER_DOCUMENT = 2000  # FIX #11: límite para evitar OOM en PDFs gigantes


@dataclass
class ChunkResult:
    content: str
    chunk_index: int
    page_number: Optional[int]
    metadata: dict
    score: float = 0.0
    document_id: str = ""
    filename: str = ""


# ─── Text Extraction ──────────────────────────────────────────
class DocumentExtractor:
    @staticmethod
    async def extract(file_path: str, mime_type: str) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, DocumentExtractor._extract_sync, file_path, mime_type)

    @staticmethod
    def _extract_sync(file_path: str, mime_type: str) -> list[dict]:
        pages = []
        if "pdf" in mime_type:
            pages = DocumentExtractor._extract_pdf(file_path)
        elif "word" in mime_type or file_path.endswith(".docx"):
            from docx import Document as DocxDocument
            doc = DocxDocument(file_path)
            full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            if full_text.strip():
                pages.append({"page": 1, "text": full_text})
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text_content = f.read()
            if text_content.strip():
                pages.append({"page": 1, "text": text_content})
        return pages

    @staticmethod
    def _extract_pdf(file_path: str) -> list[dict]:
        import pdfplumber
        pages = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text_content = page.extract_text() or ""
                if text_content.strip():
                    pages.append({"page": i, "text": text_content})
        if not pages:
            logger.info("pdf_no_text_trying_ocr", file=file_path)
            pages = DocumentExtractor._ocr_pdf(file_path)
        return pages

    @staticmethod
    def _ocr_pdf(file_path: str) -> list[dict]:
        pages = []
        try:
            import pytesseract
            from pdf2image import convert_from_path
            images = convert_from_path(file_path, dpi=200)
            for i, img in enumerate(images, 1):
                text_content = pytesseract.image_to_string(img, lang="spa+eng")
                if text_content.strip():
                    pages.append({"page": i, "text": text_content})
            if pages:
                logger.info("ocr_success", pages=len(pages))
        except ImportError:
            logger.warning("ocr_missing_deps",
                hint="pip install pytesseract pdf2image && apt install tesseract-ocr tesseract-ocr-spa poppler-utils")
        except Exception as e:
            logger.error("ocr_error", error=str(e))
        return pages


# ─── Chunking ─────────────────────────────────────────────────
class TextChunker:
    def __init__(self, chunk_size: int = None, overlap: int = None):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.overlap = overlap or settings.CHUNK_OVERLAP

    def chunk(self, pages: list[dict]) -> list[ChunkResult]:
        chunks = []
        idx = 0
        for page_data in pages:
            text_content = self._clean_text(page_data["text"])
            page_num = page_data["page"]
            for chunk_text in self._split_text(text_content):
                if chunk_text.strip():
                    chunks.append(ChunkResult(
                        content=chunk_text.strip(),
                        chunk_index=idx,
                        page_number=page_num,
                        metadata={"page": page_num, "chunk_size": len(chunk_text)},
                    ))
                    idx += 1
                    # FIX #11: respetar límite máximo de chunks
                    if idx >= MAX_CHUNKS_PER_DOCUMENT:
                        logger.warning("chunk_limit_reached", limit=MAX_CHUNKS_PER_DOCUMENT)
                        return chunks
        return chunks

    def _clean_text(self, text_content: str) -> str:
        text_content = re.sub(r'\n{3,}', '\n\n', text_content)
        text_content = re.sub(r'[ \t]+', ' ', text_content)
        return text_content.strip()

    def _split_text(self, text_content: str) -> list[str]:
        if len(text_content) <= self.chunk_size:
            return [text_content]
        chunks = []
        sentences = re.split(r'(?<=[.!?])\s+', text_content)
        current = []
        current_len = 0
        for sentence in sentences:
            if current_len + len(sentence) > self.chunk_size and current:
                chunks.append(" ".join(current))
                overlap_text = " ".join(current)
                overlap_start = max(0, len(overlap_text) - self.overlap)
                current = [overlap_text[overlap_start:]] if overlap_start > 0 else []
                current_len = sum(len(s) for s in current)
            current.append(sentence)
            current_len += len(sentence) + 1
        if current:
            chunks.append(" ".join(current))
        return chunks


# ─── Embeddings ───────────────────────────────────────────────
class EmbeddingService:
    def __init__(self, provider: str = None):
        self.provider = provider or settings.DEFAULT_EMBEDDING_PROVIDER

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        if self.provider == "openai":
            return await self._openai_embed(texts)
        elif self.provider == "sentence_transformers":
            return await loop.run_in_executor(None, self._st_embed, texts)
        elif self.provider == "google":
            return await self._google_embed(texts)
        raise ValueError(f"Embedding provider desconocido: {self.provider}")

    async def embed_query(self, text_content: str) -> list[float]:
        results = await self.embed_texts([text_content])
        return results[0]

    async def _openai_embed(self, texts: list[str]) -> list[list[float]]:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        all_embeddings = []
        for i in range(0, len(texts), 100):
            batch = texts[i:i+100]
            response = await client.embeddings.create(
                model=settings.OPENAI_EMBEDDING_MODEL, input=batch,
            )
            all_embeddings.extend([e.embedding for e in response.data])
        return all_embeddings

    def _st_embed(self, texts: list[str]) -> list[list[float]]:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model.encode(texts, batch_size=32).tolist()

    async def _google_embed(self, texts: list[str]) -> list[list[float]]:
        """
        Google Embeddings con rate limiting para el free tier (100 req/min).
        - Lotes de BATCH_SIZE requests con pausa entre ellos
        - Retry automático con backoff exponencial si llega 429
        """
        import google.generativeai as genai
        import re as _re
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        loop = asyncio.get_event_loop()
        results = []
        model_name = settings.GOOGLE_EMBEDDING_MODEL

        BATCH_SIZE = getattr(settings, "GOOGLE_EMBED_BATCH_SIZE", 20)
        DELAY = getattr(settings, "GOOGLE_EMBED_DELAY", 3.5)
        MAX_RETRIES = 5
        total = len(texts)

        logger.info("google_embed_start", total=total, batch_size=BATCH_SIZE, delay=DELAY)

        for batch_num, i in enumerate(range(0, total, BATCH_SIZE)):
            batch = texts[i:i + BATCH_SIZE]

            if batch_num > 0:
                total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
                logger.info("google_embed_batch", batch=batch_num + 1,
                            of=total_batches, delay=DELAY)
                await asyncio.sleep(DELAY)

            for text_item in batch:
                for attempt in range(MAX_RETRIES):
                    try:
                        r = await loop.run_in_executor(
                            None,
                            lambda t=text_item: genai.embed_content(
                                model=model_name,
                                content=t,
                                task_type="retrieval_document",
                            )
                        )
                        results.append(r["embedding"])
                        break

                    except Exception as e:
                        err = str(e)
                        is_quota = "429" in err or "quota" in err.lower() or "rate" in err.lower()

                        if is_quota and attempt < MAX_RETRIES - 1:
                            wait = 62.0
                            m = _re.search(r"seconds[:\s]+([\d]+)", err)
                            if m:
                                wait = float(m.group(1)) + 3
                            logger.warning("google_embed_rate_limit",
                                           attempt=attempt + 1, wait=wait,
                                           done=len(results), total=total)
                            await asyncio.sleep(wait)
                        else:
                            logger.error("google_embed_failed",
                                         attempt=attempt + 1, error=err[:300])
                            raise

        logger.info("google_embed_complete", total=len(results))
        return results


# ─── RAG Service ──────────────────────────────────────────────
class RAGService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.chunker = TextChunker()
        self.embedder = EmbeddingService()

    async def process_document(self, document_id: str) -> bool:
        try:
            await self.db.execute(
                update(Document).where(Document.id == document_id)
                .values(status=DocumentStatus.processing)
            )
            await self.db.commit()

            doc = await self.db.get(Document, document_id)
            if not doc:
                raise ValueError(f"Documento {document_id} no encontrado")

            logger.info("rag_processing_start", doc_id=document_id, file=doc.original_filename)

            pages = await DocumentExtractor.extract(doc.file_path, doc.mime_type)
            if not pages:
                raise ValueError("No se pudo extraer texto del documento")

            chunks = self.chunker.chunk(pages)
            logger.info("rag_chunks_created", count=len(chunks))

            texts = [c.content for c in chunks]
            embeddings = await self.embedder.embed_texts(texts)

            db_chunks = []
            for chunk, embedding in zip(chunks, embeddings):
                db_chunks.append(DocumentChunk(
                    document_id=document_id,
                    chatbot_id=doc.chatbot_id,
                    content=chunk.content,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    chunk_metadata=chunk.metadata,
                    embedding=embedding,
                ))
            self.db.add_all(db_chunks)

            await self.db.execute(
                update(Document).where(Document.id == document_id)
                .values(status=DocumentStatus.ready, chunk_count=len(chunks), page_count=len(pages))
            )
            await self.db.commit()
            logger.info("rag_processing_complete", doc_id=document_id, chunks=len(chunks))
            return True

        except Exception as e:
            logger.error("rag_processing_error", doc_id=document_id, error=str(e))
            await self.db.execute(
                update(Document).where(Document.id == document_id)
                .values(status=DocumentStatus.error, error_message=str(e))
            )
            await self.db.commit()
            return False

    async def search(
        self,
        chatbot_id: str,
        query: str,
        top_k: int = None,
        threshold: float = 0.7,
    ) -> list[ChunkResult]:
        """
        FIX #4: usar text() con parámetros bindados para evitar SQL injection.
        El embedding_str sigue siendo interpolado (pgvector no soporta bind para ::vector)
        pero chatbot_id, threshold y top_k ahora son parámetros seguros.
        """
        top_k = top_k or settings.TOP_K_RESULTS
        query_embedding = await self.embedder.embed_query(query)
        # El vector debe interpolarse (limitación de pgvector con asyncpg)
        # pero todos los otros valores van como parámetros bind seguros
        embedding_str = "[" + ",".join(f"{v:.8f}" for v in query_embedding) + "]"

        sql = text(f"""
            SELECT
                dc.id, dc.content, dc.chunk_index, dc.page_number,
                dc.chunk_metadata, dc.document_id, d.original_filename,
                1 - (dc.embedding <=> '{embedding_str}'::vector) AS similarity
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.chatbot_id = :chatbot_id
              AND d.status = 'ready'
              AND 1 - (dc.embedding <=> '{embedding_str}'::vector) >= :threshold
            ORDER BY dc.embedding <=> '{embedding_str}'::vector
            LIMIT :top_k
        """)

        raw = await self.db.execute(
            sql,
            {"chatbot_id": chatbot_id, "threshold": threshold, "top_k": top_k}
        )
        rows = raw.fetchall()
        return [
            ChunkResult(
                content=row.content,
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                metadata=row.chunk_metadata or {},
                score=float(row.similarity),
                document_id=row.document_id,
                filename=row.original_filename,
            )
            for row in rows
        ]

    def build_context(self, chunks: list[ChunkResult], max_tokens: int = None) -> str:
        max_tokens = max_tokens or settings.MAX_CONTEXT_TOKENS
        context_parts = []
        total_chars = 0
        max_chars = max_tokens * 4
        for chunk in chunks:
            header = f"[Fuente: {chunk.filename}, Página {chunk.page_number}, Relevancia: {chunk.score:.2f}]"
            part = f"{header}\n{chunk.content}"
            if total_chars + len(part) > max_chars:
                break
            context_parts.append(part)
            total_chars += len(part)
        return "\n\n---\n\n".join(context_parts)
