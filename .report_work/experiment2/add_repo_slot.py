from pathlib import Path
from copy import deepcopy
import zipfile
from lxml import etree

ROOT = Path(__file__).resolve().parent
path = ROOT.parents[1] / '实验2/实验二 纹理映射 实验报告（含尽头贴图）.docx'
ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W='{'+ns['w']+'}'
with zipfile.ZipFile(path) as z:
    parts = {i.filename:z.read(i.filename) for i in z.infolist()}
    infos=z.infolist()
root=etree.fromstring(parts['word/document.xml'])
body=root.find('w:body',ns)
assert not any('GitHub 仓库链接：' in ''.join(p.itertext()) for p in body.findall('w:p',ns))
target=next(p for p in body.findall('w:p',ns) if ''.join(p.xpath('.//w:t/text()',namespaces=ns))=='源程序清单')
slot=etree.Element(W+'p')
props=etree.SubElement(slot,W+'pPr')
spacing=etree.SubElement(props,W+'spacing')
spacing.set(W+'after','100');spacing.set(W+'line','380');spacing.set(W+'lineRule','exact')
run=etree.SubElement(slot,W+'r');rpr=etree.SubElement(run,W+'rPr')
fonts=etree.SubElement(rpr,W+'rFonts')
fonts.set(W+'ascii','Times New Roman');fonts.set(W+'hAnsi','Times New Roman');fonts.set(W+'eastAsia','宋体')
size=etree.SubElement(rpr,W+'sz');size.set(W+'val','24')
color=etree.SubElement(rpr,W+'color');color.set(W+'val','000000')
text=etree.SubElement(run,W+'t')
text.text='GitHub 仓库链接：________________________________________'
target.addnext(slot)
backup=ROOT/'report-before-repo-slot.docx'
if not backup.exists(): backup.write_bytes(path.read_bytes())
temp=ROOT/'report-repo-slot.docx'
with zipfile.ZipFile(temp,'w') as z:
    for info in infos:
        data=etree.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True) if info.filename=='word/document.xml' else parts[info.filename]
        z.writestr(info,data)
with zipfile.ZipFile(temp) as z:
    assert all(z.read(name)==data for name,data in parts.items() if name!='word/document.xml')
output=path.with_name('实验二 纹理映射 实验报告（含插图及仓库链接）.docx')
output.write_bytes(temp.read_bytes())
print(output)
