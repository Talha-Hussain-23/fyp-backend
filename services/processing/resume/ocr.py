"""
OCR and text extraction from various file formats.
Supports PDF, DOCX, images, and text files.
"""
import io
import logging
from fastapi import UploadFile, HTTPException

logger = logging.getLogger(__name__)


async def extract_text(file: UploadFile) -> str:
    """
    Extract text from PDF, DOCX, or image files
    
    Args:
        file: Uploaded file object
        
    Returns:
        Extracted text content
        
    Raises:
        HTTPException: If file type is unsupported or extraction fails
    """
    file_type = file.content_type
    filename = file.filename or "resume"
    file_extension = filename.split('.')[-1].lower() if '.' in filename else ''
    
    # Read file content
    content = await file.read()
    await file.seek(0)
    
    logger.info(f"OCR Processing {len(content)} bytes from {filename} ({file_type})")
    
    text = ""
    
    try:
        # Handle PDF files
        if file_type == 'application/pdf' or file_extension == 'pdf':
            text = await _extract_from_pdf(content, filename)
        
        # Handle DOCX files
        elif file_type in ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'] or file_extension in ['docx', 'doc']:
            text = await _extract_from_docx(content, filename)
        
        # Handle image files (JPEG, PNG)
        elif file_type in ['image/jpeg', 'image/jpg', 'image/png']:
            text = await _extract_from_image(content, filename)
                
        # Handle Text files
        elif file_type == 'text/plain' or file_extension == 'txt':
            text = await _extract_from_text(content, filename)
                 
        # Fallback: Try decoding as text if content seems like text
        if not text and len(content) > 0:
            try:
                decoded = content.decode('utf-8')
                if len(decoded.strip()) > 0:
                    logger.info(f"Fallback: Treated {filename} as plain text")
                    text = decoded
            except:
                pass
        
        # Explicitly reject unsupported file types
        if not text and len(content) > 0:
            # Check known unsafe types
            unsafe_extensions = ['.exe', '.sh', '.bat', '.cmd', '.js', '.vbs', '.scr', '.dll']
            if any(filename.lower().endswith(ext) for ext in unsafe_extensions):
                raise HTTPException(
                    status_code=400,
                    detail="Security Warning: Executable files are strictly prohibited."
                )
            
            # General unsupported type
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Please upload a valid PDF, DOCX, or Image."
            )

        if not text or len(text.strip()) < 10:
            logger.warning(f"WARNING: Insufficient text extracted from {filename} ({len(text)} chars)")
            text = f"Resume: {filename}\\n(Text extraction incomplete)"
        
        return text.strip()
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File processing error: {e}")
        return f"Error processing file {filename}: {str(e)}"


async def _extract_from_pdf(content: bytes, filename: str) -> str:
    """Extract text from PDF file"""
    try:
        import PyPDF2
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
        return "\\n".join([page.extract_text() for page in pdf_reader.pages])
    except Exception as e:
        try:
            import pymupdf
            doc = pymupdf.open(stream=content, filetype="pdf")
            text = "\\n".join([page.get_text() for page in doc])
            doc.close()
            return text
        except Exception as e2:
            logger.warning(f"PDF parsing error: {e}, {e2}")
            return ""


async def _extract_from_docx(content: bytes, filename: str) -> str:
    """Extract text from DOCX file"""
    try:
        from docx import Document
        doc = Document(io.BytesIO(content))
        return "\\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        logger.warning(f"DOCX parsing error: {e}")
        return ""


async def _extract_from_image(content: bytes, filename: str) -> str:
    """Extract text from image using OCR"""
    try:
        from PIL import Image
        import pytesseract
        image = Image.open(io.BytesIO(content))
        return pytesseract.image_to_string(image)
    except Exception as e:
        logger.warning(f"OCR error: {e}")
        return f"Image file: {filename}\\n(OCR not available - please use PDF or DOCX)"


async def _extract_from_text(content: bytes, filename: str) -> str:
    """Extract text from plain text file"""
    try:
        return content.decode('utf-8', errors='ignore')
    except Exception as e:
        logger.warning(f"Text parsing error: {e}")
        return ""
