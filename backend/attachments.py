import base64
import io
from pathlib import Path
import zipfile
from PIL import Image,ImageOps
from pypdf import PdfReader
from docx import Document

def extract(data,name):
    ext=Path(name).suffix.lower()
    if ext in {'.png','.jpg','.jpeg','.webp','.bmp'}:
        with Image.open(io.BytesIO(data)) as image:
            image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((1024,1024))
            out=io.BytesIO();image.save(out,'JPEG',quality=85)
        return {'kind':'image','data':'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode()}
    if ext=='.pdf':
        pdf=PdfReader(io.BytesIO(data))
        if pdf.is_encrypted or len(pdf.pages)>50:raise ValueError('Use an unlocked PDF with at most 50 pages.')
        text='\n'.join(p.extract_text() or '' for p in pdf.pages)
    elif ext=='.docx':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(x.file_size for x in z.infolist())>40*1024*1024:raise ValueError('Expanded document exceeds 40 MB.')
        doc=Document(io.BytesIO(data));text='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(' | '.join(c.text for c in r.cells) for t in doc.tables for r in t.rows)
    elif ext in {'.txt','.md','.csv','.tsv','.json','.py','.js','.ts','.html','.css','.yaml','.yml','.xml','.log'}:
        text=data.decode('utf-8-sig')
        if '\x00' in text:raise ValueError('Binary text files are unsupported.')
    else:raise ValueError('Supported attachments: images, PDF, DOCX, and UTF-8 text/code files.')
    if not text.strip():raise ValueError('No readable text. For scanned PDFs, attach the relevant page as an image.')
    if len(text)>18000:raise ValueError('Attach an excerpt of at most 18,000 characters.')
    return {'kind':'text','text':text}
