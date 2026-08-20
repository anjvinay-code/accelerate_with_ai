import zipfile, xml.etree.ElementTree as ET, json, pathlib, sys
p = pathlib.Path(r"C:\Users\anjvinay\Downloads\Groq API Creation Steps (1).docx")
if not p.exists():
    print(json.dumps({'error': 'file not found', 'path': str(p)}))
    sys.exit(0)
with zipfile.ZipFile(p) as z:
    xml = z.read('word/document.xml')
root = ET.fromstring(xml)
ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
paras = []
for p_el in root.findall('.//w:p', ns):
    texts = [t.text for t in p_el.findall('.//w:t', ns) if t.text]
    if texts:
        paras.append(''.join(texts).strip())
paras = [p for p in paras if p]
print(json.dumps({'paras': paras}, ensure_ascii=False, indent=2))
