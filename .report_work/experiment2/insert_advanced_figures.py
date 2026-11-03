from pathlib import Path
from copy import deepcopy
from io import BytesIO
import hashlib
import re
import zipfile
from lxml import etree
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parents[1]/'实验2/实验二 纹理映射 实验报告（含插图及仓库链接）.docx'
OUT=SOURCE.with_name('实验二 纹理映射 实验报告（补充进阶插图）.docx')
data=SOURCE.read_bytes()
(ROOT/'advanced-figures-reference.docx').write_bytes(data)
ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'}
z=zipfile.ZipFile(BytesIO(data))
original={i.filename:z.read(i.filename) for i in z.infolist()}
doc=etree.fromstring(original['word/document.xml'])
body=doc.find('w:body',ns)
def text(p):return ''.join(p.xpath('.//w:t/text()',namespaces=ns))
target=next(p for p in body.findall('w:p',ns) if text(p)=='5 交互功能与进阶插件检查')
section_title=target.getprevious()
page_break=section_title.getprevious()
assert page_break.xpath('.//w:br[@w:type="page"]',namespaces=ns)

scratch=Document()
def paragraph(text='',size=12,bold=False,after=4,leading=18):
    p=scratch.add_paragraph()
    p.paragraph_format.first_line_indent=Pt(0)
    p.paragraph_format.space_before=Pt(0)
    p.paragraph_format.space_after=Pt(after)
    p.paragraph_format.line_spacing=Pt(leading)
    r=p.add_run(text)
    r.font.name='Times New Roman';r.font.size=Pt(size);r.font.bold=bold
    r.font.color.rgb=RGBColor(0,0,0)
    r._r.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'宋体')
    return p

p=paragraph('八、实验数据及结果分析（续）',bold=True,after=4)
p.paragraph_format.page_break_before=True
p.paragraph_format.keep_with_next=True
p=paragraph('5 进阶插件运行效果',bold=True,after=5)
p.paragraph_format.keep_with_next=True

def figure(filename,caption,description):
    p=paragraph('',after=2)
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.line_spacing=1
    p.paragraph_format.keep_with_next=True
    p.add_run().add_picture(str(ROOT/filename),width=Cm(15.8))
    p._p.xpath('.//wp:docPr')[0].set('descr',caption)
    p=paragraph(caption,size=10.5,after=4,leading=14)
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next=True
    paragraph(description,size=10.5,after=6,leading=15)

figure('advanced-mipmap-ui.png','图6 模型查看器中的普通贴图与 Mipmap 设置插件',
       '加载瓶子模型并选择普通贴图，在“Mipmap 设置”中选择三线性过滤。该选项作用于当前模型贴图的底层纹理采样参数，面板同时显示对应的过滤说明。')
figure('advanced-environment-ui.png','图7 模型查看器中的环境反射与全景背景插件',
       '勾选“启用模型镜面反射”和“显示全景背景”，瓶体呈现周围环境的倒影，背景与反射共用同一张 EXR 全景纹理；关闭镜面反射后可恢复普通贴图。')

buf=BytesIO();scratch.save(buf)
sz=zipfile.ZipFile(BytesIO(buf.getvalue()))
sd=etree.fromstring(sz.read('word/document.xml'))
rels=etree.fromstring(original['word/_rels/document.xml.rels'])
PR='http://schemas.openxmlformats.org/package/2006/relationships'
sr=etree.fromstring(sz.read('word/_rels/document.xml.rels'))
maxid=max([int(r.get('Id')[3:]) for r in rels if re.fullmatch(r'rId\d+',r.get('Id',''))]+[0])
mapping={};added={}
for i,r in enumerate([r for r in sr if r.get('Type','').endswith('/image')],1):
    rid='rId'+str(maxid+i)
    mapping[r.get('Id')]=rid
    name='media/advanced-plugin-'+str(i)+'.png'
    new=etree.SubElement(rels,'{'+PR+'}Relationship')
    new.set('Id',rid);new.set('Type',r.get('Type'));new.set('Target',name)
    added['word/'+name]=sz.read('word/'+r.get('Target'))

docprids=[int(p.get('id','0')) for p in doc.xpath('.//wp:docPr',namespaces=ns)]
docprmax=max(docprids+[0])
index=list(body).index(page_break)
for p in sd.find('w:body',ns):
    if p.tag==qn('w:sectPr'):continue
    p=deepcopy(p)
    for blip in p.xpath('.//a:blip',namespaces=ns):
        key=qn('r:embed')
        blip.set(key,mapping[blip.get(key)])
    for docpr in p.xpath('.//wp:docPr',namespaces=ns):
        docprmax+=1;docpr.set('id',str(docprmax))
    body.insert(index,p);index+=1
nodes=target.xpath('.//w:t',namespaces=ns)
nodes[0].text='6 交互功能与进阶插件检查'
for node in nodes[1:]:node.text=''

ct=etree.fromstring(original['[Content_Types].xml'])
CT='http://schemas.openxmlformats.org/package/2006/content-types'
if not any(n.get('Extension','').lower()=='png' for n in ct):
    n=etree.SubElement(ct,'{'+CT+'}Default');n.set('Extension','png');n.set('ContentType','image/png')
changes={'word/document.xml':doc,'word/_rels/document.xml.rels':rels,'[Content_Types].xml':ct}
with zipfile.ZipFile(OUT,'w',zipfile.ZIP_DEFLATED) as out:
    for info in z.infolist():
        content=etree.tostring(changes[info.filename],encoding='UTF-8',xml_declaration=True,standalone=True) if info.filename in changes else original[info.filename]
        out.writestr(info,content)
    for name,content in added.items():out.writestr(name,content)
with zipfile.ZipFile(OUT) as out:
    for name,content in original.items():
        if name not in changes:assert out.read(name)==content,name
    final=etree.fromstring(out.read('word/document.xml'))
    assert len(final.xpath('.//a:blip',namespaces=ns))==len(doc.xpath('.//a:blip',namespaces=ns))
    for source_img in etree.fromstring(original['word/document.xml']).xpath('.//w:drawing',namespaces=ns):
        assert any(etree.tostring(source_img)==etree.tostring(item) for item in final.xpath('.//w:drawing',namespaces=ns))
print('Output:',OUT)
print('Preserved original package parts and existing drawings; added 2 plugin figures.')
