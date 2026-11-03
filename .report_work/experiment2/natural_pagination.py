from pathlib import Path
from copy import deepcopy
from io import BytesIO
import re
import zipfile
from lxml import etree

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parents[1]/'实验2/实验二 纹理映射 实验报告（补充进阶插图）.docx'
OUT=SOURCE.with_name('实验二 纹理映射 实验报告（自然分页版）.docx')
data=SOURCE.read_bytes()
(ROOT/'report-before-natural-pagination.docx').write_bytes(data)
z=zipfile.ZipFile(BytesIO(data))
original={i.filename:z.read(i.filename) for i in z.infolist()}
root=etree.fromstring(original['word/document.xml'])
ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
W='{'+ns['w']+'}';WP='{'+ns['wp']+'}'
body=root.find('w:body',ns)
first=body.find('w:p',ns)
breaks_removed=0;headings_removed=0;converted=0
def text(p):return ''.join(p.xpath('.//w:t/text()',namespaces=ns))
def props(p):
    pr=p.find(W+'pPr')
    if pr is None:pr=etree.Element(W+'pPr');p.insert(0,pr)
    return pr
def set_flag(pr,name,on=True):
    node=pr.find(W+name)
    if node is None:node=etree.SubElement(pr,W+name)
    node.set(W+'val','1' if on else '0')

for p in list(body.findall('w:p',ns)):
    if text(p) in ('四、实验原理（续）','七、实验步骤（续）','八、实验数据及结果分析（续）'):
        body.remove(p);headings_removed+=1;continue
    if p is not first:
        had_page_break=False
        for br in p.xpath('.//w:br[@w:type="page"]',namespaces=ns):
            br.getparent().remove(br);breaks_removed+=1;had_page_break=True
        for before in p.xpath('./w:pPr/w:pageBreakBefore',namespaces=ns):
            before.getparent().remove(before);breaks_removed+=1
        # 空的手动换页段落无正文或图形，清除后不再占一行。
        if had_page_break and not text(p) and not p.xpath('.//w:drawing|.//w:pict|.//w:br',namespaces=ns):
            body.remove(p)
    for stale in p.xpath('.//w:lastRenderedPageBreak',namespaces=ns):
        stale.getparent().remove(stale)

# 将用户另存后形成的浮动图片改为随文字排列，避免自然分页时重叠。
for anchor in list(body.xpath('.//wp:anchor',namespaces=ns)):
    inline=etree.Element(WP+'inline',distT='0',distB='0',distL='0',distR='0')
    for tag in (WP+'extent',WP+'effectExtent',WP+'docPr',WP+'cNvGraphicFramePr','{'+ns['a']+'}graphic'):
        node=anchor.find(tag)
        if node is not None:inline.append(deepcopy(node))
    anchor.getparent().replace(anchor,inline);converted+=1

for p in body.findall('w:p',ns):
    if p.xpath('.//w:drawing',namespaces=ns):
        pr=props(p)
        spacing=pr.find(W+'spacing')
        if spacing is None:spacing=etree.SubElement(pr,W+'spacing')
        spacing.set(W+'line','240');spacing.set(W+'lineRule','auto')
        spacing.set(W+'after','60')
        set_flag(pr,'keepNext')
    if re.match(r'^图\s*\d+\s',text(p)):
        set_flag(props(p),'keepNext',False)

assert len(body.xpath('.//w:br[@w:type="page"]',namespaces=ns))==1
assert not body.xpath('./w:p/w:pPr/w:pageBreakBefore',namespaces=ns)
oldroot=etree.fromstring(original['word/document.xml'])
assert etree.tostring(body.find('w:tbl',ns))==etree.tostring(oldroot.find('w:body/w:tbl',ns))
assert etree.tostring(body.find('w:sectPr',ns))==etree.tostring(oldroot.find('w:body/w:sectPr',ns))
assert len(body.xpath('.//a:blip',namespaces=ns))==len(oldroot.xpath('.//a:blip',namespaces=ns))
with zipfile.ZipFile(OUT,'w') as final:
    for info in z.infolist():
        content=etree.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True) if info.filename=='word/document.xml' else original[info.filename]
        final.writestr(info,content)
with zipfile.ZipFile(OUT) as final:
    assert all(final.read(name)==content for name,content in original.items() if name!='word/document.xml')
print('Output:',OUT)
print('Removed manual breaks:',breaks_removed,'removed continuation headings:',headings_removed,'images set inline:',converted)
