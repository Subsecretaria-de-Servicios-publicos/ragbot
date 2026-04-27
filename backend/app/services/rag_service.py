"""
app/services/rag_service.py — Procesamiento RAG completo: extracción, chunking, embeddings, búsqueda
"""
import os
import re
import asyncio
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import numpy as np
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from google.api_core.exceptions import ResourceExhausted
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Document, DocumentChunk, DocumentStatus

logger = structlog.get_logger()


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
        """Extrae texto con metadata de página."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, DocumentExtractor._extract_sync, file_path, mime_type)

    @staticmethod
    def _extract_sync(file_path: str, mime_type: str) -> list[dict]:
        pages = []
        if "pdf" in mime_type:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages, 1):
                    text = page.extract_text() or ""
                    if text.strip():
                        pages.append({"page": i, "text": text})
        elif "word" in mime_type or file_path.endswith(".docx"):
            from docx import Document as DocxDocument
            doc = DocxDocument(file_path)
            full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            pages.append({"page": 1, "text": full_text})
        else:
            # Texto plano
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                pages.append({"page": 1, "text": f.read()})
        return pages


# ─── Chunking ────────────────────────────────────────────────
class TextChunker:
    def __init__(self, chunk_size: int = None, overlap: int = None):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.overlap = overlap or settings.CHUNK_OVERLAP

    def chunk(self, pages: list[dict]) -> list[ChunkResult]:
        chunks = []
        idx = 0
        for page_data in pages:
            text = self._clean_text(page_data["text"])
            page_num = page_data["page"]
            page_chunks = self._split_text(text)
            for chunk_text in page_chunks:
                if chunk_text.strip():
                    chunks.append(ChunkResult(
                        content=chunk_text.strip(),
                        chunk_index=idx,
                        page_number=page_num,
                        metadata={"page": page_num, "chunk_size": len(chunk_text)},
                    ))
                    idx += 1
        return chunks

    def _clean_text(self, text: str) -> str:
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        return text.strip()

    def _split_text(self, text: str) -> list[str]:
        """Split por oraciones/párrafos respetando tamaño y overlap."""
        if len(text) <= self.chunk_size:
            return [text]

        chunks = []
        sentences = re.split(r'(?<=[.!?])\s+', text)
        current = []
        current_len = 0

        for sentence in sentences:
            if current_len + len(sentence) > self.chunk_size and current:
                chunks.append(" ".join(current))
                # Overlap: mantener últimas oraciones
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
    # Semáforo global para evitar saturar las APIs en procesos concurrentes
    # Se inicializa de forma diferida para evitar errores con el event loop en el import
    _semaphore: Optional[asyncio.Semaphore] = None
    _last_call_time: float = 0.0

    def __init__(self, provider: str = None):
        self.provider = provider or settings.DEFAULT_EMBEDDING_PROVIDER

    @classmethod
    def get_semaphore(cls) -> asyncio.Semaphore:
        if cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(1)
        return cls._semaphore

    async def _wait_for_rate_limit(self):
        """Implementa un retardo entre llamadas para respetar el RPM configurado."""
        if self.provider == "google" and settings.GOOGLE_EMBEDDING_RPM > 0:
            interval = 60.0 / settings.GOOGLE_EMBEDDING_RPM
            elapsed = time.time() - EmbeddingService._last_call_time
            if elapsed < interval:
                wait_time = interval - elapsed
                logger.debug("embedding_rate_limit_wait", wait_time=wait_time)
                await asyncio.sleep(wait_time)
            EmbeddingService._last_call_time = time.time()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings en lotes para optimizar costos."""
        loop = asyncio.get_event_loop()
        if self.provider == "openai":
            return await self._openai_embed(texts)
        elif self.provider == "sentence_transformers":
            return await loop.run_in_executor(None, self._st_embed, texts)
        elif self.provider == "google":
            return await self._google_embed(texts)
        raise ValueError(f"Embedding provider desconocido: {self.provider}")

    async def embed_query(self, text: str) -> list[float]:
        if self.provider == "google":
            import google.generativeai as genai
            genai.configure(api_key=settings.GOOGLE_API_KEY)
            loop = asyncio.get_event_loop()

            async with self.get_semaphore():
                await self._wait_for_rate_limit()
                r = await loop.run_in_executor(None, self._call_google_single_with_retry, text)
            return r["embedding"]

        results = await self.embed_texts([text])
        return results[0]

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=12, max=60),
        retry=retry_if_exception_type(ResourceExhausted),
        reraise=True
    )
    def _call_google_single_with_retry(self, text: str):
        import google.generativeai as genai
        return genai.embed_content(
            model=settings.GOOGLE_EMBEDDING_MODEL,
            content=text,
            task_type="retrieval_query",
            output_dimensionality=settings.EMBEDDING_DIMENSION
        )

    async def _openai_embed(self, texts: list[str]) -> list[list[float]]:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        # Lotes de 100 para optimizar rate limits
        all_embeddings = []
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            async with self.get_semaphore():
                response = await client.embeddings.create(
                    model=settings.OPENAI_EMBEDDING_MODEL,
                    input=batch,
                    dimensions=settings.EMBEDDING_DIMENSION,
                )
            all_embeddings.extend([e.embedding for e in response.data])
        return all_embeddings

    def _st_embed(self, texts: list[str]) -> list[list[float]]:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model.encode(texts, batch_size=32).tolist()

    async def _google_embed(self, texts: list[str]) -> list[list[float]]:
        import google.generativeai as genai
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        loop = asyncio.get_event_loop()
        all_embeddings = []

        # Lotes de 100 para optimizar el uso de la API
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            async with self.get_semaphore():
                await self._wait_for_rate_limit()
                r = await loop.run_in_executor(None, self._call_google_batch_with_retry, batch)
            all_embeddings.extend(r["embedding"])
        return all_embeddings

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=12, max=60),
        retry=retry_if_exception_type(ResourceExhausted),
        reraise=True
    )
    def _call_google_batch_with_retry(self, batch: list[str]):
        import google.generativeai as genai
        return genai.embed_content(
            model=settings.GOOGLE_EMBEDDING_MODEL,
            content=batch,
            task_type="retrieval_document",
            output_dimensionality=settings.EMBEDDING_DIMENSION
        )


# ─── RAG Service ─────────────────────────────────────────────
class RAGService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.chunker = TextChunker()
        self.embedder = EmbeddingService()

    async def process_document(self, document_id: str) -> bool:
        """Pipeline completo: extracción → chunking → embedding → almacenamiento."""
        try:
            # Marcar como procesando
            await self.db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.processing)
            )
            await self.db.commit()

            doc = await self.db.get(Document, document_id)
            if not doc:
                raise ValueError(f"Documento {document_id} no encontrado")

            logger.info("rag_processing_start", doc_id=document_id, file=doc.original_filename)

            # 1. Extraer texto
            pages = await DocumentExtractor.extract(doc.file_path, doc.mime_type)
            if not pages:
                raise ValueError("No se pudo extraer texto del documento")

            # 2. Chunking
            chunks = self.chunker.chunk(pages)
            logger.info("rag_chunks_created", count=len(chunks))

            # 3. Embeddings en lote
            texts = [c.content for c in chunks]
            embeddings = await self.embedder.embed_texts(texts)

            # 4. Guardar en BD
            db_chunks = []
            for chunk, embedding in zip(chunks, embeddings):
                db_chunk = DocumentChunk(
                    document_id=document_id,
                    chatbot_id=doc.chatbot_id,
                    content=chunk.content,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    chunk_metadata=chunk.metadata,
                    embedding=embedding,
                )
                db_chunks.append(db_chunk)

            self.db.add_all(db_chunks)

            # 5. Actualizar documento
            await self.db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(
                    status=DocumentStatus.ready,
                    chunk_count=len(chunks),
                    page_count=len(pages),
                )
            )
            await self.db.commit()
            logger.info("rag_processing_complete", doc_id=document_id, chunks=len(chunks))
            return True

        except Exception as e:
            logger.error("rag_processing_error", doc_id=document_id, error=str(e))
            await self.db.execute(
                update(Document)
                .where(Document.id == document_id)
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
        """Búsqueda semántica con pgvector."""
        top_k = top_k or settings.TOP_K_RESULTS
        query_embedding = await self.embedder.embed_query(query)
        embedding_str = f"[{','.join(map(str, query_embedding))}]"

        # Consulta con distancia coseno (1 - similitud)
        raw = await self.db.execute(
            f"""
            SELECT
                dc.id, dc.content, dc.chunk_index, dc.page_number,
                dc.chunk_metadata, dc.document_id,
                d.original_filename,
                1 - (dc.embedding <=> '{embedding_str}'::vector) AS similarity
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.chatbot_id = '{chatbot_id}'
              AND d.status = 'ready'
              AND 1 - (dc.embedding <=> '{embedding_str}'::vector) >= {threshold}
            ORDER BY dc.embedding <=> '{embedding_str}'::vector
            LIMIT {top_k}
            """
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
        """Construye el contexto para el LLM desde los chunks recuperados."""
        max_tokens = max_tokens or settings.MAX_CONTEXT_TOKENS
        context_parts = []
        total_chars = 0
        # Aproximación: 1 token ≈ 4 caracteres
        max_chars = max_tokens * 4

        for chunk in chunks:
            header = f"[Fuente: {chunk.filename}, Página {chunk.page_number}, Relevancia: {chunk.score:.2f}]"
            part = f"{header}\n{chunk.content}"
            if total_chars + len(part) > max_chars:
                break
            context_parts.append(part)
            total_chars += len(part)

        return "\n\n---\n\n".join(context_parts)
